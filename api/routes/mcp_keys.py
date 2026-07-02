"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
MCP API key management — customer-facing CRUD.

POST   /mcp/keys           — generate a new scoped API key (raw key returned once)
GET    /mcp/keys           — list active keys for this workspace (prefixes only)
DELETE /mcp/keys/{key_id}  — revoke a specific key
DELETE /mcp/keys           — revoke ALL keys for this workspace (emergency stop)
GET    /mcp/status         — connection telemetry from mcp_audit_log

Security rules:
  - Raw key is returned ONCE on creation and never stored
  - Only SHA-256 hash is persisted in mcp_api_keys
  - Enterprise workspaces cannot create API keys (OAuth 2.1 required)
  - Max expiry: 90 days — no infinite-lifetime keys
  - API keys are workspace-scoped, not user-scoped
"""

import hashlib
import logging
import secrets
from datetime import datetime, timezone, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.middleware.auth import get_workspace

log = logging.getLogger(__name__)
router = APIRouter(prefix="/mcp", tags=["mcp"])

_API_KEY_PREFIX = "cd_mcp_"
_MAX_EXPIRY_DAYS = 90
_OAUTH_ONLY_TIERS = frozenset({"enterprise"})


def _generate_raw_key() -> str:
    return f"{_API_KEY_PREFIX}{secrets.token_urlsafe(22)}"


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── Request / response models ─────────────────────────────────────────────────

class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: list[str] = Field(default=["mcp:read"])
    expiry_days: int = Field(default=30, ge=1, le=90)


class KeySummary(BaseModel):
    id: str
    name: str
    key_prefix: str
    scopes: list[str]
    expires_at: str
    last_used_at: str | None
    created_at: str
    is_expired: bool


class CreateKeyResponse(BaseModel):
    raw_key: str        # ONLY time the full key is shown — store it now
    key: KeySummary
    warning: str = "Save this key now — it will not be shown again."


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/keys", response_model=CreateKeyResponse, status_code=201)
async def create_mcp_key(
    body: CreateKeyRequest,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> CreateKeyResponse:
    workspace_id = str(workspace["id"])
    tier = workspace.get("product_tier", "starter")

    if tier in _OAUTH_ONLY_TIERS:
        raise HTTPException(
            status_code=403,
            detail="Enterprise workspaces must use OAuth 2.1. API key creation is not permitted.",
        )

    # Validate requested scopes
    valid_scopes = {"mcp:read", "mcp:write"}
    clean_scopes = [s for s in body.scopes if s in valid_scopes]
    if not clean_scopes:
        raise HTTPException(status_code=400, detail="At least one valid scope required: mcp:read, mcp:write")

    # mcp:write requires mcp:read too
    if "mcp:write" in clean_scopes and "mcp:read" not in clean_scopes:
        clean_scopes.insert(0, "mcp:read")

    raw_key = _generate_raw_key()
    key_hash = _hash_key(raw_key)
    key_prefix = raw_key[:12]
    expires_at = datetime.now(timezone.utc) + timedelta(days=body.expiry_days)

    async with request.app.state.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO mcp_api_keys (workspace_id, key_hash, key_prefix, name, scopes, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, name, key_prefix, scopes, expires_at, last_used_at, created_at
            """,
            UUID(workspace_id),
            key_hash,
            key_prefix,
            body.name,
            clean_scopes,
            expires_at,
        )

    key_summary = KeySummary(
        id=str(row["id"]),
        name=row["name"],
        key_prefix=row["key_prefix"],
        scopes=list(row["scopes"]),
        expires_at=row["expires_at"].isoformat(),
        last_used_at=None,
        created_at=row["created_at"].isoformat(),
        is_expired=False,
    )

    log.info("[MCPKeys] Key created workspace=%s name=%s scopes=%s", workspace_id, body.name, clean_scopes)

    return CreateKeyResponse(raw_key=raw_key, key=key_summary)


@router.get("/keys")
async def list_mcp_keys(
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> list[KeySummary]:
    workspace_id = str(workspace["id"])
    now = datetime.now(timezone.utc)

    async with request.app.state.db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, key_prefix, scopes, expires_at, last_used_at, created_at
            FROM mcp_api_keys
            WHERE workspace_id = $1 AND revoked_at IS NULL
            ORDER BY created_at DESC
            """,
            UUID(workspace_id),
        )

    return [
        KeySummary(
            id=str(r["id"]),
            name=r["name"],
            key_prefix=r["key_prefix"],
            scopes=list(r["scopes"]),
            expires_at=r["expires_at"].isoformat(),
            last_used_at=r["last_used_at"].isoformat() if r["last_used_at"] else None,
            created_at=r["created_at"].isoformat(),
            is_expired=r["expires_at"] < now,
        )
        for r in rows
    ]


@router.delete("/keys/{key_id}")
async def revoke_mcp_key(
    key_id: str,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> dict:
    workspace_id = str(workspace["id"])

    async with request.app.state.db_pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE mcp_api_keys
            SET revoked_at = NOW()
            WHERE id = $1 AND workspace_id = $2 AND revoked_at IS NULL
            """,
            UUID(key_id),
            UUID(workspace_id),
        )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail=f"Key {key_id} not found or already revoked")

    log.info("[MCPKeys] Key revoked key_id=%s workspace=%s", key_id, workspace_id)
    return {"key_id": key_id, "status": "revoked"}


@router.delete("/keys")
async def revoke_all_mcp_keys(
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> dict:
    """Emergency stop — revokes every active key for this workspace."""
    workspace_id = str(workspace["id"])

    async with request.app.state.db_pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE mcp_api_keys
            SET revoked_at = NOW()
            WHERE workspace_id = $1 AND revoked_at IS NULL
            """,
            UUID(workspace_id),
        )

    count = int(result.split()[-1]) if result else 0
    log.warning("[MCPKeys] All keys revoked workspace=%s count=%d", workspace_id, count)
    return {"status": "all_revoked", "count": count}


@router.get("/status")
async def get_mcp_status(
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> dict:
    """Connection telemetry for this workspace from mcp_audit_log."""
    workspace_id = str(workspace["id"])

    async with request.app.state.db_pool.acquire() as conn:
        # Most recent call
        last_call = await conn.fetchrow(
            """
            SELECT created_at, tool_name
            FROM mcp_audit_log
            WHERE workspace_id = $1 AND status = 'ok'
            ORDER BY created_at DESC LIMIT 1
            """,
            UUID(workspace_id),
        )

        # Per-tool call counts (all time)
        tool_counts = await conn.fetch(
            """
            SELECT tool_name, COUNT(*) as call_count
            FROM mcp_audit_log
            WHERE workspace_id = $1 AND status = 'ok'
            GROUP BY tool_name
            ORDER BY call_count DESC
            """,
            UUID(workspace_id),
        )

        # Distinct callers (subjects) in last 7 days
        recent_callers = await conn.fetchval(
            """
            SELECT COUNT(DISTINCT caller_subject)
            FROM mcp_audit_log
            WHERE workspace_id = $1
              AND created_at > NOW() - INTERVAL '7 days'
            """,
            UUID(workspace_id),
        ) or 0

        total = await conn.fetchval(
            "SELECT COUNT(*) FROM mcp_audit_log WHERE workspace_id = $1",
            UUID(workspace_id),
        ) or 0

    return {
        "last_seen_at":        last_call["created_at"].isoformat() if last_call else None,
        "last_tool":           last_call["tool_name"] if last_call else None,
        "active_connections":  int(recent_callers),
        "tool_call_counts":    {r["tool_name"]: r["call_count"] for r in tool_counts},
        "total_calls":         int(total),
    }
