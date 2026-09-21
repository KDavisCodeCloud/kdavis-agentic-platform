"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Cloud Decoded email lifecycle system -- the one trigger with no Stripe
event to hook: abandoned checkout. A workspace defaults to
stripe_subscription_status='pending_payment' on creation (migration 021)
and stays there until checkout.session.completed ever fires -- there is
no webhook for "it's been N hours and still hasn't". This periodic scan
(api/main.py, hourly) is the only way to catch that.

Every other trigger (checkout completed, payment failed/past_due,
subscription deleted) is wired directly into api/routes/stripe_billing.py's
existing webhook handlers, next to the transactional emails those
handlers already send -- no separate module needed for those, since a
real Stripe event already exists to hang the enrollment call on.
"""

import logging
from datetime import datetime, timedelta, timezone

from core.email_enrollment import enroll_by_email, has_ever_enrolled_by_email
from core.setup_checklist import compute_setup_checklist

log = logging.getLogger(__name__)

# Distinct from every other advisory lock constant in this codebase.
_ABANDONED_CHECKOUT_LOCK_ID = 118_263_745
_STALL_NUDGE_LOCK_ID = 552_970_314
_STALL_NUDGE_WINDOW = timedelta(hours=72)

_STEP1_WINDOW = timedelta(hours=24)
# Same reasoning as core/onboarding_sequence.py's _ELIGIBILITY_SLACK --
# covers the gap between consecutive hourly scans without emailing a
# workspace that's been abandoned for weeks.
_ELIGIBILITY_SLACK = timedelta(hours=6)


async def run_abandoned_checkout_scan(pool) -> dict:
    """
    One pass: enrolls any still-pending_payment workspace with a known
    contact_email into 'abandoned_checkout' once it crosses the 24h mark
    (its own template steps handle the 24h/72h cadence from there via
    delay_days -- this only needs to enroll once, the scheduler advances
    it). Re-enrolling an already-enrolled workspace is a no-op (enroll()
    resets to step 0 -- guarded against by only enrolling within the
    24h-36h eligibility window, never again after).
    """
    summary = {"enrolled": 0}
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        async with conn.transaction():
            got_lock = await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)", _ABANDONED_CHECKOUT_LOCK_ID)
            if not got_lock:
                return summary

            candidates = await conn.fetch(
                """
                SELECT id, contact_email, created_at
                FROM workspaces
                WHERE stripe_subscription_status = 'pending_payment'
                  AND contact_email IS NOT NULL
                  AND created_at <= $1 AND created_at >= $2
                """,
                now - _STEP1_WINDOW, now - _STEP1_WINDOW - _ELIGIBILITY_SLACK,
            )

            for row in candidates:
                try:
                    await enroll_by_email(
                        conn, row["contact_email"], "abandoned_checkout",
                        source="checkout", workspace_id=str(row["id"]),
                    )
                    summary["enrolled"] += 1
                except Exception:
                    log.exception(
                        "[EmailTriggers] Failed to enroll workspace=%s in abandoned_checkout", row["id"],
                    )

    log.info("[EmailTriggers] Abandoned-checkout scan complete: %s", summary)
    return summary


async def run_stall_nudge_scan(pool) -> dict:
    """
    One pass: enrolls a workspace into 'stall_nudges' once it's 72h past
    its FIRST connection (earliest of aws/azure/k8s/github/azure_devops
    verified_at) with no verified alert source yet -- the narrower
    "connected something but stalled before the real payoff" audience,
    distinct from onboarding's own day-based nudges (which already cover
    "never connected anything"). Step 2 (day-7 "no first incident" nudge)
    fires from step 1 via the template's own delay_days rather than a
    second independent trigger condition -- see GAPS.md for this
    documented simplification.
    """
    summary = {"enrolled": 0}
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        async with conn.transaction():
            got_lock = await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)", _STALL_NUDGE_LOCK_ID)
            if not got_lock:
                return summary

            candidates = await conn.fetch(
                """
                SELECT id, contact_email, aws_role_verified_at, azure_verified_at,
                       k8s_verified_at, github_pat_verified_at, azure_devops_pat_verified_at,
                       github_app_installation_id, setup_test_passed_at
                FROM workspaces
                WHERE contact_email IS NOT NULL
                  AND stripe_subscription_status IN ('active', 'trialing')
                """,
            )

            for row in candidates:
                connected_ats = [
                    ts for ts in (
                        row["aws_role_verified_at"], row["azure_verified_at"], row["k8s_verified_at"],
                        row["github_pat_verified_at"], row["azure_devops_pat_verified_at"],
                    ) if ts is not None
                ]
                if not connected_ats:
                    continue
                first_connected_at = min(connected_ats)
                if now - first_connected_at < _STALL_NUDGE_WINDOW:
                    continue

                checklist = await compute_setup_checklist(conn, dict(row))
                if checklist["alert_source_verified"]:
                    continue

                if await has_ever_enrolled_by_email(conn, row["contact_email"], "stall_nudges"):
                    continue

                try:
                    await enroll_by_email(
                        conn, row["contact_email"], "stall_nudges",
                        source="checkout", workspace_id=str(row["id"]),
                    )
                    summary["enrolled"] += 1
                except Exception:
                    log.exception(
                        "[EmailTriggers] Failed to enroll workspace=%s in stall_nudges", row["id"],
                    )

    log.info("[EmailTriggers] Stall-nudge scan complete: %s", summary)
    return summary
