"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Ticketing-system integration fired on incident RESOLUTION (execution_status
flips to 'executed' or 'resolved_manually') -- never on incident creation.
That's core/notifications.py's job (Slack/PagerDuty on creation, wired into
core/hitl.py's create_incident/create_failed_incident). This module is the
resolution-side mirror: same best-effort, non-fatal, fire-and-forget shape,
same standalone-asyncpg-connection reasoning (schedule_resolution_notification
is called via asyncio.create_task() detached from the caller's own request/
resume connection, which may already be released back to the pool by the
time the task actually runs -- see core/notifications.py's module docstring
for the full explanation of why a short-lived DATABASE_URL connection is
used instead of reusing the caller's).

TICKETING_CHANNEL_TYPES are a distinct category from the notification
channels in workspace_notification_channels (slack/pagerduty on creation):
a workspace may have at most ONE ticketing channel configured at a time
(enforced at the application layer in api/routes/workspace_ticketing.py),
whereas Slack and PagerDuty notification channels can both be enabled
simultaneously. PagerDuty resolution-sync (Phase 3) is NOT a ticketing
channel in this sense -- it reuses the workspace's existing 'pagerduty'
notification channel (the same row core/notifications.py's
send_pagerduty_notification already writes a trigger event to) to send a
*resolve* event with a matching dedup_key, so it is dispatched independently
of whatever ticketing channel (if any) is configured.
"""

import asyncio
import json
import logging
import os
from typing import Optional

import asyncpg
import httpx

from security.encryption import decrypt

log = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS = 20.0
_FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")

# The four ticketing providers. A workspace may have zero or one of these
# configured at a time -- see api/routes/workspace_ticketing.py's
# _assert_no_conflicting_ticketing_channel. Kept as one shared constant
# (not four copy-pasted checks) per CLAUDE.md's "extract duplicated pattern
# immediately" rule.
TICKETING_CHANNEL_TYPES = frozenset({"jira", "linear", "github_issues", "servicenow"})


def _incident_url(incident_id: Optional[str]) -> str:
    """
    Best-effort deep link back to the incident. NOTE: as of this build,
    the frontend has no dedicated /incidents/{id} route (confirmed by
    searching frontend/src -- only IncidentConsole.tsx, which renders the
    HITL queue inline on the main dashboard, no per-incident URL). This
    constructs a query-param link on the dashboard route that a future
    incident-detail view could pick up; until then it's a reasonable
    "open the dashboard" link, not a guaranteed working deep link -- a
    real gap, noted here plainly rather than invented away.
    """
    if not incident_id:
        return _FRONTEND_URL
    return f"{_FRONTEND_URL}/dashboard?incident={incident_id}"


def _build_narrative(incident_summary: dict) -> str:
    """
    Full incident narrative shared across every provider's description/
    work_notes field -- one builder instead of four near-identical ones.
    """
    lines = []
    if incident_summary.get("resource_name"):
        lines.append(f"Resource: {incident_summary['resource_name']}")
    if incident_summary.get("resource_group"):
        lines.append(f"Resource group: {incident_summary['resource_group']}")
    if incident_summary.get("metric_name"):
        lines.append(f"Metric: {incident_summary['metric_name']}")
    if incident_summary.get("cloud_provider"):
        lines.append(f"Cloud provider: {incident_summary['cloud_provider']}")
    if incident_summary.get("parsed_error"):
        lines.append(f"Error: {incident_summary['parsed_error']}")
    if incident_summary.get("selected_option_id"):
        lines.append(f"Remediation applied: {incident_summary['selected_option_id']}")
    if incident_summary.get("resolution_note"):
        lines.append(f"Resolution note: {incident_summary['resolution_note']}")
    if incident_summary.get("resolved_by"):
        lines.append(f"Resolved by: {incident_summary['resolved_by']}")
    if incident_summary.get("resolved_at"):
        lines.append(f"Resolved at: {incident_summary['resolved_at']}")
    lines.append(f"Incident: {_incident_url(incident_summary.get('incident_id'))}")
    return "\n".join(lines)


def _summary_line(incident_summary: dict) -> str:
    return (
        incident_summary.get("parsed_error")
        or incident_summary.get("resource_name")
        or "Cloud Decoded incident resolved"
    )


# ── Jira (Phase 1) ──────────────────────────────────────────────────────────

def _jira_priority(incident_summary: dict) -> str:
    """
    Maps incident severity -> Jira priority. GAP: incidents carries no
    severity concept today (confirmed against db/migrations/001 and 029 --
    no severity column exists, and execution_status at resolution time is
    always 'executed' or 'resolved_manually', never a signal of how bad the
    original incident was). Rather than inventing a fake severity field,
    every resolved incident defaults to P3 here. Revisit if/when incidents
    gains a real severity column.
    """
    return "P3"


def _jira_description_adf(text: str) -> dict:
    """Minimal Atlassian Document Format wrapper for a plain-text body --
    Jira Cloud's v3 issue API requires ADF, not a plain string, for
    multi-line description fields."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line}]}
            for line in text.split("\n")
        ],
    }


