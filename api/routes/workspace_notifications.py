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
from datetime import time
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from api.middleware.auth import get_workspace
from security.encryption import encrypt
from core.severity import VALID_SEVERITIES

log = logging.getLogger(__name__)
router = APIRouter(prefix="/workspace/notifications", tags=["workspace-notifications"])


# ── Request / response models ─────────────────────────────────────────────────

class QuietHoursFields(BaseModel):
    """
    24-gap-closure Phase 3. Shared by every channel type -- Kelvin's own
    example ("PagerDuty critical-only, Slack all") makes both
    min_severity and quiet hours per-channel settings, not one
    workspace-wide toggle. All optional; omitting all three (the default)
    is exactly this channel's pre-Phase-3 behavior, unchanged.
    """
    min_severity: Optional[str] = None
    quiet_hours_start: Optional[time] = None
    quiet_hours_end: Optional[time] = None
    quiet_hours_timezone: Optional[str] = None

    @field_validator("min_severity")
    @classmethod
    def _validate_severity(cls, v):
        if v is not None and v not in VALID_SEVERITIES:
            raise ValueError(f"min_severity must be one of {sorted(VALID_SEVERITIES)}")
        return v

    @field_validator("quiet_hours_timezone")
    @classmethod
    def _validate_timezone(cls, v):
        if v is not None:
            try:
                ZoneInfo(v)
            except Exception:
                raise ValueError(f"{v!r} is not a valid IANA timezone name")
        return v


class ConnectSlackRequest(QuietHoursFields):
    webhook_url: str = Field(..., min_length=1)
    enabled: bool = True


class ConnectPagerDutyRequest(QuietHoursFields):
    routing_key: str = Field(..., min_length=1)
    enabled: bool = True


class ConnectEmailRequest(QuietHoursFields):
    to: str = Field(..., min_length=1)
    enabled: bool = True


class ChannelStatusResponse(BaseModel):
    channel_type: str
    enabled: bool
    min_severity: Optional[str] = None
    quiet_hours_start: Optional[time] = None
    quiet_hours_end: Optional[time] = None
    quiet_hours_timezone: Optional[str] = None


class NotificationChannelsResponse(BaseModel):
    channels: list[ChannelStatusResponse]


class ExhaustedRetryResponse(BaseModel):
    id: str
    channel_type: str
    send_kind: str
    attempt_count: int
    last_error: Optional[str]
    created_at: str
    updated_at: str


class ExhaustedRetriesResponse(BaseModel):
    retries: list[ExhaustedRetryResponse]


# ── Endpoints ─────────────────────────────────────────────────────────────────

