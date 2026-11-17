"""
G15 generalized (Kelvin, 2026-11-17): an agent that checked and found nothing
creates no incident and no approval card, only an audit entry.

Which agents can "find nothing":
  - 05 IAM: no permission to remove, judged against a real access log
  - 06 FinOps: no savings, recommendation or idle resource in real cost data
  - 08 Drift: no drift items
  - 10 Dependencies: OSV.dev checked every pinned dependency, none vulnerable
    (decided before the LLM call, so a clean scan costs no tokens)

"Couldn't check" is never "nothing found": missing input or failed lookups
become a failed incident with the reason.

Agents 01, 02, 07, 09 and 11 are triggered by an event that is itself the
finding (a failed CI run, a firing alert, an operator-started runbook or
question). Agent 03 always has a verdict to post. Agent 04 runs on an
operator's migration request. None of them route through "nothing found";
the static test below pins that list so a new agent is a deliberate choice.
"""
from __future__ import annotations

import importlib
import inspect
import json
from unittest.mock import AsyncMock, patch

import pytest

NOTHING_FOUND_AGENTS = {
    "agent_05_iam_minimizer", "agent_06_finops", "agent_08_drift_detection", "agent_10_dependency_patch",
}
ALL_AGENTS = [
    "agent_01_cicd_triage", "agent_02_k8s_alert", "agent_03_pr_review", "agent_04_migration",
    "agent_05_iam_minimizer", "agent_06_finops", "agent_07_runbook", "agent_08_drift_detection",
    "agent_09_onboarding_buddy", "agent_10_dependency_patch", "agent_11_resource_health",
]


def _make(agent: str, mock_db, workspace_id, mock_router):
    mod = importlib.import_module(f"tests.test_{agent[:8].replace('_', '')}")
    return mod._make_workflow(mock_db, workspace_id, mock_router)


def _workflow_class(agent: str):
    mod = importlib.import_module(f"agents.{agent}.workflow")
    return next(c for _, c in inspect.getmembers(mod, inspect.isclass)
                if c.__module__ == mod.__name__ and hasattr(c, "_build_graph"))


# ── wiring ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("agent", ALL_AGENTS)
def test_which_agents_route_nothing_found(agent):
    src = inspect.getsource(_workflow_class(agent)._build_graph)
    routed = "self._add_diagnose_routing(graph)" in src
    assert routed == (agent in NOTHING_FOUND_AGENTS)
    if routed:
        assert 'add_edge("diagnose",  "hitl_gate")' not in src


@pytest.mark.parametrize("agent", sorted(NOTHING_FOUND_AGENTS))
def test_real_graph_has_the_nothing_found_branch(agent, mock_db, workspace_id, mock_router):
    from langgraph.checkpoint.memory import MemorySaver
    cls = _workflow_class(agent)
    with patch("agents.base_agent._load_router", return_value=mock_router):
        wf = cls(mock_db, workspace_id, MemorySaver())
    g = wf._graph.get_graph()
    assert "nothing_found_complete" in g.nodes
    targets = {e.target for e in g.edges if e.source == "diagnose"}
    assert targets == {"nothing_found_complete", "hitl_gate"}


async def test_nothing_found_node_writes_audit_with_reason_and_no_incident(mock_db, workspace_id, mock_router):
    wf = _make("agent_08_drift_detection", mock_db, workspace_id, mock_router)
    with patch.object(wf, "_write_audit") as audit, \
         patch.object(wf.hitl, "create_incident", new=AsyncMock()) as create:
        out = await wf._nothing_found_complete_node({"nothing_found": "No drift detected", "tokens_used": 50})
    assert out == {}
    create.assert_not_called()
    audit.assert_called_once()
    assert audit.call_args.args == ("complete", "nothing_found")
    assert audit.call_args.kwargs["metadata"] == {"reason": "No drift detected"}


def test_error_wins_over_nothing_found(mock_db, workspace_id, mock_router):
    wf = _make("agent_08_drift_detection", mock_db, workspace_id, mock_router)
    assert wf._route_after_diagnose({"error": "boom", "nothing_found": "x"}) == "findings"


# ── Agent 10: decided from the OSV scan, before any LLM call ────────────────

def _manifest():
    from tests.test_agent10 import SAMPLE_REQUIREMENTS_TXT
    return {"path": "requirements.txt", "url": "u", "content": SAMPLE_REQUIREMENTS_TXT, "sha": "s"}


async def _agent10_diagnose(wf, workspace_id, osv_results, scan):
    from tests.test_agent10 import _diagnose_state

    async def osv(*_a, **_k):
        wf._tools.last_osv_scan = scan
        return osv_results

    with patch.object(wf._tools, "fetch_manifest", new=AsyncMock(return_value=_manifest())), \
         patch.object(wf._tools, "query_osv_batch", new=osv), \
         patch.object(wf, "check_budget", new=AsyncMock()), \
         patch.object(wf, "call_llm") as llm:
        out = await wf._diagnose_node(_diagnose_state(workspace_id))
    return out, llm


