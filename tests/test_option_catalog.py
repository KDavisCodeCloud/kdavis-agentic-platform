"""
G12 (Break-It Lab, cloud-decoded-lab results.md @ 365ea2b): an option's label
must describe exactly the code its id runs.

For every agent, every context variant and every option in that agent's
catalog, run execute_option with every tool method mocked and assert:
  * the methods actually called are exactly the catalog entry's `calls`,
  * the option doesn't fall through to skipped / not_implemented,
  * ids outside the catalog run nothing and return not_available.
Plus: every diagnose node binds the LLM's options to the catalog, and the A3
case from the lab ("Enable CloudTrail…" on opt_1) can no longer be shown.
"""
from __future__ import annotations

import importlib
import inspect
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.option_catalog import HOLD_ID, OptionSpec, bind_options, catalog_dict, catalog_prompt_block

ROOT = Path(__file__).resolve().parent.parent
RG = "/subscriptions/sub-1/resourceGroups/rg"

# (agent package, tools class, [context variants]). Each context carries every
# key that agent's execute_option reads, so no option can be skipped for lack of input.
AGENTS = [
    ("agent_01_cicd_triage", "CICDTools", [
        {"cloud_provider": "github", "owner": "o", "org": "o", "repo": "r", "project": "o/r",
         "run_id": 1, "pr_number": 7, "parsed_error": "x"},
        {"cloud_provider": "github", "owner": "o", "org": "o", "repo": "r", "project": "o/r",
         "run_id": 1, "pr_number": None, "parsed_error": "x"},
        {"cloud_provider": "azure_devops", "owner": "o", "org": "o", "repo": "r", "project": "p", "run_id": 1},
    ]),
    ("agent_02_k8s_alert", "K8sTools", [
        {"namespace": "ns", "deployment_name": "web", "container_name": "web"},
    ]),
    ("agent_03_pr_review", "PRReviewTools", [
        {"owner": "o", "repo": "r", "pr_number": 1, "review_body": "b", "head_sha": "abc"},
    ]),
    ("agent_04_migration", "MigrationTools", [
        {"owner": "o", "repo": "r", "file_path": "f.py", "migrated_code": "x", "migration_plan": "p"},
    ]),
    ("agent_05_iam_minimizer", "IAMMinimizeTools", [
        {"cloud_provider": "aws", "policy_arn": "arn:aws:iam::1:policy/p", "principal_id": "p",
         "minimized_policy": {"Statement": []}, "owner": "o", "repo": "r"},
        {"cloud_provider": "azure", "subscription_id": "sub-1", "principal_id": "p",
         "minimized_policy": {"role_assignments": [{"role": "Reader", "scope": RG}]}, "owner": "o", "repo": "r"},
        {"cloud_provider": "azure", "subscription_id": "sub-1", "principal_id": "p",
         "minimized_policy": {"role_assignments": [{"role": "Reader", "scope": RG}]}, "owner": "o", "repo": "r",
         "azure_remove": [{"id": "/subscriptions/sub-1/providers/Microsoft.Authorization/roleAssignments/o",
                           "role": "Owner", "scope": "/subscriptions/sub-1"}]},
        {"cloud_provider": "gcp", "resource": "proj", "principal_id": "p", "minimized_policy": {}, "owner": "o", "repo": "r"},
        {"cloud_provider": "oracle", "principal_id": "p", "owner": "o", "repo": "r"},
    ]),
    ("agent_06_finops", "FinOpsTools", [
        {"cloud_provider": "aws", "owner": "o", "repo": "r",
         "quick_win_resources": {"instance_ids": ["i-1"], "volume_ids": ["vol-1"], "allocation_ids": ["eipalloc-1"]}},
        {"cloud_provider": "azure", "owner": "o", "repo": "r",
         "quick_win_resources": {"vm_names": ["vm"], "disk_names": ["d"], "resource_group": "rg", "subscription_id": "s"}},
        {"cloud_provider": "gcp", "owner": "o", "repo": "r",
         "quick_win_resources": {"instance_names": ["n"], "zone": "z", "project": "p"}},
        {"cloud_provider": "oracle", "owner": "o", "repo": "r"},
    ]),
    ("agent_07_runbook", "RunbookTools", [
        {"plan_steps": [{"id": "s1", "type": "shell"}], "owner": "o", "repo": "r", "report_body": "b"},
    ]),
    ("agent_08_drift_detection", "DriftTools", [
        {"drift_source": "terraform", "owner": "o", "repo": "r", "resource_id": "sg-1", "corrected_content": "x"},
        {"drift_source": "kubernetes", "owner": "o", "repo": "r", "resource_id": "deploy/web",
         "corrected_content": "kind: Deployment", "scope": "ns"},
    ]),
    ("agent_09_onboarding_buddy", "OnboardingTools", [
        {"owner": "o", "repo": "r", "report_body": "b", "query_type": "onboarding"},
    ]),
    ("agent_10_dependency_patch", "DependencyPatchTools", [
        {"owner": "o", "repo": "r", "branch_name": "b", "file_path": "package.json", "file_sha": "s",
         "patched_content": "{}", "pr_body": "b", "issue_title": "t", "issue_body": "b"},
    ]),
    ("agent_11_resource_health", "ResourceHealthTools", [
        {"owner": "o", "repo": "r", "resource_id": "i-1", "report_body": "b", "corrected_content": "x"},
    ]),
]

