"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Incidents API routes.

POST /incidents/{id}/approve — operator approves a remediation option
GET  /incidents/{id}         — get incident status and options
GET  /incidents              — list workspace incidents (paginated)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.middleware.auth import get_workspace_or_member
from pydantic import BaseModel

from db.models import (
    IncidentApproveRequest,
    IncidentResolveManuallyRequest,
    IncidentResponse,
    ApprovalResponse,
    ManualResolutionResponse,
    RemediationOption,
)

from agents.agent_01_cicd_triage.workflow import CICDTriageWorkflow
from agents.agent_02_k8s_alert.workflow import K8sAlertWorkflow
from agents.agent_03_pr_review.workflow import PRReviewWorkflow
from agents.agent_04_migration.workflow import MigrationWorkflow
from agents.agent_05_iam_minimizer.workflow import IAMMinimizeWorkflow
from agents.agent_06_finops.workflow import FinOpsWorkflow
from agents.agent_07_runbook.workflow import RunbookWorkflow
from agents.agent_08_drift_detection.workflow import DriftWorkflow
from agents.agent_09_onboarding_buddy.workflow import OnboardingWorkflow
from agents.agent_10_dependency_patch.workflow import DependencyPatchWorkflow
from agents.agent_11_resource_health.workflow import ResourceHealthWorkflow
from core.workspace_credentials import build_agent_credentials, build_k8s_credentials, resolve_k8s_context
from core.workspace_scope import workspace_scoped_connection


class IncidentRejectRequest(BaseModel):
    reason: str

log = logging.getLogger(__name__)
router = APIRouter(prefix="/incidents", tags=["incidents"])

# Membership plan, Phase C (RBAC). A token-authenticated caller (no
# member_role key at all -- see get_workspace_or_member) is always
# permitted, same full-trust model the workspace token already has for
# everything else. A member session must be 'admin' or 'approver';
# 'viewer' is read-only and rejected here.
_APPROVAL_ROLES = frozenset({"admin", "approver"})


def _caller_can_approve_or_reject(workspace: dict) -> bool:
    member_role = workspace.get("member_role")
    if member_role is None:
        return True
    return member_role in _APPROVAL_ROLES

# Every agent's workflow class shares an identical constructor shape
# (WorkflowClass(db_conn, workspace_id, checkpointer)) and .resume(thread_id,
# selected_option) method -- confirmed directly against each agents/agent_0N_*/
# workflow.py before writing this table. approve_incident must dispatch on the
# incident's real agent_id rather than assuming a single agent, or approving a
# non-Agent-01 incident silently resumes the wrong agent's graph (the bug this
# table fixes).
_WORKFLOW_CLASSES: dict[str, type] = {
    "agent_01_cicd_triage": CICDTriageWorkflow,
    "agent_02_k8s_alert": K8sAlertWorkflow,
    "agent_03_pr_review": PRReviewWorkflow,
    "agent_04_migration": MigrationWorkflow,
    "agent_05_iam_minimizer": IAMMinimizeWorkflow,
    "agent_06_finops": FinOpsWorkflow,
    "agent_07_runbook": RunbookWorkflow,
    "agent_08_drift_detection": DriftWorkflow,
    "agent_09_onboarding_buddy": OnboardingWorkflow,
    "agent_10_dependency_patch": DependencyPatchWorkflow,
    "agent_11_resource_health": ResourceHealthWorkflow,
}

