"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Settings → Policies (migrations 048/049/050). Admin-only, RBAC-gated, per
Kelvin's spec:

GET   /workspace/policies                  -- read the execution policy
PATCH /workspace/policies/execution        -- toggle auto_execution_enabled
GET   /workspace/policies/exemptions       -- list resource exemptions
DELETE/workspace/policies/exemptions/{id}  -- revoke ("un-exempt") one
POST  /incidents/{id}/exempt-resource      -- "Exempt this resource" action
                                               on the incident card itself
                                               (admin OR approver, same
                                               role gate as approve/reject
                                               — not admin-only, since this
                                               is a routine incident-review
                                               action, not a policy change)

Connection-mode reads (aws_connection_mode/azure_connection_mode) live on
GET /workspace/credentials/status already (workspace_credentials.py) —
not duplicated here; this file owns auto_execution_enabled and resource
exemptions only.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from pydantic import BaseModel, Field

from api.middleware.auth import get_workspace_or_member
from core.audit import write_audit_event
from core.workspace_scope import workspace_scoped_connection

log = logging.getLogger(__name__)
router = APIRouter(tags=["policies"])

# Settings → Policies is admin-only, per spec — stricter than incident
# approve/reject (admin OR approver). A token-authenticated caller (no
# member_role at all) is always permitted, same full-trust convention as
# every other route in this codebase.
_POLICY_ADMIN_ROLES = frozenset({"admin"})
# "Exempt this resource" on the incident card is a routine review action,
# not a policy change — same role gate as api/routes/incidents.py's
# approve_incident/reject_incident (_APPROVAL_ROLES), duplicated here
# rather than imported since that constant is private to that module.
_EXEMPT_ROLES = frozenset({"admin", "approver"})


def _caller_is_policy_admin(workspace: dict) -> bool:
    member_role = workspace.get("member_role")
    if member_role is None:
        return True
    return member_role in _POLICY_ADMIN_ROLES


def _caller_can_exempt(workspace: dict) -> bool:
    member_role = workspace.get("member_role")
    if member_role is None:
        return True
    return member_role in _EXEMPT_ROLES


# ── Models ───────────────────────────────────────────────────────────────

class ExecutionPolicyResponse(BaseModel):
    auto_execution_enabled: bool
    aws_connection_mode: str
    azure_connection_mode: str


class SetExecutionPolicyRequest(BaseModel):
    auto_execution_enabled: bool


class ResourceExemptionResponse(BaseModel):
    id: str
    resource_id: str
    resource_name: Optional[str] = None
    reason: str
    suppressed_count: int
    created_by_email: Optional[str] = None
    created_at: str
    revoked_at: Optional[str] = None


class ExemptionListResponse(BaseModel):
    exemptions: list[ResourceExemptionResponse]


class ExemptResourceRequest(BaseModel):
    reason: str = Field(..., min_length=1)


# ── Execution policy ────────────────────────────────────────────────────

@router.get("/workspace/policies", response_model=ExecutionPolicyResponse)
async def get_execution_policy(
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
) -> ExecutionPolicyResponse:
    if not _caller_is_policy_admin(workspace):
        raise HTTPException(status_code=403, detail="Only a workspace admin can view execution policy")

    async with request.app.state.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT auto_execution_enabled, aws_connection_mode, azure_connection_mode "
            "FROM workspaces WHERE id = $1",
            workspace["id"],
        )
    if not row:
        raise HTTPException(status_code=404, detail="Workspace not found")

    return ExecutionPolicyResponse(
        auto_execution_enabled=row["auto_execution_enabled"],
        aws_connection_mode=row["aws_connection_mode"],
        azure_connection_mode=row["azure_connection_mode"],
    )


@router.patch("/workspace/policies/execution", response_model=ExecutionPolicyResponse)
async def set_execution_policy(
    body: SetExecutionPolicyRequest,
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
) -> ExecutionPolicyResponse:
    """
    Every change writes an audit_events row (Step 1's requirement) with
    the before/after value in metadata — this is the one setting on this
    page that changes what "requires approval" structurally means for the
    workspace, so its change history has to be reconstructable, not just
    its current value.
    """
    if not _caller_is_policy_admin(workspace):
        raise HTTPException(status_code=403, detail="Only a workspace admin can change execution policy")

    workspace_id = workspace["id"]
    async with request.app.state.db_pool.acquire() as conn:
        before = await conn.fetchrow("SELECT auto_execution_enabled FROM workspaces WHERE id = $1", workspace_id)
        if not before:
            raise HTTPException(status_code=404, detail="Workspace not found")

        row = await conn.fetchrow(
            """
            UPDATE workspaces
            SET auto_execution_enabled = $1
            WHERE id = $2
            RETURNING auto_execution_enabled, aws_connection_mode, azure_connection_mode
            """,
            body.auto_execution_enabled,
            workspace_id,
        )

    log.info(
        "[Policies] workspace=%s auto_execution_enabled %s -> %s",
        workspace_id, before["auto_execution_enabled"], body.auto_execution_enabled,
    )
    await write_audit_event(
        workspace_id=str(workspace_id),
        action="execution_policy_changed",
        status="success",
        metadata={
            "before": {"auto_execution_enabled": before["auto_execution_enabled"]},
            "after": {"auto_execution_enabled": body.auto_execution_enabled},
            "changed_by": workspace.get("member_email"),
        },
    )

    return ExecutionPolicyResponse(
        auto_execution_enabled=row["auto_execution_enabled"],
        aws_connection_mode=row["aws_connection_mode"],
        azure_connection_mode=row["azure_connection_mode"],
    )


# ── Resource exemptions ─────────────────────────────────────────────────

