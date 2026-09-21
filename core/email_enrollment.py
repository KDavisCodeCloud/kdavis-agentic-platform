"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Cloud Decoded email lifecycle system -- subscriber/enrollment helpers
(migration 051). Shared by api/routes/email_public.py (subscribe/lead
magnet capture), api/routes/stripe_billing.py (checkout/dunning/winback
triggers), and core/email_scheduler.py (advancing/exiting enrollments on
each pass). Kept separate from core/email_scheduler.py so the public
routes -- which only ever need to enroll/exit, never run a send pass --
don't import the scheduler's send-loop machinery.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

log = logging.getLogger(__name__)


async def get_or_create_subscriber(
    conn, email: str, source: str, workspace_id: Optional[str] = None,
) -> str:
    """Upserts by lower(email). A repeat signup (or a checkout by an
    existing newsletter subscriber) reactivates rather than duplicating --
    sets sunset_status back to 'active' and clears unsubscribed_at, since
    a fresh explicit action is itself renewed consent."""
    email_norm = email.strip().lower()
    row = await conn.fetchrow(
        """
        INSERT INTO cd_email_subscribers (email, source, workspace_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (lower(email)) DO UPDATE SET
            workspace_id = COALESCE(EXCLUDED.workspace_id, cd_email_subscribers.workspace_id),
            unsubscribed_at = NULL,
            sunset_status = 'active'
        RETURNING id
        """,
        email_norm, source, UUID(workspace_id) if workspace_id else None,
    )
    return str(row["id"])


async def get_subscriber_id_by_email(conn, email: str) -> Optional[str]:
    row = await conn.fetchrow(
        "SELECT id FROM cd_email_subscribers WHERE lower(email) = lower($1)", email,
    )
    return str(row["id"]) if row else None


async def enroll(conn, subscriber_id: str, sequence_key: str) -> str:
    """
    Enrolls (or re-enrolls, if a prior enrollment in this sequence had
    exited/completed) a subscriber into a sequence, due to send its first
    step immediately on the scheduler's next pass. Re-enrolling resets
    current_step to 0 -- a subscriber who exited onboarding and later
    qualifies again starts that sequence over, not mid-way.
    """
    row = await conn.fetchrow(
        """
        INSERT INTO cd_email_enrollments (subscriber_id, sequence_key, current_step, status, next_send_at)
        VALUES ($1, $2, 0, 'active', NOW())
        ON CONFLICT (subscriber_id, sequence_key) DO UPDATE SET
            current_step = 0, status = 'active', next_send_at = NOW(),
            enrolled_at = NOW(), exit_reason = NULL
        RETURNING id
        """,
        UUID(subscriber_id), sequence_key,
    )
    return str(row["id"])


async def exit_enrollment(conn, subscriber_id: str, sequence_key: str, reason: str) -> None:
    await conn.execute(
        """
        UPDATE cd_email_enrollments SET status = 'exited', exit_reason = $3
        WHERE subscriber_id = $1 AND sequence_key = $2 AND status = 'active'
        """,
        UUID(subscriber_id), sequence_key, reason,
    )


async def exit_all_enrollments(
    conn, subscriber_id: str, reason: str, except_sequences: tuple[str, ...] = (),
) -> None:
    """Exits every active enrollment for this subscriber except the named
    sequences -- used by the subscription.deleted webhook ('a canceled
    workspace exits everything except winback')."""
    await conn.execute(
        """
        UPDATE cd_email_enrollments SET status = 'exited', exit_reason = $2
        WHERE subscriber_id = $1 AND status = 'active' AND sequence_key <> ALL($3::text[])
        """,
        UUID(subscriber_id), reason, list(except_sequences),
    )


async def enroll_by_email(
    conn, email: str, sequence_key: str, source: str, workspace_id: Optional[str] = None,
) -> str:
    """Convenience wrapper for trigger call sites (Stripe webhooks) that
    only have an email, not an already-resolved subscriber_id."""
    subscriber_id = await get_or_create_subscriber(conn, email, source, workspace_id)
    return await enroll(conn, subscriber_id, sequence_key)


async def has_ever_enrolled_by_email(conn, email: str, sequence_key: str) -> bool:
    """True if a subscriber for this email already has ANY row (active,
    completed, or exited) for this sequence. Used by scheduled scans
    (core/email_triggers.py) whose trigger condition stays true across
    many passes -- without this check, calling enroll_by_email on every
    pass would repeatedly reset the sequence to step 0 and re-send its
    first email forever."""
    row = await conn.fetchrow(
        """
        SELECT 1 FROM cd_email_enrollments e
        JOIN cd_email_subscribers s ON s.id = e.subscriber_id
        WHERE lower(s.email) = lower($1) AND e.sequence_key = $2
        """,
        email, sequence_key,
    )
    return row is not None


async def exit_by_email(
    conn, email: str, sequence_key: str, reason: str,
) -> None:
    subscriber_id = await get_subscriber_id_by_email(conn, email)
    if subscriber_id is None:
        return
    await exit_enrollment(conn, subscriber_id, sequence_key, reason)


async def exit_all_by_email(
    conn, email: str, reason: str, except_sequences: tuple[str, ...] = (),
) -> None:
    subscriber_id = await get_subscriber_id_by_email(conn, email)
    if subscriber_id is None:
        return
    await exit_all_enrollments(conn, subscriber_id, reason, except_sequences)