# Only these agents' workflow constructors accept the credential kwargs
# build_agent_credentials() returns (github_token/aws_session/azure_access_token/
# azure_devops_token/azure_devops_org) -- see core/workspace_credentials.py.
# Every other agent's *Tools() class takes none of these, so passing them
# unconditionally would raise TypeError.
#
# agent_04_migration and agent_10_dependency_patch were missing from this
# set entirely until the fix that added this comment -- their workflow
# constructors didn't accept credential kwargs at all, so the *initial* run
# (webhooks.py's _run_migration/_run_dependency_patch) AND this resume path
# both always fell back to MigrationTools/DependencyPatchTools' own
# `os.environ.get("GITHUB_TOKEN", "")`, i.e. every real customer's
# migration/dependency-patch PR was either created with the *platform's own*
# GitHub token (a cross-tenant credential leak) or failed outright if that
# env var was unset -- since this resume path is where create_migration_pr/
# create_patch_pr actually execute (the execute node runs after HITL
# approval), that fallback was never actually replaced by the webhooks.py
# fix alone; both call sites needed it.
#
# agent_02_k8s_alert had the exact same gap (Phase 4) -- its workflow
# constructor accepted no credential kwargs either, so K8sTools always fell
# back to a shared os.environ["K8S_API_URL"]/["K8S_TOKEN"]/["GITHUB_TOKEN"].
#
# agent_11_resource_health was missing from _WORKFLOW_CLASSES entirely (not
# just this set) until the live Azure Action Group verification found it,
# 2026-09-15: every real approval of a real Agent 11 incident -- every
# customer, since this agent shipped -- hit a 500 "No workflow class
# registered for agent_id 'agent_11_resource_health'" the moment anything
# other than 'hold' was selected, because approve_incident's dispatch
# never had an entry for it at all. Its constructor takes the exact same
# uniform **creds shape as every other credentialed agent (github_token/
# azure_devops_token/azure_devops_org -- see ResourceHealthWorkflow's
# __init__), so it needs this set too, same as the others above.
_CREDENTIALED_AGENTS = {
    "agent_01_cicd_triage",
    "agent_02_k8s_alert",
    "agent_04_migration",
    "agent_05_iam_minimizer",
    "agent_06_finops",
    "agent_08_drift_detection",
    "agent_10_dependency_patch",
    "agent_11_resource_health",
}


@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(
    incident_id: str,
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
) -> IncidentResponse:
    """
    Get current status of an incident, including diagnosis and options.
    Only returns incidents belonging to the authenticated workspace.
    """
    db = request.app.state.db_pool
    async with workspace_scoped_connection(db, workspace["id"]) as conn:
        row = await conn.fetchrow(
            """
            SELECT id, workspace_id, agent_id, parsed_error, remediation_options,
                   selected_option_id, execution_status, estimated_duration_seconds, tokens_used
            FROM incidents
            WHERE id = $1 AND workspace_id = $2
            """,
            UUID(incident_id),
            workspace["id"],
        )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )

    options_raw = row["remediation_options"]
    if isinstance(options_raw, str):
        options_raw = json.loads(options_raw)

    options = [RemediationOption(**o) for o in (options_raw or [])]

    return IncidentResponse(
        incident_id=str(row["id"]),
        status=row["execution_status"],
        parsed_error=row["parsed_error"],
        options=options,
        estimated_duration_seconds=row["estimated_duration_seconds"],
    )