CASES = [
    pytest.param(pkg, cls, ctx, spec_id, id=f"{pkg[6:8]}-{ctx.get('cloud_provider') or ctx.get('drift_source') or 'default'}"
                                          f"{'' if ctx.get('pr_number', 1) else '-nopr'}-{spec_id}")
    for pkg, cls, ctxs in AGENTS
    for ctx in ctxs
    for spec_id in importlib.import_module(f"agents.{pkg}.tools").option_catalog(ctx)
]


def _mocked_tools(pkg: str, cls_name: str):
    """A tools instance whose every async method except execute_option is an AsyncMock."""
    cls = getattr(importlib.import_module(f"agents.{pkg}.tools"), cls_name)
    tools = object.__new__(cls)
    mocks = {}
    for name, fn in inspect.getmembers(cls, inspect.iscoroutinefunction):
        if name == "execute_option":
            continue
        mocks[name] = AsyncMock(return_value={"status": "ok", "pr_url": "u", "pr_number": 1,
                                              "issue_url": "u", "issue_number": 1})
        setattr(tools, name, mocks[name])
    return tools, mocks


@pytest.mark.parametrize("pkg,cls_name,ctx,option_id", CASES)
async def test_option_runs_exactly_the_calls_its_label_describes(pkg, cls_name, ctx, option_id):
    catalog = importlib.import_module(f"agents.{pkg}.tools").option_catalog(ctx)
    spec = catalog[option_id]
    tools, mocks = _mocked_tools(pkg, cls_name)

    result = await tools.execute_option({"id": option_id, "title": "LLM-written text that must not matter"}, dict(ctx))

    called = {name for name, m in mocks.items() if m.await_count}
    assert called == set(spec.calls), (
        f"{pkg} {option_id} is labeled {spec.title!r} and declares {spec.calls}, but called {sorted(called)}"
    )
    if option_id == HOLD_ID:
        assert result["status"] == "held"
    else:
        assert result.get("status") not in ("skipped", "not_implemented", "not_available"), result


@pytest.mark.parametrize("pkg,cls_name,ctxs", [pytest.param(*a, id=a[0][:8]) for a in AGENTS])
async def test_ids_outside_the_catalog_run_nothing(pkg, cls_name, ctxs):
    mod = importlib.import_module(f"agents.{pkg}.tools")
    for ctx in ctxs:
        catalog = mod.option_catalog(ctx)
        for option_id in ("opt_1", "opt_2", "opt_3", "opt_4", "custom", ""):
            if option_id in catalog:
                continue
            tools, mocks = _mocked_tools(pkg, cls_name)
            result = await tools.execute_option({"id": option_id}, dict(ctx))
            assert result["status"] == "not_available", (pkg, ctx, option_id, result)
            assert not any(m.await_count for m in mocks.values()), (pkg, option_id)


def test_every_agent_with_execute_option_has_a_catalog_and_is_covered_here():
    with_execute = sorted(
        p.parent.name for p in ROOT.glob("agents/agent_*/tools.py")
        if "async def execute_option" in p.read_text()
    )
    assert with_execute == sorted(pkg for pkg, _, _ in AGENTS)


