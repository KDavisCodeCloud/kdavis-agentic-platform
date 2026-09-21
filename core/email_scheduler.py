"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Cloud Decoded email lifecycle system -- enrollment scheduler (migration
051). Mirrors core/notification_retry.py's claim-loop shape exactly (per
Kelvin's own build spec: "same architecture, don't invent a new one"):
one advisory-locked pass, `LIMIT 100` claim, per-row try/except so one bad
row never blocks the batch, in-process periodic task registered in
api/main.py -- this platform still has no separate worker/cron service.

Runs every 15 minutes (api/main.py). Each pass, per due enrollment:
  1. Skip entirely (whole pass) if outside the send window -- quiet hours
     default 06:00-18:00 America/Phoenix (CD_EMAIL_QUIET_HOURS_TZ env
     override; see GAPS.md -- we don't know a subscriber's real
     timezone, so this is a platform-wide default, not per-recipient).
  2. Evaluate the sequence's exit_rules (jsonb) against the subscriber's
     workspace, if any -- exit without sending if met.
  3. Look up the next approved template for (sequence_key, current_step+1).
     No approved template at that step -> sequence complete.
  4. If the template's skip_if condition is already true, advance past it
     without sending (picked up again next pass for the step after).
  5. Otherwise send via core.marketing_email.send_marketing_email, then
     advance current_step and schedule next_send_at from the FOLLOWING
     step's delay_days (0 if there is no following step -- doesn't matter,
     status flips to 'completed' next pass when no template is found).
