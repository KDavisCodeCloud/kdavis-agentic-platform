"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

24-gap-closure Phase 4's member-deactivation mechanism, factored out so
it has exactly one definition. Originally lived inline in
api/routes/workspace_members.py's deactivate_member (admin-triggered,
single member). Kelvin's item 3 (2026-09-17) reuses it for automatic,
bulk deactivation when a Stripe downgrade drops a workspace below its
new tier's seat cap (api/routes/stripe_billing.py) -- same mechanism,
same guarantees: status='deactivated', any assigned incident returns to
unassigned, one audit_events row per member.
"""

import logging
from uuid import UUID

from core.audit import write_audit_event

log = logging.getLogger(__name__)


async def deactivate_member_row(
    conn,
    workspace_id,
    member_id: UUID,
    member_email: str,
    action: str = "member_deactivated",
) -> dict:
    """
    Runs the deactivation UPDATE + incident-reassignment inside one
    transaction on the given connection, then writes the audit event.
    Caller owns the connection/pool acquisition and any surrounding
    transaction scope for a batch of these.
    """
    async with conn.transaction():
        updated = await conn.fetchrow(
            """
            UPDATE workspace_members
            SET status = 'deactivated', deactivated_at = NOW()
            WHERE id = $1
            RETURNING id, email, role, status, invited_at, joined_at
            """,
            member_id,
        )
        reassigned = await conn.execute(
            "UPDATE incidents SET assigned_to = NULL WHERE assigned_to = $1",
            member_id,
        )

    await write_audit_event(
        workspace_id=str(workspace_id),
        action=action,
        status="success",
        metadata={
            "member_id": str(member_id),
            "member_email": member_email,
            "incidents_unassigned": reassigned,
        },
    )

    log.info(
        "[MemberDeactivation] Deactivated member=%s email=%s workspace=%s action=%s",
        member_id, member_email, workspace_id, action,
    )

    return dict(updated)
