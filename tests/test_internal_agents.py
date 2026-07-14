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
        assert "product-metrics snapshot" in exc.value.detail

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
