"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

24-gap-closure build, Phase 7 -- LLM usage visibility. token_usage
(db/schema.sql, populated by every agent workflow via
core/token_budget.py's record_usage on every real LLM call) already
existed and was already being written to on every real run -- there was
simply no dashboard-facing read of it anywhere in the frontend before
this. This is that read: per-workspace, this month, broken down by agent.

GET /workspace/llm-usage -- this month's total + per-agent breakdown,
                            plus the existing budget/spend figures
                            core/token_budget.py's get_spend_summary
                            already tracks on workspaces itself.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from api.middleware.auth import get_workspace_or_member

router = APIRouter(prefix="/workspace/llm-usage", tags=["llm-usage"])


class AgentUsage(BaseModel):
    agent_id: str
    tokens_used: int
    cost_usd: float


class LlmUsageResponse(BaseModel):
    billing_month: str
    total_tokens: int
    total_cost_usd: float
    budget_usd: float
    utilization_pct: float
    by_agent: list[AgentUsage]


@router.get("", response_model=LlmUsageResponse)
async def get_llm_usage(
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
) -> LlmUsageResponse:
    billing_month = datetime.now(timezone.utc).strftime("%Y-%m")

    async with request.app.state.db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT agent_id, SUM(tokens_used) AS tokens_used, SUM(cost_usd) AS cost_usd
            FROM token_usage
            WHERE workspace_id = $1 AND billing_month = $2
            GROUP BY agent_id
            ORDER BY cost_usd DESC
            """,
            workspace["id"], billing_month,
        )

    by_agent = [
        AgentUsage(agent_id=r["agent_id"] or "unknown", tokens_used=r["tokens_used"] or 0, cost_usd=float(r["cost_usd"] or 0))
        for r in rows
    ]
    total_tokens = sum(a.tokens_used for a in by_agent)
    total_cost = sum(a.cost_usd for a in by_agent)
    budget = float(workspace.get("monthly_token_budget_usd") or 0)

    return LlmUsageResponse(
        billing_month=billing_month,
        total_tokens=total_tokens,
        total_cost_usd=total_cost,
        budget_usd=budget,
        utilization_pct=round((total_cost / budget * 100) if budget > 0 else 0, 1),
        by_agent=by_agent,
    )