@pytest.mark.parametrize("pkg", [pkg for pkg, _, _ in AGENTS])
def test_diagnose_node_binds_llm_options_to_the_catalog(pkg):
    src = (ROOT / f"agents/{pkg}/workflow.py").read_text()
    diagnose = src[src.index("async def _diagnose_node"):src.index("async def _hitl_gate_node")]
    assert re.search(r"_catalog = option_catalog\(", diagnose)
    assert "catalog_prompt_block(_catalog)" in diagnose
    assert 'bind_options(diagnosis.get("options", []), _catalog, self.agent_id)' in diagnose


@pytest.mark.parametrize("pkg", [pkg for pkg, _, _ in AGENTS])
def test_catalog_entries_are_well_formed(pkg):
    mod = importlib.import_module(f"agents.{pkg}.tools")
    for _, _, ctxs in [a for a in AGENTS if a[0] == pkg]:
        for ctx in ctxs:
            catalog = mod.option_catalog(ctx)
            assert list(catalog)[-1] == HOLD_ID
            for spec in catalog.values():
                assert spec.title and spec.description
                for call in spec.calls:  # every declared call is a real tool method
                    assert callable(getattr(getattr(mod, dict((a[0], a[1]) for a in AGENTS)[pkg]), call)), call


# ── bind_options ─────────────────────────────────────────────────────────────

CAT = catalog_dict(
    OptionSpec("opt_1", "Apply the minimized policy", "Creates a new policy version.", "high", ("apply",)),
    OptionSpec("opt_2", "Open a PR", "Opens a PR.", "low", ("pr",)),
)


def test_bind_replaces_llm_labels_and_keeps_its_text_as_rationale():
    llm = [
        {"id": "opt_1", "title": "Enable CloudTrail and re-analyze in 30 days", "description": "Turn on logging",
         "impact": "LOW", "docs_url": "https://docs"},
        {"id": "opt_3", "title": "Remove Owner role assignment immediately", "description": "x"},  # no code
        {"id": "hold", "title": "Stay broken", "description": "y"},
    ]
    bound = bind_options(llm, CAT)
    assert [o["id"] for o in bound] == ["opt_1", "hold"]  # opt_3 dropped, opt_2 wasn't proposed
    assert bound[0]["title"] == "Apply the minimized policy"
    assert bound[0]["description"] == "Creates a new policy version."
    assert bound[0]["impact"] == "high"
    assert bound[0]["docs_url"] == "https://docs"
    assert bound[0]["rationale"] == "Enable CloudTrail and re-analyze in 30 days — Turn on logging"
    assert bound[1]["title"] == CAT["hold"].title


def test_bind_always_offers_hold_even_if_llm_omits_it_or_returns_garbage():
    assert [o["id"] for o in bind_options(None, CAT)] == ["hold"]
    assert [o["id"] for o in bind_options(["not a dict", {"id": "opt_2"}], CAT)] == ["opt_2", "hold"]


def test_prompt_block_lists_only_catalog_actions():
    block = catalog_prompt_block(CAT)
    assert "opt_1: Apply the minimized policy" in block and "opt_2: Open a PR" in block
    assert "Do not invent other ids" in block


def test_spec_validation():
    with pytest.raises(ValueError):
        OptionSpec("opt_1", "t", "d", "MEDIUM — modifies", ("x",))
    with pytest.raises(ValueError):
        OptionSpec("opt_1", "t", "d", "low", ())
    with pytest.raises(ValueError):
        catalog_dict(OptionSpec("hold", "t", "d", "low"))


# ── The lab's A3 case, end to end through Agent 05's diagnose node ───────────

