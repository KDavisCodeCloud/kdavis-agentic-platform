"""
tests/test_agent01_local.py
End-to-end integration tests for Agent 01 using mock data.

Purpose: see the full agent flow run locally, verify sanitization, state
transitions, and HITL mechanics without touching real AWS/Azure/Anthropic.

Run:
    pytest tests/test_agent01_local.py -v -s

What each test proves:
  test_security_shield_strips_aws_key_from_log
    The DataSanitizationShield must redact AKIAIOSFODNN7EXAMPLE before any
    text reaches the LLM router. This is the most important governance check.

  test_ingest_node_parses_github_failure_payload
    _ingest_node extracts structured fields from the mock GitHub webhook and
    the assembled log excerpt does not contain the original fake AWS key.

  test_diagnose_node_returns_three_options
    _diagnose_node calls the LLM router with task_type="issue_triage" and
    parses the mock response into parsed_error + remediation_options.

  test_hitl_gate_creates_incident_and_pauses
    _hitl_gate_node calls create_incident, then calls interrupt() to pause
    the graph. The selected option is returned from the interrupt stub.

  test_stay_broken_returns_held_status
    execute_option("hold") returns {"status": "held"} without making any
    external API call.

  test_execute_node_dispatches_github_rerun
    _execute_node calls tools.execute_option with the approved option and
    context derived from the state — no cloud call, just dispatch logic.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# conftest.py stubs langgraph before these imports run
from core.security import DataSanitizationShield, shield
from agents.agent_01_cicd_triage.tools import CICDTools
from tests.mocks.aws_fixtures import (
    MOCK_GITHUB_ACTIONS_LOG,
    MOCK_GITHUB_WEBHOOK_FAILURE,
)
from tests.mocks.azure_fixtures import MOCK_AZURE_DEVOPS_WEBHOOK_FAILURE

# Canonical mock LLM response — same shape the real router would return
MOCK_LLM_DIAGNOSIS = json.dumps({
    "parsed_error": (
        "AWS IAM permission denied: s3:PutObject not authorized on prod-assets-bucket. "
        "GitHub Actions runner role 'github-deploy-role' is missing write access."
    ),
    "options": [
        {
            "id": "opt_1",
            "title": "Attach S3 write policy to runner role",
            "description": "Add s3:PutObject permission scoped to prod-assets-bucket.",
            "impact": "low",
            "docs_url": "https://docs.aws.amazon.com/AmazonS3/latest/userguide/example-policies-s3.html",
        },
        {
            "id": "opt_2",
            "title": "Create scoped S3 deployment policy",
            "description": "New managed policy with least-privilege S3 access.",
            "impact": "low",
            "docs_url": "https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_create.html",
        },
        {
            "id": "custom",
            "title": "Custom / stay broken",
            "description": "Hold for manual fix.",
            "impact": "none",
            "docs_url": None,
        },
    ],
    "estimated_duration_seconds": 45,
})


def _make_workflow(mock_db, workspace_id, mock_router):
    """Create a CICDTriageWorkflow with real components but mocked LLM and graph compile."""
    from agents.agent_01_cicd_triage.workflow import CICDTriageWorkflow
    with (
        patch("agents.base_agent._load_router", return_value=mock_router),
        patch.object(CICDTriageWorkflow, "_build_graph", return_value=MagicMock()),
    ):
        return CICDTriageWorkflow(mock_db, workspace_id, MagicMock())


def _github_state(workspace_id):
    from agents.agent_01_cicd_triage.workflow import CICDTriageState
    return {
        "workspace_id": workspace_id,
        "cloud_provider": "github",
        "webhook_payload": MOCK_GITHUB_WEBHOOK_FAILURE,
        "job_name": "",
        "repository": "",
        "branch": "",
        "run_id": 0,
        "owner_or_org": "",
        "log_excerpt": "",
        "pr_number": None,
        "incident_id": None,
        "parsed_error": None,
        "remediation_options": None,
        "estimated_duration_seconds": None,
        "tokens_used": 0,
        "selected_option": None,
        "execution_result": None,
        "error": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Security: credential sanitization
# ─────────────────────────────────────────────────────────────────────────────

def test_security_shield_strips_aws_key_from_log():
    """Credentials in the raw log must be gone before the LLM ever sees them."""
    result = shield.sanitize(MOCK_GITHUB_ACTIONS_LOG, context="test_local")

    assert "AKIAIOSFODNN7EXAMPLE" not in result.sanitized_text, (
        "AWS access key leaked past sanitizer"
    )
    assert "wJalrXUtnFEMI" not in result.sanitized_text, (
        "AWS secret key leaked past sanitizer"
    )
    assert "[REDACTED" in result.sanitized_text, (
        "Sanitizer should replace credentials with [REDACTED:...] tokens"
    )
    assert result.redaction_count >= 2, (
        f"Expected at least 2 redactions, got {result.redaction_count}"
    )
    print(f"\n  redaction_count={result.redaction_count}")
    print(f"  sanitized excerpt: {result.sanitized_text[:120]}...")


def test_security_shield_preserves_non_credential_content():
    """Sanitizer must not redact error messages or URLs."""
    log = "upload failed: ./build/main.js to s3://prod-assets-bucket/static/main.js\nAccessDenied"
    result = shield.sanitize(log, context="test_local")

    assert "upload failed" in result.sanitized_text
    assert "AccessDenied" in result.sanitized_text
    assert result.redaction_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# _ingest_node: field extraction + sanitization
# ─────────────────────────────────────────────────────────────────────────────

async def test_ingest_node_parses_github_failure_payload(mock_db, workspace_id, mock_router):
    """_ingest_node must extract all structured fields from the mock GitHub payload."""
    wf = _make_workflow(mock_db, workspace_id, mock_router)
    state = _github_state(workspace_id)

    result = await wf._ingest_node(state)

    assert result["job_name"] == "Deploy Frontend Assets"
    assert result["repository"] == "acme/backend"
    assert result["branch"] == "main"
    assert result["run_id"] == 99887766
    assert result["owner_or_org"] == "acme"
    assert result["pr_number"] is None  # no pull_requests in this payload

    print(f"\n  job_name={result['job_name']}")
    print(f"  run_id={result['run_id']}")
    print(f"  log_excerpt[:100]={result['log_excerpt'][:100]}")


async def test_ingest_node_sanitizes_log_excerpt(mock_db, workspace_id, mock_router):
    """The assembled log excerpt must not contain raw credential values."""
    # Inject a fake key into the commit message to verify the sanitizer runs on output
    payload = dict(MOCK_GITHUB_WEBHOOK_FAILURE)
    payload["workflow_run"] = dict(payload["workflow_run"])
    payload["workflow_run"]["head_commit"] = {
        "message": "ci: deploy AKIAIOSFODNN7EXAMPLE to prod"
    }

    from agents.agent_01_cicd_triage.workflow import CICDTriageState
    state = _github_state(workspace_id)
    state["webhook_payload"] = payload

    wf = _make_workflow(mock_db, workspace_id, mock_router)
    result = await wf._ingest_node(state)

    assert "AKIAIOSFODNN7EXAMPLE" not in result["log_excerpt"], (
        "Raw AWS key must not appear in the log_excerpt passed to the LLM"
    )
    print(f"\n  log_excerpt contains redaction: {'[REDACTED' in result['log_excerpt']}")


async def test_ingest_node_azure_devops_payload(mock_db, workspace_id, mock_router):
    """_ingest_node correctly handles Azure DevOps webhook payloads."""
    from agents.agent_01_cicd_triage.workflow import CICDTriageState
    state: CICDTriageState = {
        "workspace_id": workspace_id,
        "cloud_provider": "azure_devops",
        "webhook_payload": MOCK_AZURE_DEVOPS_WEBHOOK_FAILURE,
        "job_name": "", "repository": "", "branch": "", "run_id": 0,
        "owner_or_org": "", "log_excerpt": "", "pr_number": None,
        "incident_id": None, "parsed_error": None, "remediation_options": None,
        "estimated_duration_seconds": None, "tokens_used": 0,
        "selected_option": None, "execution_result": None, "error": None,
    }

    wf = _make_workflow(mock_db, workspace_id, mock_router)
    result = await wf._ingest_node(state)

    assert result["job_name"] == "Deploy to Staging"
    assert result["branch"] == "main"           # refs/heads/ stripped
    assert result["run_id"] == 555
    assert result["owner_or_org"] == "contoso"
    print(f"\n  Azure branch={result['branch']} run_id={result['run_id']}")


# ─────────────────────────────────────────────────────────────────────────────
# _diagnose_node: LLM call + JSON parse
# ─────────────────────────────────────────────────────────────────────────────

async def test_diagnose_node_returns_three_options(mock_db, workspace_id, mock_router):
    """_diagnose_node calls the router and parses 3 remediation options."""
    wf = _make_workflow(mock_db, workspace_id, mock_router)

    # Provide the pre-filled state _ingest_node would produce
    state = _github_state(workspace_id)
    state["job_name"] = "Deploy Frontend Assets"
    state["repository"] = "acme/backend"
    state["branch"] = "main"
    state["run_id"] = 99887766
    state["owner_or_org"] = "acme"
    state["log_excerpt"] = "AccessDenied s3:PutObject on prod-assets-bucket"

    with patch.object(wf.budget, "assert_budget_available"):
        result = await wf._diagnose_node(state)

    assert result.get("error") is None, f"Unexpected error: {result.get('error')}"
    assert result["parsed_error"] is not None
    assert len(result["remediation_options"]) == 3
    assert result["estimated_duration_seconds"] == 45

    print(f"\n  parsed_error: {result['parsed_error'][:80]}...")
    print(f"  options: {[o['title'] for o in result['remediation_options']]}")


async def test_diagnose_node_routes_through_router(mock_db, workspace_id, mock_router):
    """_diagnose_node must call router.complete() with task_type='issue_triage'."""
    wf = _make_workflow(mock_db, workspace_id, mock_router)
    state = _github_state(workspace_id)
    state["log_excerpt"] = "AccessDenied"

    with patch.object(wf.budget, "assert_budget_available"):
        await wf._diagnose_node(state)

    call_args = mock_router.complete.call_args
    task_type = call_args.kwargs.get("task_type") or call_args.args[0]
    assert task_type == "issue_triage"
    print(f"\n  router called with task_type={task_type}")


async def test_diagnose_node_no_credentials_in_llm_message(mock_db, workspace_id, mock_router):
    """The message sent to the LLM must not contain raw AWS credentials."""
    wf = _make_workflow(mock_db, workspace_id, mock_router)
    state = _github_state(workspace_id)
    # Simulate a log excerpt that still contains a key somehow
    state["log_excerpt"] = "Error: AKIAIOSFODNN7EXAMPLE caused AccessDenied"

    with patch.object(wf.budget, "assert_budget_available"):
        await wf._diagnose_node(state)

    call_args = mock_router.complete.call_args
    messages = call_args.kwargs.get("messages") or call_args.args[1]
    full_text = " ".join(m["content"] for m in messages)
    assert "AKIAIOSFODNN7EXAMPLE" not in full_text, (
        "AWS key must be sanitized before reaching the router"
    )
    print("\n  Confirmed: no raw credentials in LLM message")


# ─────────────────────────────────────────────────────────────────────────────
# _hitl_gate_node: incident creation + interrupt
# ─────────────────────────────────────────────────────────────────────────────

async def test_hitl_gate_creates_incident_and_pauses(mock_db, workspace_id, mock_router):
    """_hitl_gate_node must persist incident to DB and call interrupt()."""
    incident_uuid = uuid4()
    mock_db.fetchrow.return_value = {"id": incident_uuid}
    mock_db.fetchrow.reset_mock()

    wf = _make_workflow(mock_db, workspace_id, mock_router)
    state = _github_state(workspace_id)
    state["parsed_error"] = "AWS IAM permission denied"
    state["remediation_options"] = [
        {"id": "opt_1", "title": "Attach S3 write policy", "description": "...",
         "impact": "low", "docs_url": "https://docs.aws.amazon.com/"},
        {"id": "custom", "title": "Stay broken", "description": "...",
         "impact": "none", "docs_url": None},
    ]
    state["tokens_used"] = 1800

    with patch("agents.agent_01_cicd_triage.workflow.interrupt") as mock_interrupt:
        mock_interrupt.return_value = {"id": "opt_1", "title": "Attach S3 write policy",
                                       "description": "...", "impact": "low",
                                       "docs_url": "https://docs.aws.amazon.com/"}
        result = await wf._hitl_gate_node(state)

    # Incident persisted
    mock_db.fetchrow.assert_called_once()
    insert_query = mock_db.fetchrow.call_args.args[0]
    assert "INSERT INTO incidents" in insert_query

    # Graph interrupted
    mock_interrupt.assert_called_once()
    interrupt_payload = mock_interrupt.call_args.args[0]
    assert interrupt_payload["incident_id"] == str(incident_uuid)
    assert len(interrupt_payload["options"]) == 2

    # Return value contains both ids
    assert result["incident_id"] == str(incident_uuid)
    assert result["selected_option"]["id"] == "opt_1"

    print(f"\n  incident_id={result['incident_id']}")
    print(f"  selected_option={result['selected_option']['id']}")
    print(f"  interrupt payload keys={list(interrupt_payload.keys())}")


# ─────────────────────────────────────────────────────────────────────────────
# execute_option: dispatch + hold
# ─────────────────────────────────────────────────────────────────────────────

async def test_stay_broken_returns_held_status():
    """execute_option('hold') must return held status without any external call."""
    tools = CICDTools(github_token="gh_test", azure_token="az_test")

    with patch.object(tools, "rerun_failed_jobs_only") as mock_rerun, \
         patch.object(tools, "retry_azure_pipeline") as mock_azure:
        result = await tools.execute_option(
            {"id": "hold", "title": "Custom solution / stay broken"},
            {"cloud_provider": "github", "owner": "acme", "repo": "backend", "run_id": 1},
        )

    mock_rerun.assert_not_called()
    mock_azure.assert_not_called()
    assert result["status"] == "held"
    print(f"\n  hold result: {result}")


async def test_execute_node_dispatches_github_rerun(mock_db, workspace_id, mock_router):
    """_execute_node calls the right tool and records execution_result in state."""
    mock_tool_result = {"status": "triggered", "mode": "failed_jobs_only", "run_id": 99887766}

    wf = _make_workflow(mock_db, workspace_id, mock_router)
    state = _github_state(workspace_id)
    state["job_name"] = "Deploy Frontend Assets"
    state["repository"] = "acme/backend"
    state["owner_or_org"] = "acme"
    state["run_id"] = 99887766
    state["incident_id"] = str(uuid4())
    state["parsed_error"] = "AWS IAM AccessDenied"
    state["selected_option"] = {
        "id": "opt_1",
        "title": "Attach S3 write policy",
        "description": "...",
        "impact": "low",
        "docs_url": "https://docs.aws.amazon.com/",
    }

    with patch.object(wf._tools, "execute_option", return_value=mock_tool_result) as mock_exec:
        result = await wf._execute_node(state)

    mock_exec.assert_called_once()
    call_option = mock_exec.call_args.args[0]
    assert call_option["id"] == "opt_1"

    context = mock_exec.call_args.args[1]
    assert context["cloud_provider"] == "github"
    assert context["owner"] == "acme"
    assert context["run_id"] == 99887766

    assert result["execution_result"]["status"] == "triggered"
    print(f"\n  execution_result={result['execution_result']}")
