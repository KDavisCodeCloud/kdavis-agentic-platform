"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

24-gap-closure build, Phase 3 — durable outbound retry queue + quiet-hours
digest (migration 043). Both core/notifications.py's notify_incident_channels
and core/ticketing.py's notify_resolution used to just log-and-drop any
failed send ("never raises... every failure is caught and logged as a
warning" — each module's own prior docstring). This module is what those
two now call INTO on a failure instead of only logging, and what the two
new periodic loops (api/main.py) drain.

send_kind distinguishes which sender a retry needs, because channel_type
alone is ambiguous for 'pagerduty' (a create-time trigger event from
core/notifications.py, or a resolve-time resolve event from
core/ticketing.py — two different functions, same channel_type). slack/
email are always 'create'; jira/linear/github_issues/servicenow are
always 'resolve' (ticketing only ever fires on resolution).

Retrying re-fetches the channel's config fresh from
workspace_notification_channels at retry time rather than trusting a
config snapshot taken when the row was enqueued — a channel disabled or
reconfigured between the original failure and a retry attempt should be
respected, not retried against stale/deleted credentials.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import asyncpg

from security.encryption import decrypt

log = logging.getLogger(__name__)

# Exponential backoff by attempt number (0-indexed: the Nth attempt about
# to be made). 5 attempts total, matching Kelvin's own spec exactly.
_BACKOFF_MINUTES = [1, 5, 15, 60, 240]

# Distinct from every other advisory lock constant in this codebase
# (db/migrate.py 847_291_055, core/retention.py 592_014_773,
# core/onboarding_sequence.py 401_887_226) -- must never collide.
_RETRY_LOCK_ID = 738_204_915
_DIGEST_LOCK_ID = 219_663_408


def _asyncpg_url() -> Optional[str]:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        return None
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


async def enqueue_retry(
    workspace_id: str,
    channel_type: str,
    send_kind: str,
    payload_json: dict,
    error: str,
    resolved_by: Optional[str] = None,
) -> None:
    """
    Called from the except block of a failed send, in place of (not in
    addition to — callers still log their own warning first) letting the
    failure just disappear. Opens its own short-lived connection, same
    reasoning as every other detached-background-task DB access in this
    codebase (core/notifications.py's own module docstring explains why).
    Never raises -- an enqueue failure must not be allowed to matter more
    than the send failure that triggered it.
    """
    asyncpg_url = _asyncpg_url()
    if not asyncpg_url:
        return
    try:
        conn = await asyncpg.connect(asyncpg_url, statement_cache_size=0)
    except Exception:
        return
    try:
        await conn.execute(
            """
            INSERT INTO notification_retry_queue
                (workspace_id, channel_type, send_kind, resolved_by, payload_json, last_error, next_attempt_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            workspace_id, channel_type, send_kind, resolved_by,
            json.dumps(payload_json), str(error)[:500],
            datetime.now(timezone.utc) + timedelta(minutes=_BACKOFF_MINUTES[0]),
        )
    except Exception as exc:
        log.warning(
            "[NotificationRetry] Failed to enqueue retry for workspace=%s channel_type=%s: %s",
            workspace_id, channel_type, exc,
        )
    finally:
        await conn.close()


async def _attempt_send(row) -> None:
    """Dispatches one retry row to the correct sender. Raises on failure
    (caller decides backoff/exhaustion) -- mirrors every sender function
    in core/notifications.py/core/ticketing.py, which already raise on
    failure by design."""
    from core.notifications import send_slack_notification, send_pagerduty_notification, send_email_notification
    from core.ticketing import (
        send_pagerduty_resolve_event, create_jira_ticket, create_linear_ticket,
        create_github_issue_ticket, create_servicenow_ticket,
    )

    channel_type = row["channel_type"]
    send_kind = row["send_kind"]
    payload = json.loads(row["payload_json"]) if isinstance(row["payload_json"], str) else row["payload_json"]

    cm = _channel_config(row["workspace_id"], channel_type)
    async with cm as config:
        if config is None:
            raise ValueError(f"channel_type={channel_type} is no longer configured for this workspace")

        if send_kind == "create":
            if channel_type == "slack":
                await send_slack_notification(config["webhook_url"], payload)
            elif channel_type == "pagerduty":
                await send_pagerduty_notification(config["routing_key"], payload)
            elif channel_type == "email":
                await send_email_notification(config["to"], payload)
            else:
                raise ValueError(f"No 'create' sender for channel_type={channel_type!r}")
        else:  # resolve
            resolved_by = row["resolved_by"]
            if channel_type == "pagerduty":
                await send_pagerduty_resolve_event(config["routing_key"], payload)
            elif channel_type == "jira":
                await create_jira_ticket(config, payload, resolved_by)
            elif channel_type == "linear":
                await create_linear_ticket(config, payload, resolved_by)
            elif channel_type == "servicenow":
                await create_servicenow_ticket(config, payload, resolved_by)
            elif channel_type == "github_issues":
                # create_github_issue_ticket needs a live conn -- reuses
                # the same short-lived connection `cm` already opened,
                # matching this module's "one connection per detached
                # task" discipline elsewhere.
                await create_github_issue_ticket(
                    cm.conn, str(row["workspace_id"]), config, payload, resolved_by,
                )
            else:
                raise ValueError(f"No 'resolve' sender for channel_type={channel_type!r}")


class _channel_config:
    """Async context manager: opens one connection, fetches+decrypts the
    named channel's current config (None if disabled/removed since
    enqueue), and exposes the raw connection as .conn for the one sender
    (github_issues) that needs it directly."""
    def __init__(self, workspace_id, channel_type: str):
        self._workspace_id = workspace_id
        self._channel_type = channel_type
        self.conn = None

    async def __aenter__(self):
        asyncpg_url = _asyncpg_url()
        if not asyncpg_url:
            return None
        self.conn = await asyncpg.connect(asyncpg_url, statement_cache_size=0)
        row = await self.conn.fetchrow(
            "SELECT config_encrypted FROM workspace_notification_channels "
            "WHERE workspace_id = $1 AND channel_type = $2 AND enabled = true",
            self._workspace_id, self._channel_type,
        )
        if row is None:
            return None
        return json.loads(decrypt(row["config_encrypted"]))

    async def __aexit__(self, *exc):
        if self.conn is not None:
            await self.conn.close()
        return False


async def run_pending_retries(pool) -> dict:
    """
    One pass: claims every 'pending' row whose next_attempt_at has
    arrived, attempts it, and either deletes it (success), reschedules it
    with the next backoff step, or marks it 'exhausted' (final attempt
    failed). pg_try_advisory_xact_lock keeps this app's multiple
    --workers processes from double-processing the same batch -- same
    reasoning as core/retention.py's own lock.
    """
    summary = {"attempted": 0, "succeeded": 0, "rescheduled": 0, "exhausted": 0}
    async with pool.acquire() as conn:
        async with conn.transaction():
            got_lock = await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)", _RETRY_LOCK_ID)
            if not got_lock:
                return summary

            rows = await conn.fetch(
                """
                SELECT id, workspace_id, channel_type, send_kind, resolved_by, payload_json, attempt_count, max_attempts
                FROM notification_retry_queue
                WHERE status = 'pending' AND next_attempt_at <= NOW()
                ORDER BY next_attempt_at ASC
                LIMIT 100
                """,
            )

            for row in rows:
                summary["attempted"] += 1
                try:
                    await _attempt_send(row)
                    await conn.execute("DELETE FROM notification_retry_queue WHERE id = $1", row["id"])
                    summary["succeeded"] += 1
                except Exception as exc:
                    new_attempt_count = row["attempt_count"] + 1
                    if new_attempt_count >= row["max_attempts"]:
                        await conn.execute(
                            "UPDATE notification_retry_queue SET status = 'exhausted', attempt_count = $1, last_error = $2 WHERE id = $3",
                            new_attempt_count, str(exc)[:500], row["id"],
                        )
                        summary["exhausted"] += 1
                        log.warning(
                            "[NotificationRetry] Exhausted retries for workspace=%s channel_type=%s: %s",
                            row["workspace_id"], row["channel_type"], exc,
                        )
                    else:
                        backoff_idx = min(new_attempt_count, len(_BACKOFF_MINUTES) - 1)
                        next_attempt = datetime.now(timezone.utc) + timedelta(minutes=_BACKOFF_MINUTES[backoff_idx])
                        await conn.execute(
                            "UPDATE notification_retry_queue SET attempt_count = $1, next_attempt_at = $2, last_error = $3 WHERE id = $4",
                            new_attempt_count, next_attempt, str(exc)[:500], row["id"],
                        )
                        summary["rescheduled"] += 1

    return summary


def _in_quiet_hours(start, end, tz_name: str, now_utc: datetime) -> bool:
    """True if now_utc, converted into tz_name, falls within [start, end).
    Handles a window that wraps midnight (e.g. 22:00-07:00). Fails
    OPEN (returns False -- never suppress) on an invalid timezone name,
    since a config error must never silently swallow every incident
    notification for a channel."""
    try:
        local_now = now_utc.astimezone(ZoneInfo(tz_name)).time()
    except Exception:
        return False
    if start <= end:
        return start <= local_now < end
    return local_now >= start or local_now < end  # wraps midnight


async def is_channel_in_quiet_hours(channel_row: dict, now_utc: Optional[datetime] = None) -> bool:
    """channel_row must have quiet_hours_start/quiet_hours_end/quiet_hours_timezone
    keys (may be None -- a channel with no quiet hours configured is
    never in them)."""
    start = channel_row.get("quiet_hours_start")
    end = channel_row.get("quiet_hours_end")
    tz_name = channel_row.get("quiet_hours_timezone")
    if start is None or end is None or not tz_name:
        return False
    return _in_quiet_hours(start, end, tz_name, now_utc or datetime.now(timezone.utc))


async def suppress_for_quiet_hours(workspace_id: str, channel_type: str, incident_summary: dict) -> None:
    """Records a would-have-sent notification as suppressed instead of
    sending it. Never raises -- same discipline as enqueue_retry."""
    asyncpg_url = _asyncpg_url()
    if not asyncpg_url:
        return
    try:
        conn = await asyncpg.connect(asyncpg_url, statement_cache_size=0)
    except Exception:
        return
    try:
        await conn.execute(
            """
            INSERT INTO notification_suppressed (workspace_id, channel_type, incident_id, payload_json)
            VALUES ($1, $2, $3, $4)
            """,
            workspace_id, channel_type, incident_summary.get("incident_id"), json.dumps(incident_summary),
        )
    except Exception as exc:
        log.warning(
            "[NotificationRetry] Failed to record quiet-hours suppression for workspace=%s channel_type=%s: %s",
            workspace_id, channel_type, exc,
        )
    finally:
        await conn.close()


def _format_digest_text(rows: list[dict]) -> str:
    lines = [f"Quiet hours ended — {len(rows)} incident(s) were suppressed:"]
    for r in rows[:20]:
        payload = json.loads(r["payload_json"]) if isinstance(r["payload_json"], str) else r["payload_json"]
        lines.append(f"• {payload.get('summary') or payload.get('parsed_error') or 'Incident'} ({r['incident_id']})")
    if len(rows) > 20:
        lines.append(f"...and {len(rows) - 20} more.")
    return "\n".join(lines)


async def run_quiet_hours_digests(pool) -> dict:
    """
    One pass: for every channel with quiet hours configured that is
    CURRENTLY outside its own window, sends one digest covering every
    un-digested suppressed row for that (workspace, channel) and marks
    them digested. Checking "currently outside the window" on every pass
    (rather than trying to detect the exact moment the window closes)
    means a digest fires on whichever periodic check first runs after
    the window ends -- at most one check-interval late, never missed.
    """
    from core.notifications import send_slack_notification, send_pagerduty_notification, send_email_notification

    summary = {"digests_sent": 0, "incidents_digested": 0}
    async with pool.acquire() as conn:
        async with conn.transaction():
            got_lock = await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)", _DIGEST_LOCK_ID)
            if not got_lock:
                return summary

            channels = await conn.fetch(
                """
                SELECT workspace_id, channel_type, config_encrypted, quiet_hours_start,
                       quiet_hours_end, quiet_hours_timezone
                FROM workspace_notification_channels
                WHERE enabled = true AND quiet_hours_start IS NOT NULL
                  AND quiet_hours_end IS NOT NULL AND quiet_hours_timezone IS NOT NULL
                """,
            )

            for ch in channels:
                if await is_channel_in_quiet_hours(dict(ch)):
                    continue  # still inside the window -- nothing to digest yet

                pending = await conn.fetch(
                    """
                    SELECT id, incident_id, payload_json FROM notification_suppressed
                    WHERE workspace_id = $1 AND channel_type = $2 AND digested = false
                    ORDER BY suppressed_at ASC
                    """,
                    ch["workspace_id"], ch["channel_type"],
                )
                if not pending:
                    continue

                digest_text = _format_digest_text([dict(p) for p in pending])
                try:
                    config = json.loads(decrypt(ch["config_encrypted"]))
                    digest_payload = {"summary": digest_text, "execution_status": "digest"}
                    if ch["channel_type"] == "slack":
                        await send_slack_notification(config["webhook_url"], digest_payload)
                    elif ch["channel_type"] == "email":
                        await send_email_notification(config["to"], digest_payload)
                    elif ch["channel_type"] == "pagerduty":
                        # PagerDuty has no "digest" event shape -- a quiet-hours
                        # digest for PagerDuty is a no-op by design (documented,
                        # not silently skipped): PagerDuty pages are meant to be
                        # real-time, and Kelvin's own spec names it among the
                        # channels that get a *severity floor*, not among the
                        # channels a digest makes sense for.
                        pass
                    summary["digests_sent"] += 1
                    summary["incidents_digested"] += len(pending)
                    await conn.execute(
                        "UPDATE notification_suppressed SET digested = true WHERE id = ANY($1::uuid[])",
                        [p["id"] for p in pending],
                    )
                except Exception as exc:
                    log.warning(
                        "[NotificationRetry] Quiet-hours digest failed for workspace=%s channel_type=%s: %s",
                        ch["workspace_id"], ch["channel_type"], exc,
                    )

    return summary
