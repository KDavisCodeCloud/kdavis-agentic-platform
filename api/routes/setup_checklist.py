"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

24-gap-closure build, Phase 6 -- the 5-item setup completeness checklist
(cloud connected / repo connected / alert source verified / notification
channel set / end-to-end test passed) as a persistent dashboard card
until 5/5, plus the connection-test button that proves item 5.

GET    /workspace/setup-checklist               -- read all 5 items
POST   /workspace/setup-checklist/test           -- create a synthetic
                                                     TEST incident through
                                                     the real pipeline
DELETE /workspace/setup-checklist/test/{id}      -- one-click cleanup;
                                                     flips item 5 true

alert_source_verified deliberately reads alert_ingestion_log (migration
030, written only by core/ingestion_log.log_alert_received on a real
inbound webhook) rather than any self-reported flag -- per Kelvin's
explicit spec, this item must flip only on a real received delivery.
This is the exact same real signal core/onboarding_sequence.py's
_has_verified_alert_source already used as its pre-Phase-6 proxy; see
that module's own updated docstring for the follow-up this phase closes.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.middleware.auth import get_workspace_or_member
from core.audit import write_audit_event
from core.hitl import HITLGate
from core.setup_checklist import compute_setup_checklist

log = logging.getLogger(__name__)
router = APIRouter(prefix="/workspace/setup-checklist", tags=["setup-checklist"])


class SetupChecklistResponse(BaseModel):
    cloud_connected: bool
    repo_connected: bool
    alert_source_verified: bool
    notification_channel_set: bool
    end_to_end_test_passed: bool
    completed_count: int


class ConnectionTestResponse(BaseModel):
    incident_id: str


class CleanupConnectionTestResponse(BaseModel):
    status: str = "cleaned_up"


@router.get("", response_model=SetupChecklistResponse)
async def get_setup_checklist(
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
) -> SetupChecklistResponse:
    async with request.app.state.db_pool.acquire() as conn:
        checklist = await compute_setup_checklist(conn, workspace)
    return SetupChecklistResponse(**checklist)


@router.post("/test", response_model=ConnectionTestResponse, status_code=201)
async def run_connection_test(
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
) -> ConnectionTestResponse:
    """
    Creates a real incident row through the exact same HITLGate.create_incident
    path every real agent uses -- proves the DB write, notification
    fan-out, and dashboard listing all genuinely work end to end, not a
    fabricated "looks connected" response. agent_id is a sentinel with no
    entry in api/routes/incidents.py's _WORKFLOW_CLASSES, so approving it
    is short-circuited there to simulate success rather than 500ing on a
    missing workflow class.
    """
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        gate = HITLGate(conn)
        incident_id = await gate.create_incident(
            workspace_id=str(workspace["id"]),
            agent_id="system_connection_test",
            raw_log="Synthetic end-to-end connection test",
            parsed_error="TEST: synthetic incident created to verify your pipeline end to end",
            remediation_options=[
                {
                    "id": "opt_1",
                    "title": "Approve (test)",
                    "description": "Simulates approving a real remediation -- nothing executes.",
                },
            ],
            severity="low",
        )
        await conn.execute("UPDATE incidents SET is_test = true WHERE id = $1", UUID(incident_id))

    log.info("[SetupChecklist] Connection test incident=%s workspace=%s", incident_id, workspace["id"])
    return ConnectionTestResponse(incident_id=incident_id)


@router.delete("/test/{incident_id}", response_model=CleanupConnectionTestResponse)
async def cleanup_connection_test(
    incident_id: str,
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
) -> CleanupConnectionTestResponse:
    """
    One-click cleanup. Scoped to is_test = true so this can never delete
    a real incident even given a crafted id. Flips end_to_end_test_passed
    here (not on creation) -- proof the customer actually saw the test
    incident land in their dashboard and closed the loop, not just that
    the create call itself succeeded.
    """
    try:
        incident_uuid = UUID(incident_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="incident_id must be a valid UUID")

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM incidents WHERE id = $1 AND workspace_id = $2 AND is_test = true",
            incident_uuid, workspace["id"],
        )
        if not row:
            raise HTTPException(status_code=404, detail="Test incident not found")

        await conn.execute("DELETE FROM incidents WHERE id = $1", incident_uuid)
        await conn.execute(
            "UPDATE workspaces SET setup_test_passed_at = NOW() WHERE id = $1", workspace["id"],
        )

    await write_audit_event(
        workspace_id=str(workspace["id"]),
        action="connection_test_cleaned_up",
        status="success",
        incident_id=incident_id,
    )
    log.info("[SetupChecklist] Test incident=%s cleaned up workspace=%s", incident_id, workspace["id"])
    return CleanupConnectionTestResponse()
