"""
core/workspace_comp.py
Complimentary ("comped") workspaces (migration 069).

A comp gives a workspace a paid tier with no Stripe subscription: it sets
product_tier, marks the subscription active (so api/middleware/auth.py's
paywall lets it in), and records who/when/why. Every comp writes a
`workspace_comped` audit_events row in the same transaction, so the change
is reconstructable from the workspace's own audit trail.

Callers: POST /internal/workspaces/{id}/comp (platform admin) and
scripts/comp_workspace.py (operator CLI). Both go through comp_workspace().
"""

import json
import logging
from uuid import UUID

from core.compliance import WorkspaceComplianceGuard

log = logging.getLogger(__name__)


class CompError(ValueError):
    """The comp was refused; the message says why."""


async def comp_workspace(conn, workspace_id: str, tier: str, reason: str, actor: str) -> dict:
    """
    Comp `workspace_id` to `tier`. Refuses an unknown tier, an empty reason or
    actor, and a workspace that already has a Stripe customer (it would then
    be both comped and billed). Returns the updated billing fields.
    """
    if tier not in WorkspaceComplianceGuard.TIER_LIMITS:
        raise CompError(f"Unknown tier '{tier}' — must be one of: {', '.join(WorkspaceComplianceGuard.TIER_LIMITS)}")
    reason, actor = (reason or "").strip(), (actor or "").strip()
    if not reason:
        raise CompError("A comp needs a reason")
    if not actor:
        raise CompError("A comp needs the acting admin's identity")

    wid = UUID(str(workspace_id))
    async with conn.transaction():
        ws = await conn.fetchrow(
            "SELECT id, company_name, product_tier, stripe_subscription_status, stripe_customer_id "
            "FROM workspaces WHERE id = $1 FOR UPDATE",
            wid,
        )
        if not ws:
            raise CompError(f"Workspace {workspace_id} not found")
        if ws["stripe_customer_id"]:
            raise CompError("This workspace already has a Stripe customer; cancel its subscription before comping it")

        row = await conn.fetchrow(
            """
            UPDATE workspaces
               SET product_tier = $1, stripe_subscription_status = 'active',
                   comped_at = NOW(), comped_by = $2, comp_reason = $3, updated_at = NOW()
             WHERE id = $4
         RETURNING product_tier, stripe_subscription_status, comped_at, comped_by, comp_reason
            """,
            tier, actor, reason, wid,
        )
        await conn.execute(
            "INSERT INTO audit_events (workspace_id, action, status, metadata) VALUES ($1, 'workspace_comped', 'success', $2::text::jsonb)",
            wid,
            json.dumps({
                "tier": tier,
                "previous_tier": ws["product_tier"],
                "previous_subscription_status": ws["stripe_subscription_status"],
                "reason": reason,
                "comped_by": actor,
            }),
        )

    log.info("[Comp] Workspace=%s (%s) comped to %s by %s", workspace_id, ws["company_name"], tier, actor)
    return dict(row)