@router.get("/workspace/policies/exemptions", response_model=ExemptionListResponse)
async def list_resource_exemptions(
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
) -> ExemptionListResponse:
    if not _caller_is_policy_admin(workspace):
        raise HTTPException(status_code=403, detail="Only a workspace admin can view resource exemptions")

    async with workspace_scoped_connection(request.app.state.db_pool, str(workspace["id"])) as conn:
        rows = await conn.fetch(
            """
            SELECT e.id, e.resource_id, e.resource_name, e.reason, e.suppressed_count,
                   e.created_at, e.revoked_at, m.email AS created_by_email
            FROM resource_exemptions e
            LEFT JOIN workspace_members m ON m.id = e.created_by
            WHERE e.workspace_id = $1
            ORDER BY e.revoked_at IS NOT NULL, e.created_at DESC
            """,
            workspace["id"],
        )

    return ExemptionListResponse(exemptions=[
        ResourceExemptionResponse(
            id=str(r["id"]),
            resource_id=r["resource_id"],
            resource_name=r["resource_name"],
            reason=r["reason"],
            suppressed_count=r["suppressed_count"],
            created_by_email=r["created_by_email"],
            created_at=r["created_at"].isoformat(),
            revoked_at=r["revoked_at"].isoformat() if r["revoked_at"] else None,
        )
        for r in rows
    ])


@router.delete("/workspace/policies/exemptions/{exemption_id}", response_model=ResourceExemptionResponse)
async def revoke_resource_exemption(
    exemption_id: str,
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
) -> ResourceExemptionResponse:
    if not _caller_is_policy_admin(workspace):
        raise HTTPException(status_code=403, detail="Only a workspace admin can revoke a resource exemption")

    async with workspace_scoped_connection(request.app.state.db_pool, str(workspace["id"])) as conn:
        row = await conn.fetchrow(
            """
            UPDATE resource_exemptions
            SET revoked_at = NOW(), revoked_by = $1
            WHERE id = $2 AND workspace_id = $3 AND revoked_at IS NULL
            RETURNING id, resource_id, resource_name, reason, suppressed_count, created_at, revoked_at
            """,
            UUID(workspace["member_id"]) if workspace.get("member_id") else None,
            UUID(exemption_id),
            workspace["id"],
        )

    if not row:
        raise HTTPException(status_code=404, detail="Exemption not found, or already revoked")

    await write_audit_event(
        workspace_id=str(workspace["id"]),
        action="resource_exemption_revoked",
        status="success",
        metadata={"resource_id": row["resource_id"], "exemption_id": exemption_id},
    )

    return ResourceExemptionResponse(
        id=str(row["id"]),
        resource_id=row["resource_id"],
        resource_name=row["resource_name"],
        reason=row["reason"],
        suppressed_count=row["suppressed_count"],
        created_by_email=None,
        created_at=row["created_at"].isoformat(),
        revoked_at=row["revoked_at"].isoformat() if row["revoked_at"] else None,
    )


@router.post("/incidents/{incident_id}/exempt-resource", response_model=ResourceExemptionResponse)
async def exempt_resource_from_incident(
    incident_id: str,
    body: ExemptResourceRequest,
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
) -> ResourceExemptionResponse:
    """
    "Exempt this resource" on the incident card. Reads resource_id/
    resource_name off the incident itself rather than asking the operator
    to retype them — those columns are only reliably populated for
    resource-scoped agents (08/11, migration 029); an incident with no
    resource_id can't be exempted this way (400, not a silent no-op).

    Does not change this incident's own execution_status — exempting a
    resource governs FUTURE alerts for it (checked at ingest, before
    diagnosis); the operator still approves/holds/rejects/resolves the
    incident that's already open through the card's normal controls.
    """
    if not _caller_can_exempt(workspace):
        raise HTTPException(status_code=403, detail="Only an admin or approver can exempt a resource")

    async with workspace_scoped_connection(request.app.state.db_pool, str(workspace["id"])) as conn:
        incident = await conn.fetchrow(
            "SELECT resource_id, resource_name FROM incidents WHERE id = $1 AND workspace_id = $2",
            UUID(incident_id),
            workspace["id"],
        )
        if not incident:
            raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
        if not incident["resource_id"]:
            raise HTTPException(
                status_code=400,
                detail="This incident has no identified resource_id to exempt (only resource-scoped "
                       "agents like Drift Detection and Resource Health populate one).",
            )

        row = await conn.fetchrow(
            """
            INSERT INTO resource_exemptions (workspace_id, resource_id, resource_name, reason, created_by)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (workspace_id, resource_id) DO UPDATE
                SET reason = EXCLUDED.reason, revoked_at = NULL, revoked_by = NULL,
                    created_by = EXCLUDED.created_by, created_at = NOW()
            RETURNING id, resource_id, resource_name, reason, suppressed_count, created_at, revoked_at
            """,
            workspace["id"],
            incident["resource_id"],
            incident["resource_name"],
            body.reason,
            UUID(workspace["member_id"]) if workspace.get("member_id") else None,
        )

    log.info("[Policies] workspace=%s resource=%s exempted", workspace["id"], incident["resource_id"])
    await write_audit_event(
        workspace_id=str(workspace["id"]),
        action="resource_exemption_created",
        status="success",
        incident_id=incident_id,
        metadata={"resource_id": incident["resource_id"], "reason": body.reason},
    )

    return ResourceExemptionResponse(
        id=str(row["id"]),
        resource_id=row["resource_id"],
        resource_name=row["resource_name"],
        reason=row["reason"],
        suppressed_count=row["suppressed_count"],
        created_by_email=workspace.get("member_email"),
        created_at=row["created_at"].isoformat(),
        revoked_at=row["revoked_at"].isoformat() if row["revoked_at"] else None,
    )
