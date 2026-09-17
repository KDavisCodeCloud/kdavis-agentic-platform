"""
tests/test_llm_usage.py
24-gap-closure build, Phase 7 -- api/routes/llm_usage.py. token_usage
was already written to by every agent workflow via
core/token_budget.py's record_usage; this is the first dashboard-facing
read of it.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from api.routes import llm_usage


def _make_request(fetch_return=None) -> tuple:
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=fetch_return or [])
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))
    return request, conn


class TestGetLlmUsage:
    async def test_no_usage_this_month_is_all_zero(self):
        request, conn = _make_request(fetch_return=[])
        result = await llm_usage.get_llm_usage(request, workspace={"id": uuid4(), "monthly_token_budget_usd": 50.0})

        assert result.total_tokens == 0
        assert result.total_cost_usd == 0.0
        assert result.by_agent == []

    async def test_aggregates_by_agent_and_totals(self):
        rows = [
            {"agent_id": "agent_01_cicd_triage", "tokens_used": 1200, "cost_usd": 3.5},
            {"agent_id": "agent_06_finops", "tokens_used": 400, "cost_usd": 1.2},
        ]
        request, conn = _make_request(fetch_return=rows)

        result = await llm_usage.get_llm_usage(request, workspace={"id": uuid4(), "monthly_token_budget_usd": 50.0})

        assert result.total_tokens == 1600
        assert result.total_cost_usd == 4.7
        assert len(result.by_agent) == 2
        assert result.by_agent[0].agent_id == "agent_01_cicd_triage"

    async def test_filters_by_current_billing_month(self):
        request, conn = _make_request(fetch_return=[])
        await llm_usage.get_llm_usage(request, workspace={"id": uuid4(), "monthly_token_budget_usd": 50.0})

        sql, ws_id, billing_month = conn.fetch.await_args.args
        assert "token_usage" in sql
        assert "GROUP BY agent_id" in sql
        assert len(billing_month) == 7 and billing_month[4] == "-"

    async def test_utilization_pct_computed_against_budget(self):
        rows = [{"agent_id": "agent_01_cicd_triage", "tokens_used": 100, "cost_usd": 25.0}]
        request, conn = _make_request(fetch_return=rows)

        result = await llm_usage.get_llm_usage(request, workspace={"id": uuid4(), "monthly_token_budget_usd": 50.0})

        assert result.utilization_pct == 50.0

    async def test_zero_budget_does_not_divide_by_zero(self):
        rows = [{"agent_id": "agent_01_cicd_triage", "tokens_used": 100, "cost_usd": 25.0}]
        request, conn = _make_request(fetch_return=rows)

        result = await llm_usage.get_llm_usage(request, workspace={"id": uuid4(), "monthly_token_budget_usd": 0})

        assert result.utilization_pct == 0
