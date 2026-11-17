"""
G1 (Break-It Lab): an incident's final status says what execution actually did.

  - classify_execution: skipped / not_implemented / not_available / errors are
    never 'executed'; PR/issue options end as 'proposed'; partial runs are failed.
  - Every agent's _complete_node goes through HITLGate.record_execution: a
    `skipped` result marks the incident failed (with a reason), never executed.
  - Lab cases: A1/Z1 (Agent 11 `skipped`) -> failed/not_executed;
    A2/Z2 (Agent 08 PR opened) -> proposed.
  - G15: Agent 08 "no drift" creates no incident.
"""
from __future__ import annotations

import importlib
import json
from unittest.mock import AsyncMock, patch

import pytest

from core.execution_outcome import (
    FAILURE_NOT_EXECUTED, FAILURE_PARTIAL, classify_execution,
)
from core.hitl import HITLGate

AGENTS = [
    "agent_01", "agent_02", "agent_03", "agent_04", "agent_05", "agent_06",
    "agent_07", "agent_08", "agent_09", "agent_10", "agent_11",
]
LIVE = {"id": "opt_1", "proposal": False}
PROPOSAL = {"id": "opt_1", "proposal": True}


# ── classify_execution ───────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["skipped", "not_implemented", "not_available", "failed", "error", "no_change"])
def test_did_nothing_is_failed_not_executed(status):
    out = classify_execution({"status": status, "reason": "no repo in alert payload"}, LIVE)
    assert out.status == "failed"
    assert out.failure_kind == FAILURE_NOT_EXECUTED
    assert "no repo in alert payload" in out.reason


@pytest.mark.parametrize("result", [{}, None, {"error": "boom"}, {"status": ""}])
def test_missing_or_error_result_is_not_executed(result):
    assert classify_execution(result, LIVE).status == "failed"


def test_held():
    assert classify_execution({"status": "held"}, LIVE).status == "held"


def test_live_change_is_executed():
    assert classify_execution({"status": "policy_updated"}, LIVE).status == "executed"


def test_pr_option_is_proposed_not_executed():
    """Lab A2/Z2: a PR was opened and nothing changed live."""
    assert classify_execution({"status": "pr_created", "pr_url": "u"}, PROPOSAL).status == "proposed"


def test_proposal_that_did_nothing_is_still_failed():
    out = classify_execution({"status": "skipped", "reason": "no repo"}, PROPOSAL)
    assert out.status == "failed" and out.failure_kind == FAILURE_NOT_EXECUTED


def test_runbook_partial_is_partial_execution():
    out = classify_execution({"status": "partial", "steps_failed": 1}, LIVE)
    assert out.status == "failed" and out.failure_kind == FAILURE_PARTIAL


def test_multi_call_with_a_skipped_part_is_partial():
    result = {"status": "quick_wins_applied", "results": {
        "ec2": {"status": "instances_stopped"}, "ebs": {"status": "skipped", "reason": "no volume IDs"}}}
    out = classify_execution(result, LIVE)
    assert out.status == "failed" and out.failure_kind == FAILURE_PARTIAL
    assert "ebs: skipped" in out.reason


def test_multi_call_where_every_part_failed_is_not_executed():
    result = {"status": "done", "pr": {"status": "skipped"}, "issue": {"status": "failed", "error": "403"}}
    assert classify_execution(result, PROPOSAL).failure_kind == FAILURE_NOT_EXECUTED


# ── HITLGate.record_execution ────────────────────────────────────────────────

async def test_record_execution_marks_failed_with_reason(mock_db):
    gate = HITLGate(mock_db)
    with patch.object(gate, "mark_executed", new=AsyncMock()) as executed, \
         patch.object(gate, "mark_failed", new=AsyncMock()) as failed:
        status = await gate.record_execution(
            "11111111-1111-1111-1111-111111111111", {"status": "skipped", "reason": "no repo"}, LIVE)
    assert status == "failed"
    executed.assert_not_called()
    assert failed.await_args.kwargs["failure_kind"] == FAILURE_NOT_EXECUTED
    assert "no repo" in failed.await_args.args[1]


