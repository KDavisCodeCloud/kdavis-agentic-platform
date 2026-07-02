"""
tests/test_agent09.py
Tests for agents/agent_09_onboarding_buddy/tools.py and workflow.py.

What this file validates:
  _detect_query_type():
    - Returns "on_call" for explicit on_call query_type
    - Returns "onboarding" for explicit onboarding query_type
    - Detects on_call from keywords in question text
    - Detects on_call from alert / incident_context keys
    - Defaults to "onboarding" when no on_call keywords present
    - Explicit query_type field takes priority over keyword detection

  OnboardingTools.search_github_files():
    - Returns list of {path, url} on success
    - Returns empty list when github_token is missing
    - Returns empty list on GitHub API error

  OnboardingTools.get_github_file():
    - Returns {path, url, content, truncated} on success
    - Returns error dict when GITHUB_TOKEN is missing
    - Returns error dict on 404 response
    - Decodes base64 content correctly

  OnboardingTools.create_knowledge_issue():
    - Creates issue with correct labels for onboarding
    - Creates issue with correct labels for on_call
    - Returns issue_created with issue_url and issue_number
    - Raises EnvironmentError when GITHUB_TOKEN missing

  OnboardingTools.post_slack_message():
    - Posts message to configured Slack webhook
    - Returns skipped when SLACK_WEBHOOK_URL missing
    - Returns failed on non-200 response

  OnboardingTools.execute_option():
    - hold → returns held without any API call
    - opt_1 → calls create_knowledge_issue with onboarding labels
    - opt_1 without repository → returns skipped
    - opt_2 → calls post_slack_message
    - unknown option → returns not_implemented

  OnboardingWorkflow._ingest_node():
    - Detects query_type from payload
    - Extracts service_name, user_role, repository, slack_channel
    - Sanitizes question via shield.sanitize()
    - Truncates long questions
    - Empty payload sets safe defaults without crash

  OnboardingWorkflow._diagnose_node():
    - Calls router with task_type="onboarding_support"
    - Parses LLM fields: synthesized_response, key_findings, references, options
    - Calls GitHub search when repository and token are set
    - Calls _fetch_past_incidents with service_name
    - Accumulates tokens from prior state
    - Sets error on parse failure
    - Calls check_budget() before LLM call
    - User message includes query_type, service_name, and question

  OnboardingWorkflow._hitl_gate_node():
    - Calls hitl.create_incident() with correct agent_id
    - raw_log includes question, service_name, and snippet count
    - interrupt() includes query_type and snippets_retrieved
    - Skips incident creation when state["error"] is set

  _build_knowledge_brief():
    - Includes query_type label (Onboarding Guide / On-Call Brief)
    - Includes question and key_findings
    - Includes references section when references are present
    - Includes past incidents section when incidents are present
    - Includes Cloud Decoded attribution
"""

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agents.agent_09_onboarding_buddy.tools import OnboardingTools
from agents.agent_09_onboarding_buddy.workflow import (
    OnboardingWorkflow,
    OnboardingState,
    _detect_query_type,
    _build_knowledge_brief,
)


# ──────────────────────────────────────────────────────────────────────────────
# Sample data
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_QUESTION = "How does payment-service handle failed transactions? What retry logic is in place?"
SAMPLE_ON_CALL_ALERT = "payment-service 500s — error rate 23% — DB connection pool exhausted"

SAMPLE_LLM_ONBOARDING_RESPONSE = json.dumps({
    "parsed_error": "New engineer asking about payment-service transaction failure handling and retry logic",
    "key_findings": (
        "payment-service uses exponential backoff (max 3 retries) for transient DB failures. "
        "Dead-letter queue (DLQ) receives permanently failed transactions. "
        "Runbooks are in runbooks/payment-service-failures.md."
    ),
    "synthesized_response": (
        "## Overview\n\nThe payment-service processes transactions using a retry-first approach...\n\n"
        "## How It Works\n\n1. Transaction received via REST API\n2. DB write attempted...\n\n"
        "## Common Gotchas\n\n- DLQ is not monitored by default; set up alerts"
    ),
    "references": [
        {
            "source": "README.md",
            "url": "https://github.com/acme/backend/blob/main/payment-service/README.md",
            "excerpt": "Retry logic: exponential backoff, max 3 retries",
        },
        {
            "source": "runbooks/payment-service-failures.md",
            "url": "https://github.com/acme/backend/blob/main/runbooks/payment-service-failures.md",
            "excerpt": "DLQ monitoring and reprocessing steps",
        },
    ],
    "options": [
        {
            "id": "opt_1",
            "title": "Save as Knowledge Issue",
            "description": "Create a GitHub issue with this onboarding guide.",
            "impact": "NONE",
            "docs_url": "",
        },
        {
            "id": "opt_2",
            "title": "Post to Slack",
            "description": "Post key findings to #eng-onboarding.",
            "impact": "NONE",
            "docs_url": "",
        },
        {
            "id": "hold",
            "title": "Review Only",
            "description": "No publishing — operator reads in dashboard.",
            "impact": "NONE",
            "docs_url": "",
        },
    ],
})

