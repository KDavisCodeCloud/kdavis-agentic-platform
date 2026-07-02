"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
Read-only MCP tools — scope: mcp:read, all tiers, 100 req/min.

list_incidents        — incident queue summary
get_incident          — full incident detail
list_agents           — agents active for this workspace tier
get_workspace_status  — tier, token usage, outreach pacing, billing period
"""

import time
import logging

import httpx
from mcp.server.fastmcp import Context

from mcp_instance import mcp
from middleware import guard
from middleware.audit import write_audit
import upstream

log = logging.getLogger(__name__)


# ── list_incidents ────────────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "List the current incident queue for this workspace. "
        "Returns summary fields only — call get_incident for the full diff and approval history. "
        "Filter by status: pending_approval | executing | executed | held | rejected | failed. "
        "Only incidents from agents accessible to your tier are returned."
    )
)
async def list_incidents(
    ctx: Context,
    status_filter: str | None = None,
) -> list[dict]:
    arg_keys = ["status_filter"] if status_filter is not None else []
    caller, t0 = await guard("list_incidents", arg_keys)

    try:
        params = {"status_filter": status_filter} if status_filter else None
        data = await upstream.get("/incidents", caller.workspace_id, params=params)

        # Reshape to the MCP-facing summary schema
        result = [
            {
                "id":                   inc.get("incident_id"),
                "agent_id":             inc.get("agent_id", "unknown"),
                "status":               inc.get("status"),
                "created_at":           inc.get("created_at"),
                "proposed_fix_summary": _summarize_options(inc.get("options", [])),
                "estimated_duration_s": inc.get("estimated_duration_seconds"),
            }
            for inc in (data if isinstance(data, list) else [])
        ]

        await write_audit("list_incidents", caller, arg_keys, "ok",
                          int((time.monotonic() - t0) * 1000), None)
        return result

    except Exception as exc:
        await write_audit("list_incidents", caller, arg_keys, "error",
                          int((time.monotonic() - t0) * 1000), type(exc).__name__)
        raise ValueError(f"list_incidents failed: {exc}") from exc


def _summarize_options(options: list[dict]) -> str:
    if not options:
        return "No options yet"
    first = options[0]
    title = first.get("title", "")
    desc  = first.get("description", "")
    summary = title if title else desc
    return summary[:200] if summary else "Proposed fix pending"


# ── get_incident ──────────────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Get full detail for a specific incident: the triggering event, "
        "diagnosis, all proposed fix options with descriptions, current status, "
        "and estimated duration. "
        "Raises 404 if the incident does not belong to your workspace."
    )
)
async def get_incident(
    ctx: Context,
    incident_id: str,
) -> dict:
    arg_keys = ["incident_id"]
    caller, t0 = await guard("get_incident", arg_keys)

    try:
        data = await upstream.get(f"/incidents/{incident_id}", caller.workspace_id)

        result = {
            "id":                    data.get("incident_id"),
            "status":                data.get("status"),
            "diagnosis":             data.get("parsed_error"),
            "estimated_duration_s":  data.get("estimated_duration_seconds"),
            "proposed_options":      [
                {
                    "id":          opt.get("id"),
                    "title":       opt.get("title"),
                    "description": opt.get("description"),
                    "impact":      opt.get("impact"),
                    "docs_url":    opt.get("docs_url"),
                }
                for opt in data.get("options", [])
            ],
            "how_to_approve": (
                f"Call approve_incident(incident_id='{data.get('incident_id')}', "
                f"approver_note='your note here') to approve the top option."
            ),
        }

        await write_audit("get_incident", caller, arg_keys, "ok",
                          int((time.monotonic() - t0) * 1000), None)
        return result

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        await write_audit("get_incident", caller, arg_keys, "error",
                          int((time.monotonic() - t0) * 1000), f"http_{status_code}")
        if status_code == 404:
            raise ValueError(
                f"Incident '{incident_id}' not found or does not belong to your workspace."
            ) from exc
        raise ValueError(f"get_incident failed: HTTP {status_code}") from exc

    except Exception as exc:
        await write_audit("get_incident", caller, arg_keys, "error",
                          int((time.monotonic() - t0) * 1000), type(exc).__name__)
        raise ValueError(f"get_incident failed: {exc}") from exc


# ── list_agents ───────────────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "List agents available for your workspace tier. "
        "Agents not accessible to your tier are omitted entirely. "
        "Use the agent IDs from this list when calling request_triage."
    )
)
async def list_agents(ctx: Context) -> list[dict]:
    arg_keys: list[str] = []
    caller, t0 = await guard("list_agents", arg_keys)

    try:
        data = await upstream.get("/agents", caller.workspace_id)

        result = [
            {
                "agent_id":    a.get("id"),
                "name":        a.get("name"),
                "status":      a.get("status", "available"),
            }
            for a in data.get("available_agents", [])
        ]

        await write_audit("list_agents", caller, arg_keys, "ok",
                          int((time.monotonic() - t0) * 1000), None)
        return result

    except Exception as exc:
        await write_audit("list_agents", caller, arg_keys, "error",
                          int((time.monotonic() - t0) * 1000), type(exc).__name__)
        raise ValueError(f"list_agents failed: {exc}") from exc


# ── get_workspace_status ──────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Get current workspace status: subscription tier, active agent count, "
        "monthly token usage vs budget, outreach pacing (daily and weekly sends "
        "vs limits), and the current billing status."
    )
)
async def get_workspace_status(ctx: Context) -> dict:
    arg_keys: list[str] = []
    caller, t0 = await guard("get_workspace_status", arg_keys)

    try:
        # Fetch agents list for active count + pacing in parallel-ish
        # (sequential is fine — both are fast DB reads on the backend)
        agents_data  = await upstream.get("/agents", caller.workspace_id)
        pacing_data  = await upstream.get("/outreach/pacing", caller.workspace_id)
        billing_data = await upstream.get("/billing/status", caller.workspace_id)

        result = {
            "tier":                      billing_data.get("tier", caller.workspace_tier),
            "subscription_status":       billing_data.get("subscription_status"),
            "active_agent_count":        len(agents_data.get("available_agents", [])),
            "outreach_daily_sent":       pacing_data.get("daily_sent"),
            "outreach_daily_limit":      pacing_data.get("daily_limit"),
            "outreach_daily_warning":    pacing_data.get("daily_warning"),
            "outreach_weekly_sent":      pacing_data.get("weekly_sent"),
            "outreach_weekly_limit":     pacing_data.get("weekly_limit"),
            "outreach_weekly_warning":   pacing_data.get("weekly_warning"),
            "acceptance_rate":           pacing_data.get("acceptance_rate"),
            "pacing_message":            pacing_data.get("message"),
        }

        await write_audit("get_workspace_status", caller, arg_keys, "ok",
                          int((time.monotonic() - t0) * 1000), None)
        return result

    except Exception as exc:
        await write_audit("get_workspace_status", caller, arg_keys, "error",
                          int((time.monotonic() - t0) * 1000), type(exc).__name__)
        raise ValueError(f"get_workspace_status failed: {exc}") from exc
