"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Customer-facing Slack/PagerDuty notification-channel config -- Tier 1
webhook build (2026-09-14). Lets a workspace configure where incident
notifications fire (core/hitl.py's create_incident/create_failed_incident
best-effort dispatch, via core/notifications.py), modeled directly on
api/routes/workspace_credentials.py's self-serve credential pattern
(get_workspace auth, verify-then-store) rather than
internal_workspaces.py's admin-only pattern -- a real paying customer
configures their own Slack/PagerDuty, not just Kelvin.

PATCH  /workspace/notifications/slack       -- set/update the Slack webhook URL
PATCH  /workspace/notifications/pagerduty   -- set/update the PagerDuty routing key
GET    /workspace/notifications             -- list configured channels
                                                (never returns the decrypted secret)
"""

import json
import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from api.middleware.auth import get_workspace
from security.encryption import encrypt

log = logging.getLogger(__name__)
router = APIRouter(prefix="/workspace/notifications", tags=["workspace-notifications"])


# ── Request / response models ─────────────────────────────────────────────────

class ConnectSlackRequest(BaseModel):
    webhook_url: str = Field(..., min_length=1)
    enabled: bool = True


class ConnectPagerDutyRequest(BaseModel):
    routing_key: str = Field(..., min_length=1)
    enabled: bool = True


class ChannelStatusResponse(BaseModel):
    channel_type: str
    enabled: bool


class NotificationChannelsResponse(BaseModel):
    channels: list[ChannelStatusResponse]


# ── Endpoints ─────────────────────────────────────────────────────────────────

async def _upsert_channel(
    request: Request, workspace_id, channel_type: str, config: dict, enabled: bool,
) -> None:
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


@router.patch("/slack", response_model=ChannelStatusResponse)
async def connect_slack(
    body: ConnectSlackRequest,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> ChannelStatusResponse:
    workspace_id = workspace["id"]
    await _upsert_channel(request, workspace_id, "slack", {"webhook_url": body.webhook_url}, body.enabled)
    log.info("[WorkspaceNotifications] Slack channel configured workspace=%s", workspace_id)
    return ChannelStatusResponse(channel_type="slack", enabled=body.enabled)


@router.patch("/pagerduty", response_model=ChannelStatusResponse)
async def connect_pagerduty(
    body: ConnectPagerDutyRequest,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> ChannelStatusResponse:
    workspace_id = workspace["id"]
    await _upsert_channel(request, workspace_id, "pagerduty", {"routing_key": body.routing_key}, body.enabled)
    log.info("[WorkspaceNotifications] PagerDuty channel configured workspace=%s", workspace_id)
    return ChannelStatusResponse(channel_type="pagerduty", enabled=body.enabled)


@router.get("", response_model=NotificationChannelsResponse)
async def list_notification_channels(
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> NotificationChannelsResponse:
    """
    Read-only channel status for the Connections settings page. Never
    reads config_encrypted back out to a caller -- only channel_type and
    enabled, so a configured secret can never leak back through this
    endpoint even by accident.
    """
    async with request.app.state.db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT channel_type, enabled FROM workspace_notification_channels WHERE workspace_id = $1",
            workspace["id"],
        )
    return NotificationChannelsResponse(
        channels=[ChannelStatusResponse(channel_type=r["channel_type"], enabled=r["enabled"]) for r in rows]
    )