async def test_lab_a3_card_says_what_opt_1_does(mock_db, workspace_id, mock_router):
    from tests.test_agent05 import _diagnose_state, _make_workflow

    wf = _make_workflow(mock_db, workspace_id, mock_router)
    llm = {
        "parsed_error": "Lambda role has *:*", "risk_score": "CRITICAL",
        "minimized_policy": {"Statement": []}, "permissions_removed": ["*"], "permissions_kept": [],
        "options": [
            {"id": "opt_1", "title": "Enable CloudTrail and re-analyze in 30 days", "description": "...",
             "impact": "LOW", "docs_url": ""},
            {"id": "opt_2", "title": "Create PR", "description": "...", "impact": "LOW", "docs_url": ""},
            {"id": "opt_3", "title": "Detach the policy", "description": "...", "impact": "LOW", "docs_url": ""},
            {"id": "hold", "title": "Hold", "description": "", "impact": "NONE", "docs_url": ""},
        ],
    }
    with patch.object(wf, "check_budget", new=AsyncMock()), \
         patch.object(wf, "call_llm", return_value=(json.dumps(llm), 100)) as call, \
         patch.object(wf, "parse_llm_json", return_value=llm):
        out = await wf._diagnose_node(_diagnose_state(workspace_id))

    opts = {o["id"]: o for o in out["remediation_options"]}
    assert list(opts) == ["opt_1", "opt_2", "hold"]
    assert opts["opt_1"]["title"] == "Apply the minimized policy as a new default version"
    assert "CloudTrail" in opts["opt_1"]["rationale"]
    sent = call.call_args.kwargs["messages"][0]["content"]
    assert "AVAILABLE ACTIONS" in sent and "opt_3" not in sent.split("AVAILABLE ACTIONS")[1]


# ── The lab's Z3 case: the card names exactly the assignment opt_1 deletes ───

def _z3_llm():
    return {
        "parsed_error": "Managed identity holds Owner on the subscription", "risk_score": "CRITICAL",
        "minimized_policy": {"role_assignments": [{"role": "Reader", "scope": RG}]},
        "permissions_removed": ["Owner"], "permissions_kept": ["Reader"],
        "options": [
            {"id": "opt_1", "title": "Remove Owner role assignment", "description": "...", "impact": "HIGH",
             "docs_url": ""},
            {"id": "hold", "title": "Hold", "description": "", "impact": "NONE", "docs_url": ""},
        ],
    }


async def test_lab_z3_card_lists_the_assignment_to_delete(mock_db, workspace_id, mock_router):
    from tests.test_agent05 import _diagnose_state, _make_workflow

    wf = _make_workflow(mock_db, workspace_id, mock_router)
    owner_id = "/subscriptions/sub-1/providers/Microsoft.Authorization/roleAssignments/owner-1"
    flagged = [{"id": owner_id, "role": "Owner", "scope": "/subscriptions/sub-1"}]
    state = _diagnose_state(workspace_id)
    state.update({"cloud_provider": "azure", "principal_id": "pid", "resource_scope": "sub-1"})
    llm = _z3_llm()
    with patch.object(wf, "check_budget", new=AsyncMock()), \
         patch.object(wf._tools, "list_flagged_azure_assignments", new=AsyncMock(return_value=flagged)), \
         patch.object(wf, "call_llm", return_value=(json.dumps(llm), 100)), \
         patch.object(wf, "parse_llm_json", return_value=llm):
        out = await wf._diagnose_node(state)

    opt_1 = {o["id"]: o for o in out["remediation_options"]}["opt_1"]
    assert opt_1["title"] == "Remove the over-privileged role assignment(s)"
    assert f"Owner at /subscriptions/sub-1 (assignment {owner_id})" in opt_1["description"]
    assert out["azure_removal_plan"] == flagged


async def test_lab_z3_no_opt_1_when_assignments_cannot_be_listed(mock_db, workspace_id, mock_router):
    from tests.test_agent05 import _diagnose_state, _make_workflow

    wf = _make_workflow(mock_db, workspace_id, mock_router)
    state = _diagnose_state(workspace_id)
    state.update({"cloud_provider": "azure", "principal_id": "pid", "resource_scope": "sub-1"})
    llm = _z3_llm()
    with patch.object(wf, "check_budget", new=AsyncMock()), \
         patch.object(wf._tools, "list_flagged_azure_assignments",
                      new=AsyncMock(side_effect=RuntimeError("403 Forbidden"))), \
         patch.object(wf, "call_llm", return_value=(json.dumps(llm), 100)), \
         patch.object(wf, "parse_llm_json", return_value=llm):
        out = await wf._diagnose_node(state)

    assert [o["id"] for o in out["remediation_options"]] == ["hold"]
    assert "403 Forbidden" in out["azure_removal_note"]
