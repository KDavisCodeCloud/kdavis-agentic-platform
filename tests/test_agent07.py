"""
tests/test_agent07.py
Tests for agents/agent_07_runbook/tools.py and workflow.py.

What this file validates:
  Runbook execution disabled (2026-11-18 claims audit — steps ran on
  Cloud Decoded's shared API host):
    - no shell/HTTP/kubectl/notification step executor exists
    - execute_runbook_plan() refuses without running anything
    - execute_option(opt_1) refuses; never spawns a process or makes a request
    - diagnose offers only opt_2 (file plan as issue) and hold, whatever the LLM says
    - approving a stale opt_1 card marks the incident failed, not executed
    - create_runbook_issue() creates GitHub issue with runbook labels
    - create_runbook_issue() raises EnvironmentError when GITHUB_TOKEN missing
    - _build_plan_report() says the plan was not executed

  _normalize_runbook_steps():
    - Parses a list of step dicts
    - Parses a dict with a 'steps' key
    - Parses a JSON string
    - Caps at MAX_STEPS (50)
    - Returns (list, text) tuple

  RunbookWorkflow._ingest_node():
    - Extracts runbook_name, version, repository, trigger_source
    - Normalizes and sanitizes steps
    - Sanitizes incident_context
    - Empty payload sets safe defaults without crash

  RunbookWorkflow._diagnose_node():
    - Calls router with task_type="runbook_automation"
    - Parses LLM fields: execution_plan, skipped_steps, plan_summary
    - Accumulates tokens from prior state
    - Sets error on parse failure
    - Calls check_budget() before LLM call
    - Includes runbook_name and incident_context in user message

  RunbookWorkflow._hitl_gate_node():
    - Calls hitl.create_incident() with correct agent_id
    - raw_log includes runbook name and step count
    - interrupt() includes steps_count and plan_summary
    - Skips incident creation when state["error"] is set
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agents.agent_07_runbook import tools as runbook_tools
from agents.agent_07_runbook.tools import EXECUTION_DISABLED_REASON, RunbookTools
from agents.agent_07_runbook.workflow import (
    RunbookWorkflow,
    RunbookState,
    _normalize_runbook_steps,
    _build_plan_report,
)


# ──────────────────────────────────────────────────────────────────────────────
# Sample data
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_STEPS = [
    {
        "id": "step-01",
        "name": "Check pod status",
        "type": "shell",
        "command": "kubectl get pods -n {{namespace}}",
        "on_failure": "continue",
        "timeout_seconds": 15,
    },
    {
        "id": "step-02",
        "name": "Get pod logs",
        "type": "shell",
        "command": "kubectl logs -n {{namespace}} {{pod_name}} --tail=50",
        "on_failure": "continue",
        "timeout_seconds": 15,
    },
    {
        "id": "step-03",
        "name": "Notify team",
        "type": "notification",
        "channel": "slack",
        "message": "Runbook applied for {{deployment_name}}",
        "on_failure": "continue",
    },
]

SAMPLE_HTTP_STEP = {
    "id": "http-01",
    "name": "Trigger deploy webhook",
    "type": "http",
    "method": "POST",
    "url": "https://api.example.com/deploy/{{deployment_name}}",
    "headers": {"Authorization": "Bearer {{api_token}}"},
    "body": {"action": "restart"},
    "on_failure": "stop",
}

SAMPLE_LLM_RUNBOOK_DIAGNOSIS = json.dumps({
    "parsed_error": "OOMKilled recovery runbook has 3 steps; step-01 and step-02 are diagnostic (safe), step-03 is a notification.",
    "plan_summary": "Running 3 steps: check pod status, get logs, notify team. All relevant to OOMKilled incident.",
    "execution_plan": SAMPLE_STEPS,
    "skipped_steps": [],
    "options": [
        {
            "id": "opt_1",
            "title": "Execute Runbook Plan",
            "description": "Run all 3 steps sequentially.",
            "impact": "LOW",
            "docs_url": "",
        },
        {
            "id": "opt_2",
            "title": "Create Dry-Run Issue",
            "description": "Create a GitHub issue with the plan.",
            "impact": "NONE",
            "docs_url": "https://docs.github.com/en/issues",
        },
        {
            "id": "hold",
            "title": "Hold — Manual Execution",
            "description": "Pause for manual handling.",
            "impact": "NONE",
            "docs_url": "",
        },
    ],
    "estimated_duration_seconds": 45,
})


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_http_resp(status_code: int, body) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = json.dumps(body)[:200] if isinstance(body, (dict, list)) else str(body)[:200]
    return resp


def _make_workflow(mock_db, workspace_id, mock_router) -> RunbookWorkflow:
    with (
        patch("agents.base_agent._load_router", return_value=mock_router),
        patch.object(RunbookWorkflow, "_build_graph", return_value=MagicMock()),
    ):
        wf = RunbookWorkflow(mock_db, workspace_id, MagicMock())
    return wf


def _base_state(workspace_id: str, payload: dict | None = None) -> RunbookState:
    return {
        "workspace_id": workspace_id,
        "cloud_provider": "aws",
        "webhook_payload": payload or {},
        "runbook_name": "",
        "runbook_version": "",
        "runbook_steps_raw": [],
        "runbook_steps_text": "",
        "incident_context": "",
        "repository": "",
        "trigger_source": "manual",
        "incident_id": None,
        "parsed_error": None,
        "execution_plan": None,
        "plan_summary": None,
        "skipped_steps": None,
        "estimated_duration_seconds": None,
        "remediation_options": None,
        "tokens_used": 0,
        "selected_option": None,
        "execution_result": None,
        "error": None,
    }


def _diagnose_state(workspace_id: str) -> RunbookState:
    s = _base_state(workspace_id)
    s.update({
        "runbook_name": "OOMKilled Recovery Runbook",
        "runbook_version": "1.2",
        "runbook_steps_raw": SAMPLE_STEPS,
        "runbook_steps_text": "\n".join(
            f"{i+1}. [{s['id']}] {s['name']} (type={s['type']}): {s.get('command', '')}"
            for i, s in enumerate(SAMPLE_STEPS)
        ),
        "incident_context": "payment-service OOMKilled 4 times in 10 minutes, exit code 137, 512Mi limit",
        "repository": "acme/ops",
        "trigger_source": "agent_02",
    })
    return s


def _hitl_state(workspace_id: str) -> RunbookState:
    s = _diagnose_state(workspace_id)
    parsed = json.loads(SAMPLE_LLM_RUNBOOK_DIAGNOSIS)
    s.update({
        "parsed_error": parsed["parsed_error"],
        "execution_plan": parsed["execution_plan"],
        "plan_summary": parsed["plan_summary"],
        "skipped_steps": parsed["skipped_steps"],
        "remediation_options": parsed["options"],
        "estimated_duration_seconds": 45,
        "tokens_used": 800,
    })
    return s


# ──────────────────────────────────────────────────────────────────────────────
# _normalize_runbook_steps()
# ──────────────────────────────────────────────────────────────────────────────

class TestNormalizeRunbookSteps:
    def test_parses_list_of_step_dicts(self):
        steps, text = _normalize_runbook_steps(SAMPLE_STEPS)
        assert len(steps) == 3
        assert steps[0]["id"] == "step-01"

    def test_parses_dict_with_steps_key(self):
        steps, text = _normalize_runbook_steps({"steps": SAMPLE_STEPS, "name": "Test"})
        assert len(steps) == 3

    def test_parses_json_string(self):
        steps, text = _normalize_runbook_steps(json.dumps(SAMPLE_STEPS))
        assert len(steps) == 3

    def test_caps_at_max_steps(self):
        many_steps = [{"id": f"step-{i:03d}", "name": f"Step {i}", "type": "shell", "command": "echo ok"} for i in range(60)]
        steps, _ = _normalize_runbook_steps(many_steps)
        assert len(steps) == 50

    def test_returns_text_with_step_ids(self):
        steps, text = _normalize_runbook_steps(SAMPLE_STEPS)
        assert "step-01" in text
        assert "step-02" in text

    def test_empty_list_returns_empty(self):
        steps, text = _normalize_runbook_steps([])
        assert steps == []
        assert text == ""

    def test_invalid_json_string_returns_raw_text(self):
        steps, text = _normalize_runbook_steps("not valid json")
        assert steps == []
        assert "not valid json" in text


# ──────────────────────────────────────────────────────────────────────────────
# RunbookTools — create_runbook_issue()
# ──────────────────────────────────────────────────────────────────────────────

class TestCreateRunbookIssue:
    @pytest.fixture
    def tools(self):
        return RunbookTools(github_token="gh_test_token")

    async def test_raises_without_github_token(self):
        no_token = RunbookTools(github_token="")
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            await no_token.create_runbook_issue("acme", "ops", "title", "body")

    async def test_creates_issue_with_runbook_labels(self, tools):
        issue_resp = _make_http_resp(201, {"number": 55, "html_url": "https://github.com/acme/ops/issues/55"})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=issue_resp)

        with patch("agents.agent_07_runbook.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.create_runbook_issue(
                "acme", "ops", "Runbook: OOMKilled Recovery", "## Report",
                labels=["runbook", "operations"],
            )

        assert result["status"] == "issue_created"
        assert result["issue_number"] == 55
        payload = ctx.post.call_args.kwargs["json"]
        assert "runbook" in payload.get("labels", [])


# ──────────────────────────────────────────────────────────────────────────────
# RunbookWorkflow._ingest_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestIngestNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        return _make_workflow(mock_db, workspace_id, mock_router)

    async def test_extracts_runbook_name_and_version(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "runbook_name": "OOMKilled Recovery",
            "runbook_version": "1.2",
            "steps": SAMPLE_STEPS,
        })
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="sanitized")

        with patch("agents.agent_07_runbook.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["runbook_name"] == "OOMKilled Recovery"
        assert result["runbook_version"] == "1.2"

    async def test_normalizes_and_sanitizes_steps(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "runbook_name": "Test",
            "steps": SAMPLE_STEPS,
        })
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="sanitized steps")

        with patch("agents.agent_07_runbook.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert len(result["runbook_steps_raw"]) == 3
        assert result["runbook_steps_text"] == "sanitized steps"

    async def test_sanitizes_incident_context(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "runbook_name": "Test",
            "incident_context": "payment-service OOMKilled",
            "steps": [],
        })
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="sanitized")

        with patch("agents.agent_07_runbook.workflow.shield", shield_mock):
            await wf._ingest_node(state)

        assert shield_mock.sanitize.call_count == 2  # steps + incident_context

    async def test_empty_payload_sets_safe_defaults(self, wf, workspace_id):
        state = _base_state(workspace_id, {})
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="")

        with patch("agents.agent_07_runbook.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["error"] is None
        assert result["runbook_name"] == "Unnamed Runbook"
        assert result["runbook_steps_raw"] == []

    async def test_uses_runbook_steps_key_as_fallback(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "runbook_name": "Test",
            "runbook_steps": SAMPLE_STEPS,  # alternate key
        })
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="text")

        with patch("agents.agent_07_runbook.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert len(result["runbook_steps_raw"]) == 3


# ──────────────────────────────────────────────────────────────────────────────
# RunbookWorkflow._diagnose_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestDiagnoseNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        wf._router = mock_router
        mock_router.complete.return_value = SAMPLE_LLM_RUNBOOK_DIAGNOSIS
        return wf

    async def test_calls_router_with_runbook_automation_task_type(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_RUNBOOK_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_RUNBOOK_DIAGNOSIS, 900)) as mock_llm, \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        assert mock_llm.call_args.kwargs["task_type"] == "runbook_automation"

    async def test_parses_all_llm_fields(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_RUNBOOK_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_RUNBOOK_DIAGNOSIS, 900)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(state)

        assert result["parsed_error"] == parsed["parsed_error"]
        assert result["plan_summary"] == parsed["plan_summary"]
        assert len(result["execution_plan"]) == 3
        assert result["skipped_steps"] == []
        assert result["estimated_duration_seconds"] == 45

    async def test_accumulates_tokens(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        state["tokens_used"] = 200
        parsed = json.loads(SAMPLE_LLM_RUNBOOK_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_RUNBOOK_DIAGNOSIS, 900)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(state)

        assert result["tokens_used"] == 1100

    async def test_sets_error_on_parse_failure(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=("bad json", 100)), \
             patch.object(wf, "parse_llm_json", side_effect=ValueError("JSON parse failed")):
            result = await wf._diagnose_node(state)

        assert result.get("error") is not None

    async def test_calls_check_budget_before_llm(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_RUNBOOK_DIAGNOSIS)
        order = []

        async def mock_budget(*a, **kw): order.append("budget")
        def mock_llm(*a, **kw):
            order.append("llm")
            return (SAMPLE_LLM_RUNBOOK_DIAGNOSIS, 900)

        with patch.object(wf, "check_budget", side_effect=mock_budget), \
             patch.object(wf, "call_llm", side_effect=mock_llm), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        assert order.index("budget") < order.index("llm")

    async def test_user_message_includes_runbook_name_and_incident_context(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_RUNBOOK_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_RUNBOOK_DIAGNOSIS, 900)) as mock_llm, \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        content = mock_llm.call_args.kwargs["messages"][0]["content"]
        assert "OOMKilled Recovery Runbook" in content
        assert "payment-service" in content


# ──────────────────────────────────────────────────────────────────────────────
# RunbookWorkflow._hitl_gate_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestHITLGateNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        return _make_workflow(mock_db, workspace_id, mock_router)

    async def test_calls_create_incident_with_correct_agent_id(self, wf, workspace_id):
        state = _hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_07_runbook.workflow.interrupt", return_value={"id": "hold"}):
            await wf._hitl_gate_node(state)

        call_kwargs = mock_hitl.create_incident.call_args.kwargs
        assert call_kwargs["agent_id"] == "agent_07_runbook"
        assert call_kwargs["workspace_id"] == workspace_id

    async def test_raw_log_includes_runbook_name_and_step_count(self, wf, workspace_id):
        state = _hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_07_runbook.workflow.interrupt", return_value={"id": "hold"}):
            await wf._hitl_gate_node(state)

        raw_log = mock_hitl.create_incident.call_args.kwargs["raw_log"]
        assert "OOMKilled Recovery Runbook" in raw_log
        assert "3" in raw_log  # 3 steps in plan

    async def test_interrupt_includes_steps_count_and_plan_summary(self, wf, workspace_id):
        state = _hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_07_runbook.workflow.interrupt", return_value={"id": "opt_1"}) as mock_interrupt:
            await wf._hitl_gate_node(state)

        interrupt_arg = mock_interrupt.call_args.args[0]
        assert interrupt_arg["steps_count"] == 3
        assert "plan_summary" in interrupt_arg

    async def test_skips_incident_creation_on_error(self, wf, workspace_id):
        state = _hitl_state(workspace_id)
        state["error"] = "LLM failed"

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock()
        mock_hitl.create_failed_incident = AsyncMock(return_value="failed-incident-1")
        wf.hitl = mock_hitl

        result = await wf._hitl_gate_node(state)

        mock_hitl.create_incident.assert_not_called()
        mock_hitl.create_failed_incident.assert_awaited_once()
        assert result == {"incident_id": "failed-incident-1"}


# ──────────────────────────────────────────────────────────────────────────────
# Runbook execution is disabled
# ──────────────────────────────────────────────────────────────────────────────

class TestExecutionDisabled:
    @pytest.fixture
    def tools(self):
        return RunbookTools(github_token="gh_test_token")

    @pytest.fixture
    def context(self):
        return {
            "plan_steps": SAMPLE_STEPS + [SAMPLE_HTTP_STEP],
            "owner": "acme",
            "repo": "ops",
            "report_title": "Runbook Plan: OOMKilled Recovery",
            "report_body": "## Plan",
        }

    def test_no_step_executor_exists(self):
        for name in ("run_shell_step", "run_http_step", "run_kubectl_step", "run_notification_step"):
            assert not hasattr(RunbookTools, name), name

    def test_module_cannot_spawn_processes(self):
        assert not hasattr(runbook_tools, "asyncio")
        assert not hasattr(runbook_tools, "shlex")
        assert not hasattr(runbook_tools, "subprocess")

    def test_no_plan_executor_exists(self):
        assert not hasattr(RunbookTools, "execute_runbook_plan")

    def test_run_option_is_not_in_the_catalog(self):
        assert list(runbook_tools.option_catalog({})) == ["opt_2", "hold"]

    async def test_opt1_refuses_without_running_anything(self, tools, context):
        with patch("asyncio.create_subprocess_exec") as spawn, \
             patch("httpx.AsyncClient") as http:
            result = await tools.execute_option({"id": "opt_1"}, context)
        assert result["status"] == "not_available"
        assert result["reason"] == EXECUTION_DISABLED_REASON
        spawn.assert_not_called()
        http.assert_not_called()

    async def test_hold_returns_held(self, tools, context):
        result = await tools.execute_option({"id": "hold"}, context)
        assert result["status"] == "held"

    async def test_opt2_files_the_plan_as_an_issue(self, tools, context):
        expected = {"status": "issue_created", "issue_url": "https://github.com/acme/ops/issues/55", "issue_number": 55}
        with patch.object(tools, "create_runbook_issue", new=AsyncMock(return_value=expected)) as mock_issue:
            result = await tools.execute_option({"id": "opt_2"}, context)
        assert result["status"] == "issue_created"
        assert mock_issue.call_args.kwargs["body"] == "## Plan"

    async def test_unknown_option_returns_not_available(self, tools, context):
        result = await tools.execute_option({"id": "opt_99"}, context)
        assert result["status"] == "not_available"


class TestOfferedOptions:
    async def test_llm_execute_option_is_never_offered_and_plan_issue_always_is(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        parsed = json.loads(SAMPLE_LLM_RUNBOOK_DIAGNOSIS)
        assert parsed["options"][0]["id"] == "opt_1"  # the LLM still proposes it
        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_RUNBOOK_DIAGNOSIS, 900)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(_diagnose_state(workspace_id))
        assert [o["id"] for o in result["remediation_options"]] == ["opt_2", "hold"]
        for opt in result["remediation_options"]:
            assert {"id", "title", "description", "impact", "docs_url"} <= opt.keys()

    async def test_plan_issue_offered_even_when_llm_proposes_only_execution(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        parsed = json.loads(SAMPLE_LLM_RUNBOOK_DIAGNOSIS)
        parsed["options"] = [parsed["options"][0]]  # opt_1 only
        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_RUNBOOK_DIAGNOSIS, 900)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(_diagnose_state(workspace_id))
        assert [o["id"] for o in result["remediation_options"]] == ["opt_2", "hold"]


class TestExecuteAndCompleteNodes:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        wf._tools = RunbookTools(github_token="gh_test_token")
        wf.hitl = MagicMock()
        wf.hitl.mark_failed = AsyncMock()
        wf.hitl.mark_executed = AsyncMock()
        return wf

    def _state(self, workspace_id, option_id):
        s = _hitl_state(workspace_id)
        s["incident_id"] = str(uuid4())
        s["selected_option"] = {"id": option_id}
        return s

    async def test_stale_opt1_approval_is_refused_and_marked_failed(self, wf, workspace_id):
        state = self._state(workspace_id, "opt_1")
        with patch("asyncio.create_subprocess_exec") as spawn:
            out = await wf._execute_node(state)
        spawn.assert_not_called()
        assert out["execution_result"]["status"] == "not_available"
        state.update(out)
        await wf._complete_node(state)
        wf.hitl.mark_failed.assert_awaited_once()
        assert wf.hitl.mark_failed.call_args.kwargs["reason"] == EXECUTION_DISABLED_REASON
        wf.hitl.mark_executed.assert_not_called()

    async def test_opt2_issue_body_is_the_plan(self, wf, workspace_id):
        state = self._state(workspace_id, "opt_2")
        created = {"status": "issue_created", "issue_url": "u", "issue_number": 1}
        with patch.object(wf._tools, "create_runbook_issue", new=AsyncMock(return_value=created)) as mk:
            out = await wf._execute_node(state)
        assert out["execution_result"]["status"] == "issue_created"
        body = mk.call_args.kwargs["body"]
        assert "not executed" in body and "Check pod status" in body
        state.update(out)
        await wf._complete_node(state)
        wf.hitl.mark_executed.assert_awaited_once()

    async def test_opt2_failure_is_marked_failed(self, wf, workspace_id):
        state = self._state(workspace_id, "opt_2")
        wf._tools.github_token = ""
        out = await wf._execute_node(state)
        assert out["execution_result"]["status"] == "failed"
        state.update(out)
        await wf._complete_node(state)
        wf.hitl.mark_failed.assert_awaited_once()
        wf.hitl.mark_executed.assert_not_called()


class TestBuildPlanReport:
    def test_lists_steps_and_says_not_executed(self):
        report = _build_plan_report("OOMKilled Recovery", "1.2", "ctx", "summary", SAMPLE_STEPS, [])
        assert "OOMKilled Recovery" in report and "1.2" in report
        assert "not executed" in report
        assert "Check pod status" in report and "kubectl get pods" in report

    def test_handles_empty_plan_and_skipped_steps(self):
        report = _build_plan_report("R", "1", "", "", [], [{"id": "s4", "reason": "irrelevant"}])
        assert "No steps in the plan" in report
        assert "irrelevant" in report
