"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Slack + PagerDuty outbound notifications on incident creation (Tier 1
webhook build, 2026-09-14). Fired best-effort from core/hitl.py's
create_incident() and create_failed_incident() — the single choke point
every one of the 11 agents' _hitl_gate_node already routes through, so
wiring notification dispatch there gives full agent coverage for free.

notify_incident_channels() is fired via asyncio.create_task() from
core/hitl.py, detached from the request/agent-run that triggered it. It
cannot reuse the caller's db connection: HITLGate is handed a connection
checked out from api/routes/webhooks.py's `async with app.state.db_pool.
acquire() as conn:` block, which is very likely to release that
connection back to the pool before a detached background task actually
gets scheduled to run. Reusing it would risk running a query on a
connection another request has since checked out. Instead this opens its
own short-lived asyncpg connection, using the same DATABASE_URL +
statement_cache_size=0 pattern already proven by agents/internal/
portfolio_monitor.py and gap_detector_agent.py for exactly this kind of
standalone, out-of-request connection.
"""

import json
import logging
import os

import asyncpg
import httpx

from security.encryption import decrypt

log = logging.getLogger(__name__)

_SLACK_TIMEOUT_SECONDS = 10.0
_PAGERDUTY_TIMEOUT_SECONDS = 10.0
_PAGERDUTY_EVENTS_URL = "https://events.pagerduty.com/v2/enqueue"


async def send_slack_notification(webhook_url: str, incident_summary: dict) -> None:
    """
    POST a Slack incoming-webhook-compatible message. Raises on failure —
    callers (notify_incident_channels below) are responsible for catching;
    this function itself stays a thin, directly-testable HTTP call.
    """
    async with httpx.AsyncClient(timeout=_SLACK_TIMEOUT_SECONDS) as client:
        response = await client.post(webhook_url, json={"text": _format_slack_text(incident_summary)})
        response.raise_for_status()


async def send_pagerduty_notification(routing_key: str, incident_summary: dict) -> None:
    """
    Trigger a PagerDuty Events API v2 event. Raises on failure — callers
    are responsible for catching.

    Severity mapping: create_failed_incident() means diagnosis itself
    never completed (see core/hitl.py's docstring there) — nothing to
    review, just a broken run — mapped to "critical". A normal
    create_incident() call is a real incident that is already correctly
    paused for a human decision (the system worked as designed), so it's
    mapped to "warning" rather than paging on-call as if something were
    on fire; the operator triages real severity from the options
    presented in the dashboard.

    dedup_key is the incident id, so a future resolution event (not built
    yet — HITL approval doesn't currently emit one) can correlate back to
    this same PagerDuty alert instead of opening a new one.
    """
    severity = "critical" if incident_summary.get("execution_status") == "failed" else "warning"
    body = {
        "routing_key": routing_key,
        "event_action": "trigger",
        "dedup_key": incident_summary.get("incident_id"),
        "payload": {
            "summary": incident_summary.get("summary") or "Cloud Decoded incident",
            "source": incident_summary.get("agent_id") or "cloud-decoded",
            "severity": severity,
            "custom_details": incident_summary,
        },
    }
    async with httpx.AsyncClient(timeout=_PAGERDUTY_TIMEOUT_SECONDS) as client:
        response = await client.post(_PAGERDUTY_EVENTS_URL, json=body)
        response.raise_for_status()


async def send_pagerduty_resolve_event(routing_key: str, incident_summary: dict) -> None:
    """
    Ticketing build, Phase 3 (2026-09-15): sends the resolve event this
    module's own docstring above called out as "not built yet". Uses the
    SAME dedup_key (the incident id) as send_pagerduty_notification's own
    trigger event above -- PagerDuty correlates trigger/resolve purely by
    an exact dedup_key match, so this must read incident_summary["incident_id"]
    the identical way, never re-derive or reformat it. No `payload` block:
    unlike a trigger event, PagerDuty's Events API v2 resolve/acknowledge
    events take only routing_key + event_action + dedup_key. Raises on
    failure -- callers (core/ticketing.py's notify_resolution) catch.
    """
    body = {
        "routing_key": routing_key,
        "event_action": "resolve",
        "dedup_key": incident_summary.get("incident_id"),
    }
    async with httpx.AsyncClient(timeout=_PAGERDUTY_TIMEOUT_SECONDS) as client:
        response = await client.post(_PAGERDUTY_EVENTS_URL, json=body)
        response.raise_for_status()


def _format_slack_text(incident_summary: dict) -> str:
    status = incident_summary.get("execution_status")
    header = "Cloud Decoded — run failed" if status == "failed" else "Cloud Decoded — incident needs approval"
    lines = [
        f"*{header}*",
        f"Agent: {incident_summary.get('agent_id', 'unknown')}",
        f"Summary: {incident_summary.get('summary', '')}",
    ]
    if incident_summary.get("resource_name"):
        lines.append(f"Resource: {incident_summary['resource_name']}")
    if incident_summary.get("alert_name"):
        lines.append(f"Alert: {incident_summary['alert_name']}")
    if incident_summary.get("incident_id"):
        lines.append(f"Incident: {incident_summary['incident_id']}")
    return "\n".join(lines)


async def notify_incident_channels(workspace_id: str, incident_summary: dict) -> None:
    """
    Best-effort fan-out to every enabled notification channel configured
    for a workspace. Never raises — every failure (missing DATABASE_URL,
    the DB lookup itself, decrypt, or the outbound HTTP call) is caught
    and logged as a warning, since this always runs detached from the
    incident-creation path that scheduled it (core/hitl.py) with nothing
    left to propagate a failure back to.
    """
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        log.warning(
            "[Notifications] DATABASE_URL not set — skipping notification fan-out",
            extra={"workspace_id": workspace_id},
        )
        return
    asyncpg_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    try:
        conn = await asyncpg.connect(asyncpg_url, statement_cache_size=0)
    except Exception as exc:
        log.warning(
            "[Notifications] Could not open DB connection for workspace=%s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id},
        )
        return

    try:
        rows = await conn.fetch(
            "SELECT channel_type, config_encrypted FROM workspace_notification_channels "
            "WHERE workspace_id = $1 AND enabled = true",
            workspace_id,
        )
    except Exception as exc:
        log.warning(
            "[Notifications] Channel lookup failed for workspace=%s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id},
        )
        return
    finally:
        await conn.close()

    for row in rows:
        channel_type = row["channel_type"]
        try:
            config = json.loads(decrypt(row["config_encrypted"]))
            if channel_type == "slack":
                await send_slack_notification(config["webhook_url"], incident_summary)
            elif channel_type == "pagerduty":
                await send_pagerduty_notification(config["routing_key"], incident_summary)
            else:
                log.warning(
                    "[Notifications] Unknown channel_type=%s for workspace=%s — skipping",
                    channel_type, workspace_id,
                    extra={"workspace_id": workspace_id, "channel_type": channel_type},
                )
        except Exception as exc:
            log.warning(
                "[Notifications] Failed to notify workspace=%s channel_type=%s: %s",
                workspace_id, channel_type, exc,
                extra={"workspace_id": workspace_id, "channel_type": channel_type},
            )
