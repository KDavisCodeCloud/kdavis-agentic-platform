"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 KDavis Agentic Systems LLC. All rights reserved.

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

from fastapi import Request, HTTPException, status
from fastapi.security import APIKeyHeader

log = logging.getLogger(__name__)

WORKSPACE_TOKEN_HEADER = APIKeyHeader(name="X-Workspace-Token", auto_error=False)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def get_workspace(request: Request) -> dict:
    """
    FastAPI dependency: validates the workspace token and returns the workspace row.
    Raises 401 if missing, 403 if invalid or subscription blocked.

    Usage:
        @router.get("/...")
        async def endpoint(workspace: dict = Depends(get_workspace)):
            ...
    """
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