"""

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from core.email_enrollment import enroll, exit_enrollment
from core.marketing_email import send_marketing_email
from core.setup_checklist import compute_setup_checklist
from core.unsubscribe_token import UnsubscribeConfigError

log = logging.getLogger(__name__)

# Distinct from every other advisory lock constant in this codebase
# (db/migrate.py 847_291_055, core/retention.py 592_014_773,
# core/onboarding_sequence.py 401_887_226, core/notification_retry.py
# 738_204_915 / 219_663_408) -- must never collide.
_SCHEDULER_LOCK_ID = 674_510_823

_DEFAULT_QUIET_HOURS_TZ = "America/Phoenix"
_SEND_WINDOW_START = time(6, 0)
_SEND_WINDOW_END = time(18, 0)


def _within_send_window(now_utc: datetime, tz_name: str) -> bool:
    """True if now_utc, converted into tz_name, falls within the platform-
    wide send window. Fails OPEN (treats an invalid timezone name as
    'within window' -- i.e. sends proceed) rather than silently freezing
    every marketing send indefinitely on a config typo."""
    try:
        local_now = now_utc.astimezone(ZoneInfo(tz_name)).time()
    except Exception:
        return True
    return _SEND_WINDOW_START <= local_now < _SEND_WINDOW_END


async def _workspace_row(conn, workspace_id) -> Optional[dict]:
    if workspace_id is None:
        return None
    row = await conn.fetchrow(
        """
        SELECT id, stripe_subscription_status, github_app_installation_id,
               github_pat_verified_at, aws_role_verified_at, azure_verified_at,
               azure_devops_pat_verified_at, k8s_verified_at, setup_test_passed_at
        FROM workspaces WHERE id = $1
        """,
        workspace_id,
    )
    return dict(row) if row else None


def _evaluate_exit_rules(exit_rules: dict, workspace: Optional[dict]) -> Optional[str]:
    """Returns an exit reason string if a documented exit condition is
    met, else None. Vocabulary supported this build: 'workspace_active'
    and 'workspace_canceled' -- see GAPS.md for the documented scope of
    the exit-rules engine."""
    if workspace is None:
        return None
    conditions = exit_rules.get("exit_on", [])
    status = workspace.get("stripe_subscription_status")
    if "workspace_active" in conditions and status == "active":
        return "workspace_active"
    if "workspace_canceled" in conditions and status == "canceled":
        return "workspace_canceled"
    return None


async def _evaluate_skip_if(conn, skip_if: Optional[str], workspace: Optional[dict]) -> bool:
    """True if this step's content is already moot and should be skipped
    without sending. Any skip_if that needs workspace data defaults to
    False (never skip) when there is no workspace -- a pure newsletter/
    lead-magnet subscriber has no 'already done' signal to check."""
    if not skip_if or workspace is None:
        return False

    checklist_keys = {
        "cloud_connected", "repo_connected", "alert_source_verified",
        "notification_channel_set", "end_to_end_test_passed",
    }
    if skip_if in checklist_keys:
        checklist = await compute_setup_checklist(conn, workspace)
        return bool(checklist[skip_if])

    if skip_if == "connected_anything":
        checklist = await compute_setup_checklist(conn, workspace)
        return bool(checklist["cloud_connected"] or checklist["repo_connected"])

    if skip_if == "has_members":
        count_row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM workspace_members WHERE workspace_id = $1 AND status IN ('invited', 'active')",
            workspace["id"],
        )
        return count_row["n"] > 1

    if skip_if == "has_first_incident":
        row = await conn.fetchrow("SELECT 1 FROM incidents WHERE workspace_id = $1 LIMIT 1", workspace["id"])
        return row is not None

    log.warning("[EmailScheduler] Unknown skip_if=%r -- treating as never-skip", skip_if)
    return False


async def _next_template(conn, sequence_key: str, step_number: int) -> Optional[dict]:
    row = await conn.fetchrow(
        """
        SELECT key, sequence_key, subject, body_html, body_text, status,
               cta_url, utm_campaign, skip_if, delay_days
        FROM cd_email_templates
        WHERE sequence_key = $1 AND step_number = $2 AND status = 'approved'
        """,
        sequence_key, step_number,
    )
    return dict(row) if row else None


async def _process_one(conn, row: dict) -> str:
    """Returns one of: 'sent', 'skipped', 'suppressed', 'failed',
    'exited', 'completed', 'sequence_inactive'."""
    enrollment_id = str(row["id"])
    subscriber_id = str(row["subscriber_id"])
    sequence_key = row["sequence_key"]
    email = row["email"]

    seq = await conn.fetchrow(
        "SELECT active, exit_rules FROM cd_email_sequences WHERE key = $1", sequence_key,
    )
    if seq is None or not seq["active"]:
        return "sequence_inactive"

    workspace = await _workspace_row(conn, row["workspace_id"])

    exit_reason = _evaluate_exit_rules(dict(seq["exit_rules"]), workspace)
    if exit_reason:
        await exit_enrollment(conn, subscriber_id, sequence_key, exit_reason)
        return "exited"

    next_step = row["current_step"] + 1
    template = await _next_template(conn, sequence_key, next_step)
    if template is None:
        await conn.execute(
            "UPDATE cd_email_enrollments SET status = 'completed' WHERE id = $1", row["id"],
        )
        if sequence_key == "trust_drip":
            # Phase 5 capture spec: trust_drip cross-enrolls into the
            # evergreen newsletter on completion -- a lead-magnet
            # subscriber who finishes the trust sequence becomes a
            # regular newsletter subscriber, not silently done forever.
            await enroll(conn, subscriber_id, "newsletter")
        return "completed"

    if await _evaluate_skip_if(conn, template["skip_if"], workspace):
        await conn.execute(
            "UPDATE cd_email_enrollments SET current_step = $2, next_send_at = NOW() WHERE id = $1",
            row["id"], next_step,
        )
        return "skipped"

    outcome = await send_marketing_email(conn, recipient=email, template=template, enrollment_id=enrollment_id)

    upcoming = await _next_template(conn, sequence_key, next_step + 1)
    next_send_at = datetime.now(timezone.utc) + timedelta(days=upcoming["delay_days"] if upcoming else 0)
    await conn.execute(
        "UPDATE cd_email_enrollments SET current_step = $2, next_send_at = $3 WHERE id = $1",
        row["id"], next_step, next_send_at,
    )
    return outcome


async def run_pending_sends(pool, tz_name: Optional[str] = None) -> dict:
    """One pass: claims every active enrollment due to advance, processes
    each. pg_try_advisory_xact_lock keeps this app's multiple --workers
    processes from double-sending the same batch."""
    tz_name = tz_name or __import__("os").environ.get("CD_EMAIL_QUIET_HOURS_TZ", _DEFAULT_QUIET_HOURS_TZ)
    summary = {
        "attempted": 0, "sent": 0, "skipped": 0, "suppressed": 0,
        "failed": 0, "exited": 0, "completed": 0, "quiet_hours": False,
    }

    now_utc = datetime.now(timezone.utc)
    if not _within_send_window(now_utc, tz_name):
        summary["quiet_hours"] = True
        return summary

    async with pool.acquire() as conn:
        async with conn.transaction():
            got_lock = await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)", _SCHEDULER_LOCK_ID)
            if not got_lock:
                return summary

            rows = await conn.fetch(
                """
                SELECT e.id, e.subscriber_id, e.sequence_key, e.current_step,
                       s.email, s.workspace_id
                FROM cd_email_enrollments e
                JOIN cd_email_subscribers s ON s.id = e.subscriber_id
                WHERE e.status = 'active' AND e.next_send_at <= NOW()
                  AND s.sunset_status = 'active' AND s.unsubscribed_at IS NULL
                ORDER BY e.next_send_at ASC
                LIMIT 100
                """,
            )

            for row in rows:
                summary["attempted"] += 1
                try:
                    outcome = await _process_one(conn, dict(row))
                except UnsubscribeConfigError:
                    log.error(
                        "[EmailScheduler] CD_UNSUBSCRIBE_SECRET is not set -- "
                        "aborting the rest of this pass, no marketing email may send without it"
                    )
                    return summary
                except Exception:
                    log.exception(
                        "[EmailScheduler] Row failed enrollment=%s sequence=%s -- will retry next pass",
                        row["id"], row["sequence_key"],
                    )
                    continue

                if outcome in summary:
                    summary[outcome] += 1

    log.info("[EmailScheduler] Pass complete: %s", summary)
    return summary
