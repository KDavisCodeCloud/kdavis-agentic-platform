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

Success/failure logging to audit_events uses core/audit.py's
schedule_audit_event() (GAPS.md #28's real DB writer, landed alongside
this build) rather than a second, parallel ad-hoc INSERT -- one writer
for the whole codebase, same call-site shape core/hitl.py's
_write_audit_entry() uses.
"""

import asyncio
import json
import logging
import os
from typing import Optional

import asyncpg
import httpx

from core.audit import schedule_audit_event
from core.notifications import send_pagerduty_resolve_event
from core.workspace_credentials import build_agent_credentials
from security.encryption import decrypt

log = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS = 20.0
_FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
_GITHUB_API_URL = "https://api.github.com"

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

_JIRA_PRIORITY_MAP = {
    "critical": "P1",
    "high": "P2",
    "medium": "P3",
    "low": "P4",
}


def _jira_priority(incident_summary: dict) -> str:
    """
    Maps incident severity -> Jira priority. Migration 042 (GAPS.md
    24-gap closure Phase 1) added a real severity column to incidents --
    this no longer defaults every ticket to P3 uniformly. Falls back to
    P3 only when severity is genuinely missing (an incident created
    before this migration, or a caller that hasn't threaded severity
    through incident_summary yet), matching the same conservative
    'medium' default used everywhere else severity is unknown.
    """
    return _JIRA_PRIORITY_MAP.get((incident_summary.get("severity") or "").lower(), "P3")


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


# ── Linear (Phase 2) ─────────────────────────────────────────────────────

_LINEAR_API_URL = "https://api.linear.app/graphql"
_LINEAR_LABEL_NAME = "Cloud Decoded"


def _linear_headers(api_key: str) -> dict:
    """Linear's REST-over-GraphQL API takes the API key as a bare
    Authorization header value -- no 'Bearer ' prefix (that's only for
    OAuth access tokens, not personal/workspace API keys). Ref:
    https://developers.linear.app/docs/graphql/working-with-the-graphql-api#authentication"""
    return {"Authorization": api_key, "Content-Type": "application/json"}


async def _linear_graphql(client: httpx.AsyncClient, headers: dict, query: str, variables: dict) -> dict:
    """One GraphQL call. Raises on transport failure (raise_for_status) or
    a GraphQL-level error -- Linear returns HTTP 200 even when the query
    itself failed, with an `errors` array instead of (or alongside)
    `data`, so an HTTP-status-only check would silently treat a bad query
    as success."""
    response = await client.post(_LINEAR_API_URL, headers=headers, json={"query": query, "variables": variables})
    response.raise_for_status()
    body = response.json()
    if body.get("errors"):
        raise RuntimeError(f"Linear GraphQL error: {body['errors']}")
    return body["data"]


async def _linear_label_id(client: httpx.AsyncClient, headers: dict, team_id: str) -> str:
    """Finds this team's 'Cloud Decoded' label, creating it if it doesn't
    exist yet -- Linear has no upsert-by-name for labels, so this is a
    look-up-then-create, same verify-before-write discipline the rest of
    this codebase uses for external credentials."""
    data = await _linear_graphql(
        client, headers,
        "query($teamId: String!, $name: String!) { team(id: $teamId) { "
        "labels(filter: {name: {eq: $name}}) { nodes { id } } } }",
        {"teamId": team_id, "name": _LINEAR_LABEL_NAME},
    )
    nodes = data["team"]["labels"]["nodes"]
    if nodes:
        return nodes[0]["id"]

    data = await _linear_graphql(
        client, headers,
        "mutation($teamId: String!, $name: String!) { "
        "issueLabelCreate(input: {name: $name, teamId: $teamId}) { issueLabel { id } } }",
        {"teamId": team_id, "name": _LINEAR_LABEL_NAME},
    )
    return data["issueLabelCreate"]["issueLabel"]["id"]


async def _linear_done_state_id(client: httpx.AsyncClient, headers: dict, team_id: str) -> Optional[str]:
    """Finds this team's workflow state with type == 'completed' (Linear's
    canonical "Done" bucket -- a team's actual state name can be
    localized/customized, but the `type` enum is stable). Returns None if
    the team somehow has no completed-type state (unusual, not fatal --
    the issue still gets created via create_linear_ticket, just without
    an explicit stateId, so it lands in the team's default state)."""
    data = await _linear_graphql(
        client, headers,
        "query($teamId: String!) { team(id: $teamId) { states(filter: {type: {eq: \"completed\"}}) "
        "{ nodes { id } } } }",
        {"teamId": team_id},
    )
    nodes = data["team"]["states"]["nodes"]
    return nodes[0]["id"] if nodes else None