async def test_record_execution_proposed_does_not_resolve(mock_db):
    gate = HITLGate(mock_db)
    with patch.object(gate, "mark_executed", new=AsyncMock()) as executed:
        status = await gate.record_execution(
            "11111111-1111-1111-1111-111111111111", {"status": "pr_created"}, PROPOSAL)
    assert status == "proposed"
    executed.assert_not_called()
    sql, written = mock_db.execute.await_args.args[0], mock_db.execute.await_args.args[1]
    assert "execution_status" in sql and "resolved_at" not in sql and written == "proposed"


async def test_record_execution_passes_before_state(mock_db):
    gate = HITLGate(mock_db)
    with patch.object(gate, "mark_executed", new=AsyncMock()) as executed:
        await gate.record_execution("11111111-1111-1111-1111-111111111111",
                                    {"status": "patched"}, LIVE, before_state={"replicas": 2})
    assert executed.await_args.kwargs["before_state"] == {"replicas": 2}


# ── every agent's complete node ─────────────────────────────────────────────

def _make(agent: str, mock_db, workspace_id, mock_router):
    mod = importlib.import_module(f"tests.test_{agent.replace('_', '')}")
    return mod._make_workflow(mock_db, workspace_id, mock_router)


@pytest.mark.parametrize("agent", AGENTS)
async def test_every_agent_marks_skipped_as_failed_never_executed(agent, mock_db, workspace_id, mock_router):
    wf = _make(agent, mock_db, workspace_id, mock_router)
    state = {"incident_id": "11111111-1111-1111-1111-111111111111",
             "selected_option": dict(LIVE), "execution_result": {"status": "skipped", "reason": "no repo"}}
    with patch.object(wf.hitl, "mark_executed", new=AsyncMock()) as executed, \
         patch.object(wf.hitl, "mark_failed", new=AsyncMock()) as failed:
        await wf._complete_node(state)
    executed.assert_not_called()
    failed.assert_awaited_once()
    assert failed.await_args.kwargs["failure_kind"] == FAILURE_NOT_EXECUTED


@pytest.mark.parametrize("agent", AGENTS)
async def test_every_agent_marks_a_proposal_as_proposed(agent, mock_db, workspace_id, mock_router):
    wf = _make(agent, mock_db, workspace_id, mock_router)
    state = {"incident_id": "11111111-1111-1111-1111-111111111111",
             "selected_option": dict(PROPOSAL), "execution_result": {"status": "pr_created"}}
    with patch.object(wf.hitl, "mark_executed", new=AsyncMock()) as executed:
        await wf._complete_node(state)
    executed.assert_not_called()


def test_every_catalog_pr_or_issue_option_is_a_proposal():
    """Static guard: an option whose only calls open a PR or issue must be flagged as a proposal,
    or it would end as 'executed' with nothing changed (lab A2/Z2)."""
    from tests.test_option_catalog import AGENTS as CATALOG_AGENTS
    proposing = ("_pr", "_issue")
    # Agent 09 answers onboarding questions: the issue *is* the answer, not a proposed fix.
    deliverable = {("agent_09_onboarding_buddy", "opt_1")}
    for module, _cls, contexts in CATALOG_AGENTS:
        tools = importlib.import_module(f"agents.{module}.tools")
        for ctx in contexts:
            for spec in tools.option_catalog(ctx).values():
                if (module, spec.id) in deliverable:
                    continue
                if spec.calls and all(c.endswith(proposing) for c in spec.calls):
                    assert spec.proposal, f"{module} {spec.id} only opens a PR/issue but isn't proposal=True"


# ── lab cases end to end through the real tools ─────────────────────────────

