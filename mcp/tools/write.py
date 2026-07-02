"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
Write MCP tools — scope: mcp:write, Growth + Enterprise only, 10 req/min.

approve_incident  — approve the top-recommended fix through the HITL gate
reject_incident   — reject a proposed fix, log reason to audit trail
request_triage    — manually trigger an agent triage against a described event

COMPLIANCE BOUNDARY — enforced on every call:
  - approve_incident calls POST /incidents/{id}/approve on the backend.
    It does NOT bypass or re-implement the HITL gate.
  - execute_fix() is never called from the MCP layer. Execution happens
    inside the backend's LangGraph workflow after the HITL gate clears it.
  - All write actions are logged with full caller identity.
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

# Simple keyword routing table for request_triage.
# Maps keyword substrings (lowercase) → preferred agent_id.
# First match wins. Falls back to agent_01_cicd_triage.
_TRIAGE_ROUTING: list[tuple[str, str]] = [
    ("kubernetes",         "agent_02_k8s_alert"),
    ("k8s",                "agent_02_k8s_alert"),
    ("pod",                "agent_02_k8s_alert"),
    ("crashloopbackoff",   "agent_02_k8s_alert"),
    ("oomkilled",          "agent_02_k8s_alert"),
    ("pull request",       "agent_03_pr_review"),
    ("pr review",          "agent_03_pr_review"),
    ("migration",          "agent_04_migration"),
    ("database",           "agent_04_migration"),
    ("iam",                "agent_05_iam_minimizer"),
    ("permission",         "agent_05_iam_minimizer"),
    ("role",               "agent_05_iam_minimizer"),
    ("cost",               "agent_06_finops"),
    ("spend",              "agent_06_finops"),
    ("billing",            "agent_06_finops"),
    ("runbook",            "agent_07_runbook"),
    ("drift",              "agent_08_drift_detection"),
    ("onboard",            "agent_09_onboarding_buddy"),
    ("dependency",         "agent_10_dependency_patch"),
    ("vulnerability",      "agent_10_dependency_patch"),
    ("cve",                "agent_10_dependency_patch"),
]


def _route_triage(description: str) -> str:
    lower = description.lower()
    for keyword, agent_id in _TRIAGE_ROUTING:
        if keyword in lower:
            return agent_id
    return "agent_01_cicd_triage"


# ── approve_incident ──────────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Approve a proposed incident fix. Triggers the existing HITL approval gate — "
        "the fix is queued for execution, not executed immediately. "
        "Approves the top-recommended option (opt_1) by default. "
        "For custom option selection, use the dashboard. "
        "The approver identity is logged to the audit trail. "
        "Requires mcp:write scope. Growth and Enterprise tiers only."
    )
)
async def approve_incident(
    ctx: Context,
    incident_id: str,
    approver_note: str = "",
) -> dict:
    arg_keys = ["incident_id"] + (["approver_note"] if approver_note else [])
    caller, t0 = await guard("approve_incident", arg_keys)

    try:
        # First, fetch the incident to find the actual option IDs
        incident = await upstream.get(f"/incidents/{incident_id}", caller.workspace_id)
        options: list[dict] = incident.get("options", [])

        if not options:
            await write_audit("approve_incident", caller, arg_keys, "error",
                              int((time.monotonic() - t0) * 1000), "no_options")
            raise ValueError(
                f"Incident '{incident_id}' has no remediation options yet. "
                f"Triage may still be running — call get_incident to check status."
            )

        current_status = incident.get("status")
        if current_status != "pending_approval":
            await write_audit("approve_incident", caller, arg_keys, "error",
                              int((time.monotonic() - t0) * 1000), "wrong_status")
            raise ValueError(
                f"Incident '{incident_id}' is '{current_status}' — "
                f"only incidents in 'pending_approval' state can be approved."
            )

        # Select the first (top-recommended) option
        selected_option_id = options[0].get("id", "opt_1")

        # HARD RULE: call the existing HITL approval gate — never bypass it
        result = await upstream.post(
            f"/incidents/{incident_id}/approve",
            caller.workspace_id,
            body={
                "selected_option_id": selected_option_id,
                "custom_solution_input": approver_note or None,
            },
        )

        approved_option_title = options[0].get("title", selected_option_id)

        response = {
            "incident_id":         incident_id,
            "status":              result.get("status", "executing"),
            "approved_option_id":  selected_option_id,
            "approved_option":     approved_option_title,
            "approver_note":       approver_note or None,
            "approved_by":         caller.subject,
            "message": (
                f"Option '{approved_option_title}' approved. "
                f"Remediation is queued for execution. "
                f"Poll get_incident('{incident_id}') for status updates."
            ),
        }

        await write_audit("approve_incident", caller, arg_keys, "ok",
                          int((time.monotonic() - t0) * 1000), None)
        return response

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        await write_audit("approve_incident", caller, arg_keys, "error",
                          int((time.monotonic() - t0) * 1000), f"http_{status_code}")
        if status_code == 404:
            raise ValueError(
                f"Incident '{incident_id}' not found or does not belong to your workspace."
            ) from exc
        if status_code == 409:
            raise ValueError(
                f"Incident '{incident_id}' cannot be approved in its current state."
            ) from exc
        raise ValueError(f"approve_incident failed: HTTP {status_code}") from exc

    except ValueError:
        raise  # already handled above

    except Exception as exc:
        await write_audit("approve_incident", caller, arg_keys, "error",
                          int((time.monotonic() - t0) * 1000), type(exc).__name__)
        raise ValueError(f"approve_incident failed: {exc}") from exc


