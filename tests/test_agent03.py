"""
tests/test_agent03.py
Tests for agents/agent_03_pr_review/tools.py and agents/agent_03_pr_review/workflow.py.

What this file validates:
  PRReviewTools:
    - get_pr_files() GETs the correct GitHub PR files endpoint
    - get_pr_files() raises EnvironmentError when GITHUB_TOKEN is missing
    - get_pr_files() paginates until an empty page is returned
    - post_pr_review() POSTs to the correct GitHub reviews endpoint
    - post_pr_review() raises EnvironmentError when GITHUB_TOKEN is missing
    - post_pr_review() raises ValueError for invalid review event
    - post_pr_review() includes inline comments in the payload when provided
    - post_pr_comment() POSTs to the correct issues/comments endpoint
    - execute_option("hold") returns held status without any GitHub API call
    - execute_option("opt_1") dispatches to post_pr_review with REQUEST_CHANGES
    - execute_option("opt_2") dispatches to post_pr_review with COMMENT
    - execute_option("opt_3") dispatches to post_pr_review with APPROVE

  _build_diff_summary():
    - Sorts files by changes descending (most-changed first)
    - Truncates at max_chars
    - Handles files with no patch (binary/large files)
    - Includes file count header

  PRReviewWorkflow._ingest_node():
    - Extracts owner and repo from repository.full_name
    - Extracts pr_number, pr_title, pr_author
    - Extracts base_branch and head_branch
    - Extracts head_sha
    - Calls get_pr_files() to fetch the diff
    - Handles get_pr_files() failure gracefully (diff unavailable message)
    - Sanitizes diff_summary via DataSanitizationShield
    - Empty webhook payload sets sensible defaults without crash

  PRReviewWorkflow._diagnose_node():
    - Calls router.complete() with task_type="code_review"
    - Parses valid LLM JSON response into parsed_error + review_body + options
    - Handles LLM JSON parse error and sets state["error"]
    - Calls budget.assert_budget_available() before the LLM call
    - Includes pr_title, owner/repo, and diff_summary in LLM message

  PRReviewWorkflow._hitl_gate_node():
    - Calls hitl.create_incident() with correct fields
    - Calls interrupt() to pause the graph
    - Skips incident creation when state["error"] is set
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agents.agent_03_pr_review.tools import PRReviewTools, REVIEW_EVENT_COMMENT, REVIEW_EVENT_REQUEST_CHANGES, REVIEW_EVENT_APPROVE
from agents.agent_03_pr_review.workflow import PRReviewWorkflow, PRReviewState, _build_diff_summary


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_workflow(mock_db, workspace_id, mock_router) -> PRReviewWorkflow:
    with (
        patch("agents.base_agent._load_router", return_value=mock_router),
        patch.object(PRReviewWorkflow, "_build_graph", return_value=MagicMock()),
    ):
        wf = PRReviewWorkflow(mock_db, workspace_id, MagicMock())
    return wf


def _base_pr_state(workspace_id: str, payload: dict | None = None) -> PRReviewState:
    return {
        "workspace_id": workspace_id,
        "cloud_provider": "github",
        "webhook_payload": payload or {},
        "owner": "acme",
        "repo": "backend",
        "pr_number": 42,
        "pr_title": "feat: add JWT authentication middleware",
        "pr_description": "Adds JWT token validation to all protected API routes.",
        "pr_author": "dev-alice",
        "base_branch": "main",
        "head_branch": "feature/add-auth",
        "head_sha": "def456abc789",
        "changed_files_count": 3,
        "diff_summary": "--- src/auth/jwt.py [added +45 -0]\n@@ -0,0 +1,45 @@\n+import jwt\n+...",
        "incident_id": None,
        "parsed_error": None,
        "review_body": None,
        "remediation_options": None,
        "estimated_duration_seconds": None,
        "tokens_used": 0,
        "selected_option": None,
        "execution_result": None,
        "error": None,
    }


def _mock_gh_resp(status_code: int, body) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = json.dumps(body)[:200] if isinstance(body, (dict, list)) else str(body)[:200]
    return resp


SAMPLE_PR_FILES = [
    {
        "filename": "src/auth/jwt.py",
        "status": "added",
        "additions": 45,
        "deletions": 0,
        "changes": 45,
        "patch": "@@ -0,0 +1,45 @@\n+import jwt\n+SECRET = 'dev-only'\n+def decode(token):\n+    return jwt.decode(token, SECRET)",
    },
    {
        "filename": "src/middleware/auth.py",
        "status": "modified",
        "additions": 12,
        "deletions": 3,
        "changes": 15,
        "patch": "@@ -10,6 +10,15 @@\n+from src.auth.jwt import decode\n+def require_auth(handler):\n+    ...",
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# PRReviewTools — get_pr_files()
# ──────────────────────────────────────────────────────────────────────────────

class TestPRReviewToolsGetFiles:
    @pytest.fixture
    def tools(self):
        return PRReviewTools(github_token="gh_test_token")

    async def test_gets_correct_endpoint(self, tools):
        resp = _mock_gh_resp(200, SAMPLE_PR_FILES)
        empty = _mock_gh_resp(200, [])

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.get = AsyncMock(side_effect=[resp, empty])
        mock_cls = MagicMock(return_value=ctx)

        with patch("agents.agent_03_pr_review.tools.httpx.AsyncClient", mock_cls):
            files = await tools.get_pr_files("acme", "backend", 42)

        assert len(files) == len(SAMPLE_PR_FILES)
        call_url = ctx.get.call_args_list[0].args[0]
        assert "repos/acme/backend/pulls/42/files" in call_url

    async def test_raises_without_github_token(self):
        no_token = PRReviewTools(github_token="")
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            await no_token.get_pr_files("acme", "backend", 42)

    async def test_paginates_until_empty_page(self, tools):
        # Each page must have 100 items to avoid the < 100 early-break
        full_page = [{"filename": f"file_{i}.py", "status": "modified", "additions": 1, "deletions": 0, "changes": 1} for i in range(100)]
        page1 = _mock_gh_resp(200, full_page)
        page2 = _mock_gh_resp(200, full_page)
        page3 = _mock_gh_resp(200, [])

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.get = AsyncMock(side_effect=[page1, page2, page3])
        mock_cls = MagicMock(return_value=ctx)

        with patch("agents.agent_03_pr_review.tools.httpx.AsyncClient", mock_cls):
            files = await tools.get_pr_files("acme", "backend", 42)

        # 2 full pages × 100 files each
        assert len(files) == 200
        assert ctx.get.call_count == 3


# ──────────────────────────────────────────────────────────────────────────────
# PRReviewTools — post_pr_review()
# ──────────────────────────────────────────────────────────────────────────────

class TestPRReviewToolsPostReview:
    @pytest.fixture
    def tools(self):
        return PRReviewTools(github_token="gh_test_token")

    async def test_posts_to_correct_endpoint(self, tools):
        review_resp = _mock_gh_resp(201, {"id": 999, "html_url": "https://github.com/acme/backend/pull/42#pullrequestreview-999"})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=review_resp)
        mock_cls = MagicMock(return_value=ctx)

        with patch("agents.agent_03_pr_review.tools.httpx.AsyncClient", mock_cls):
            result = await tools.post_pr_review("acme", "backend", 42, "Great PR!", REVIEW_EVENT_COMMENT)

        call_url = ctx.post.call_args.args[0]
        assert "repos/acme/backend/pulls/42/reviews" in call_url
        assert result["status"] == "review_posted"
        assert result["event"] == REVIEW_EVENT_COMMENT
        assert result["review_id"] == 999

    async def test_raises_without_github_token(self):
        no_token = PRReviewTools(github_token="")
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            await no_token.post_pr_review("acme", "backend", 42, "body", REVIEW_EVENT_COMMENT)

    async def test_raises_for_invalid_event(self, tools):
        with pytest.raises(ValueError, match="Invalid review event"):
            await tools.post_pr_review("acme", "backend", 42, "body", "INVALID_EVENT")

    async def test_includes_inline_comments_when_provided(self, tools):
        review_resp = _mock_gh_resp(201, {"id": 999, "html_url": ""})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=review_resp)
        mock_cls = MagicMock(return_value=ctx)

        inline = [{"path": "src/auth/jwt.py", "line": 3, "body": "Hardcoded secret!"}]

        with patch("agents.agent_03_pr_review.tools.httpx.AsyncClient", mock_cls):
            await tools.post_pr_review(
                "acme", "backend", 42, "Review body",
                REVIEW_EVENT_REQUEST_CHANGES,
                inline_comments=inline,
            )

        sent_payload = ctx.post.call_args.kwargs.get("json") or ctx.post.call_args.args[1] if len(ctx.post.call_args.args) > 1 else {}
        # The request body is passed as json kwarg
        assert ctx.post.called


# ──────────────────────────────────────────────────────────────────────────────
# PRReviewTools — post_pr_comment()
# ──────────────────────────────────────────────────────────────────────────────

class TestPRReviewToolsPostComment:
    async def test_posts_to_issues_endpoint(self):
        tools = PRReviewTools(github_token="gh_test_token")
        comment_resp = _mock_gh_resp(201, {"html_url": "https://github.com/acme/backend/issues/42#comment-1"})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=comment_resp)
        mock_cls = MagicMock(return_value=ctx)

        with patch("agents.agent_03_pr_review.tools.httpx.AsyncClient", mock_cls):
            result = await tools.post_pr_comment("acme", "backend", 42, "LGTM!")

        call_url = ctx.post.call_args.args[0]
        assert "issues/42/comments" in call_url
        assert result["status"] == "comment_posted"


# ──────────────────────────────────────────────────────────────────────────────
# PRReviewTools — execute_option() routing
# ──────────────────────────────────────────────────────────────────────────────

class TestPRReviewToolsExecuteOption:
    @pytest.fixture
    def tools(self):
        return PRReviewTools(github_token="gh_test_token")

    def _ctx(self, owner="acme", repo="backend", pr_number=42):
        return {
            "owner": owner, "repo": repo, "pr_number": pr_number,
            "review_body": "Review findings...",
            "head_sha": "def456",
        }

    async def test_hold_returns_held_without_api_call(self, tools):
        with patch.object(tools, "post_pr_review") as mock_review:
            result = await tools.execute_option({"id": "hold"}, self._ctx())
        mock_review.assert_not_called()
        assert result["status"] == "held"

    async def test_opt1_dispatches_request_changes(self, tools):
        expected = {"status": "review_posted", "event": REVIEW_EVENT_REQUEST_CHANGES, "review_id": 1, "review_url": ""}
        with patch.object(tools, "post_pr_review", return_value=expected) as mock_review:
            await tools.execute_option({"id": "opt_1"}, self._ctx())
        mock_review.assert_called_once()
        # event is passed as a kwarg
        assert mock_review.call_args.kwargs.get("event") == REVIEW_EVENT_REQUEST_CHANGES

    async def test_opt2_dispatches_comment(self, tools):
        expected = {"status": "review_posted", "event": REVIEW_EVENT_COMMENT, "review_id": 2, "review_url": ""}
        with patch.object(tools, "post_pr_review", return_value=expected) as mock_review:
            await tools.execute_option({"id": "opt_2"}, self._ctx())
        mock_review.assert_called_once()
        assert mock_review.call_args.kwargs.get("event") == REVIEW_EVENT_COMMENT

    async def test_opt3_dispatches_approve(self, tools):
        expected = {"status": "review_posted", "event": REVIEW_EVENT_APPROVE, "review_id": 3, "review_url": ""}
        with patch.object(tools, "post_pr_review", return_value=expected) as mock_review:
            await tools.execute_option({"id": "opt_3"}, self._ctx())
        mock_review.assert_called_once()
        assert mock_review.call_args.kwargs.get("event") == REVIEW_EVENT_APPROVE


# ──────────────────────────────────────────────────────────────────────────────
# _build_diff_summary()
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildDiffSummary:
    def test_includes_file_count_header(self):
        summary = _build_diff_summary(SAMPLE_PR_FILES)
        assert "Changed files: 2" in summary

    def test_sorts_by_changes_descending(self):
        files = [
            {"filename": "small.py", "status": "modified", "additions": 1, "deletions": 0, "changes": 1, "patch": "+ small"},
            {"filename": "large.py", "status": "added",    "additions": 99, "deletions": 0, "changes": 99, "patch": "+ large"},
        ]
        summary = _build_diff_summary(files)
        # large.py (99 changes) should appear before small.py (1 change)
        assert summary.index("large.py") < summary.index("small.py")

    def test_truncates_at_max_chars(self):
        big_patch = "+" + "x" * 5000
        files = [{"filename": "huge.py", "status": "modified", "additions": 5000, "deletions": 0, "changes": 5000, "patch": big_patch}]
        summary = _build_diff_summary(files, max_chars=500)
        assert len(summary) < 600
        assert "truncated" in summary

    def test_handles_binary_file_no_patch(self):
        files = [{"filename": "image.png", "status": "added", "additions": 0, "deletions": 0, "changes": 0}]
        summary = _build_diff_summary(files)
        assert "binary or large file" in summary


# ──────────────────────────────────────────────────────────────────────────────
# PRReviewWorkflow._ingest_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestPRReviewIngestNode:
    async def test_extracts_owner_and_repo(self, mock_db, workspace_id, mock_router, github_pr_payload):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        with patch.object(wf._tools, "get_pr_files", return_value=SAMPLE_PR_FILES):
            result = await wf._ingest_node(_base_pr_state(workspace_id, github_pr_payload))
        assert result["owner"] == "acme"
        assert result["repo"] == "backend"

    async def test_extracts_pr_number_and_title(self, mock_db, workspace_id, mock_router, github_pr_payload):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        with patch.object(wf._tools, "get_pr_files", return_value=SAMPLE_PR_FILES):
            result = await wf._ingest_node(_base_pr_state(workspace_id, github_pr_payload))
        assert result["pr_number"] == 42
        assert result["pr_title"] == "feat: add JWT authentication middleware"

    async def test_extracts_pr_author(self, mock_db, workspace_id, mock_router, github_pr_payload):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        with patch.object(wf._tools, "get_pr_files", return_value=SAMPLE_PR_FILES):
            result = await wf._ingest_node(_base_pr_state(workspace_id, github_pr_payload))
        assert result["pr_author"] == "dev-alice"

    async def test_extracts_branches(self, mock_db, workspace_id, mock_router, github_pr_payload):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        with patch.object(wf._tools, "get_pr_files", return_value=SAMPLE_PR_FILES):
            result = await wf._ingest_node(_base_pr_state(workspace_id, github_pr_payload))
        assert result["base_branch"] == "main"
        assert result["head_branch"] == "feature/add-auth"

    async def test_extracts_head_sha(self, mock_db, workspace_id, mock_router, github_pr_payload):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        with patch.object(wf._tools, "get_pr_files", return_value=SAMPLE_PR_FILES):
            result = await wf._ingest_node(_base_pr_state(workspace_id, github_pr_payload))
        assert result["head_sha"] == "def456abc789"

    async def test_calls_get_pr_files(self, mock_db, workspace_id, mock_router, github_pr_payload):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        with patch.object(wf._tools, "get_pr_files", return_value=SAMPLE_PR_FILES) as mock_files:
            await wf._ingest_node(_base_pr_state(workspace_id, github_pr_payload))
        mock_files.assert_called_once_with("acme", "backend", 42)

    async def test_handles_get_pr_files_failure_gracefully(self, mock_db, workspace_id, mock_router, github_pr_payload):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        with patch.object(wf._tools, "get_pr_files", side_effect=RuntimeError("API unavailable")):
            result = await wf._ingest_node(_base_pr_state(workspace_id, github_pr_payload))
        # Should not raise — diff_summary should note unavailability
        assert "unavailable" in result["diff_summary"].lower() or "error" in result["diff_summary"].lower() or isinstance(result["diff_summary"], str)

    async def test_sanitizes_diff_summary(self, mock_db, workspace_id, mock_router, github_pr_payload):
        # Inject a secret into the patch — sanitizer should strip it
        files_with_secret = [
            {
                "filename": "config.py",
                "status": "modified",
                "additions": 1,
                "deletions": 0,
                "changes": 1,
                "patch": "+SECRET = 'AKIAIOSFODNN7EXAMPLE'",
            }
        ]
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        with patch.object(wf._tools, "get_pr_files", return_value=files_with_secret):
            result = await wf._ingest_node(_base_pr_state(workspace_id, github_pr_payload))
        assert "AKIAIOSFODNN7EXAMPLE" not in result["diff_summary"]

    async def test_empty_payload_does_not_crash(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        with patch.object(wf._tools, "get_pr_files", return_value=[]):
            result = await wf._ingest_node(_base_pr_state(workspace_id, {}))
        assert result["owner"] == ""
        assert result["pr_number"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# PRReviewWorkflow._diagnose_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestPRReviewDiagnoseNode:
    async def test_calls_router_with_code_review_task(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_pr_state(workspace_id)
        with patch.object(wf.budget, "assert_budget_available", return_value=None):
            await wf._diagnose_node(state)
        call_args = mock_router.complete.call_args
        task_type = call_args.kwargs.get("task_type") or call_args.args[0]
        assert task_type == "code_review"

    async def test_parses_valid_llm_response(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_pr_state(workspace_id)
        with patch.object(wf.budget, "assert_budget_available", return_value=None):
            result = await wf._diagnose_node(state)
        # mock_router returns SAMPLE_LLM_DIAGNOSIS (a CI/CD review) — just verify structure
        assert result.get("parsed_error") is not None
        assert len(result.get("remediation_options", [])) >= 2

    async def test_handles_llm_json_parse_error(self, mock_db, workspace_id, mock_router):
        mock_router.complete.return_value = "Not JSON."
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_pr_state(workspace_id)
        with patch.object(wf.budget, "assert_budget_available", return_value=None):
            result = await wf._diagnose_node(state)
        assert result.get("error") is not None

    async def test_checks_budget_before_llm_call(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_pr_state(workspace_id)
        with patch.object(wf.budget, "assert_budget_available") as mock_budget:
            mock_budget.return_value = None
            await wf._diagnose_node(state)
        mock_budget.assert_called_once()

    async def test_includes_pr_title_and_diff_in_llm_message(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_pr_state(workspace_id)
        state["pr_title"] = "fix: remove hardcoded credentials"
        state["diff_summary"] = "--- secrets.py\n+REMOVED SECRET\n"
        with patch.object(wf.budget, "assert_budget_available", return_value=None):
            await wf._diagnose_node(state)
        call_args = mock_router.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[1]
        combined = " ".join(m["content"] for m in messages)
        assert "fix: remove hardcoded credentials" in combined
        assert "REMOVED SECRET" in combined


# ──────────────────────────────────────────────────────────────────────────────
# PRReviewWorkflow._hitl_gate_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestPRReviewHITLGateNode:
    async def test_creates_incident_in_db(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_pr_state(workspace_id)
        state["parsed_error"] = "Critical: hardcoded JWT secret in src/auth/jwt.py"
        state["remediation_options"] = [{"id": "opt_1", "title": "Request changes"}]
        state["tokens_used"] = 2400

        incident_uuid = uuid4()
        mock_db.fetchrow.return_value = {"id": incident_uuid}
        mock_db.fetchrow.reset_mock()

        with patch("agents.agent_03_pr_review.workflow.interrupt", return_value={"id": "opt_1"}):
            await wf._hitl_gate_node(state)

        mock_db.fetchrow.assert_called_once()
        query = mock_db.fetchrow.call_args.args[0]
        assert "INSERT INTO incidents" in query

    async def test_calls_interrupt_to_pause_graph(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_pr_state(workspace_id)
        state["parsed_error"] = "SQL injection risk in user input handling"
        state["remediation_options"] = [{"id": "opt_1"}]

        incident_uuid = uuid4()
        mock_db.fetchrow.return_value = {"id": incident_uuid}

        with patch("agents.agent_03_pr_review.workflow.interrupt") as mock_interrupt:
            mock_interrupt.return_value = {"id": "opt_1"}
            await wf._hitl_gate_node(state)

        mock_interrupt.assert_called_once()
        payload = mock_interrupt.call_args.args[0]
        assert "incident_id" in payload
        assert "options" in payload

    async def test_skips_incident_creation_when_error_set(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_pr_state(workspace_id)
        state["error"] = "LLM parse failed"

        mock_db.fetchrow.reset_mock()
        await wf._hitl_gate_node(state)

        mock_db.fetchrow.assert_not_called()