@router.post("/{incident_id}/approve", response_model=ApprovalResponse)
async def approve_incident(
    incident_id: str,
    body: IncidentApproveRequest,
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
) -> ApprovalResponse:
    """
    Operator approves a remediation option.
    Resumes the paused LangGraph workflow with the selected option.

    - selected_option_id: "opt_1" | "opt_2" | "opt_3" | "hold" | "custom"
    - custom_solution_input: required when selected_option_id == "custom"

    Governance Rule 11: No fix executes without this endpoint being called.
    Membership plan, Phase C: a member session needs role 'admin' or
    'approver' -- 'viewer' is rejected. A token-authenticated caller is
    unaffected (see _caller_can_approve_or_reject).
    """
    if not _caller_can_approve_or_reject(workspace):
        raise HTTPException(
            status_code=403,
            detail="Only an admin or approver can approve a remediation",
        )

    db = request.app.state.db_pool

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, workspace_id, agent_id, execution_status, remediation_options,
                   estimated_duration_seconds, cloud_provider
            FROM incidents
            WHERE id = $1 AND workspace_id = $2
            """,
            UUID(incident_id),
            workspace["id"],
        )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )

    if row["execution_status"] != "pending_approval":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Incident already has status '{row['execution_status']}' — cannot approve",
        )

    selected_id = body.selected_option_id
    custom_input = body.custom_solution_input

    if selected_id == "custom" and not custom_input:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="custom_solution_input is required when selected_option_id is 'custom'",
        )

    # Find the full option object from the stored JSONB
    options_raw = row["remediation_options"]
    if isinstance(options_raw, str):
        options_raw = json.loads(options_raw)
    options = options_raw or []

    if selected_id == "hold":
        selected_option = {
            "id": "hold",
            "title": "Stay broken / custom solution",
            "description": "Operator chose to hold",
        }
        new_status = "held"
    elif selected_id == "custom":
        selected_option = {
            "id": "custom",
            "title": "Custom solution",
            "description": custom_input,
            "custom_input": custom_input,
        }
        new_status = "executing"
    else:
        selected_option = next((o for o in options if o["id"] == selected_id), None)
        if not selected_option:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Option '{selected_id}' not found in this incident",
            )
        new_status = "executing"

    # Update DB status
    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE incidents
            SET execution_status = $1, selected_option_id = $2, custom_solution_input = $3
            WHERE id = $4
            """,
            new_status,
            selected_id,
            custom_input,
            UUID(incident_id),
        )

    log.info(
        "[IncidentsRoute] Incident %s approved: option=%s status=%s",
        incident_id, selected_id, new_status
    )

    # Resume the LangGraph workflow asynchronously
    if new_status == "executing":
        checkpointer = request.app.state.checkpointer

        workflow_cls = _WORKFLOW_CLASSES.get(row["agent_id"])
        if workflow_cls is None:
            # Fail loud, not fail open -- silently resuming some other
            # agent's graph would run the wrong remediation entirely.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"No workflow class registered for agent_id '{row['agent_id']}'",
            )

        # The thread_id stored in the incident's langgraph_thread_id field
        # For now we use incident_id as thread_id (set during workflow.run())
        import asyncio

        async def _resume():
            async with db.acquire() as conn:
                if row["agent_id"] in _CREDENTIALED_AGENTS:
                    creds = await build_agent_credentials(conn, str(workspace["id"]))
                    if row["agent_id"] in ("agent_02_k8s_alert", "agent_08_drift_detection"):
                        # Resume is a separate instantiation from run() (webhooks.py's
                        # _run_k8s_alert_triage/_run_drift_detection) -- both need
                        # this workspace's real per-workspace cluster credentials
                        # (Phase 4) here too, not just on the initial run.
                        creds.update(await build_k8s_credentials(conn, str(workspace["id"])))
                    if row["agent_id"] == "agent_08_drift_detection":
                        # Previously had no idea which cluster this incident was
                        # about on resume -- kubectl always fell back to
                        # KUBECONFIG's default context. Found live: an AKS
                        # incident's real "Apply Correction Directly" approval
                        # silently no-op'd against EKS instead. cloud_provider is
                        # already persisted on the incident row (core/hitl.py's
                        # create_incident), so resolve it the same way run() does.
                        # Only a fallback now -- DriftTools prefers the real
                        # per-workspace k8s_api_url/k8s_token above when present.
                        creds["k8s_context"] = resolve_k8s_context(row["cloud_provider"])
                    agent = workflow_cls(conn, str(workspace["id"]), checkpointer, **creds)
                else:
                    agent = workflow_cls(conn, str(workspace["id"]), checkpointer)
                await agent.resume(incident_id, selected_option)

        # Fire and forget — result is polled via GET /incidents/{id}
        asyncio.create_task(_resume())

    return ApprovalResponse(
        incident_id=incident_id,
        status=new_status,
        selected_option_id=selected_id,
        message="Held — no action taken" if new_status == "held" else "Remediation initiated",
    )


