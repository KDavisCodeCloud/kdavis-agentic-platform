"""
Onboarding completeness build, item 5 -- extends the existing single
welcome email (core/email.py's welcome_email_html, sent synchronously at
checkout by api/routes/stripe_billing.py's _handle_checkout_completed)
into a 3-email sequence: day 0 (existing, unchanged), day 2, day 5.

Runs as a periodic in-process background task, same pattern as
core/retention.py / api/main.py's _retention_loop -- this platform has
no separate worker/cron service to host a scheduled job elsewhere.
Checked every 6 hours (not 24h like retention) since "day 2"/"day 5" are
date-granularity but a workspace's checkout can happen at any hour --
checking more often keeps each email landing within a few hours of its
target day rather than being delayed up to a full day by an unlucky
checkout time.

Real-signal gating, reading the actual 5-item checklist as of
24-gap-closure Phase 6 (core/setup_checklist.py, migration 046):
  - day-2 ("has this workspace connected anything") -- checklist's
    cloud_connected OR repo_connected.
  - day-5 ("has a real alert source ever delivered a webhook") --
    checklist's alert_source_verified (still, as it always was, backed
    by a real alert_ingestion_log row, migration 030 -- written by
    core/ingestion_log.log_alert_received on every real inbound webhook,
    never a self-reported flag).
  Before Phase 6 shipped the real field, this module re-derived both
  signals independently from raw *_verified_at columns and
  alert_ingestion_log directly -- now calls
  core/setup_checklist.compute_setup_checklist so there is exactly one
  place that decides what "connected" and "alert source verified" mean,
  not two definitions that could drift apart.
  - Each email is sent at most once per workspace (workspace_onboarding_emails,
    migration 041's UNIQUE (workspace_id, email_type) constraint is the
    real enforcement; this module's own check-before-send is redundant
    but avoids a guaranteed-failing INSERT on every cycle after the
    first send).
  - The sequence "stops" implicitly: once a workspace's real signal goes
    true, that email's gate is never true again on a later cycle, so
    nothing further sends for that stage -- there's no separate "cancel"
    step because there's nothing to cancel.
"""

import logging
from datetime import datetime, timedelta, timezone

import asyncpg

from core.email import (
    EmailError,
    onboarding_day2_checklist_html,
    onboarding_day5_setup_help_html,
    send_email,
)
from core.setup_checklist import compute_setup_checklist

log = logging.getLogger(__name__)

# Distinct from db/migrate.py's _ADVISORY_LOCK_ID (847_291_055) and
# core/retention.py's _RETENTION_LOCK_ID (592_014_773) -- must never
# collide with either or any other advisory lock this app takes.
_ONBOARDING_LOCK_ID = 401_887_226

_DAY2_WINDOW = timedelta(days=2)
_DAY5_WINDOW = timedelta(days=5)
# How far past the target day a workspace is still eligible -- covers the
# gap between consecutive 6-hourly checks plus normal operational slack,
# without emailing a workspace that's been stale for weeks.
_ELIGIBILITY_SLACK = timedelta(days=2)


async def _has_connected_anything(conn, row: dict) -> bool:
    checklist = await compute_setup_checklist(conn, row)
    return checklist["cloud_connected"] or checklist["repo_connected"]


async def _has_verified_alert_source(conn, row: dict) -> bool:
    checklist = await compute_setup_checklist(conn, row)
    return checklist["alert_source_verified"]


async def run_onboarding_sequence_check(pool: asyncpg.Pool) -> dict:
    """
    One pass: finds workspaces due for the day-2 or day-5 email, sends
    whichever real signal says is still needed, records it. Returns a
    summary dict for logging/tests -- never raises for an individual
    workspace's email failure (matches core/email.py's own "a broken
    provider must never break the caller" discipline); does propagate a
    genuine DB-connectivity failure, since that's the caller's job to
    retry next cycle, same as core/retention.py's own top-level catch.
    """
    now = datetime.now(timezone.utc)
    sent = {"day2_checklist": 0, "day5_setup_help": 0}

    # Holds one connection + the advisory lock for the whole cycle,
    # including the outbound Resend calls inside _send_once -- correct
    # (the lock is real mutual exclusion across this app's 4 --workers
    # processes, not just a scan optimization; a short-held lock would
    # let two workers both pass the try-lock check across separate
    # transactions and double-send) but a real, bounded tradeoff at this
    # product's current scale (early stage, low candidate volume) --
    # same "hold across the slow part" acceptance core/retention.py's own
    # docstring makes for its DELETE pass. Revisit if candidate volume
    # ever makes a held connection here contend with the request-serving
    # pool (GAPS.md #18 already flags this general class of issue).
    async with pool.acquire() as conn:
        async with conn.transaction():
            locked = await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)", _ONBOARDING_LOCK_ID)
            if not locked:
                log.info("[Onboarding] Another worker already running this cycle's check -- skipping")
                return sent

            candidates = await conn.fetch(
                """
                SELECT id, contact_email, company_name, created_at,
                       github_app_installation_id, github_pat_verified_at,
                       aws_role_verified_at, azure_verified_at,
                       azure_devops_pat_verified_at, k8s_verified_at
                FROM workspaces
                WHERE created_at <= $1 AND contact_email IS NOT NULL
                """,
                now - _DAY2_WINDOW,
            )

            for row in candidates:
                workspace_id = row["id"]
                age = now - row["created_at"]

                if _DAY2_WINDOW <= age <= _DAY2_WINDOW + _ELIGIBILITY_SLACK and not await _has_connected_anything(conn, row):
                    if await _send_once(conn, workspace_id, "day2_checklist", row["contact_email"],
                                         onboarding_day2_checklist_html(row["company_name"])):
                        sent["day2_checklist"] += 1

                if _DAY5_WINDOW <= age <= _DAY5_WINDOW + _ELIGIBILITY_SLACK:
                    if not await _has_verified_alert_source(conn, row):
                        if await _send_once(conn, workspace_id, "day5_setup_help", row["contact_email"],
                                             onboarding_day5_setup_help_html(row["company_name"])):
                            sent["day5_setup_help"] += 1

    log.info("[Onboarding] Sequence check complete: %s", sent)
    return sent


async def _send_once(conn, workspace_id, email_type: str, contact_email: str, html: str) -> bool:
    already_sent = await conn.fetchval(
        "SELECT 1 FROM workspace_onboarding_emails WHERE workspace_id = $1 AND email_type = $2",
        workspace_id, email_type,
    )
    if already_sent:
        return False

    subject = {
        "day2_checklist": "Still time to connect your stack",
        "day5_setup_help": "Let's get an alert source connected",
    }[email_type]

    try:
        await send_email(to=contact_email, subject=subject, html=html)
    except EmailError as exc:
        log.warning("[Onboarding] %s email failed for workspace=%s: %s", email_type, workspace_id, exc)
        return False

    await conn.execute(
        "INSERT INTO workspace_onboarding_emails (workspace_id, email_type) VALUES ($1, $2) "
        "ON CONFLICT (workspace_id, email_type) DO NOTHING",
        workspace_id, email_type,
    )
    return True
