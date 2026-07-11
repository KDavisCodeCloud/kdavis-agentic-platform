"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

"""
Per-workspace token circuit breaker.

Governance: Rule 10 (fail safe). If a workspace exceeds its monthly token budget,
ALL agent calls are blocked and the incident status is set to 'budget_exceeded'.
Operator must increase the budget or the billing cycle must reset before resuming.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

log = logging.getLogger(__name__)

# Cost-per-token estimates in USD (adjust when provider pricing changes)
COST_PER_TOKEN = {
    "claude-sonnet-4-20250514":   0.000003,   # $3 / 1M output tokens
    "claude-haiku-4-5-20251001":  0.00000125, # $1.25 / 1M output tokens
    "gpt-4o":                     0.000005,   # $5 / 1M output tokens
    "gpt-4o-mini":                0.0000006,  # $0.60 / 1M output tokens
    "default":                    0.000003,   # conservative fallback
}


class BudgetExceededError(Exception):
    """Raised when workspace monthly token budget is exhausted."""
    def __init__(self, workspace_id: str, budget_usd: float, spent_usd: float):
        self.workspace_id = workspace_id
        self.budget_usd = budget_usd
        self.spent_usd = spent_usd
        super().__init__(
            f"[BUDGET] Workspace {workspace_id} budget exhausted: "
            f"${spent_usd:.4f} / ${budget_usd:.2f}"
        )


class TokenBudgetGuard:
    """
    Checks and records token spend per workspace per calendar month.

    Usage:
        guard = TokenBudgetGuard(db_conn)
        await guard.assert_budget_available(workspace_id, estimated_tokens, model)
        # ... run LLM call ...
        await guard.record_usage(workspace_id, incident_id, agent_id, tokens_used, model)
    """

    def __init__(self, db_conn):
        self._db = db_conn

    async def assert_budget_available(
        self,
        workspace_id: str,
        estimated_tokens: int,
        model: str = "default",
    ) -> None:
        """
        Checks that estimated_tokens will not push workspace over budget.
        Raises BudgetExceededError if budget is already exceeded or would be exceeded.
        """
        row = await self._db.fetchrow(
            "SELECT monthly_token_budget_usd, current_month_spend_usd FROM workspaces WHERE id = $1",
            UUID(workspace_id),
        )
        if not row:
            raise ValueError(f"Workspace {workspace_id} not found")

        budget_usd = float(row["monthly_token_budget_usd"])
        spent_usd = float(row["current_month_spend_usd"])
        estimated_cost = estimated_tokens * COST_PER_TOKEN.get(model, COST_PER_TOKEN["default"])

        if spent_usd + estimated_cost > budget_usd:
            log.warning(
                f"[BUDGET] Workspace {workspace_id} would exceed budget: "
                f"${spent_usd:.4f} + ${estimated_cost:.4f} > ${budget_usd:.2f}"
            )
            raise BudgetExceededError(workspace_id, budget_usd, spent_usd)

        remaining = budget_usd - spent_usd
        log.debug(
            f"[BUDGET] Workspace {workspace_id} OK — "
            f"${spent_usd:.4f} spent / ${budget_usd:.2f} budget / ${remaining:.4f} remaining"
        )

    async def record_usage(
        self,
        workspace_id: str,
        tokens_used: int,
        model: str = "default",
        incident_id: str = None,
        agent_id: str = None,
    ) -> float:
        """
        Records token usage and updates workspace running spend.
        Returns the cost in USD for this call.
        """
        cost_usd = tokens_used * COST_PER_TOKEN.get(model, COST_PER_TOKEN["default"])
        billing_month = datetime.now(timezone.utc).strftime("%Y-%m")

        async with self._db.transaction():
            await self._db.execute(
                """
                INSERT INTO token_usage (workspace_id, incident_id, agent_id, tokens_used, cost_usd, billing_month)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                UUID(workspace_id),
                UUID(incident_id) if incident_id else None,
                agent_id,
                tokens_used,
                cost_usd,
                billing_month,
            )
            await self._db.execute(
                """
                UPDATE workspaces
                SET current_month_spend_usd = current_month_spend_usd + $1
                WHERE id = $2
                """,
                cost_usd,
                UUID(workspace_id),
            )

        log.info(
            f"[BUDGET] Recorded {tokens_used} tokens (${cost_usd:.6f}) "
            f"for workspace {workspace_id}"
        )
        return cost_usd

    async def reset_monthly_spend(self, workspace_id: str) -> None:
        """
        Resets current_month_spend_usd to 0 at billing cycle renewal.
        Called by Stripe webhook on invoice.paid.
        """
        await self._db.execute(
            "UPDATE workspaces SET current_month_spend_usd = 0.00 WHERE id = $1",
            UUID(workspace_id),
        )
        log.info(f"[BUDGET] Monthly spend reset for workspace {workspace_id}")

    async def get_spend_summary(self, workspace_id: str) -> dict:
        """Returns current spend vs budget for a workspace."""
        row = await self._db.fetchrow(
            "SELECT monthly_token_budget_usd, current_month_spend_usd FROM workspaces WHERE id = $1",
            UUID(workspace_id),
        )
        if not row:
            raise ValueError(f"Workspace {workspace_id} not found")

        budget = float(row["monthly_token_budget_usd"])
        spent = float(row["current_month_spend_usd"])
        return {
            "workspace_id": workspace_id,
            "budget_usd": budget,
            "spent_usd": spent,
            "remaining_usd": max(0.0, budget - spent),
            "utilization_pct": round((spent / budget * 100) if budget > 0 else 0, 1),
        }
