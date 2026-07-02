"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

"""
Incidents API routes.

POST /incidents/{id}/approve — operator approves a remediation option
GET  /incidents/{id}         — get incident status and options
GET  /incidents              — list workspace incidents (paginated)
"""

import json
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.middleware.auth import get_workspace
from pydantic import BaseModel

from db.models import (
    Incident,
    IncidentApproveRequest,
    IncidentResponse,
    ApprovalResponse,
    RemediationOption,
)


class IncidentRejectRequest(BaseModel):
    reason: str

log = logging.getLogger(__name__)
router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(
    incident_id: str,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> IncidentResponse:
    """
    Get current status of an incident, including diagnosis and options.
    Only returns incidents belonging to the authenticated workspace.
    """
    db = request.app.state.db_pool
    async with db.acquire() as conn:
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
    workspace: dict = Depends(get_workspace),
) -> ApprovalResponse:
    """
    Operator approves a remediation option.
    Resumes the paused LangGraph workflow with the selected option.

    - selected_option_id: "opt_1" | "opt_2" | "opt_3" | "hold" | "custom"
    - custom_solution_input: required when selected_option_id == "custom"

    Governance Rule 11: No fix executes without this endpoint being called.
    """
    db = request.app.state.db_pool

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, workspace_id, agent_id, execution_status, remediation_options,
                   estimated_duration_seconds
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

        # The thread_id stored in the incident's langgraph_thread_id field
        # For now we use incident_id as thread_id (set during workflow.run())
        from agents.agent_01_cicd_triage.workflow import CICDTriageWorkflow
        import asyncio

        async def _resume():
            async with db.acquire() as conn:
                agent = CICDTriageWorkflow(conn, str(workspace["id"]), checkpointer)
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
    workspace: dict = Depends(get_workspace),
) -> dict:
    """
    Reject a proposed remediation fix. Records the reason to the audit trail.
    Callable from the dashboard or via the MCP server (mcp:write scope required).
    """
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


@router.get("", response_model=list[IncidentResponse])
async def list_incidents(
    request: Request,
    workspace: dict = Depends(get_workspace),
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

    async with db.acquire() as conn:
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
