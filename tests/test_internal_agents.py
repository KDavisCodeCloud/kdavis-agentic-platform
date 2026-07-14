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

    async def test_product_id_captured_from_payload(self):
        # migration 009's product_id column, feeding gap_detector_agent's
        # AgentRunRecord — only populated when the caller's payload names one.
        fake_row = {"id": uuid4()}
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=fake_row)
        pool_ctx = AsyncMock()
        pool_ctx.__aenter__ = AsyncMock(return_value=conn)
        pool_ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=pool_ctx)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))

        await internal_agents.run_internal_agent(
            agent_id="visitor_capture_agent",
            body=internal_agents.InternalAgentRunRequest(
                payload={"product_id": "freight-audit", "email": "x@example.com",
                         "signup_type": "trial", "utm_source": "organic"}
            ),
            request=request,
            background_tasks=BackgroundTasks(),
            user={"id": "u1", "email": "k@thd.io", "role": "admin"},
        )
        sql, *params = conn.fetchrow.await_args.args
        assert params[-1] == "freight-audit"  # product_id is the last bound param


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
        # 2 calls now: the chat_queries INSERT (added alongside
        # gap_detector_agent's ChatQuery signal) + the status=executed UPDATE.
        assert conn.execute.await_count == 2
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

    def test_content_email_sop_agents_are_wirable(self):
        # Wired in the pass that closed out DATABASE_URL — content_agent and
        # email_sequence_agent chain off a completed research_agent run,
        # sop_agent is fireable from a bare payload (agent_name +
        # task_summary), same as visitor_capture_agent/onboarding_agent.
        for agent_id in ("content_agent", "email_sequence_agent", "sop_agent"):
            assert agent_id in internal_agents._WIRABLE_AGENTS
            assert agent_id not in internal_agents._NOT_WIRED_REASONS

    def test_gap_detector_agent_is_wirable(self):
        # migration 009: internal_agent_runs got product_id/confidence_score
        # columns, plus new hitl_corrections/chat_queries tables. Roster is
        # derived from _KNOWN_INTERNAL_AGENTS/_WIRABLE_AGENTS directly, not
        # a table.
        assert "gap_detector_agent" in internal_agents._WIRABLE_AGENTS
        assert "gap_detector_agent" not in internal_agents._NOT_WIRED_REASONS

    def test_finance_agents_are_wirable(self):
        # Partial functionality, not full: expenses persistence (migration
        # 010) unlocks accounting_agent (process_receipt/monthly_summary)
        # and tax_agent's track_deductions; the rest of each agent's methods
        # are pure math on payload inputs (quarterly_estimate_card,
        # monthly_cash_flow, surplus_opportunity_card, salary_recommendation,
        # tax_reserve_status). Invoices/revenue_events/investment_allocations
        # persistence still doesn't exist - those specific methods 400 with
        # a clear reason inside the dispatch branch itself, not via
        # _NOT_WIRED_REASONS (the agent as a whole is genuinely wirable now).
        for agent_id in ("accounting_agent", "tax_agent", "wealth_agent", "finance_assistant_agent"):
            assert agent_id in internal_agents._WIRABLE_AGENTS
            assert agent_id not in internal_agents._NOT_WIRED_REASONS

    def test_still_deferred_agents_have_specific_reasons(self):
        for agent_id in ("portfolio_monitor", "revenue_intelligence_agent"):
            assert agent_id not in internal_agents._WIRABLE_AGENTS
            assert agent_id in internal_agents._NOT_WIRED_REASONS
            assert len(internal_agents._NOT_WIRED_REASONS[agent_id]) > 20


# ──────────────────────────────────────────────────────────────────────────────
# gap_detector_agent — reads real internal_agent_runs/hitl_corrections/
# chat_queries rows (mocked here via conn.fetch), derives AgentRosterEntry
# live from _KNOWN_INTERNAL_AGENTS/_WIRABLE_AGENTS (no roster table).
# Verified separately against the real live DB during development: inserted
# a real internal_agent_runs row, fired gap_detector_agent for real, got
# back genuine roster-coverage-gap recommendations for portfolio_monitor
# and revenue_intelligence_agent (both still actually unwired at the time)
# — not fabricated output.
# ──────────────────────────────────────────────────────────────────────────────

