"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 KDavis Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

"""
WorkspaceComplianceGuard — validates workspace subscription before every agent invocation.

Governance: Rule 10 (fail safe not fail open). If subscription check fails,
access is denied and the workspace is suspended — never silently allowed through.
"""

import logging
from typing import Optional
from uuid import UUID

log = logging.getLogger(__name__)

# Statuses that allow API access
_ACTIVE_STATUSES = {"active", "trialing"}

# Statuses that block access — agent calls return 402/403 immediately
_BLOCKED_STATUSES = {"past_due", "canceled", "suspended"}


class SubscriptionError(Exception):
    """Raised when workspace subscription does not permit agent execution."""
    def __init__(self, workspace_id: str, status: str, reason: str):
        self.workspace_id = workspace_id
        self.status = status
        self.reason = reason
        super().__init__(f"[COMPLIANCE] Workspace {workspace_id} blocked: {reason}")


class WorkspaceComplianceGuard:
    """
    Checks that a workspace has an active subscription before any agent work.

    Also enforces product tier limits:
    - starter:    max 3 agents, 2 repos, 1 cloud provider
    - growth:     max 10 agents, 15 repos, 2 cloud providers
    - enterprise: unlimited (subject to custom SLA)
    """

    TIER_LIMITS = {
        "starter":    {"max_agents": 3,  "max_repos": 2,  "max_cloud_providers": 1},
        "growth":     {"max_agents": 10, "max_repos": 15, "max_cloud_providers": 2},
        "enterprise": {"max_agents": -1, "max_repos": -1, "max_cloud_providers": -1},
    }

    def __init__(self, db_conn):
        self._db = db_conn

    async def assert_workspace_active(self, workspace_id: str) -> dict:
        """
        Validates workspace subscription. Raises SubscriptionError if blocked.
        Returns workspace row dict on success.
        """
        row = await self._db.fetchrow(
            "SELECT id, stripe_subscription_status, product_tier, company_name "
            "FROM workspaces WHERE id = $1",
            UUID(workspace_id),
        )

        if not row:
            raise SubscriptionError(workspace_id, "not_found", "Workspace not found")

        status = row["stripe_subscription_status"]

        if status in _BLOCKED_STATUSES:
            reason = self._reason_for_status(status)
            log.warning(f"[COMPLIANCE] Workspace {workspace_id} ({row['company_name']}) blocked: {reason}")
            raise SubscriptionError(workspace_id, status, reason)

        if status not in _ACTIVE_STATUSES:
            raise SubscriptionError(workspace_id, status, f"Unknown subscription status: {status}")

        log.debug(f"[COMPLIANCE] Workspace {workspace_id} ({row['company_name']}) status={status} OK")
        return dict(row)

    async def assert_agent_permitted(
        self, workspace_id: str, agent_id: str, cloud_provider: Optional[str] = None
    ) -> None:
        """
        Checks that the workspace tier permits use of this agent.
        Raises SubscriptionError if agent count or cloud provider is out of tier.
        """
        row = await self._db.fetchrow(
            "SELECT product_tier, cloud_providers FROM workspaces WHERE id = $1",
            UUID(workspace_id),
        )
        if not row:
            raise SubscriptionError(workspace_id, "not_found", "Workspace not found")

        tier = row["product_tier"] or "starter"
        limits = self.TIER_LIMITS.get(tier, self.TIER_LIMITS["starter"])

        # Extract agent number from agent_id (e.g. "agent_07_runbook" -> 7)
        agent_num = self._extract_agent_number(agent_id)
        max_agents = limits["max_agents"]
        if max_agents != -1 and agent_num > max_agents:
            raise SubscriptionError(
                workspace_id, "tier_limit",
                f"Agent {agent_id} requires tier upgrade (current: {tier}, max agents: {max_agents})"
            )

        if cloud_provider:
            allowed_providers = row["cloud_providers"] or []
            max_providers = limits["max_cloud_providers"]
            if max_providers != -1 and cloud_provider not in allowed_providers:
                raise SubscriptionError(
                    workspace_id, "tier_limit",
                    f"Cloud provider '{cloud_provider}' not configured for workspace"
                )

    def _reason_for_status(self, status: str) -> str:
        return {
            "past_due":   "Subscription payment past due — please update payment method",
            "canceled":   "Subscription canceled — please resubscribe at cloud-decoded.com",
            "suspended":  "Workspace suspended for terms violation — contact support@kdavisagentic.com",
        }.get(status, f"Subscription status '{status}' does not permit access")

    def _extract_agent_number(self, agent_id: str) -> int:
        """Extracts the numeric position from agent_id like 'agent_07_runbook' -> 7."""
        try:
            parts = agent_id.split("_")
            return int(parts[1]) if len(parts) > 1 else 999
        except (ValueError, IndexError):
            return 999
