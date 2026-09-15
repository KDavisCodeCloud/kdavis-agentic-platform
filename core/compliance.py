"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

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
    - growth:     max 11 agents, 15 repos, 2 cloud providers
    - enterprise: unlimited (subject to custom SLA)

    TIER_LIMITS below is the single source of truth for agent/repo/cloud-
    provider caps across the platform -- api/routes/agents.py's
    GET /agents endpoint reads it directly rather than keeping its own
    copy (see GAPS.md #16 for the drift that caused).
    """

    # max_seats: pricing roadmap's "multi-user seats" tier (3/15/unlimited)
    # -- Membership plan, Phase B. Counts workspace_members rows in
    # ('invited', 'active') status; an invited-but-not-yet-accepted seat
    # still counts against the cap, or unlimited invites could be sent
    # and eventually all accepted past whatever cap looked enforced at
    # invite time. assert_seat_available() below is the enforcement point.
    TIER_LIMITS = {
        "starter":    {"max_agents": 3,  "max_repos": 2,  "max_cloud_providers": 1, "retention_days": 90,  "max_seats": 3},
        # 11, not 10 -- Agent 11 (Cloud Resource Health Monitoring) is a
        # real 2026-09-15 addition to the Growth+ roster, not an
        # Enterprise-exclusive by design. _extract_agent_number() gates
        # purely on the numeric position in agent_id, so this cap must be
        # bumped every time a new agent is added, or the newest agent
        # accidentally becomes Enterprise-only by numbering coincidence
        # rather than a deliberate pricing decision.
        "growth":     {"max_agents": 11, "max_repos": 15, "max_cloud_providers": 2, "retention_days": 365, "max_seats": 15},
        # retention_days: -1 -- same "-1 == unlimited" sentinel as the
        # other limits above -- means Enterprise gets no automatic
        # deletion at all. "Configurable Enterprise" retention (a
        # per-customer override) is a real product surface someone still
        # has to build (a workspace-level column + admin UI), not this
        # dict; -1 is the correct default until that exists. Phase 12,
        # scale-readiness build -- core/retention.py reads this key.
        "enterprise": {"max_agents": -1, "max_repos": -1, "max_cloud_providers": -1, "retention_days": -1, "max_seats": -1},
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

    async def assert_seat_available(self, workspace_id: str) -> None:
        """
        Checks that inviting one more member would not exceed the
        workspace's tier seat cap (TIER_LIMITS[tier]["max_seats"]).
        Raises SubscriptionError if at or over the cap. Membership plan,
        Phase B.

        Counts workspace_members rows in ('invited', 'active') status --
        an invite that's been sent but not yet accepted still occupies a
        seat, otherwise a workspace could send unlimited invites and have
        them all eventually accepted past whatever cap looked enforced at
        invite time. 'deactivated' rows free their seat back up.
        """
        row = await self._db.fetchrow(
            "SELECT product_tier FROM workspaces WHERE id = $1",
            UUID(workspace_id),
        )
        if not row:
            raise SubscriptionError(workspace_id, "not_found", "Workspace not found")

        tier = row["product_tier"] or "starter"
        max_seats = self.TIER_LIMITS.get(tier, self.TIER_LIMITS["starter"])["max_seats"]
        if max_seats == -1:
            return  # unlimited

        count_row = await self._db.fetchrow(
            "SELECT COUNT(*) AS n FROM workspace_members "
            "WHERE workspace_id = $1 AND status IN ('invited', 'active')",
            UUID(workspace_id),
        )
        current_seats = count_row["n"]
        if current_seats >= max_seats:
            raise SubscriptionError(
                workspace_id, "tier_limit",
                f"Seat limit reached (current: {current_seats}, max: {max_seats} on '{tier}' tier) "
                f"— upgrade tier or deactivate a member to invite another"
            )

    def _reason_for_status(self, status: str) -> str:
        return {
            "past_due":   "Subscription payment past due — please update payment method",
            "canceled":   "Subscription canceled — please resubscribe at cloud-decoded.com",
            "suspended":  "Workspace suspended for terms violation — contact support@cloud-decoded.com",
        }.get(status, f"Subscription status '{status}' does not permit access")

    def _extract_agent_number(self, agent_id: str) -> int:
        """Extracts the numeric position from agent_id like 'agent_07_runbook' -> 7."""
        try:
            parts = agent_id.split("_")
            return int(parts[1]) if len(parts) > 1 else 999
        except (ValueError, IndexError):
            return 999