def _make_app_for_gap_detector(run_rows=None, correction_rows=None, query_rows=None):
    app, conn = _make_app_with_db()
    conn.fetch = AsyncMock(side_effect=[run_rows or [], correction_rows or [], query_rows or []])
    return app, conn


class TestGapDetectorAgentDispatch:
    async def test_success_with_no_signal_writes_executed(self):
        app, conn = _make_app_for_gap_detector()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "gap_detector_agent", {}
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'executed'" in sql
        result = json.loads(params[0])
        assert result["runs_analyzed"] == 0
        # portfolio_monitor/revenue_intelligence_agent etc. aren't in
        # _WIRABLE_AGENTS yet in this test's own module state, so the
        # roster-coverage detector should surface them as real gaps.
        names = {r["suggested_agent_name"] for r in result["recommendations"]}
        assert "portfolio_monitor" in names

    async def test_uses_real_run_rows(self):
        import datetime
        run_rows = [
            {"agent_id": "research_agent", "product_id": None, "status": "failed",
             "confidence_score": None, "created_at": datetime.datetime.now(datetime.timezone.utc)}
            for _ in range(3)
        ]
        app, conn = _make_app_for_gap_detector(run_rows=run_rows)
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "gap_detector_agent", {"days_back": 7}
        )
        sql, *params = conn.execute.await_args.args
        result = json.loads(params[0])
        assert result["runs_analyzed"] == 3
        names = {r["suggested_agent_name"] for r in result["recommendations"]}
        assert "research_agent_review" in names  # detect_low_confidence_pattern's naming convention

    async def test_invalid_days_back_writes_failed(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "gap_detector_agent", {"days_back": 9999}
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql
        assert "days_back" in params[0]


class TestChatRouterAgentLogsQueries:
    async def test_logs_keyword_matched_query(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "chat_router_agent", {"query": "what's our MRR this month"}
        )
        assert conn.execute.await_count == 2
        insert_sql, *insert_params = conn.execute.await_args_list[0].args
        assert "INSERT INTO chat_queries" in insert_sql
        assert insert_params[0] == "what's our MRR this month"
        assert insert_params[1] is False  # keyword-matched, not routed to Claude

    async def test_logs_claude_fallback_query(self):
        app, conn = _make_app_with_db()
        fake_completion = SimpleNamespace(text="analysis")
        with patch("providers.router.complete", new=AsyncMock(return_value=fake_completion)):
            await internal_agents._execute_internal_agent(
                app, str(uuid4()), "chat_router_agent",
                {"query": "what do you think about our positioning"},
            )
        assert conn.execute.await_count == 2
        insert_sql, *insert_params = conn.execute.await_args_list[0].args
        assert "INSERT INTO chat_queries" in insert_sql
        assert insert_params[1] is True  # fell through to Claude


# ──────────────────────────────────────────────────────────────────────────────
# content_agent / email_sequence_agent — chain off a completed research_agent
# run via internal_agent_runs.result->'research'. sop_agent — fireable from a
# bare payload, no chaining. All three additionally verified against the real
# live DB during development (insert a fake executed research_agent row,
# fire content_agent/email_sequence_agent for real, confirm result written +
# a real SOP file lands on disk) — that live check isn't repeatable in CI
# without a DB, so it isn't encoded here; these tests cover the same logic
# paths with a mocked pool.
# ──────────────────────────────────────────────────────────────────────────────

_FAKE_RESEARCH = {
    "niche": "freight invoice reconciliation",
    "icp": {"job_title": "AP Manager", "company_size": "50-200", "tools_daily": ["QuickBooks"],
            "visual_environment": "spreadsheet-heavy", "emotional_register": "OPERATIONAL",
            "trust_blockers": ["data security"], "proof_format": "METRICS"},
    "pain_language": ["I spend 6 hours a week matching invoices by hand"],
    "top_llm_queries": ["best freight invoice reconciliation tool"],
    "competitor_gaps": ["no real-time discrepancy alerts"],
    "estimated_build_days": 14,
    "estimated_mrr_range": {"low": 2000, "high": 8000},
    "viability_score": 0.7,
    "design_brief_vars": {
        "pain_headline_options": ["Stop matching freight invoices by hand"],
        "roi_number": "Save 6 hours/week", "proof_stat_1": "6 hrs saved",
        "proof_stat_2": "99% match accuracy", "proof_stat_3": "3 min setup",
        "faq_questions": ["How does it work?"],
    },
}


def _make_app_with_research_row(status="executed", result=None):
    """Like _make_app_with_db but also configures conn.fetchrow for the
    research_run_id lookup content_agent/email_sequence_agent's dispatch
    branch does before the final status-update conn.execute call."""
    app, conn = _make_app_with_db()
    conn.fetchrow = AsyncMock(return_value={
        "status": status,
        "result": json.dumps(result if result is not None else {"research": _FAKE_RESEARCH, "hitl_card": {}}),
    })
    return app, conn


class TestContentAgentDispatch:
    async def test_success_writes_executed(self):
        app, conn = _make_app_with_research_row()
        with patch.object(internal_agents, "_llm_call_sync", return_value="stub"):
            await internal_agents._execute_internal_agent(
                app, str(uuid4()), "content_agent",
                {"research_run_id": str(uuid4()), "product_id": "freight-audit"},
            )
        sql, *params = conn.execute.await_args.args
        assert "status = 'executed'" in sql
        result = json.loads(params[0])
        assert result["product_id"] == "freight-audit"
        assert "landing_headlines" in result

    async def test_missing_research_run_id_writes_failed(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "content_agent", {"product_id": "freight-audit"}
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql
        assert "research_run_id" in params[0]

    async def test_research_run_not_executed_writes_failed(self):
        app, conn = _make_app_with_research_row(status="executing")
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "content_agent",
            {"research_run_id": str(uuid4()), "product_id": "freight-audit"},
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql
        assert "not 'executed'" in params[0]

    async def test_research_row_not_found_writes_failed(self):
        app, conn = _make_app_with_db()
        conn.fetchrow = AsyncMock(return_value=None)
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "content_agent",
            {"research_run_id": str(uuid4()), "product_id": "freight-audit"},
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql
        assert "not found" in params[0]


class TestEmailSequenceAgentDispatch:
    async def test_success_writes_executed(self):
        app, conn = _make_app_with_research_row()
        with patch.object(internal_agents, "_llm_call_sync", return_value="stub"):
            await internal_agents._execute_internal_agent(
                app, str(uuid4()), "email_sequence_agent",
                {"research_run_id": str(uuid4()), "product_id": "freight-audit"},
            )
        sql, *params = conn.execute.await_args.args
        assert "status = 'executed'" in sql
        result = json.loads(params[0])
        assert "sequences" in result

    async def test_missing_product_id_writes_failed(self):
        app, conn = _make_app_with_research_row()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "email_sequence_agent", {"research_run_id": str(uuid4())}
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql
        assert "product_id" in params[0]


class TestSopAgentDispatch:
    async def test_success_writes_executed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "sop_agent",
            {"agent_name": "test_agent", "task_summary": "unit test SOP write"},
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'executed'" in sql
        result = json.loads(params[0])
        assert result["file_path"].endswith(".md")
        assert (tmp_path / "KDavis Platform" / "SOPs" / "test_agent").exists()

    async def test_missing_task_summary_writes_failed(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "sop_agent", {"agent_name": "test_agent"}
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql
        assert "missing required fields" in params[0]

    async def test_no_vault_path_writes_failed(self, monkeypatch):
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "sop_agent",
            {"agent_name": "test_agent", "task_summary": "should fail, no vault"},
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql
        assert "OBSIDIAN_VAULT_PATH" in params[0]


# ──────────────────────────────────────────────────────────────────────────────
# Finance agents — partial wiring (migration 010's expenses table +
# each agent's genuinely pure, no-persistence-needed methods). Verified
# separately against the real live DB during development: fired
# accounting_agent process_receipt for real, confirmed a real row landed in
# expenses AND a real file landed on disk under the correct IRS folder
# structure, then fired monthly_summary and confirmed it read that same
# real row back correctly (not fabricated) before cleaning up. The other
# 6 (quarterly_estimate_card/monthly_cash_flow/surplus_opportunity_card/
# salary_recommendation/tax_reserve_status/track_deductions) all fired for
# real with correct results too.
# ──────────────────────────────────────────────────────────────────────────────

class TestAccountingAgentDispatch:
    async def test_process_receipt_success(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINANCE_DOCUMENT_STORE_PATH", str(tmp_path))
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "accounting_agent",
            {"action": "process_receipt", "text": "Vendor: Anthropic\nDate: 01/15/2026\nTotal: $50.00"},
        )
        # 2 execute calls: the expenses INSERT + the final status UPDATE.
        assert conn.execute.await_count == 2
        insert_sql, *insert_params = conn.execute.await_args_list[0].args
        assert "INSERT INTO expenses" in insert_sql
        final_sql, *final_params = conn.execute.await_args_list[-1].args
        assert "status = 'executed'" in final_sql

    async def test_process_receipt_no_store_path_writes_failed(self, monkeypatch):
        monkeypatch.delenv("FINANCE_DOCUMENT_STORE_PATH", raising=False)
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "accounting_agent",
            {"action": "process_receipt", "text": "Vendor: X\nTotal: $10.00"},
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql
        assert "FINANCE_DOCUMENT_STORE_PATH" in params[0]

    async def test_monthly_summary_reads_real_rows(self, tmp_path, monkeypatch):
        import datetime
        monkeypatch.setenv("FINANCE_DOCUMENT_STORE_PATH", str(tmp_path))
        app, conn = _make_app_with_db()
        conn.fetch = AsyncMock(return_value=[{
            "amount": 50, "vendor": "Anthropic", "description": "API usage",
            "expense_date": datetime.date(2026, 1, 15), "irs_category": "Software_Subscriptions",
            "receipt_url": "/tmp/x.txt", "tax_year": 2026, "deductible": True, "approved_by_cpa": False,
        }])
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "accounting_agent",
            {"action": "monthly_summary", "year": 2026, "month": 1},
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'executed'" in sql
        result = json.loads(params[0])
        assert result["expenses_this_month"] == 50.0

    async def test_unknown_action_writes_failed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINANCE_DOCUMENT_STORE_PATH", str(tmp_path))
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "accounting_agent", {"action": "track_invoice"}
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql
        assert "process_receipt" in params[0]


class TestTaxAgentDispatch:
    async def test_track_deductions_uses_real_expenses(self):
        app, conn = _make_app_with_db()
        conn.fetch = AsyncMock(return_value=[])
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "tax_agent",
            {"action": "track_deductions", "tax_year": 2026, "has_dedicated_workspace": True, "office_sqft": 150},
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'executed'" in sql
        result = json.loads(params[0])
        assert result["tax_year"] == 2026

    async def test_quarterly_estimate_card_success(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "tax_agent",
            {"action": "quarterly_estimate_card", "tax_year": 2026, "quarter": 1, "ytd_net_income": 40000},
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'executed'" in sql
        result = json.loads(params[0])
        assert result["quarter"] == 1

    async def test_unknown_action_writes_failed(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "tax_agent", {"action": "year_end_package"}
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql
        assert "track_deductions" in params[0]


class TestWealthAgentDispatch:
    async def test_monthly_cash_flow_success(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "wealth_agent",
            {"action": "monthly_cash_flow", "year": 2026, "month": 1, "revenue": 5000,
             "expenses": 2000, "annual_estimated_tax": 12000},
        )
        sql, *params = conn.execute.await_args.args
        result = json.loads(params[0])
        assert result["available_surplus"] == 2000.0

    async def test_salary_recommendation_invalid_entity_type_writes_failed(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "wealth_agent",
            {"action": "salary_recommendation", "entity_type": "not_a_real_type", "business_net_income": 80000},
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql

    async def test_unknown_action_writes_failed(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "wealth_agent", {"action": "record_allocation"}
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql
        assert "monthly_cash_flow" in params[0]


class TestFinanceAssistantAgentDispatch:
    async def test_tax_reserve_status_success(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "finance_assistant_agent",
            {"action": "tax_reserve_status", "year": 2026, "month": 1, "revenue": 5000,
             "expenses": 2000, "annual_estimated_tax": 12000},
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'executed'" in sql
        result = json.loads(params[0])
        assert "Recommended tax reserve" in result["answer"]

    async def test_other_action_writes_failed(self):
        app, conn = _make_app_with_db()
        await internal_agents._execute_internal_agent(
            app, str(uuid4()), "finance_assistant_agent", {"action": "revenue_ytd", "year": 2026}
        )
        sql, *params = conn.execute.await_args.args
        assert "status = 'failed'" in sql
        assert "tax_reserve_status" in params[0]