async def create_linear_ticket(config: dict, incident_summary: dict, resolved_by: Optional[str]) -> dict:
    """
    Creates a Linear issue, state=Done, labeled 'Cloud Decoded' (created
    for the team if it doesn't already exist). Raises on failure --
    callers (notify_resolution) catch and log.
    """
    team_id = config["team_id"]
    headers = _linear_headers(config["api_key"])

    if incident_summary.get("resolution_note"):
        title = f"Cloud Decoded incident resolved manually: {_summary_line(incident_summary)}"
    else:
        title = f"Cloud Decoded incident resolved: {_summary_line(incident_summary)}"

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        label_id = await _linear_label_id(client, headers, team_id)
        state_id = await _linear_done_state_id(client, headers, team_id)

        issue_input = {
            "teamId": team_id,
            "title": title[:255],
            "description": _build_narrative(incident_summary),
            "labelIds": [label_id],
        }
        if state_id:
            issue_input["stateId"] = state_id

        data = await _linear_graphql(
            client, headers,
            "mutation($input: IssueCreateInput!) { issueCreate(input: $input) "
            "{ success issue { id identifier url } } }",
            {"input": issue_input},
        )

    issue = (data.get("issueCreate") or {}).get("issue") or {}
    return {"external_id": issue.get("identifier") or issue.get("id", ""), "ticket_url": issue.get("url", "")}


# ── GitHub Issues (Phase 4) ──────────────────────────────────────────────

def _github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def create_github_issue_ticket(
    conn, workspace_id: str, config: dict, incident_summary: dict, resolved_by: Optional[str]
) -> dict:
    """
    Creates a GitHub issue via the workspace's existing GitHub App
    installation token -- reuses core/workspace_credentials.py's
    build_agent_credentials() (the same credential resolution every
    other agent already uses), no new credential storage for this
    provider. Config carries only `repo` ("owner/repo").

    GAP, stated plainly rather than invented away: no incident-creation-
    time GitHub issue exists anywhere in this codebase for this hook to
    close (confirmed -- core/notifications.py's create-time dispatch
    only ever sends Slack/PagerDuty). "Close the issue on resolution"
    therefore means create-then-immediately-close: GitHub's Issues API
    has no way to create an issue already in the closed state, so this
    POSTs to open it, then PATCHes state=closed right after, with the
    body making clear it documents an incident that already resolved --
    not one still needing triage.

    Raises on failure -- callers (notify_resolution) catch and log.
    """
    repo_full = config["repo"]
    if "/" not in repo_full:
        raise ValueError(f"GitHub Issues config 'repo' must be 'owner/repo', got {repo_full!r}")
    owner, repo = repo_full.split("/", 1)

    creds = await build_agent_credentials(conn, workspace_id)
    token = creds.get("github_token")
    if not token:
        raise RuntimeError(
            "No GitHub credentials configured for this workspace -- install the GitHub App first"
        )

    if incident_summary.get("resolution_note"):
        title = f"Cloud Decoded incident resolved manually: {_summary_line(incident_summary)}"
    else:
        title = f"Cloud Decoded incident resolved: {_summary_line(incident_summary)}"

    body = (
        _build_narrative(incident_summary)
        + "\n\n_This issue was opened and closed automatically by Cloud Decoded -- "
        "it documents an incident that already resolved, not one that needs triage._"
    )

    headers = _github_headers(token)

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        create_resp = await client.post(
            f"{_GITHUB_API_URL}/repos/{owner}/{repo}/issues",
            headers=headers,
            json={"title": title[:255], "body": body, "labels": ["cloud-decoded-incident"]},
        )
        create_resp.raise_for_status()
        issue = create_resp.json()
        issue_number = issue["number"]

        close_resp = await client.patch(
            f"{_GITHUB_API_URL}/repos/{owner}/{repo}/issues/{issue_number}",
            headers=headers,
            json={"state": "closed"},
        )
        close_resp.raise_for_status()

    return {"external_id": str(issue_number), "ticket_url": issue.get("html_url", "")}


# ── ServiceNow (Phase 5, Enterprise tier only) ───────────────────────────

async def create_servicenow_ticket(config: dict, incident_summary: dict, resolved_by: Optional[str]) -> dict:
    """
    POSTs a change_request to ServiceNow's Table API, state=closed (the
    incident already resolved by the time this fires). Basic Auth with
    the workspace's stored ServiceNow username/password -- ServiceNow's
    Table API supports OAuth too, but Basic Auth against a dedicated
    integration user is the documented baseline and matches this
    provider's config shape (username + password, no OAuth client
    registration step for the customer to do).

    GAP, stated plainly: ServiceNow's `state` field for change_request is
    normally a numeric choice-list value whose actual codes vary per
    instance (a customer's ServiceNow admin can remap them) -- there is
    no universal "closed" constant. This sends the literal string
    "closed" per the spec's own wording; a real customer's instance may
    require a numeric code instead (commonly "3" or "7" for Closed/
    Complete, but not guaranteed). Flagged here rather than silently
    guessing a numeric value that might be wrong for a given instance.

    Raises on failure -- callers (notify_resolution) catch and log.
    """
    instance_url = config["instance_url"].rstrip("/")
    username = config["username"]
    password = config["password"]
    assignment_group = config.get("assignment_group")

    if incident_summary.get("resolution_note"):
        short_description = f"Cloud Decoded incident resolved manually: {_summary_line(incident_summary)}"
    else:
        short_description = f"Cloud Decoded incident resolved: {_summary_line(incident_summary)}"

    payload = {
        "short_description": short_description[:160],
        "work_notes": _build_narrative(incident_summary),
        "state": "closed",
    }
    if assignment_group:
        payload["assignment_group"] = assignment_group

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{instance_url}/api/now/table/change_request",
            auth=(username, password),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()

    body = response.json()
    result = body.get("result", {})
    sys_id = result.get("sys_id", "")
    number = result.get("number", sys_id)
    ticket_url = f"{instance_url}/nav_to.do?uri=change_request.do?sys_id={sys_id}" if sys_id else ""
    return {"external_id": number, "ticket_url": ticket_url}