@router.post("/{incident_id}/reject")
async def reject_incident(
    incident_id: str,
    body: IncidentRejectRequest,
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
) -> dict:
    """
    Reject a proposed remediation fix. Records the reason to the audit trail.
    Callable from the dashboard or via the MCP server (mcp:write scope required).
    Membership plan, Phase C: same admin/approver role gate as
    approve_incident (_caller_can_approve_or_reject).
    """
    if not _caller_can_approve_or_reject(workspace):
        raise HTTPException(
            status_code=403,
            detail="Only an admin or approver can reject a remediation",
        )

    db = request.app.state.db_pool

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, execution_status FROM incidents WHERE id = $1 AND workspace_id = $2",
            UUID(incident_id),
            workspace["id"],
        )

    if not row:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

    if row["execution_status"] != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Incident is '{row['execution_status']}' — only pending_approval incidents can be rejected",
        )

    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE incidents
            SET execution_status = 'rejected', custom_solution_input = $1
            WHERE id = $2
            """,
            f"REJECTED: {body.reason}",
            UUID(incident_id),
        )

    log.info("[IncidentsRoute] Incident %s rejected: reason=%s", incident_id, body.reason[:80])

    return {
        "incident_id": incident_id,
        "status": "rejected",
        "reason": body.reason,
    }


@router.post("/{incident_id}/resolve-manually", response_model=ManualResolutionResponse)
async def resolve_incident_manually(
    incident_id: str,
    body: IncidentResolveManuallyRequest,
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
) -> ManualResolutionResponse:
    """
    "I'll handle this myself" — the fourth option on every HITL card,
    alongside the agent-proposed options. This is a resolution
    acknowledgment, not a custom execution path: the platform executes
    nothing here — no cloud API call, no agent workflow resumed, no
    credential access. It records that the operator already resolved the
    incident outside the platform and, optionally, what they did.

    Membership plan, Phase C: same admin/approver role gate as
    approve_incident/reject_incident — a member session needs role
    'admin' or 'approver'; 'viewer' is rejected. A token-authenticated
    caller is unaffected (see _caller_can_approve_or_reject).
    """
    if not _caller_can_approve_or_reject(workspace):
        raise HTTPException(
            status_code=403,
            detail="Only an admin or approver can resolve an incident manually",
        )

    db = request.app.state.db_pool

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, agent_id, execution_status FROM incidents WHERE id = $1 AND workspace_id = $2",
            UUID(incident_id),
            workspace["id"],
        )

    if not row:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

    if row["execution_status"] != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Incident is '{row['execution_status']}' — only pending_approval incidents can be resolved manually",
        )

    # Blank/whitespace-only input is "no note", not a stored empty string —
    # keeps the column and the audit metadata's presence check consistent.
    note = body.resolution_note.strip() if body.resolution_note and body.resolution_note.strip() else None
    resolved_at = datetime.now(timezone.utc)

    async with db.acquire() as conn:
        await conn.execute(
            """
            UPDATE incidents
            SET execution_status = 'resolved_manually', resolution_note = $1, resolved_at = $2
            WHERE id = $3
            """,
            note,
            resolved_at,
            UUID(incident_id),
        )
        # Real audit_events row (not core/hitl.py's operator markdown log) —
        # this is what makes "all incidents resolved manually this month"
        # queryable for the customer's own reporting, per the request this
        # endpoint was built for.
        await conn.execute(
            """
            INSERT INTO audit_events (workspace_id, agent_id, incident_id, action, status, metadata)
            VALUES ($1, $2, $3, 'manual_resolution', 'resolved_manually', $4)
            """,
            workspace["id"],
            row["agent_id"],
            UUID(incident_id),
            json.dumps({"resolution_note": note} if note else {}),
        )

    log.info(
        "[IncidentsRoute] Incident %s resolved manually%s",
        incident_id, " with note" if note else "",
    )

    return ManualResolutionResponse(
        incident_id=incident_id,
        status="resolved_manually",
        resolution_note=note,
        resolved_at=resolved_at,
    )


@router.get("", response_model=list[IncidentResponse])
async def list_incidents(
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[IncidentResponse]:
    """List incidents for the authenticated workspace, newest first."""
    db = request.app.state.db_pool

    query = """
        SELECT id, parsed_error, remediation_options, execution_status, estimated_duration_seconds
        FROM incidents
        WHERE workspace_id = $1
    """
    params = [workspace["id"]]

    if status_filter:
        query += " AND execution_status = $2"
        params.append(status_filter)

    query += f" ORDER BY created_at DESC LIMIT {limit} OFFSET {offset}"

    async with workspace_scoped_connection(db, workspace["id"]) as conn:
        rows = await conn.fetch(query, *params)

    results = []
    for row in rows:
        options_raw = row["remediation_options"]
        if isinstance(options_raw, str):
            options_raw = json.loads(options_raw)
        options = [RemediationOption(**o) for o in (options_raw or [])]
        results.append(
            IncidentResponse(
                incident_id=str(row["id"]),
                status=row["execution_status"],
                parsed_error=row["parsed_error"],
                options=options,
                estimated_duration_seconds=row["estimated_duration_seconds"],
            )
        )
    return results