async def test_agent10_clean_scan_is_nothing_found_without_llm(mock_db, workspace_id, mock_router):
    wf = _make("agent_10_dependency_patch", mock_db, workspace_id, mock_router)
    out, llm = await _agent10_diagnose(wf, workspace_id, [], {"checked": 5, "failed": 0, "unversioned": 1})
    llm.assert_not_called()
    assert "No known vulnerabilities in 5 dependencies" in out["nothing_found"]
    assert "1 without a pinned version" in out["nothing_found"]
    assert wf._route_after_diagnose(out) == "nothing_found"


async def test_agent10_failed_osv_queries_are_a_failed_check(mock_db, workspace_id, mock_router):
    wf = _make("agent_10_dependency_patch", mock_db, workspace_id, mock_router)
    out, llm = await _agent10_diagnose(wf, workspace_id, [], {"checked": 3, "failed": 2, "unversioned": 0})
    llm.assert_not_called()
    assert "incomplete" in out["error"] and "2 OSV.dev queries failed" in out["error"]
    assert not out.get("nothing_found")


async def test_agent10_osv_records_what_it_checked():
    from agents.agent_10_dependency_patch.tools import DependencyPatchTools
    import httpx
    tools = DependencyPatchTools(github_token="t")
    ok = httpx.Response(200, json={"vulns": []}, request=httpx.Request("POST", "https://x"))
    calls = iter([ok, httpx.RequestError("down")])

    async def post(*_a, **_k):
        nxt = next(calls)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = post
    with patch("agents.agent_10_dependency_patch.tools.httpx.AsyncClient", return_value=client):
        res = await tools.query_osv_batch(
            [{"name": "a", "version": "1"}, {"name": "b", "version": "2"}, {"name": "c", "version": ""}], "pip")
    assert res == []
    assert tools.last_osv_scan == {"checked": 1, "failed": 1, "unversioned": 1}


# ── Agents 05 / 06 / 08: decided from the analysis ───────────────────────────

async def _llm_diagnose(wf, state, llm):
    with patch.object(wf, "check_budget", new=AsyncMock()), \
         patch.object(wf, "call_llm", return_value=(json.dumps(llm), 100)), \
         patch.object(wf, "parse_llm_json", return_value=llm):
        return await wf._diagnose_node(state)


def _iam_llm(removed):
    return {"parsed_error": "x", "minimized_policy": {"Statement": []}, "permissions_removed": removed,
            "permissions_kept": ["s3:GetObject"], "risk_score": "LOW",
            "options": [{"id": "hold", "title": "Hold", "description": "", "impact": "LOW", "docs_url": ""}]}


async def test_agent05_nothing_to_remove_with_usage_data(mock_db, workspace_id, mock_router):
    from tests.test_agent05 import _diagnose_state
    wf = _make("agent_05_iam_minimizer", mock_db, workspace_id, mock_router)
    out = await _llm_diagnose(wf, _diagnose_state(workspace_id), _iam_llm([]))
    assert "nothing to remove" in out["nothing_found"]


async def test_agent05_permissions_to_remove_is_a_finding(mock_db, workspace_id, mock_router):
    from tests.test_agent05 import _diagnose_state
    wf = _make("agent_05_iam_minimizer", mock_db, workspace_id, mock_router)
    out = await _llm_diagnose(wf, _diagnose_state(workspace_id), _iam_llm(["iam:*"]))
    assert out["nothing_found"] is None


async def test_agent05_empty_access_log_is_not_nothing_found(mock_db, workspace_id, mock_router):
    from tests.test_agent05 import _diagnose_state
    wf = _make("agent_05_iam_minimizer", mock_db, workspace_id, mock_router)
    state = _diagnose_state(workspace_id)
    state["access_log_summary"] = ""
    out = await _llm_diagnose(wf, state, _iam_llm([]))
    assert out["nothing_found"] is None  # can't judge usage → still an incident


def _finops_llm(savings, recs, quick):
    return {"parsed_error": "x", "cost_report": "r", "recommendations": recs, "quick_win_resources": quick,
            "estimated_monthly_savings": savings,
            "options": [{"id": "hold", "title": "Hold", "description": "", "impact": "LOW", "docs_url": ""}]}


@pytest.mark.parametrize("savings,recs,quick,nothing", [
    (0, [], {"instance_ids": []}, True),
    (0, [], {}, True),
    (120.0, [], {}, False),
    (0, [{"title": "rightsize"}], {}, False),
    (0, [], {"volume_ids": ["vol-1"]}, False),
])
async def test_agent06_nothing_found(savings, recs, quick, nothing, mock_db, workspace_id, mock_router):
    from tests.test_agent06 import _diagnose_state
    wf = _make("agent_06_finops", mock_db, workspace_id, mock_router)
    out = await _llm_diagnose(wf, _diagnose_state(workspace_id), _finops_llm(savings, recs, quick))
    assert bool(out.get("nothing_found")) is nothing


async def test_agent06_no_cost_data_is_a_failed_check(mock_db, workspace_id, mock_router):
    from tests.test_agent06 import _diagnose_state
    wf = _make("agent_06_finops", mock_db, workspace_id, mock_router)
    state = _diagnose_state(workspace_id)
    state["cost_data_summary"] = "  "
    with patch.object(wf, "call_llm") as llm:
        out = await wf._diagnose_node(state)
    llm.assert_not_called()
    assert "No cost data" in out["error"]