# ── reject_incident ───────────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Reject a proposed incident fix. The reason is written to the audit trail. "
        "Only incidents in 'pending_approval' state can be rejected. "
        "Requires mcp:write scope. Growth and Enterprise tiers only."
    )
)
async def reject_incident(
    ctx: Context,
    incident_id: str,
    reason: str,
) -> dict:
    arg_keys = ["incident_id", "reason"]
    caller, t0 = await guard("reject_incident", arg_keys)

    try:
        result = await upstream.post(
            f"/incidents/{incident_id}/reject",
            caller.workspace_id,
            body={"reason": reason},
        )

        response = {
            "incident_id": incident_id,
            "status":      "rejected",
            "rejected_by": caller.subject,
            "message":     f"Incident '{incident_id}' rejected. Reason logged to audit trail.",
        }

        await write_audit("reject_incident", caller, arg_keys, "ok",
                          int((time.monotonic() - t0) * 1000), None)
        return response

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        await write_audit("reject_incident", caller, arg_keys, "error",
                          int((time.monotonic() - t0) * 1000), f"http_{status_code}")
        if status_code == 404:
            raise ValueError(
                f"Incident '{incident_id}' not found or does not belong to your workspace."
            ) from exc
        if status_code == 409:
            raise ValueError(
                f"Incident '{incident_id}' cannot be rejected in its current state."
            ) from exc
        raise ValueError(f"reject_incident failed: HTTP {status_code}") from exc

    except ValueError:
        raise

    except Exception as exc:
        await write_audit("reject_incident", caller, arg_keys, "error",
                          int((time.monotonic() - t0) * 1000), type(exc).__name__)
        raise ValueError(f"reject_incident failed: {exc}") from exc


# ── request_triage ────────────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Manually trigger an agent triage against a described event. "
        "Returns an incident_id immediately — triage runs asynchronously. "
        "Call get_incident(incident_id) to check status and see the proposed fix. "
        "The agent is chosen automatically based on keywords in the description "
        "(kubernetes/k8s → k8s agent, IAM/permission → IAM agent, etc.). "
        "Requires mcp:write scope. Growth and Enterprise tiers only."
    )
)
async def request_triage(
    ctx: Context,
    description: str,
    context: dict | None = None,
) -> dict:
    arg_keys = ["description"] + (["context"] if context else [])
    caller, t0 = await guard("request_triage", arg_keys)

    try:
        agent_id = _route_triage(description)

        payload = {
            "description": description,
            "context":     context or {},
            "source":      "mcp_request_triage",
        }

        result = await upstream.post(
            f"/agents/{agent_id}/run",
            caller.workspace_id,
            body={"payload": payload, "cloud_provider": "unknown"},
        )

        response = {
            "incident_id":  result.get("incident_id", "pending"),
            "agent_id":     agent_id,
            "status":       "pending",
            "message": (
                f"Triage started with {agent_id}. "
                f"Call list_incidents(status_filter='pending_approval') "
                f"to find the incident when triage completes."
            ),
        }

        await write_audit("request_triage", caller, arg_keys, "ok",
                          int((time.monotonic() - t0) * 1000), None)
        return response

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        await write_audit("request_triage", caller, arg_keys, "error",
                          int((time.monotonic() - t0) * 1000), f"http_{status_code}")
        if status_code == 402:
            raise ValueError(
                "Workspace subscription issue — check billing status with get_workspace_status()."
            ) from exc
        raise ValueError(f"request_triage failed: HTTP {status_code}") from exc

    except ValueError:
        raise

    except Exception as exc:
        await write_audit("request_triage", caller, arg_keys, "error",
                          int((time.monotonic() - t0) * 1000), type(exc).__name__)
        raise ValueError(f"request_triage failed: {exc}") from exc
