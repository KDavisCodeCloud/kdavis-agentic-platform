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
Workspace token authentication middleware.

Every request must include `X-Workspace-Token: <token>` header.
The token is SHA-256 hashed before DB lookup so plain-text tokens
are never stored.
"""

import hashlib
import logging
import os
from uuid import UUID

from fastapi import Request, HTTPException, status
from fastapi.security import APIKeyHeader

log = logging.getLogger(__name__)

WORKSPACE_TOKEN_HEADER = APIKeyHeader(name="X-Workspace-Token", auto_error=False)

_MCP_SERVICE_KEY = os.environ.get("MCP_SERVICE_KEY", "")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _get_workspace_by_mcp_service(request: Request, service_key: str) -> dict:
    """
    Internal trust path for MCP server calls.

    The MCP server authenticates with X-MCP-Service-Key (shared secret)
    and supplies X-Workspace-Id (UUID) identifying the workspace to act on
    behalf of. The customer's OAuth token / API key is NEVER forwarded.

    This path is only reachable from within the private network.
    """
    if not _MCP_SERVICE_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="MCP_SERVICE_KEY not configured on this server",
        )
    if service_key != _MCP_SERVICE_KEY:
        log.warning("[Auth] Invalid MCP service key presented")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid MCP service key",
        )

    workspace_id = request.headers.get("X-Workspace-Id", "").strip()
    if not workspace_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Workspace-Id header required with X-MCP-Service-Key",
        )

    try:
        ws_uuid = UUID(workspace_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"X-Workspace-Id '{workspace_id}' is not a valid UUID",
        )

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, company_name, stripe_subscription_status, product_tier, "
            "encrypted_llm_key, monthly_token_budget_usd, current_month_spend_usd "
            "FROM workspaces WHERE id = $1",
            ws_uuid,
        )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace {workspace_id} not found",
        )

    status_val = row["stripe_subscription_status"]
    if status_val in ("canceled", "suspended"):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Workspace subscription {status_val} — access denied",
        )

    return dict(row)


async def get_workspace(request: Request) -> dict:
    """
    FastAPI dependency: validates the workspace token and returns the workspace row.
    Raises 401 if missing, 403 if invalid or subscription blocked.

    Usage:
        @router.get("/...")
        async def endpoint(workspace: dict = Depends(get_workspace)):
            ...
    """
    # MCP internal service auth — check before workspace token path
    mcp_key = request.headers.get("X-MCP-Service-Key")
    if mcp_key:
        return await _get_workspace_by_mcp_service(request, mcp_key)

    token = request.headers.get("X-Workspace-Token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Workspace-Token header required",
        )

    token_hash = _hash_token(token)
    db = request.app.state.db_pool

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, company_name, stripe_subscription_status, product_tier, "
            "encrypted_llm_key, monthly_token_budget_usd, current_month_spend_usd "
            "FROM workspaces WHERE workspace_token = $1",
            token_hash,
        )

    if not row:
        log.warning("[Auth] Invalid workspace token presented")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid workspace token",
        )

    status_val = row["stripe_subscription_status"]
    if status_val in ("canceled", "suspended"):
        log.warning(
            "[Auth] Workspace %s blocked — subscription status: %s",
            row["id"], status_val
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Workspace subscription {status_val} — access denied",
        )

    return dict(row)
