"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Workspace token authentication middleware.

Every request must include `X-Workspace-Token: <token>` header.
The token is SHA-256 hashed before DB lookup so plain-text tokens
are never stored.
"""

import asyncio
import hashlib
import logging
import os
from typing import Optional
from uuid import UUID

from fastapi import Request, HTTPException, status
from fastapi.security import APIKeyHeader

log = logging.getLogger(__name__)

WORKSPACE_TOKEN_HEADER = APIKeyHeader(name="X-Workspace-Token", auto_error=False)

_MCP_SERVICE_KEY = os.environ.get("MCP_SERVICE_KEY", "")

# Shared by _get_workspace_by_mcp_service, _get_workspace_by_token, and
# get_workspace_member's _get_workspace_row_by_id below -- previously
# duplicated verbatim in the first two, which is exactly the kind of
# drift risk GAPS.md #16 (TIER_LIMITS) already burned this codebase on
# once. One source of truth for "what a workspace row auth returns."
_WORKSPACE_SELECT_COLUMNS = (
    "id, company_name, stripe_subscription_status, product_tier, "
    "encrypted_llm_key, llm_provider, monthly_token_budget_usd, current_month_spend_usd, "
    "github_pat_encrypted, github_pat_verified_at, github_app_installation_id, "
    "encrypted_github_webhook_secret, aws_role_arn, aws_external_id, "
    "aws_role_verified_at, azure_tenant_id, azure_client_id, "
    "azure_client_secret_encrypted, azure_subscription_id, azure_verified_at, "
    "azure_devops_pat_verified_at, k8s_verified_at, "
    "workspace_token_last4, workspace_token_rotated_at, "
    "workspace_token_last_used_at, workspace_token_expires_at, require_mfa, "
    "previous_workspace_token_expires_at"
)

# 24-gap-closure Phase 4 -- fire-and-forget: a token-authenticated request
# must never be slowed down (or failed) by recording its own usage.
# Detached short-lived connection, same pattern as core/notifications.py's
# _asyncpg_url() convention -- never reuses the request-scoped pool
# connection from inside a background task.
async def _touch_workspace_token_last_used(workspace_id) -> None:
    import asyncpg

    url = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    if not url:
        return
    try:
        conn = await asyncpg.connect(url, statement_cache_size=0)
    except Exception:
        log.warning("[Auth] Could not record workspace_token_last_used_at for %s", workspace_id)
        return
    try:
        await conn.execute(
            "UPDATE workspaces SET workspace_token_last_used_at = NOW() WHERE id = $1",
            workspace_id,
        )
    except Exception:
        log.warning("[Auth] Failed to update workspace_token_last_used_at for %s", workspace_id)
    finally:
        await conn.close()

# 'pending_payment' -- the default status for every newly-created workspace
# (db/migrations/021_workspace_pending_payment.sql) -- is the actual paywall
# gate: a workspace that has never completed Stripe checkout stays blocked
# here exactly like a canceled/suspended one, until the checkout.session.
# completed webhook (api/routes/stripe_billing.py) flips it to 'active'.
_BLOCKED_SUBSCRIPTION_STATUSES = ("canceled", "suspended", "pending_payment")


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
            f"SELECT {_WORKSPACE_SELECT_COLUMNS} FROM workspaces WHERE id = $1",
            ws_uuid,
        )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace {workspace_id} not found",
        )

    status_val = row["stripe_subscription_status"]
    if status_val in _BLOCKED_SUBSCRIPTION_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Workspace subscription {status_val} — access denied",
        )

    return dict(row)


async def _get_workspace_by_token(request: Request, blocked_statuses: tuple[str, ...]) -> dict:
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
            f"SELECT {_WORKSPACE_SELECT_COLUMNS} FROM workspaces WHERE workspace_token = $1",
            token_hash,
        )
        if not row:
            # 24-gap-closure Phase 5 -- webhook token rotation grace
            # window. The just-rotated-away-from token still
            # authenticates for 72h (previous_workspace_token_expires_at,
            # set by rotate_workspace_token_self_serve) so an alert
            # source that hasn't been updated with the new token yet
            # doesn't silently break the moment someone rotates.
            row = await conn.fetchrow(
                f"SELECT {_WORKSPACE_SELECT_COLUMNS} FROM workspaces "
                f"WHERE previous_workspace_token_hash = $1 AND previous_workspace_token_expires_at > NOW()",
                token_hash,
            )

    if not row:
        log.warning("[Auth] Invalid workspace token presented")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid workspace token",
        )

    status_val = row["stripe_subscription_status"]
    if status_val in blocked_statuses:
        log.warning(
            "[Auth] Workspace %s blocked — subscription status: %s",
            row["id"], status_val
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Workspace subscription {status_val} — access denied",
        )

    # 24-gap-closure Phase 4 -- optional expiry (NULL == never expires,
    # every existing token's unchanged default). Checked before the
    # fire-and-forget last_used_at touch below so an expired token is
    # never recorded as "used". .get() (not row["..."]) so a test fixture
    # or any other caller shaped without this new column degrades to
    # "never expires" instead of a KeyError -- same defensive convention
    # every downstream workspace-dict consumer in this codebase already
    # uses.
    expires_at = row.get("workspace_token_expires_at")
    if expires_at is not None:
        from datetime import datetime, timezone
        if expires_at <= datetime.now(timezone.utc):
            log.warning("[Auth] Workspace %s presented an expired token", row["id"])
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Workspace token has expired — rotate it in Connections settings",
            )

    asyncio.create_task(_touch_workspace_token_last_used(row["id"]))

    return dict(row)


async def get_workspace(request: Request) -> dict:
    """
    FastAPI dependency: validates the workspace token and returns the workspace row.
    Raises 401 if missing, 403 if invalid, 402 if subscription blocked
    (canceled, suspended, or pending_payment -- see get_workspace_allow_pending_payment
    for the one deliberate exception to the pending_payment block).

    Usage:
        @router.get("/...")
        async def endpoint(workspace: dict = Depends(get_workspace)):
            ...
    """
    # MCP internal service auth — check before workspace token path
    mcp_key = request.headers.get("X-MCP-Service-Key")
    if mcp_key:
        return await _get_workspace_by_mcp_service(request, mcp_key)

    return await _get_workspace_by_token(request, _BLOCKED_SUBSCRIPTION_STATUSES)


async def get_workspace_allow_pending_payment(request: Request) -> dict:
    """
    Same as get_workspace, but does NOT block 'pending_payment' -- for the
    one endpoint an unpaid workspace must be able to reach in order to stop
    being unpaid: POST /billing/checkout. Without this, get_workspace's own
    pending_payment block created a deadlock where a brand-new signup could
    never call checkout at all (found live 2026-09-11 exercising the real
    signup -> checkout flow end to end, not caught by unit tests alone).

    Still blocks canceled/suspended: re-subscribing after cancellation or
    lifting a ToS suspension goes through their own explicit flows, not a
    bare retry of checkout.
    """
    mcp_key = request.headers.get("X-MCP-Service-Key")
    if mcp_key:
        return await _get_workspace_by_mcp_service(request, mcp_key)

    return await _get_workspace_by_token(request, ("canceled", "suspended"))


async def get_workspace_any_status(request: Request) -> dict:
    """
    Same token validation (401 missing, 403 invalid) as get_workspace, but
    never 402s on subscription status -- for the one thing a locked-out
    workspace must still be able to check: its own billing status.

    Without this, GET /billing/status itself 402s for exactly the
    workspaces that most need to call it (pending_payment, canceled,
    suspended), forcing the frontend to guess why it's locked instead of
    just asking. Never use this for anything other than reading status --
    every other protected route must keep using get_workspace.
    """
    mcp_key = request.headers.get("X-MCP-Service-Key")
    if mcp_key:
        return await _get_workspace_by_mcp_service(request, mcp_key)

    return await _get_workspace_by_token(request, ())


async def _get_workspace_row_by_id(conn, workspace_id) -> Optional[dict]:
    row = await conn.fetchrow(
        f"SELECT {_WORKSPACE_SELECT_COLUMNS} FROM workspaces WHERE id = $1",
        workspace_id,
    )
    return dict(row) if row else None


async def get_workspace_member(request: Request) -> dict:
    """
    FastAPI dependency: validates a Supabase session JWT
    (Authorization: Bearer <token>) and resolves it to a workspace via
    the workspace_members table (migration 033) -- the human-dashboard-
    session auth path. Membership plan, Phase A: additive to
    get_workspace()'s X-Workspace-Token path, not a replacement --
    webhooks, CI integrations, and MCP service-to-service calls never
    send an Authorization: Bearer header and are completely unaffected.

    Validates the token via an online Supabase API call
    (client.auth.get_user()), same as api/middleware/internal_auth.py's
    get_internal_user -- deliberately NOT mcp/auth/oauth.py's offline
    JWT-decode approach, since mcp/ is a separate deployable service
    (own Dockerfile/requirements.txt/config.py) this codebase does not
    import from, and online validation catches a revoked session
    immediately rather than only at next token expiry.

    Raises 401 if the session token is missing/invalid, 403 if the
    Supabase user has no active workspace_members row, 402 if the
    resolved workspace's subscription is blocked (same statuses as
    get_workspace). Returns the SAME shape as get_workspace() (the full
    workspace row) plus member_id/member_role/member_email, so any route
    depending on get_workspace_or_member sees a consistent dict
    regardless of which credential the caller used.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <session token> required",
        )
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <session token> required",
        )

    # Lazy import -- matches this repo's convention (internal_auth.py,
    # internal_workspaces.py, core/engine.py) of never importing
    # third-party clients at module top level.
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not service_key:
        log.error("[Auth] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Member auth is not configured on this server",
        )

    client = create_client(url, service_key)
    try:
        user_resp = client.auth.get_user(token)
    except Exception:
        log.warning("[Auth] Member session token verification failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )

    user = getattr(user_resp, "user", None)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        member_row = await conn.fetchrow(
            "SELECT id, workspace_id, role, email FROM workspace_members "
            "WHERE supabase_user_id = $1 AND status = 'active'",
            UUID(str(user.id)),
        )
        if not member_row:
            log.warning("[Auth] Supabase user=%s has no active workspace_members row", user.id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No active workspace membership for this account",
            )

        workspace_row = await _get_workspace_row_by_id(conn, member_row["workspace_id"])

    if not workspace_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    status_val = workspace_row["stripe_subscription_status"]
    if status_val in _BLOCKED_SUBSCRIPTION_STATUSES:
        log.warning(
            "[Auth] Workspace %s blocked (member session) — subscription status: %s",
            workspace_row["id"], status_val,
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Workspace subscription {status_val} — access denied",
        )

    if workspace_row.get("require_mfa"):
        # 24-gap-closure Phase 4 -- Enterprise workspace-wide "require MFA"
        # setting. The Supabase session token itself was already confirmed
        # valid above via the online get_user() call, so decoding its
        # claims here without re-verifying the signature is safe -- this
        # is reading a claim off a token we just proved is live, not
        # trusting an unverified token on its own. aal2 == the caller
        # completed a second factor for this session; aal1 == password
        # only. Supabase issues aal2 automatically once any TOTP factor is
        # verified for the session.
        try:
            from jose import jwt as _jose_jwt
            claims = _jose_jwt.get_unverified_claims(token)
            aal = claims.get("aal")
        except Exception:
            aal = None
        if aal != "aal2":
            log.warning(
                "[Auth] Workspace %s requires MFA — member session aal=%s rejected",
                workspace_row["id"], aal,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="mfa_required",
            )

    workspace_row["member_id"] = str(member_row["id"])
    workspace_row["member_role"] = member_row["role"]
    workspace_row["member_email"] = member_row["email"]
    return workspace_row


async def get_workspace_or_member(request: Request) -> dict:
    """
    Accepts EITHER credential: X-Workspace-Token/X-MCP-Service-Key
    (existing, unchanged, routed through get_workspace) or
    Authorization: Bearer <supabase session> resolved via
    workspace_members (get_workspace_member, Phase A membership plan).

    Prefers the token path only when a token/service-key header is
    actually present, so a request carrying only a Bearer header
    doesn't get a misleading "token required" 401 from the wrong path.
    Use this (not get_workspace directly) on any route that should
    support a logged-in human member session, not just the shared
    workspace token.
    """
    if request.headers.get("X-Workspace-Token") or request.headers.get("X-MCP-Service-Key"):
        return await get_workspace(request)
    return await get_workspace_member(request)


async def get_workspace_by_scim_token(request: Request) -> dict:
    """
    FastAPI dependency for api/routes/scim.py's IdP-facing SCIM 2.0
    endpoints only -- validates Authorization: Bearer <scim token>
    against workspace_sso_config.scim_bearer_token_hash (set by
    POST /internal/workspaces/{id}/sso-config/scim-token). Membership/
    SSO/RBAC/SCIM plan, Phase E.

    Deliberately its own dependency, not folded into get_workspace_or_member:
    a SCIM token is scoped to exactly one workspace's IdP connector, never
    a human session or the shared workspace token, and must never be
    accepted on any other route.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <SCIM token> required",
        )
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <SCIM token> required",
        )

    token_hash = _hash_token(token)
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT workspace_id, status AS sso_status FROM workspace_sso_config "
            "WHERE scim_bearer_token_hash = $1",
            token_hash,
        )

    if not row:
        log.warning("[Auth] Invalid SCIM token presented")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid SCIM token")

    return {"workspace_id": str(row["workspace_id"])}
