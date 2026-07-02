"""
tests/test_agent07.py
Tests for agents/agent_07_runbook/tools.py and workflow.py.

What this file validates:
  RunbookTools — step executors:
    - run_shell_step() executes a command and captures stdout/stderr/exit_code
    - run_shell_step() returns failed on non-zero exit code
    - run_shell_step() returns failed on timeout
    - run_shell_step() returns skipped when allow_shell=False
    - run_http_step() makes the correct HTTP request and returns status_code
    - run_http_step() returns failed on non-2xx response
    - run_http_step() returns failed on network error
    - run_notification_step() POSTs to Slack webhook
    - run_notification_step() returns skipped when SLACK_WEBHOOK_URL missing
    - run_notification_step() posts GitHub comment when channel=github_comment
    - create_runbook_issue() creates GitHub issue with runbook labels
    - create_runbook_issue() raises EnvironmentError when GITHUB_TOKEN missing

  RunbookTools — execute_runbook_plan():
    - Executes steps in order and aggregates results
    - Stops on failure when on_failure=stop
    - Continues on failure when on_failure=continue
    - Skips steps with skip_to when on_failure=skip_to:<id>
    - Returns correct succeeded/failed/skipped counts
    - Caps plan at MAX_STEPS_PER_RUN
    - Returns skipped for empty plan

  RunbookTools — execute_option():
    - hold → returns held without any execution
    - opt_1 → dispatches to execute_runbook_plan
    - opt_1 with empty plan → returns skipped
    - opt_2 → dispatches to create_runbook_issue
    - unknown option → returns not_implemented

  _substitute():
    - Replaces known {{key}} placeholders from context
    - Leaves unknown {{key}} as-is
    - Handles empty context

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
    - Parses all LLM fields: execution_plan, skipped_steps, plan_summary, options
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

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch, call
from uuid import uuid4

import pytest

from agents.agent_07_runbook.tools import (
    RunbookTools,
    _substitute,
    _summarize_step_results,
)
from agents.agent_07_runbook.workflow import (
    RunbookWorkflow,
    RunbookState,
    _normalize_runbook_steps,
    _build_execution_report,
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
# _substitute() helper
# ──────────────────────────────────────────────────────────────────────────────

class TestSubstitute:
    def test_replaces_known_key(self):
        result = _substitute("kubectl get pods -n {{namespace}}", {"namespace": "production"})
        assert result == "kubectl get pods -n production"

    def test_leaves_unknown_key_as_is(self):
        result = _substitute("kubectl logs {{pod_name}}", {})
        assert result == "kubectl logs {{pod_name}}"

    def test_replaces_multiple_keys(self):
        result = _substitute(
            "kubectl logs -n {{namespace}} {{pod_name}} --tail=50",
            {"namespace": "production", "pod_name": "payment-abc"},
        )
        assert "production" in result
        assert "payment-abc" in result

    def test_handles_empty_context(self):
        result = _substitute("echo {{missing}}", {})
        assert result == "echo {{missing}}"

    def test_handles_empty_template(self):
        assert _substitute("", {"key": "value"}) == ""


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
# RunbookTools — run_shell_step()
# ──────────────────────────────────────────────────────────────────────────────

class TestRunShellStep:
    @pytest.fixture
    def tools(self):
        return RunbookTools(allow_shell=True)

    async def test_executes_command_and_returns_stdout(self, tools):
        step = {"id": "step-01", "command": "echo hello_world", "timeout_seconds": 5}
        result = await tools.run_shell_step(step, {})
        assert result["status"] == "ok"
        assert "hello_world" in result["stdout"]
        assert result["exit_code"] == 0

    async def test_returns_failed_on_nonzero_exit(self, tools):
        step = {"id": "step-01", "command": "false", "timeout_seconds": 5}
        result = await tools.run_shell_step(step, {})
        assert result["status"] == "failed"
        assert result["exit_code"] != 0

    async def test_returns_skipped_when_shell_disabled(self):
        no_shell = RunbookTools(allow_shell=False)
        step = {"id": "step-01", "command": "echo hi"}
        result = await no_shell.run_shell_step(step, {})
        assert result["status"] == "skipped"

    async def test_substitutes_context_variables_in_command(self, tools):
        step = {"id": "step-01", "command": "echo {{namespace}}", "timeout_seconds": 5}
        result = await tools.run_shell_step(step, {"namespace": "production"})
        assert "production" in result["stdout"]

    async def test_returns_failed_on_timeout(self, tools):
        step = {"id": "step-01", "command": "sleep 10", "timeout_seconds": 1}
        result = await tools.run_shell_step(step, {})
        assert result["status"] == "failed"
        assert "timed out" in result["error"].lower()

    async def test_caps_timeout_at_max(self, tools):
        step = {"id": "step-01", "command": "echo ok", "timeout_seconds": 9999}

        captured_timeout = {}
        original_wait_for = asyncio.wait_for

        async def mock_wait_for(coro, timeout):
            captured_timeout["timeout"] = timeout
            return await original_wait_for(coro, timeout)

        with patch("agents.agent_07_runbook.tools.asyncio.wait_for", side_effect=mock_wait_for):
            await tools.run_shell_step(step, {})

        assert captured_timeout.get("timeout", 9999) <= 120


# ──────────────────────────────────────────────────────────────────────────────
# RunbookTools — run_http_step()
# ──────────────────────────────────────────────────────────────────────────────

class TestRunHTTPStep:
    @pytest.fixture
    def tools(self):
        return RunbookTools()

    async def test_makes_request_with_correct_method_and_url(self, tools):
        resp = _make_http_resp(200, {"ok": True})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.request = AsyncMock(return_value=resp)

        with patch("agents.agent_07_runbook.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.run_http_step(SAMPLE_HTTP_STEP, {"deployment_name": "payment", "api_token": "tok"})

        assert result["status"] == "ok"
        assert result["status_code"] == 200
        call_kwargs = ctx.request.call_args.kwargs
        assert call_kwargs["method"] == "POST"
        assert "payment" in call_kwargs["url"]

    async def test_returns_failed_on_4xx_response(self, tools):
        resp = _make_http_resp(404, {"error": "not found"})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.request = AsyncMock(return_value=resp)

        with patch("agents.agent_07_runbook.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.run_http_step(SAMPLE_HTTP_STEP, {})

        assert result["status"] == "failed"
        assert result["status_code"] == 404

    async def test_returns_failed_on_network_error(self, tools):
        import httpx as httpx_mod
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.request = AsyncMock(side_effect=httpx_mod.RequestError("connection refused"))

        with patch("agents.agent_07_runbook.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.run_http_step(SAMPLE_HTTP_STEP, {})

        assert result["status"] == "failed"
        assert "connection refused" in result["error"]


# ──────────────────────────────────────────────────────────────────────────────
# RunbookTools — run_notification_step()
# ──────────────────────────────────────────────────────────────────────────────

class TestRunNotificationStep:
    @pytest.fixture
    def tools(self):
        return RunbookTools(slack_webhook_url="https://hooks.slack.com/services/T000/B000/abc")

    async def test_posts_to_slack_webhook(self, tools):
        ok_resp = MagicMock(status_code=200, text="ok")
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=ok_resp)

        step = {"id": "notif-01", "channel": "slack", "message": "Done: {{deployment_name}}"}
        with patch("agents.agent_07_runbook.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.run_notification_step(step, {"deployment_name": "payment-service"})

        assert result["status"] == "ok"
        payload = ctx.post.call_args.kwargs["json"]
        assert "payment-service" in payload["text"]

    async def test_returns_skipped_when_slack_url_missing(self):
        no_slack = RunbookTools(slack_webhook_url="")
        step = {"id": "notif-01", "channel": "slack", "message": "done"}
        result = await no_slack.run_notification_step(step, {})
        assert result["status"] == "skipped"

    async def test_posts_github_comment(self, tools):
        tools.github_token = "gh_test_token"
        ok_resp = _make_http_resp(201, {"id": 123})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=ok_resp)

        step = {"id": "notif-02", "channel": "github_comment", "message": "Runbook complete"}
        context = {"owner": "acme", "repo": "ops", "github_issue_number": "42"}
        with patch("agents.agent_07_runbook.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.run_notification_step(step, context)

        assert result["status"] == "ok"
        call_url = ctx.post.call_args.args[0]
        assert "acme/ops/issues/42/comments" in call_url


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
# RunbookTools — execute_runbook_plan()
# ──────────────────────────────────────────────────────────────────────────────

class TestExecuteRunbookPlan:
    @pytest.fixture
    def tools(self):
        return RunbookTools(allow_shell=True)

    async def test_executes_steps_in_order_and_aggregates_counts(self, tools):
        shell_step = {"id": "s1", "type": "shell", "command": "echo ok", "on_failure": "continue"}
        with patch.object(tools, "run_shell_step", new=AsyncMock(return_value={"status": "ok", "step_id": "s1"})) as mock_sh:
            result = await tools.execute_runbook_plan([shell_step, {**shell_step, "id": "s2"}], {})

        assert result["status"] == "ok"
        assert result["steps_succeeded"] == 2
        assert result["steps_failed"] == 0
        assert mock_sh.call_count == 2

    async def test_stops_on_failure_when_on_failure_is_stop(self, tools):
        steps = [
            {"id": "s1", "type": "shell", "command": "false", "on_failure": "stop"},
            {"id": "s2", "type": "shell", "command": "echo ok", "on_failure": "continue"},
        ]
        with patch.object(tools, "run_shell_step", new=AsyncMock(side_effect=[
            {"status": "failed", "step_id": "s1"},
            {"status": "ok", "step_id": "s2"},
        ])) as mock_sh:
            result = await tools.execute_runbook_plan(steps, {})

        assert result["steps_failed"] == 1
        assert mock_sh.call_count == 1  # stopped after s1

    async def test_continues_on_failure_when_on_failure_is_continue(self, tools):
        steps = [
            {"id": "s1", "type": "shell", "command": "false", "on_failure": "continue"},
            {"id": "s2", "type": "shell", "command": "echo ok", "on_failure": "continue"},
        ]
        with patch.object(tools, "run_shell_step", new=AsyncMock(side_effect=[
            {"status": "failed", "step_id": "s1"},
            {"status": "ok", "step_id": "s2"},
        ])):
            result = await tools.execute_runbook_plan(steps, {})

        assert result["steps_failed"] == 1
        assert result["steps_succeeded"] == 1

    async def test_skip_to_jumps_to_target_step(self, tools):
        steps = [
            {"id": "s1", "type": "shell", "command": "false", "on_failure": "skip_to:s3"},
            {"id": "s2", "type": "shell", "command": "echo skip_me", "on_failure": "continue"},
            {"id": "s3", "type": "shell", "command": "echo ok", "on_failure": "continue"},
        ]

        call_ids = []

        async def track_shell(step, ctx):
            call_ids.append(step["id"])
            return {"status": "failed" if step["id"] == "s1" else "ok", "step_id": step["id"]}

        with patch.object(tools, "run_shell_step", side_effect=track_shell):
            result = await tools.execute_runbook_plan(steps, {})

        assert "s2" not in call_ids  # bypassed — index jumps directly to s3
        assert "s3" in call_ids
        # s2 is absent from step_results; the implementation jumps directly to the target index
        s2_result = next((r for r in result["step_results"] if r.get("step_id") == "s2"), None)
        assert s2_result is None

    async def test_returns_partial_status_when_some_fail(self, tools):
        steps = [
            {"id": "s1", "type": "shell", "command": "echo ok", "on_failure": "continue"},
            {"id": "s2", "type": "shell", "command": "false", "on_failure": "continue"},
        ]
        with patch.object(tools, "run_shell_step", new=AsyncMock(side_effect=[
            {"status": "ok", "step_id": "s1"},
            {"status": "failed", "step_id": "s2"},
        ])):
            result = await tools.execute_runbook_plan(steps, {})

        assert result["status"] == "partial"

    async def test_caps_plan_at_max_steps(self, tools):
        many = [{"id": f"s{i}", "type": "shell", "command": "echo ok", "on_failure": "continue"} for i in range(60)]
        with patch.object(tools, "run_shell_step", new=AsyncMock(return_value={"status": "ok", "step_id": "x"})) as mock_sh:
            await tools.execute_runbook_plan(many, {})

        assert mock_sh.call_count <= 50


# ──────────────────────────────────────────────────────────────────────────────
# RunbookTools — execute_option()
# ──────────────────────────────────────────────────────────────────────────────

class TestExecuteOption:
    @pytest.fixture
    def tools(self):
        return RunbookTools(github_token="gh_test_token", allow_shell=True)

    @pytest.fixture
    def context(self):
        return {
            "plan_steps": SAMPLE_STEPS,
            "owner": "acme",
            "repo": "ops",
            "report_title": "Runbook: OOMKilled Recovery",
            "report_body": "## Dry Run Plan",
            "runbook_name": "OOMKilled Recovery",
            "incident_context": "payment-service OOMKilled",
        }

    async def test_hold_returns_held_without_execution(self, tools, context):
        with patch.object(tools, "execute_runbook_plan") as mock_exec:
            result = await tools.execute_option({"id": "hold"}, context)
        assert result["status"] == "held"
        mock_exec.assert_not_called()

    async def test_opt1_dispatches_to_execute_runbook_plan(self, tools, context):
        expected = {"status": "ok", "steps_total": 3, "steps_succeeded": 3, "steps_failed": 0, "steps_skipped": 0, "step_results": []}
        with patch.object(tools, "execute_runbook_plan", new=AsyncMock(return_value=expected)) as mock_exec:
            result = await tools.execute_option({"id": "opt_1"}, context)
        assert result["status"] == "ok"
        mock_exec.assert_called_once_with(SAMPLE_STEPS, context)

    async def test_opt1_with_empty_plan_returns_skipped(self, tools, context):
        context["plan_steps"] = []
        result = await tools.execute_option({"id": "opt_1"}, context)
        assert result["status"] == "skipped"

    async def test_opt2_dispatches_to_create_runbook_issue(self, tools, context):
        expected = {"status": "issue_created", "issue_url": "https://github.com/acme/ops/issues/55", "issue_number": 55}
        with patch.object(tools, "create_runbook_issue", new=AsyncMock(return_value=expected)) as mock_issue:
            result = await tools.execute_option({"id": "opt_2"}, context)
        assert result["status"] == "issue_created"
        mock_issue.assert_called_once()

    async def test_unknown_option_returns_not_implemented(self, tools, context):
        result = await tools.execute_option({"id": "opt_99"}, context)
        assert result["status"] == "not_implemented"


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
        wf.hitl = mock_hitl

        result = await wf._hitl_gate_node(state)

        mock_hitl.create_incident.assert_not_called()
        assert result == {}


# ──────────────────────────────────────────────────────────────────────────────
# _build_execution_report()
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildExecutionReport:
    def test_includes_runbook_name_and_version(self):
        report = _build_execution_report(
            runbook_name="OOMKilled Recovery",
            runbook_version="1.2",
            incident_context="payment-service crashed",
            plan_summary="Run 3 steps",
            step_results=[{"step_id": "s1", "status": "ok"}],
            skipped_steps=[],
            overall_status="ok",
        )
        assert "OOMKilled Recovery" in report
        assert "1.2" in report

    def test_includes_correct_status_icon(self):
        ok_report = _build_execution_report("R", "1", "", "", [], [], "ok")
        fail_report = _build_execution_report("R", "1", "", "", [], [], "failed")
        partial_report = _build_execution_report("R", "1", "", "", [], [], "partial")
        assert "✅" in ok_report
        assert "❌" in fail_report
        assert "⚠️" in partial_report

    def test_includes_step_results_table(self):
        results = [
            {"step_id": "s1", "status": "ok"},
            {"step_id": "s2", "status": "failed", "error": "command not found"},
        ]
        report = _build_execution_report("R", "1", "", "", results, [], "partial")
        assert "s1" in report
        assert "s2" in report

    def test_includes_cloud_decoded_attribution(self):
        report = _build_execution_report("R", "1", "", "", [], [], "ok")
        assert "Cloud Decoded" in report