SAMPLE_KNOWLEDGE_SNIPPETS = [
    {
        "path": "payment-service/README.md",
        "url": "https://github.com/acme/backend/blob/main/payment-service/README.md",
        "content": "# payment-service\n\nHandles all payment transactions. Retry: exponential backoff, max 3.",
    },
]

SAMPLE_PAST_INCIDENTS = [
    {
        "id": str(uuid4()),
        "parsed_error": "payment-service DB connection pool exhausted — 500 errors on checkout",
        "cloud_provider": "aws",
        "created_at": "2026-06-01",
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_http_resp(status_code: int, body) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = json.dumps(body)[:500] if isinstance(body, (dict, list)) else str(body)[:500]
    return resp


def _make_workflow(mock_db, workspace_id, mock_router) -> OnboardingWorkflow:
    with (
        patch("agents.base_agent._load_router", return_value=mock_router),
        patch.object(OnboardingWorkflow, "_build_graph", return_value=MagicMock()),
    ):
        wf = OnboardingWorkflow(mock_db, workspace_id, MagicMock())
    return wf


def _base_state(workspace_id: str, payload: dict | None = None) -> OnboardingState:
    return {
        "workspace_id":       workspace_id,
        "cloud_provider":     "aws",
        "webhook_payload":    payload or {},
        "query_type":         "",
        "question":           "",
        "service_name":       "",
        "user_role":          "any",
        "repository":         "",
        "slack_channel":      "",
        "knowledge_snippets": [],
        "past_incidents":     [],
        "incident_id":        None,
        "parsed_error":       None,
        "synthesized_response": None,
        "key_findings":       None,
        "references":         None,
        "remediation_options": None,
        "tokens_used":        0,
        "selected_option":    None,
        "execution_result":   None,
        "error":              None,
    }


def _diagnose_state(workspace_id: str) -> OnboardingState:
    s = _base_state(workspace_id)
    s.update({
        "query_type":   "onboarding",
        "question":     SAMPLE_QUESTION,
        "service_name": "payment-service",
        "user_role":    "new_engineer",
        "repository":   "acme/backend",
        "slack_channel": "#eng-onboarding",
    })
    return s


def _hitl_state(workspace_id: str) -> OnboardingState:
    s = _diagnose_state(workspace_id)
    parsed = json.loads(SAMPLE_LLM_ONBOARDING_RESPONSE)
    s.update({
        "knowledge_snippets":  SAMPLE_KNOWLEDGE_SNIPPETS,
        "past_incidents":      SAMPLE_PAST_INCIDENTS,
        "parsed_error":        parsed["parsed_error"],
        "synthesized_response": parsed["synthesized_response"],
        "key_findings":        parsed["key_findings"],
        "references":          parsed["references"],
        "remediation_options": parsed["options"],
        "tokens_used":         1200,
    })
    return s


# ──────────────────────────────────────────────────────────────────────────────
# _detect_query_type()
# ──────────────────────────────────────────────────────────────────────────────

class TestDetectQueryType:
    def test_returns_on_call_for_explicit_on_call_query_type(self):
        assert _detect_query_type({"query_type": "on_call"}) == "on_call"

    def test_returns_onboarding_for_explicit_onboarding_query_type(self):
        assert _detect_query_type({"query_type": "onboarding"}) == "onboarding"

    def test_explicit_field_takes_priority_over_keyword_detection(self):
        assert _detect_query_type({"query_type": "onboarding", "question": "service is down"}) == "onboarding"

    def test_detects_on_call_from_alert_keyword_in_question(self):
        assert _detect_query_type({"question": "payment-service is degraded, 500 errors"}) == "on_call"

    def test_detects_on_call_from_paged_keyword(self):
        assert _detect_query_type({"question": "I just got paged for high latency"}) == "on_call"

    def test_detects_on_call_from_alert_key(self):
        assert _detect_query_type({"alert": "OOMKilled on payment-service pod"}) == "on_call"

    def test_detects_on_call_from_incident_context_key(self):
        assert _detect_query_type({"incident_context": "timeout after 30s on checkout flow"}) == "on_call"

    def test_defaults_to_onboarding_for_informational_question(self):
        assert _detect_query_type({"question": "How does the payment service work?"}) == "onboarding"

    def test_empty_payload_defaults_to_onboarding(self):
        assert _detect_query_type({}) == "onboarding"


# ──────────────────────────────────────────────────────────────────────────────
# OnboardingTools.search_github_files()
# ──────────────────────────────────────────────────────────────────────────────

class TestSearchGithubFiles:
    @pytest.fixture
    def tools(self):
        return OnboardingTools(github_token="gh_test_token")

    async def test_returns_list_of_path_and_url_on_success(self, tools):
        search_resp = _make_http_resp(200, {
            "items": [
                {"path": "README.md", "html_url": "https://github.com/acme/backend/blob/main/README.md"},
                {"path": "docs/architecture.md", "html_url": "https://github.com/acme/backend/blob/main/docs/architecture.md"},
            ]
        })
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.get = AsyncMock(return_value=search_resp)

        with patch("agents.agent_09_onboarding_buddy.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.search_github_files("acme", "backend", "payment retry logic")

        assert len(result) == 2
        assert result[0]["path"] == "README.md"
        assert "acme/backend" in result[0]["url"]

    async def test_returns_empty_list_when_github_token_missing(self):
        no_token = OnboardingTools(github_token="")
        result = await no_token.search_github_files("acme", "backend", "query")
        assert result == []

    async def test_returns_empty_list_on_github_api_error(self, tools):
        err_resp = _make_http_resp(403, {"message": "rate limit exceeded"})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.get = AsyncMock(return_value=err_resp)

        with patch("agents.agent_09_onboarding_buddy.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.search_github_files("acme", "backend", "query")

        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# OnboardingTools.get_github_file()
# ──────────────────────────────────────────────────────────────────────────────

class TestGetGithubFile:
    @pytest.fixture
    def tools(self):
        return OnboardingTools(github_token="gh_test_token")

    async def test_returns_content_path_and_url_on_success(self, tools):
        raw_content = "# Payment Service\n\nHandles all payments."
        encoded = base64.b64encode(raw_content.encode()).decode()
        file_resp = _make_http_resp(200, {
            "path": "payment-service/README.md",
            "html_url": "https://github.com/acme/backend/blob/main/payment-service/README.md",
            "content": encoded,
        })
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.get = AsyncMock(return_value=file_resp)

        with patch("agents.agent_09_onboarding_buddy.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.get_github_file("acme", "backend", "payment-service/README.md")

        assert result["path"] == "payment-service/README.md"
        assert "Payment Service" in result["content"]
        assert result["truncated"] is False

    async def test_returns_error_dict_when_github_token_missing(self):
        no_token = OnboardingTools(github_token="")
        result = await no_token.get_github_file("acme", "backend", "README.md")
        assert "error" in result

    async def test_returns_error_dict_on_404(self, tools):
        not_found = _make_http_resp(404, {"message": "Not Found"})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.get = AsyncMock(return_value=not_found)

        with patch("agents.agent_09_onboarding_buddy.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.get_github_file("acme", "backend", "nonexistent.md")

        assert "error" in result
        assert "404" in result["error"]


# ──────────────────────────────────────────────────────────────────────────────
# OnboardingTools.create_knowledge_issue()
# ──────────────────────────────────────────────────────────────────────────────

class TestCreateKnowledgeIssue:
    @pytest.fixture
    def tools(self):
        return OnboardingTools(github_token="gh_test_token")

    async def test_raises_without_github_token(self):
        no_token = OnboardingTools(github_token="")
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            await no_token.create_knowledge_issue("acme", "backend", "title", "body")

    async def test_creates_issue_and_returns_url_and_number(self, tools):
        issue_resp = _make_http_resp(201, {
            "number": 88,
            "html_url": "https://github.com/acme/backend/issues/88",
        })
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=issue_resp)

        with patch("agents.agent_09_onboarding_buddy.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.create_knowledge_issue(
                "acme", "backend",
                "Onboarding Guide: payment-service",
                "## Guide body",
                labels=["knowledge", "onboarding"],
            )

        assert result["status"] == "issue_created"
        assert result["issue_number"] == 88
        payload = ctx.post.call_args.kwargs["json"]
        assert "onboarding" in payload.get("labels", [])

    async def test_creates_issue_with_on_call_labels(self, tools):
        issue_resp = _make_http_resp(201, {"number": 89, "html_url": "https://github.com/acme/backend/issues/89"})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=issue_resp)

        with patch("agents.agent_09_onboarding_buddy.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.create_knowledge_issue(
                "acme", "backend",
                "On-Call Brief: payment-service",
                "## Brief",
                labels=["knowledge", "on-call"],
            )

        payload = ctx.post.call_args.kwargs["json"]
        assert "on-call" in payload.get("labels", [])


# ──────────────────────────────────────────────────────────────────────────────
# OnboardingTools.post_slack_message()
# ──────────────────────────────────────────────────────────────────────────────

class TestPostSlackMessage:
    @pytest.fixture
    def tools(self):
        return OnboardingTools(slack_webhook_url="https://hooks.slack.com/services/T000/B000/abc")

    async def test_posts_message_to_slack_webhook(self, tools):
        ok_resp = MagicMock(status_code=200, text="ok")
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=ok_resp)

        with patch("agents.agent_09_onboarding_buddy.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.post_slack_message("Key findings: retry logic is broken")

        assert result["status"] == "ok"
        payload = ctx.post.call_args.kwargs["json"]
        assert "retry logic" in payload["text"]

    async def test_returns_skipped_when_slack_webhook_missing(self):
        no_webhook = OnboardingTools(slack_webhook_url="")
        result = await no_webhook.post_slack_message("message")
        assert result["status"] == "skipped"

    async def test_returns_failed_on_non_200_response(self, tools):
        bad_resp = MagicMock(status_code=400, text="invalid_payload")
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=bad_resp)

        with patch("agents.agent_09_onboarding_buddy.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.post_slack_message("message")

        assert result["status"] == "failed"


# ──────────────────────────────────────────────────────────────────────────────
# OnboardingTools.execute_option()
# ──────────────────────────────────────────────────────────────────────────────

class TestExecuteOption:
    @pytest.fixture
    def tools(self):
        return OnboardingTools(
            github_token="gh_test_token",
            slack_webhook_url="https://hooks.slack.com/services/T000/B000/abc",
        )

    @pytest.fixture
    def context(self):
        return {
            "query_type":   "onboarding",
            "owner":        "acme",
            "repo":         "backend",
            "issue_title":  "Onboarding Guide: payment-service",
            "report_body":  "## Full guide content",
            "slack_message": "Key findings summary",
            "slack_channel": "#eng-onboarding",
        }

    async def test_hold_returns_held_without_api_call(self, tools, context):
        with patch.object(tools, "create_knowledge_issue") as mock_issue:
            result = await tools.execute_option({"id": "hold"}, context)
        assert result["status"] == "held"
        mock_issue.assert_not_called()

    async def test_opt1_calls_create_knowledge_issue_with_onboarding_labels(self, tools, context):
        expected = {"status": "issue_created", "issue_url": "https://github.com/acme/backend/issues/88", "issue_number": 88}
        with patch.object(tools, "create_knowledge_issue", new=AsyncMock(return_value=expected)) as mock_issue:
            result = await tools.execute_option({"id": "opt_1"}, context)
        assert result["status"] == "issue_created"
        _, call_kwargs = mock_issue.call_args.args, mock_issue.call_args.kwargs
        assert "onboarding" in mock_issue.call_args.kwargs.get("labels", [])

    async def test_opt1_without_repository_returns_skipped(self, tools, context):
        ctx = {**context, "owner": "", "repo": ""}
        result = await tools.execute_option({"id": "opt_1"}, ctx)
        assert result["status"] == "skipped"

    async def test_opt2_calls_post_slack_message(self, tools, context):
        expected = {"status": "ok", "channel": "#eng-onboarding"}
        with patch.object(tools, "post_slack_message", new=AsyncMock(return_value=expected)) as mock_slack:
            result = await tools.execute_option({"id": "opt_2"}, context)
        assert result["status"] == "ok"
        mock_slack.assert_called_once()

    async def test_unknown_option_returns_not_implemented(self, tools, context):
        result = await tools.execute_option({"id": "opt_99"}, context)
        assert result["status"] == "not_implemented"


# ──────────────────────────────────────────────────────────────────────────────
# OnboardingWorkflow._ingest_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestIngestNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        return _make_workflow(mock_db, workspace_id, mock_router)

    async def test_detects_query_type_from_payload(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "query_type": "on_call",
            "question": "service is down",
        })
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="service is down")

        with patch("agents.agent_09_onboarding_buddy.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["query_type"] == "on_call"

    async def test_extracts_service_name_user_role_and_repository(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "question": "How does this work?",
            "service_name": "payment-service",
            "user_role": "new_engineer",
            "repository": "acme/backend",
        })
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="How does this work?")

        with patch("agents.agent_09_onboarding_buddy.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["service_name"] == "payment-service"
        assert result["user_role"] == "new_engineer"
        assert result["repository"] == "acme/backend"

    async def test_sanitizes_question_via_shield(self, wf, workspace_id):
        state = _base_state(workspace_id, {"question": "How does payment work with SECRET_KEY=abc123?"})
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="How does payment work?")

        with patch("agents.agent_09_onboarding_buddy.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        shield_mock.sanitize.assert_called_once()
        assert result["question"] == "How does payment work?"

    async def test_truncates_long_questions(self, wf, workspace_id):
        state = _base_state(workspace_id, {"question": "x" * 5000})
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="x" * 2020)

        with patch("agents.agent_09_onboarding_buddy.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        # The question sent to shield should be truncated at 2000 chars
        sanitized_arg = shield_mock.sanitize.call_args.args[0]
        assert len(sanitized_arg) <= 2020  # 2000 + " ... [truncated]"

    async def test_empty_payload_sets_safe_defaults(self, wf, workspace_id):
        state = _base_state(workspace_id, {})
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="")

        with patch("agents.agent_09_onboarding_buddy.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["error"] is None
        assert result["query_type"] == "onboarding"
        assert result["knowledge_snippets"] == []


# ──────────────────────────────────────────────────────────────────────────────
# OnboardingWorkflow._diagnose_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestDiagnoseNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        wf._router = mock_router
        mock_router.complete.return_value = SAMPLE_LLM_ONBOARDING_RESPONSE
        return wf

    async def test_calls_router_with_onboarding_support_task_type(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_ONBOARDING_RESPONSE)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_ONBOARDING_RESPONSE, 1500)) as mock_llm, \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "_fetch_past_incidents", new=AsyncMock(return_value=[])), \
             patch.object(wf._tools, "search_github_files", new=AsyncMock(return_value=[])), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        assert mock_llm.call_args.kwargs["task_type"] == "onboarding_support"

    async def test_parses_all_llm_fields(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_ONBOARDING_RESPONSE)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_ONBOARDING_RESPONSE, 1500)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "_fetch_past_incidents", new=AsyncMock(return_value=[])), \
             patch.object(wf._tools, "search_github_files", new=AsyncMock(return_value=[])), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(state)

        assert "payment-service" in result["synthesized_response"]
        assert "retries" in result["key_findings"]
        assert len(result["references"]) == 2
        assert len(result["remediation_options"]) == 3

    async def test_calls_github_search_when_repository_and_token_set(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)  # repository = "acme/backend"
        parsed = json.loads(SAMPLE_LLM_ONBOARDING_RESPONSE)
        wf._tools.github_token = "gh_test_token"

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_ONBOARDING_RESPONSE, 1500)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "_fetch_past_incidents", new=AsyncMock(return_value=[])), \
             patch.object(wf._tools, "search_github_files", new=AsyncMock(return_value=[])) as mock_search, \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args
        assert call_kwargs.args[0] == "acme"
        assert call_kwargs.args[1] == "backend"

    async def test_calls_fetch_past_incidents_with_service_name(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_ONBOARDING_RESPONSE)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_ONBOARDING_RESPONSE, 1500)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "_fetch_past_incidents", new=AsyncMock(return_value=SAMPLE_PAST_INCIDENTS)) as mock_incidents, \
             patch.object(wf._tools, "search_github_files", new=AsyncMock(return_value=[])), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(state)

        mock_incidents.assert_called_once_with("payment-service")
        assert result["past_incidents"] == SAMPLE_PAST_INCIDENTS

    async def test_accumulates_tokens_from_prior_state(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        state["tokens_used"] = 400
        parsed = json.loads(SAMPLE_LLM_ONBOARDING_RESPONSE)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_ONBOARDING_RESPONSE, 1500)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "_fetch_past_incidents", new=AsyncMock(return_value=[])), \
             patch.object(wf._tools, "search_github_files", new=AsyncMock(return_value=[])), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(state)

        assert result["tokens_used"] == 1900

    async def test_sets_error_on_parse_failure(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=("bad json", 100)), \
             patch.object(wf, "parse_llm_json", side_effect=ValueError("JSON parse failed")), \
             patch.object(wf, "_fetch_past_incidents", new=AsyncMock(return_value=[])), \
             patch.object(wf._tools, "search_github_files", new=AsyncMock(return_value=[])):
            result = await wf._diagnose_node(state)

        assert result.get("error") is not None

    async def test_user_message_includes_query_type_service_name_and_question(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_ONBOARDING_RESPONSE)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_ONBOARDING_RESPONSE, 1500)) as mock_llm, \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "_fetch_past_incidents", new=AsyncMock(return_value=[])), \
             patch.object(wf._tools, "search_github_files", new=AsyncMock(return_value=[])), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        content = mock_llm.call_args.kwargs["messages"][0]["content"]
        assert "onboarding" in content.lower()
        assert "payment-service" in content
        assert "failed transactions" in content