# ── Dispatch ─────────────────────────────────────────────────────────────

async def _dispatch_ticket(
    channel_type: str,
    config: dict,
    incident_summary: dict,
    resolved_by: Optional[str],
    conn=None,
    workspace_id: Optional[str] = None,
) -> dict:
    if channel_type == "jira":
        return await create_jira_ticket(config, incident_summary, resolved_by)
    if channel_type == "linear":
        return await create_linear_ticket(config, incident_summary, resolved_by)
    if channel_type == "github_issues":
        return await create_github_issue_ticket(conn, workspace_id, config, incident_summary, resolved_by)
    if channel_type == "servicenow":
        return await create_servicenow_ticket(config, incident_summary, resolved_by)
    raise ValueError(f"No ticketing sender registered for channel_type={channel_type!r}")


async def _dispatch_pagerduty_resolve(conn, workspace_id: str, incident_summary: dict) -> None:
    """
    Independent of the one-ticketing-channel dispatch below -- reuses the
    workspace's existing PagerDuty *notification* channel (migration 037,
    the same row core/notifications.py's send_pagerduty_notification
    already sends a trigger event to on incident creation), not the
    ticketing-channel category. Best-effort: any failure here (no channel
    configured, decrypt failure, HTTP failure) is caught and logged, never
    raised -- a workspace with no PagerDuty channel at all is the normal
    case and must not log a warning for it, so a missing row is a silent
    no-op, not treated as a failure.
    """
    try:
        row = await conn.fetchrow(
            "SELECT config_encrypted FROM workspace_notification_channels "
            "WHERE workspace_id = $1 AND channel_type = 'pagerduty' AND enabled = true",
            workspace_id,
        )
        if row is None:
            return

        config = json.loads(decrypt(row["config_encrypted"]))
        await send_pagerduty_resolve_event(config["routing_key"], incident_summary)
        schedule_audit_event(
            workspace_id=workspace_id,
            action="ticket_created",
            status="success",
            incident_id=incident_summary.get("incident_id"),
            agent_id=incident_summary.get("agent_id"),
            metadata={"provider": "pagerduty_resolve"},
        )
    except Exception as exc:
        log.warning(
            "[Ticketing] PagerDuty resolve-event failed for workspace=%s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id},
        )
        try:
            schedule_audit_event(
                workspace_id=workspace_id,
                action="ticket_creation_failed",
                status="failed",
                incident_id=incident_summary.get("incident_id"),
                agent_id=incident_summary.get("agent_id"),
                metadata={"provider": "pagerduty_resolve", "error": str(exc)[:500]},
            )
        except Exception:
            pass


async def notify_resolution(workspace_id: str, incident_summary: dict, resolved_by: Optional[str] = None) -> None:
    """
    Best-effort, fire-and-forget dispatch on incident resolution. Never
    raises -- every failure (missing DATABASE_URL, DB lookup, decrypt, or
    the outbound ticketing HTTP call) is caught and logged as a warning,
    mirroring core/notifications.py's notify_incident_channels exactly,
    since this always runs detached from the resolution path that
    scheduled it (schedule_resolution_notification below) with nothing
    left to propagate a failure back to.

    Does two independent things: (1) sends a PagerDuty resolve event via
    _dispatch_pagerduty_resolve if the workspace has a PagerDuty
    *notification* channel configured (a separate category from ticketing
    channels, see module docstring); (2) looks up the workspace's single
    configured ticketing channel (if any) and creates a ticket via the
    matching provider. Either, both, or neither may fire for a given
    resolution depending on what the workspace has configured.
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
        await _dispatch_pagerduty_resolve(conn, workspace_id, incident_summary)

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
            result = await _dispatch_ticket(
                channel_type, config, incident_summary, resolved_by, conn=conn, workspace_id=workspace_id,
            )
            schedule_audit_event(
                workspace_id=workspace_id,
                action="ticket_created",
                status="success",
                incident_id=incident_id,
                agent_id=agent_id,
                metadata={"provider": channel_type, **(result or {})},
            )
        except Exception as exc:
            log.warning(
                "[Ticketing] Failed to create ticket for workspace=%s provider=%s: %s",
                workspace_id, channel_type, exc,
                extra={"workspace_id": workspace_id, "channel_type": channel_type},
            )
            try:
                schedule_audit_event(
                    workspace_id=workspace_id,
                    action="ticket_creation_failed",
                    status="failed",
                    incident_id=incident_id,
                    agent_id=agent_id,
                    metadata={"provider": channel_type, "error": str(exc)[:500]},
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