async def _upsert_channel(
    request: Request, workspace_id, channel_type: str, config: dict, enabled: bool, quiet: QuietHoursFields,
) -> None:
    config_encrypted = encrypt(json.dumps(config))
    async with request.app.state.db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO workspace_notification_channels
                (workspace_id, channel_type, config_encrypted, enabled,
                 min_severity, quiet_hours_start, quiet_hours_end, quiet_hours_timezone)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (workspace_id, channel_type)
            DO UPDATE SET config_encrypted = $3, enabled = $4, min_severity = $5,
                          quiet_hours_start = $6, quiet_hours_end = $7, quiet_hours_timezone = $8,
                          updated_at = NOW()
            """,
            workspace_id, channel_type, config_encrypted, enabled,
            quiet.min_severity, quiet.quiet_hours_start, quiet.quiet_hours_end, quiet.quiet_hours_timezone,
        )


@router.patch("/slack", response_model=ChannelStatusResponse)
async def connect_slack(
    body: ConnectSlackRequest,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> ChannelStatusResponse:
    workspace_id = workspace["id"]
    await _upsert_channel(request, workspace_id, "slack", {"webhook_url": body.webhook_url}, body.enabled, body)
    log.info("[WorkspaceNotifications] Slack channel configured workspace=%s", workspace_id)
    return ChannelStatusResponse(
        channel_type="slack", enabled=body.enabled, min_severity=body.min_severity,
        quiet_hours_start=body.quiet_hours_start, quiet_hours_end=body.quiet_hours_end,
        quiet_hours_timezone=body.quiet_hours_timezone,
    )


@router.patch("/pagerduty", response_model=ChannelStatusResponse)
async def connect_pagerduty(
    body: ConnectPagerDutyRequest,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> ChannelStatusResponse:
    workspace_id = workspace["id"]
    await _upsert_channel(request, workspace_id, "pagerduty", {"routing_key": body.routing_key}, body.enabled, body)
    log.info("[WorkspaceNotifications] PagerDuty channel configured workspace=%s", workspace_id)
    return ChannelStatusResponse(
        channel_type="pagerduty", enabled=body.enabled, min_severity=body.min_severity,
        quiet_hours_start=body.quiet_hours_start, quiet_hours_end=body.quiet_hours_end,
        quiet_hours_timezone=body.quiet_hours_timezone,
    )


@router.patch("/email", response_model=ChannelStatusResponse)
async def connect_email(
    body: ConnectEmailRequest,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> ChannelStatusResponse:
    """24-gap-closure Phase 3 -- email as a third channel type."""
    workspace_id = workspace["id"]
    await _upsert_channel(request, workspace_id, "email", {"to": body.to}, body.enabled, body)
    log.info("[WorkspaceNotifications] Email channel configured workspace=%s", workspace_id)
    return ChannelStatusResponse(
        channel_type="email", enabled=body.enabled, min_severity=body.min_severity,
        quiet_hours_start=body.quiet_hours_start, quiet_hours_end=body.quiet_hours_end,
        quiet_hours_timezone=body.quiet_hours_timezone,
    )


@router.get("", response_model=NotificationChannelsResponse)
async def list_notification_channels(
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> NotificationChannelsResponse:
    """
    Read-only channel status for the Connections settings page. Never
    reads config_encrypted back out to a caller -- only channel_type and
    enabled (plus the non-secret severity/quiet-hours settings, added
    Phase 3), so a configured secret can never leak back through this
    endpoint even by accident.
    """
    async with request.app.state.db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT channel_type, enabled, min_severity, quiet_hours_start, quiet_hours_end, "
            "quiet_hours_timezone FROM workspace_notification_channels WHERE workspace_id = $1",
            workspace["id"],
        )
    return NotificationChannelsResponse(
        channels=[
            ChannelStatusResponse(
                channel_type=r["channel_type"], enabled=r["enabled"], min_severity=r["min_severity"],
                quiet_hours_start=r["quiet_hours_start"], quiet_hours_end=r["quiet_hours_end"],
                quiet_hours_timezone=r["quiet_hours_timezone"],
            )
            for r in rows
        ]
    )


@router.get("/retry-queue/exhausted", response_model=ExhaustedRetriesResponse)
async def list_exhausted_retries(
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> ExhaustedRetriesResponse:
    """
    24-gap-closure Phase 3 -- "flagged in dashboard" for a notification
    send that exhausted all 5 retry attempts. This is the one real
    dashboard-visible surface Kelvin's spec named explicitly for the
    retry queue; a full retry-queue management UI (retry now, dismiss,
    etc.) was not asked for and isn't built here.
    """
    async with request.app.state.db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, channel_type, send_kind, attempt_count, last_error, created_at, updated_at
            FROM notification_retry_queue
            WHERE workspace_id = $1 AND status = 'exhausted'
            ORDER BY updated_at DESC
            """,
            workspace["id"],
        )
    return ExhaustedRetriesResponse(
        retries=[
            ExhaustedRetryResponse(
                id=str(r["id"]), channel_type=r["channel_type"], send_kind=r["send_kind"],
                attempt_count=r["attempt_count"], last_error=r["last_error"],
                created_at=r["created_at"].isoformat(), updated_at=r["updated_at"].isoformat(),
            )
            for r in rows
        ]
    )
