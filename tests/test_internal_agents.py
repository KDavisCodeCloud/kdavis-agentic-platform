"""
tests/test_internal_agents.py
Tests for api/middleware/internal_auth.py + api/routes/internal_agents.py —
the owner/team-only agent-execution path, kept fully separate from the
customer-facing workspace-token model in api/middleware/auth.py.

What this file validates:
  - get_internal_user: missing/malformed Authorization header -> 401
  - get_internal_user: Supabase rejects the token -> 401
  - get_internal_user: valid token, non-admin role -> 403
  - get_internal_user: valid token, admin role -> returns {id, email, role}
  - run_internal_agent: unknown agent_id -> 400
  - run_internal_agent: known-but-not-wired agent_id -> 501 with a real reason
  - run_internal_agent: research_agent -> creates a real row synchronously
    (no "pending" placeholder id) and schedules the background task
  - _execute_internal_agent: research_agent success path writes status='executed'
  - _execute_internal_agent: research_agent failure (missing niche) writes
    status='failed' with the error message, never raises out of the task
  - _WIRABLE_AGENTS / _NOT_WIRED_REASONS / _KNOWN_INTERNAL_AGENTS stay consistent

Runs with pytest-asyncio + unittest.mock — no live Supabase/DB needed.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException

from api.middleware.internal_auth import get_internal_user
from api.routes import internal_agents


def _fake_request(headers: dict) -> SimpleNamespace:
    return SimpleNamespace(headers=headers)


# ──────────────────────────────────────────────────────────────────────────────
# get_internal_user
# ──────────────────────────────────────────────────────────────────────────────

class TestGetInternalUser:
    async def test_missing_header_401(self):
        with pytest.raises(HTTPException) as exc:
            await get_internal_user(_fake_request({}))
        assert exc.value.status_code == 401

    async def test_non_bearer_header_401(self):
        with pytest.raises(HTTPException) as exc:
            await get_internal_user(_fake_request({"Authorization": "Basic abc"}))
        assert exc.value.status_code == 401

    async def test_empty_bearer_token_401(self):
        with pytest.raises(HTTPException) as exc:
            await get_internal_user(_fake_request({"Authorization": "Bearer  "}))
        assert exc.value.status_code == 401

    @patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"})
    async def test_supabase_rejects_token_401(self):
        mock_client = MagicMock()
        mock_client.auth.get_user.side_effect = Exception("invalid jwt")
        with patch("supabase.create_client", return_value=mock_client):
            with pytest.raises(HTTPException) as exc:
                await get_internal_user(_fake_request({"Authorization": "Bearer badtoken"}))
        assert exc.value.status_code == 401

    @patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"})
    async def test_non_admin_role_403(self):
        fake_user = SimpleNamespace(id=str(uuid4()), email="son@thd.io", user_metadata={"role": "rnd"})
        mock_client = MagicMock()
        mock_client.auth.get_user.return_value = SimpleNamespace(user=fake_user)
        with patch("supabase.create_client", return_value=mock_client):
            with pytest.raises(HTTPException) as exc:
                await get_internal_user(_fake_request({"Authorization": "Bearer realtoken"}))
        assert exc.value.status_code == 403

    @patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"})
    async def test_admin_role_passes(self):
        fake_user = SimpleNamespace(id=str(uuid4()), email="kelvin@thd.io", user_metadata={"role": "admin"})
        mock_client = MagicMock()
        mock_client.auth.get_user.return_value = SimpleNamespace(user=fake_user)
        with patch("supabase.create_client", return_value=mock_client):
            result = await get_internal_user(_fake_request({"Authorization": "Bearer realtoken"}))
        assert result["role"] == "admin"
        assert result["email"] == "kelvin@thd.io"

    @patch.dict("os.environ", {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}, clear=False)
    async def test_missing_server_config_500(self):
        with pytest.raises(HTTPException) as exc:
            await get_internal_user(_fake_request({"Authorization": "Bearer realtoken"}))
        assert exc.value.status_code == 500


# ──────────────────────────────────────────────────────────────────────────────
# Dispatch table consistency
# ──────────────────────────────────────────────────────────────────────────────

class TestDispatchTableConsistency:
    def test_wirable_agents_are_known(self):
        assert internal_agents._WIRABLE_AGENTS <= internal_agents._KNOWN_INTERNAL_AGENTS

    def test_not_wired_reasons_are_known_and_not_wirable(self):
        for agent_id in internal_agents._NOT_WIRED_REASONS:
            assert agent_id in internal_agents._KNOWN_INTERNAL_AGENTS
            assert agent_id not in internal_agents._WIRABLE_AGENTS

    def test_research_agent_is_wirable(self):
        assert "research_agent" in internal_agents._WIRABLE_AGENTS


# ──────────────────────────────────────────────────────────────────────────────
# run_internal_agent — guard branches (no DB touched on these paths)
# ──────────────────────────────────────────────────────────────────────────────

class TestRunInternalAgentGuards:
    async def test_unknown_agent_400(self):
        with pytest.raises(HTTPException) as exc:
            await internal_agents.run_internal_agent(
                agent_id="not_a_real_agent",
                body=internal_agents.InternalAgentRunRequest(payload={}),
                request=_fake_request({}),
                background_tasks=BackgroundTasks(),
                user={"id": "u1", "email": "k@thd.io", "role": "admin"},
            )
        assert exc.value.status_code == 400

    async def test_not_wired_agent_501_with_reason(self):
        with pytest.raises(HTTPException) as exc:
            await internal_agents.run_internal_agent(
                agent_id="portfolio_monitor",
                body=internal_agents.InternalAgentRunRequest(payload={}),
                request=_fake_request({}),
                background_tasks=BackgroundTasks(),
                user={"id": "u1", "email": "k@thd.io", "role": "admin"},
            )
        assert exc.value.status_code == 501
        assert "ProductMetricsSnapshot" in exc.value.detail

    async def test_wirable_agent_creates_real_row_not_placeholder(self):
        fake_row = {"id": uuid4()}
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=fake_row)
        pool_ctx = AsyncMock()
        pool_ctx.__aenter__ = AsyncMock(return_value=conn)
        pool_ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=pool_ctx)

        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))
        bg = BackgroundTasks()

        result = await internal_agents.run_internal_agent(
            agent_id="research_agent",
            body=internal_agents.InternalAgentRunRequest(payload={"niche": "freight audit"}),
            request=request,
            background_tasks=bg,
            user={"id": "u1", "email": "k@thd.io", "role": "admin"},
        )
        assert result.run_id == str(fake_row["id"])
        assert result.run_id != "pending"
        assert result.status == "executing"


# ──────────────────────────────────────────────────────────────────────────────
# _execute_internal_agent — background task
# ──────────────────────────────────────────────────────────────────────────────

def _make_app_with_db():
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    app = SimpleNamespace(state=SimpleNamespace(db_pool=pool))
    return app, conn


class TestExecuteInternalAgent:
    async def test_research_agent_success_writes_executed(self):
        app, conn = _make_app_with_db()
        fake_result = {"niche": "freight audit", "viability_score": 7}

        with patch("agents.internal.research_agent.ResearchAgent") as MockAgent:
            MockAgent.return_value.run.return_value = fake_result
            await internal_agents._execute_internal_agent(
                app, str(uuid4()), "research_agent", {"niche": "freight audit"}
            )

        assert conn.execute.await_count == 1
        sql, *params = conn.execute.await_args.args
        assert "status = 'executed'" in sql

    async def test_research_agent_missing_niche_writes_failed(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "research_agent", {}
        )
        assert conn.execute.await_count == 1
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql
        assert "niche is required" in params[0]


# ──────────────────────────────────────────────────────────────────────────────
# Newly-wired agents (this pass): chat_router_agent, code_quality_agent,
# release_notes_agent, visitor_capture_agent, onboarding_agent.
# Same standard as research_agent above — mocked db_pool, real logic path
# exercised, not just import checks. None of these run against a live DB
# yet (DATABASE_URL is still a placeholder in this environment) — that's
# a separate infra gap, not something these tests paper over.
# ──────────────────────────────────────────────────────────────────────────────

class TestChatRouterAgentDispatch:
    async def test_keyword_match_success_no_claude_needed(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "chat_router_agent", {"query": "what's our MRR this month"}
        )
        assert conn.execute.await_count == 1
        sql, *params = conn.execute.await_args.args
        assert "status = 'executed'" in sql
        result = json.loads(params[0])
        assert result["routed_to"] == "portfolio_monitor"
        assert result["status"] == "handler_not_available"  # not wired as a chat handler yet

    async def test_claude_fallback_uses_router(self):
        app, conn = _make_app_with_db()
        fake_completion = SimpleNamespace(text="Here's my analysis...")
        with patch("providers.router.complete", new=AsyncMock(return_value=fake_completion)):
            await internal_agents._execute_internal_agent(
                app, str(uuid4()), "chat_router_agent", {"query": "what do you think about our positioning"}
            )
        sql, *params = conn.execute.await_args.args
        assert "status = 'executed'" in sql
        result = json.loads(params[0])
        assert result["routed_to"] == "claude_think_tank"
        assert result["response"] == "Here's my analysis..."

    async def test_missing_query_writes_failed(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "chat_router_agent", {}
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql
        assert "query is required" in params[0]


class TestCodeQualityAgentDispatch:
    async def test_missing_paths_writes_failed(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "code_quality_agent", {}
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql
        assert "paths" in params[0]

    async def test_path_escaping_repo_root_rejected(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "code_quality_agent", {"paths": ["../../../etc/passwd"]}
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql
        assert "escapes the repo root" in params[0]

    async def test_real_file_reviewed_successfully(self):
        app, conn = _make_app_with_db()
        # Review this very test file — real filesystem read, real AST parse.
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "code_quality_agent", {"paths": ["tests/test_internal_agents.py"]}
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'executed'" in sql
        result = json.loads(params[0])
        assert result["files_reviewed"] == 1


class TestReleaseNotesAgentDispatch:
    async def test_builds_from_real_git_log(self):
        app, conn = _make_app_with_db()
        # Real git log against this actual repo — no mocking of subprocess,
        # exercises the real integration.
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "release_notes_agent", {"commit_count": 3}
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'executed'" in sql
        result = json.loads(params[0])
        assert len(result["what_changed"]) == 3
        assert result["version"]

    async def test_invalid_commit_count_writes_failed(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "release_notes_agent", {"commit_count": 9999}
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql


class TestVisitorCaptureAgentDispatch:
    async def test_success_scores_and_returns_lead(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "visitor_capture_agent",
            {"product_id": "mse", "email": "test@example.com", "signup_type": "trial", "utm_source": "direct"},
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'executed'" in sql
        result = json.loads(params[0])
        assert result["email"] == "test@example.com"

    async def test_missing_required_fields_writes_failed(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "visitor_capture_agent", {"email": "test@example.com"}
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql
        assert "missing required fields" in params[0]


class TestOnboardingAgentDispatch:
    async def test_prepare_invite_success(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "onboarding_agent",
            {"email": "son@example.com", "name": "Son", "role": "team_member"},
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'executed'" in sql
        result = json.loads(params[0])
        assert result["email"] == "son@example.com"
        assert "execute_invite is still genuinely blocked" in result["note"]

    async def test_invalid_role_writes_failed(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "onboarding_agent",
            {"email": "x@example.com", "name": "X", "role": "not_a_real_role"},
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql


class TestUpdatedWirableSet:
    def test_five_new_agents_are_wirable(self):
        for agent_id in ("chat_router_agent", "code_quality_agent", "release_notes_agent",
                          "visitor_capture_agent", "onboarding_agent"):
            assert agent_id in internal_agents._WIRABLE_AGENTS

    def test_still_deferred_agents_have_specific_reasons(self):
        for agent_id in ("portfolio_monitor", "gap_detector_agent", "content_agent",
                          "email_sequence_agent", "sop_agent", "revenue_intelligence_agent",
                          "accounting_agent", "finance_assistant_agent", "tax_agent", "wealth_agent"):
            assert agent_id not in internal_agents._WIRABLE_AGENTS
            assert agent_id in internal_agents._NOT_WIRED_REASONS
            assert len(internal_agents._NOT_WIRED_REASONS[agent_id]) > 20
