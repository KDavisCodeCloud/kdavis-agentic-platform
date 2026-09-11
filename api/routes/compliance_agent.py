"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Proxy routes to the separately-deployed kdavis-compliance-agent Railway
service. Mirrors api/routes/finops_agent.py's shape exactly, minus the
HITL approve/dismiss routes (compliance reports have no HITL queue --
CIS control pass/fail is deterministic, not something a human approves
or dismisses) and with GET /report in place of GET /dashboard.

GET  /compliance-agent/status      -- read-only, never creates anything
POST /compliance-agent/connect     -- creates the remote tenant once
POST /compliance-agent/verify-role -- verifies a customer-pasted role ARN
POST /compliance-agent/scan        -- triggers a scan
GET  /compliance-agent/report      -- latest CIS gap report
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.middleware.auth import get_workspace
from integrations.compliance_agent_client import AgentServiceError
from integrations import compliance_agent_client as client
from security.encryption import decrypt, encrypt

log = logging.getLogger(__name__)
router = APIRouter(prefix="/compliance-agent", tags=["compliance-agent"])


# ── Request / response models ─────────────────────────────────────────────────

class ConnectionStatusResponse(BaseModel):
    connected: bool
    pending_setup: bool
    setup: dict | None = None


class VerifyRoleRequest(BaseModel):
    role_arn: str


class VerifyRoleResponse(BaseModel):
    status: str


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _get_connection(conn, workspace_id) -> dict | None:
    row = await conn.fetchrow(
        "SELECT compliance_agent_tenant_id, encrypted_compliance_agent_tenant_token, "
        "compliance_agent_setup_json, compliance_agent_connected_at "
        "FROM workspaces WHERE id = $1",
        workspace_id,
    )
    return dict(row) if row else None


def _to_status_response(row: dict | None) -> ConnectionStatusResponse:
    if not row or not row["compliance_agent_tenant_id"]:
        return ConnectionStatusResponse(connected=False, pending_setup=False)
    if not row["compliance_agent_connected_at"]:
        return ConnectionStatusResponse(
            connected=False, pending_setup=True, setup=row["compliance_agent_setup_json"]
        )
    return ConnectionStatusResponse(connected=True, pending_setup=False)


def _require_connected(row: dict | None) -> tuple[str, str]:
    """Returns (tenant_id, decrypted_tenant_token) or raises 400."""
    if not row or not row["compliance_agent_tenant_id"] or not row["compliance_agent_connected_at"]:
        raise HTTPException(status_code=400, detail="Compliance agent not connected yet")
    return str(row["compliance_agent_tenant_id"]), decrypt(row["encrypted_compliance_agent_tenant_token"])


def _upstream_status(exc: AgentServiceError) -> int:
    """Pass through a meaningful 4xx from the remote service (e.g. 404 'no
    scans yet') instead of collapsing every failure to a generic 502."""
    return exc.status_code if exc.status_code and 400 <= exc.status_code < 500 else 502


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status", response_model=ConnectionStatusResponse)
async def get_status(request: Request, workspace: dict = Depends(get_workspace)) -> ConnectionStatusResponse:
    async with request.app.state.db_pool.acquire() as conn:
        row = await _get_connection(conn, workspace["id"])
    return _to_status_response(row)


@router.post("/connect", response_model=ConnectionStatusResponse, status_code=201)
async def connect(request: Request, workspace: dict = Depends(get_workspace)) -> ConnectionStatusResponse:
    workspace_id = workspace["id"]
    async with request.app.state.db_pool.acquire() as conn:
        existing = await _get_connection(conn, workspace_id)
        if existing and existing["compliance_agent_tenant_id"]:
            raise HTTPException(status_code=409, detail="Compliance agent already connected or pending setup")

        try:
            result = await client.create_tenant(workspace["company_name"])
        except AgentServiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        setup_json = {
            "aws_trust_policy": result["aws_trust_policy"],
            "aws_permissions_policy": result["aws_permissions_policy"],
        }
        await conn.execute(
            """
            UPDATE workspaces
            SET compliance_agent_tenant_id = $1,
                encrypted_compliance_agent_tenant_token = $2,
                compliance_agent_setup_json = $3
            WHERE id = $4
            """,
            result["id"],
            encrypt(result["tenant_token"]),
            setup_json,
            workspace_id,
        )

    log.info("[ComplianceAgent] Connected workspace=%s tenant=%s", workspace_id, result["id"])
    return ConnectionStatusResponse(connected=False, pending_setup=True, setup=setup_json)


@router.post("/verify-role", response_model=VerifyRoleResponse)
async def verify_role(
    body: VerifyRoleRequest, request: Request, workspace: dict = Depends(get_workspace)
) -> VerifyRoleResponse:
    workspace_id = workspace["id"]
    async with request.app.state.db_pool.acquire() as conn:
        row = await _get_connection(conn, workspace_id)
        if not row or not row["compliance_agent_tenant_id"]:
            raise HTTPException(status_code=400, detail="Compliance agent connection not started yet")

        tenant_id = str(row["compliance_agent_tenant_id"])
        tenant_token = decrypt(row["encrypted_compliance_agent_tenant_token"])

        try:
            await client.verify_aws_role(tenant_id, tenant_token, body.role_arn)
        except AgentServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        await conn.execute(
            "UPDATE workspaces SET compliance_agent_connected_at = NOW() WHERE id = $1",
            workspace_id,
        )

    log.info("[ComplianceAgent] AWS role verified workspace=%s", workspace_id)
    return VerifyRoleResponse(status="active")


@router.post("/scan")
async def scan(request: Request, workspace: dict = Depends(get_workspace)) -> dict:
    async with request.app.state.db_pool.acquire() as conn:
        row = await _get_connection(conn, workspace["id"])
    tenant_id, tenant_token = _require_connected(row)

    try:
        return await client.trigger_scan(tenant_id, tenant_token)
    except AgentServiceError as exc:
        raise HTTPException(status_code=_upstream_status(exc), detail=str(exc)) from exc


@router.get("/report")
async def report(request: Request, workspace: dict = Depends(get_workspace)) -> dict:
    async with request.app.state.db_pool.acquire() as conn:
        row = await _get_connection(conn, workspace["id"])
    tenant_id, tenant_token = _require_connected(row)

    try:
        return await client.get_report(tenant_id, tenant_token)
    except AgentServiceError as exc:
        raise HTTPException(status_code=_upstream_status(exc), detail=str(exc)) from exc