async def create_jira_ticket(config: dict, incident_summary: dict, resolved_by: Optional[str]) -> dict:
    """
    POST /rest/api/3/issue. Raises on failure -- callers (notify_resolution)
    catch and log.

    Auth GAP: the spec's config shape is instance_url + api_token only (no
    account email). Jira Cloud's documented auth is Basic(email, api_token);
    Jira Data Center/Server PATs authenticate as a bare Bearer token with no
    email needed. This uses `Authorization: Bearer {api_token}` -- correct
    for a Data Center PAT, but a Jira *Cloud* customer would need an email
    field this config shape doesn't currently collect. Noted plainly rather
    than silently inventing an email field the frontend form doesn't ask for.
    """
    instance_url = config["instance_url"].rstrip("/")
    project_key = config["project_key"]
    issue_type = config.get("issue_type") or "Task"

    if incident_summary.get("resolution_note"):
        summary = f"Cloud Decoded incident resolved manually: {_summary_line(incident_summary)}"
    else:
        summary = f"Cloud Decoded incident resolved: {_summary_line(incident_summary)}"

    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary[:255],
            "description": _jira_description_adf(_build_narrative(incident_summary)),
            "issuetype": {"name": issue_type},
            "labels": [
                "cloud-decoded",
                incident_summary.get("cloud_provider") or "unknown-provider",
            ],
            "priority": {"name": _jira_priority(incident_summary)},
        }
    }

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{instance_url}/rest/api/3/issue",
            headers={
                "Authorization": f"Bearer {config['api_token']}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()

    body = response.json()
    key = body.get("key", "")
    return {"external_id": key, "ticket_url": f"{instance_url}/browse/{key}"}


# ── Dispatch ─────────────────────────────────────────────────────────────

async def _dispatch_ticket(channel_type: str, config: dict, incident_summary: dict, resolved_by: Optional[str]) -> dict:
    if channel_type == "jira":
        return await create_jira_ticket(config, incident_summary, resolved_by)
    raise ValueError(f"No ticketing sender registered for channel_type={channel_type!r}")


async def _write_audit_event(conn, workspace_id, incident_id, agent_id, action: str, metadata: dict) -> None:
    await conn.execute(
        """
        INSERT INTO audit_events (workspace_id, agent_id, incident_id, action, status, metadata)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        workspace_id,
        agent_id,
        incident_id,
        action,
        "success" if action == "ticket_created" else "failed",
        json.dumps(metadata),
    )


async def notify_resolution(workspace_id: str, incident_summary: dict, resolved_by: Optional[str] = None) -> None:
    """
    Best-effort, fire-and-forget dispatch on incident resolution. Never
    raises -- every failure (missing DATABASE_URL, DB lookup, decrypt, or
    the outbound ticketing HTTP call) is caught and logged as a warning,
    mirroring core/notifications.py's notify_incident_channels exactly,
    since this always runs detached from the resolution path that
    scheduled it (schedule_resolution_notification below) with nothing
    left to propagate a failure back to.

    Looks up the workspace's single configured ticketing channel (if any)
    and creates a ticket via the matching provider. (Phase 3 adds a second,
    independent dispatch here for PagerDuty resolution-sync, reusing the
    workspace's existing PagerDuty *notification* channel -- a separate
    category from the ticketing channels above, see module docstring.)
    """
    incident_summary = {**incident_summary, "resolved_by": resolved_by}

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        log.warning(
            "[Ticketing] DATABASE_URL not set — skipping resolution ticketing",
            extra={"workspace_id": workspace_id},
        )
        return
    asyncpg_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    try:
        conn = await asyncpg.connect(asyncpg_url, statement_cache_size=0)
    except Exception as exc:
        log.warning(
            "[Ticketing] Could not open DB connection for workspace=%s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id},
        )
        return

    try:
        try:
            row = await conn.fetchrow(
                "SELECT channel_type, config_encrypted FROM workspace_notification_channels "
                "WHERE workspace_id = $1 AND enabled = true AND channel_type = ANY($2::text[])",
                workspace_id,
                list(TICKETING_CHANNEL_TYPES),
            )
        except Exception as exc:
            log.warning(
                "[Ticketing] Channel lookup failed for workspace=%s: %s", workspace_id, exc,
                extra={"workspace_id": workspace_id},
            )
            return

        if row is None:
            return  # no ticketing channel configured -- normal, not an error

        channel_type = row["channel_type"]
        incident_id = incident_summary.get("incident_id")
        agent_id = incident_summary.get("agent_id")
        try:
            config = json.loads(decrypt(row["config_encrypted"]))
            result = await _dispatch_ticket(channel_type, config, incident_summary, resolved_by)
            await _write_audit_event(
                conn, workspace_id, incident_id, agent_id, "ticket_created",
                {"provider": channel_type, **(result or {})},
            )
        except Exception as exc:
            log.warning(
                "[Ticketing] Failed to create ticket for workspace=%s provider=%s: %s",
                workspace_id, channel_type, exc,
                extra={"workspace_id": workspace_id, "channel_type": channel_type},
            )
            try:
                await _write_audit_event(
                    conn, workspace_id, incident_id, agent_id, "ticket_creation_failed",
                    {"provider": channel_type, "error": str(exc)[:500]},
                )
            except Exception:
                pass
    finally:
        await conn.close()


def schedule_resolution_notification(workspace_id: str, incident_summary: dict, resolved_by: Optional[str] = None) -> None:
    """
    Fire-and-forget scheduling helper shared by both resolution call sites
    (core/hitl.py's mark_executed and api/routes/incidents.py's
    resolve_incident_manually) -- extracted so neither duplicates the
    try/except-around-create_task guard (a failure to even schedule the
    task, e.g. no running event loop, must never block incident
    resolution). Mirrors core/hitl.py's own _fire_notification pattern.
    """
    try:
        asyncio.create_task(notify_resolution(workspace_id, incident_summary, resolved_by))
    except Exception as exc:
        log.warning(
            "[Ticketing] Failed to schedule resolution ticketing for workspace=%s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id},
        )