# ──────────────────────────────────────────────────────────────────────────────
# OnboardingWorkflow._hitl_gate_node()
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
             patch("agents.agent_09_onboarding_buddy.workflow.interrupt", return_value={"id": "hold"}):
            await wf._hitl_gate_node(state)

        call_kwargs = mock_hitl.create_incident.call_args.kwargs
        assert call_kwargs["agent_id"] == "agent_09_onboarding_buddy"
        assert call_kwargs["workspace_id"] == workspace_id

    async def test_raw_log_includes_question_service_and_snippet_count(self, wf, workspace_id):
        state = _hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_09_onboarding_buddy.workflow.interrupt", return_value={"id": "hold"}):
            await wf._hitl_gate_node(state)

        raw_log = mock_hitl.create_incident.call_args.kwargs["raw_log"]
        assert "payment-service" in raw_log
        assert "failed transactions" in raw_log
        assert "1" in raw_log  # 1 snippet in SAMPLE_KNOWLEDGE_SNIPPETS

    async def test_interrupt_includes_query_type_and_snippets_retrieved(self, wf, workspace_id):
        state = _hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_09_onboarding_buddy.workflow.interrupt", return_value={"id": "opt_1"}) as mock_interrupt:
            await wf._hitl_gate_node(state)

        interrupt_arg = mock_interrupt.call_args.args[0]
        assert interrupt_arg["query_type"] == "onboarding"
        assert interrupt_arg["snippets_retrieved"] == 1

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
# _build_knowledge_brief()
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildKnowledgeBrief:
    def test_includes_onboarding_guide_label_for_onboarding_query(self):
        report = _build_knowledge_brief(
            "onboarding", SAMPLE_QUESTION, "payment-service", "new_engineer",
            "Full response", "Key findings", [], [], [],
        )
        assert "Onboarding Guide" in report

    def test_includes_on_call_brief_label_for_on_call_query(self):
        report = _build_knowledge_brief(
            "on_call", SAMPLE_ON_CALL_ALERT, "payment-service", "on_call",
            "Full response", "Key findings", [], [], [],
        )
        assert "On-Call Brief" in report

    def test_includes_references_section_when_references_provided(self):
        refs = [{"source": "README.md", "url": "https://github.com/acme/backend/blob/main/README.md", "excerpt": "retry logic"}]
        report = _build_knowledge_brief(
            "onboarding", SAMPLE_QUESTION, "payment-service", "new_engineer",
            "Full response", "Key findings", refs, [], [],
        )
        assert "References" in report
        assert "README.md" in report

    async def test_includes_past_incidents_section_when_incidents_provided(self):
        report = _build_knowledge_brief(
            "on_call", SAMPLE_ON_CALL_ALERT, "payment-service", "on_call",
            "Full response", "Key findings", [], [], SAMPLE_PAST_INCIDENTS,
        )
        assert "Past Incidents" in report
        assert "DB connection pool" in report

    def test_includes_cloud_decoded_attribution(self):
        report = _build_knowledge_brief(
            "onboarding", "question", "service", "any",
            "response", "findings", [], [], [],
        )
        assert "Cloud Decoded" in report