async def test_lab_a1_agent11_skipped_is_not_executed(mock_db, workspace_id, mock_router):
    """A1/Z1: the alert carried no repo, opt_1 returned skipped, the incident said executed."""
    wf = _make("agent_11", mock_db, workspace_id, mock_router)
    from agents.agent_11_resource_health.tools import option_catalog
    from core.option_catalog import bind_options
    opt_1 = bind_options([{"id": "opt_1"}], option_catalog({}))[0]
    result = await wf._tools.execute_option(opt_1, {"owner": "", "repo": "", "resource_id": "vm"})
    assert result["status"] == "skipped"
    with patch.object(wf.hitl, "mark_executed", new=AsyncMock()) as executed, \
         patch.object(wf.hitl, "mark_failed", new=AsyncMock()) as failed:
        await wf._complete_node({"incident_id": "11111111-1111-1111-1111-111111111111",
                                 "selected_option": opt_1, "execution_result": result})
    executed.assert_not_called()
    failed.assert_awaited_once()


# ── G15: no drift, no incident ───────────────────────────────────────────────

def _drift_llm(items, severity, summary="Resource matches desired state"):
    return {"parsed_error": "No drift detected — resource matches desired state", "drift_items": items,
            "drift_severity": severity, "drift_summary": summary, "corrected_content": "",
            "options": [{"id": "opt_1", "title": "Create PR", "description": "", "impact": "LOW", "docs_url": ""},
                        {"id": "hold", "title": "Hold", "description": "", "impact": "NONE", "docs_url": ""}]}


async def _diagnose(wf, workspace_id, llm):
    from tests.test_agent08 import _base_state
    state = _base_state(workspace_id)
    state.update({"drift_source": "terraform", "resource_type": "aws_security_group", "resource_id": "sg-1",
                  "desired_state_text": "x", "actual_state_text": "x"})
    with patch.object(wf, "check_budget", new=AsyncMock()), \
         patch.object(wf, "call_llm", return_value=(json.dumps(llm), 100)), \
         patch.object(wf, "parse_llm_json", return_value=llm):
        out = await wf._diagnose_node(state)
    state.update(out)
    return state


async def test_lab_a2_no_drift_routes_past_the_hitl_gate(mock_db, workspace_id, mock_router):
    """A2 bad-IaC: 'No drift detected' at severity medium still became a pending_approval incident."""
    wf = _make("agent_08", mock_db, workspace_id, mock_router)
    state = await _diagnose(wf, workspace_id, _drift_llm([], "MEDIUM"))
    assert wf._route_after_diagnose(state) == "no_drift"
    with patch.object(wf.hitl, "create_incident", new=AsyncMock()) as create:
        await wf._no_drift_complete_node(state)
    create.assert_not_called()


async def test_drift_found_still_goes_to_approval(mock_db, workspace_id, mock_router):
    wf = _make("agent_08", mock_db, workspace_id, mock_router)
    items = [{"key": "ingress.22", "desired_value": "closed", "actual_value": "0.0.0.0/0", "severity": "HIGH"}]
    state = await _diagnose(wf, workspace_id, _drift_llm(items, "HIGH"))
    assert wf._route_after_diagnose(state) == "drift"


async def test_could_not_compare_is_a_failed_check_not_no_drift(mock_db, workspace_id, mock_router):
    wf = _make("agent_08", mock_db, workspace_id, mock_router)
    state = await _diagnose(wf, workspace_id, _drift_llm([], "UNKNOWN", "Desired state was empty"))
    assert "could not compare" in state["error"] and "Desired state was empty" in state["error"]
    assert wf._route_after_diagnose(state) == "drift"  # hitl_gate records it as a failed incident


def test_agent08_graph_has_no_drift_branch():
    import inspect
    from agents.agent_08_drift_detection.workflow import DriftWorkflow
    src = inspect.getsource(DriftWorkflow._build_graph)
    assert '"no_drift": "no_drift_complete"' in src
    assert 'graph.add_edge("diagnose",  "hitl_gate")' not in src
