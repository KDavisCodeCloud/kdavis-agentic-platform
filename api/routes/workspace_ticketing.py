"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Customer-facing ticketing-integration config -- fires on incident
RESOLUTION (core/ticketing.py's notify_resolution, wired into
core/hitl.py's mark_executed and api/routes/incidents.py's
resolve_incident_manually), never on creation. Modeled directly on
api/routes/workspace_notifications.py's self-serve Slack/PagerDuty
pattern (get_workspace auth, upsert into workspace_notification_channels
with a new channel_type value, config_encrypted holds the provider's
whole config as one Fernet-encrypted JSON blob, never echo a decrypted
secret back to the caller).

Distinct constraint from workspace_notifications.py: a workspace may have
at most ONE ticketing channel configured at a time (Jira/Linear/GitHub
Issues/ServiceNow are mutually exclusive) -- Slack and PagerDuty
notification channels can coexist, but this is a different category
(core.ticketing.TICKETING_CHANNEL_TYPES) and enforced here, not there.

PATCH  /workspace/ticketing/jira            -- set/update Jira config
PATCH  /workspace/ticketing/linear          -- set/update Linear config
GET    /workspace/ticketing                 -- current ticketing channel status
                                                (never returns decrypted secrets)
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from api.middleware.auth import get_workspace
from core.ticketing import TICKETING_CHANNEL_TYPES
from security.encryption import encrypt

log = logging.getLogger(__name__)
router = APIRouter(prefix="/workspace/ticketing", tags=["workspace-ticketing"])


# ── Request / response models ─────────────────────────────────────────────────

class ConnectJiraRequest(BaseModel):
    instance_url: str = Field(..., min_length=1)
    api_token: str = Field(..., min_length=1)
    project_key: str = Field(..., min_length=1)
    issue_type: str = "Task"
    enabled: bool = True


class ConnectLinearRequest(BaseModel):
    api_key: str = Field(..., min_length=1)
    team_id: str = Field(..., min_length=1)
    enabled: bool = True


class TicketingChannelStatusResponse(BaseModel):
    channel_type: str
    enabled: bool


class TicketingStatusResponse(BaseModel):
    channel: TicketingChannelStatusResponse | None = None


# ── Shared helpers ───────────────────────────────────────────────────────────

async def _assert_no_conflicting_ticketing_channel(request: Request, workspace_id, new_channel_type: str) -> None:
    """
    A workspace may have zero or one ticketing channel configured -- reject
    with 409 if a *different* ticketing-category channel already exists.
    Re-configuring the SAME channel_type (e.g. updating the Jira project
    key) is always allowed -- that's an update, not a second channel.
    """
    async with request.app.state.db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT channel_type FROM workspace_notification_channels "
            "WHERE workspace_id = $1 AND channel_type = ANY($2::text[]) AND channel_type != $3",
            workspace_id,
            list(TICKETING_CHANNEL_TYPES),
            new_channel_type,
        )
    if rows:
        existing = rows[0]["channel_type"]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This workspace already has a '{existing}' ticketing channel configured. "
                "A workspace may have only one ticketing integration at a time -- "
                "remove the existing one before connecting a different provider."
            ),
        )


async def _upsert_ticketing_channel(request: Request, workspace_id, channel_type: str, config: dict, enabled: bool) -> None:
    config_encrypted = encrypt(json.dumps(config))
    async with request.app.state.db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO workspace_notification_channels (workspace_id, channel_type, config_encrypted, enabled)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (workspace_id, channel_type)
            DO UPDATE SET config_encrypted = $3, enabled = $4, updated_at = NOW()
            """,
            workspace_id,
            channel_type,
            config_encrypted,
            enabled,
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.patch("/jira", response_model=TicketingChannelStatusResponse)
async def connect_jira(
    body: ConnectJiraRequest,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> TicketingChannelStatusResponse:
    workspace_id = workspace["id"]
    await _assert_no_conflicting_ticketing_channel(request, workspace_id, "jira")
    await _upsert_ticketing_channel(
        request,
        workspace_id,
        "jira",
        {
            "instance_url": body.instance_url,
            "api_token": body.api_token,
            "project_key": body.project_key,
            "issue_type": body.issue_type,
        },
        body.enabled,
    )
    log.info("[WorkspaceTicketing] Jira channel configured workspace=%s", workspace_id)
    return TicketingChannelStatusResponse(channel_type="jira", enabled=body.enabled)


@router.patch("/linear", response_model=TicketingChannelStatusResponse)
async def connect_linear(
    body: ConnectLinearRequest,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> TicketingChannelStatusResponse:
    workspace_id = workspace["id"]
    await _assert_no_conflicting_ticketing_channel(request, workspace_id, "linear")
    await _upsert_ticketing_channel(
        request,
        workspace_id,
        "linear",
        {"api_key": body.api_key, "team_id": body.team_id},
        body.enabled,
    )
    log.info("[WorkspaceTicketing] Linear channel configured workspace=%s", workspace_id)
    return TicketingChannelStatusResponse(channel_type="linear", enabled=body.enabled)


@router.get("", response_model=TicketingStatusResponse)
async def get_ticketing_status(
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> TicketingStatusResponse:
    """
    Read-only channel status for the Connections settings page. Never
    reads config_encrypted back out to a caller. At most one row since
    the config endpoints enforce the one-ticketing-channel-per-workspace
    constraint above.
    """
    async with request.app.state.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT channel_type, enabled FROM workspace_notification_channels "
            "WHERE workspace_id = $1 AND channel_type = ANY($2::text[])",
            workspace["id"],
            list(TICKETING_CHANNEL_TYPES),
        )
    if row is None:
        return TicketingStatusResponse(channel=None)
    return TicketingStatusResponse(
        channel=TicketingChannelStatusResponse(channel_type=row["channel_type"], enabled=row["enabled"])
    )
