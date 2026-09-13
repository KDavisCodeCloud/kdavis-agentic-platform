"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Owner/team-only workspace administration -- list customer workspaces,
and the two real access-control levers a paid product needs: suspend a
workspace for a ToS violation (independent of Stripe, which has no
concept of a ToS violation), and rotate a workspace's token (the actual
revocation mechanism for a leaked/compromised token or an immediate
cutoff -- the old token stops matching anything the moment the new hash
is written).

Gated by api.middleware.internal_auth.get_internal_user, exactly like
api/routes/internal_agents.py -- never reachable via X-Workspace-Token,
never merged with api/middleware/auth.py's customer auth path. Never
returns a workspace's token, hashed or raw, in a list/detail response --
only rotate-token ever hands back a raw token, and only once.

GET   /internal/workspaces                    -- list
GET   /internal/workspaces/{id}                -- detail
POST  /internal/workspaces/{id}/suspend        -- ToS-violation path
POST  /internal/workspaces/{id}/reactivate     -- reverse a suspension
POST  /internal/workspaces/{id}/rotate-token   -- revoke + reissue
PATCH /internal/workspaces/{id}/tier           -- set product_tier without Stripe

PATCH .../tier fills the one real gap in these admin levers: reactivate
sets stripe_subscription_status, but nothing outside a real Stripe webhook
(api/routes/stripe_billing.py's checkout/subscription handlers) ever sets
product_tier. Needed to give an owner/QA workspace Enterprise-tier access
(all 10 agents, unlimited repos/cloud providers) without a real purchase.
"""

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.middleware.auth import _hash_token
from api.middleware.internal_auth import get_internal_user
from core.compliance import WorkspaceComplianceGuard

log = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/workspaces", tags=["internal-workspaces"])

_TOKEN_PREFIX = "cd_ws_"


def _generate_raw_token() -> str:
    return f"{_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


# ── Response models ────────────────────────────────────────────────────────────

class WorkspaceSummary(BaseModel):
    id: str
    company_name: str
    product_tier: str
    stripe_subscription_status: str
    created_at: str


class WorkspaceStatusResponse(BaseModel):
    id: str
    stripe_subscription_status: str


class RotateTokenResponse(BaseModel):
    id: str
    workspace_token: str
    warning: str = "Save this token now — it will not be shown again. The previous token no longer works."


class SetTierRequest(BaseModel):
    tier: str


class WorkspaceTierResponse(BaseModel):
    id: str
    product_tier: str


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _get_workspace_or_404(conn, workspace_id: str) -> dict:
    row = await conn.fetchrow(
        "SELECT id, company_name, product_tier, stripe_subscription_status, created_at "
        "FROM workspaces WHERE id = $1",
        workspace_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return dict(row)


async def _set_subscription_status(request: Request, workspace_id: str, new_status: str) -> WorkspaceStatusResponse:
    async with request.app.state.db_pool.acquire() as conn:
        await _get_workspace_or_404(conn, workspace_id)
        row = await conn.fetchrow(
            "UPDATE workspaces SET stripe_subscription_status = $1, updated_at = NOW() "
            "WHERE id = $2 RETURNING id, stripe_subscription_status",
            new_status,
            workspace_id,
        )
    return WorkspaceStatusResponse(id=str(row["id"]), stripe_subscription_status=row["stripe_subscription_status"])


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=list[WorkspaceSummary])
async def list_workspaces(request: Request, admin: dict = Depends(get_internal_user)) -> list[WorkspaceSummary]:
    async with request.app.state.db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, company_name, product_tier, stripe_subscription_status, created_at "
            "FROM workspaces ORDER BY created_at DESC LIMIT 200"
        )
    return [
        WorkspaceSummary(
            id=str(r["id"]),
            company_name=r["company_name"],
            product_tier=r["product_tier"],
            stripe_subscription_status=r["stripe_subscription_status"],
            created_at=r["created_at"].isoformat(),
        )
        for r in rows
    ]


@router.get("/{workspace_id}", response_model=WorkspaceSummary)
async def get_workspace_detail(
    workspace_id: str, request: Request, admin: dict = Depends(get_internal_user)
) -> WorkspaceSummary:
    async with request.app.state.db_pool.acquire() as conn:
        row = await _get_workspace_or_404(conn, workspace_id)
    return WorkspaceSummary(
        id=str(row["id"]),
        company_name=row["company_name"],
        product_tier=row["product_tier"],
        stripe_subscription_status=row["stripe_subscription_status"],
        created_at=row["created_at"].isoformat(),
    )


@router.post("/{workspace_id}/suspend", response_model=WorkspaceStatusResponse)
async def suspend_workspace(
    workspace_id: str, request: Request, admin: dict = Depends(get_internal_user)
) -> WorkspaceStatusResponse:
    result = await _set_subscription_status(request, workspace_id, "suspended")
    log.info("[InternalWorkspaces] Workspace=%s suspended by admin=%s", workspace_id, admin["email"])
    return result


@router.post("/{workspace_id}/reactivate", response_model=WorkspaceStatusResponse)
async def reactivate_workspace(
    workspace_id: str, request: Request, admin: dict = Depends(get_internal_user)
) -> WorkspaceStatusResponse:
    result = await _set_subscription_status(request, workspace_id, "active")
    log.info("[InternalWorkspaces] Workspace=%s reactivated by admin=%s", workspace_id, admin["email"])
    return result


@router.post("/{workspace_id}/rotate-token", response_model=RotateTokenResponse)
async def rotate_workspace_token(
    workspace_id: str, request: Request, admin: dict = Depends(get_internal_user)
) -> RotateTokenResponse:
    raw_token = _generate_raw_token()
    token_hash = _hash_token(raw_token)

    async with request.app.state.db_pool.acquire() as conn:
        await _get_workspace_or_404(conn, workspace_id)
        row = await conn.fetchrow(
            "UPDATE workspaces SET workspace_token = $1, updated_at = NOW() WHERE id = $2 RETURNING id",
            token_hash,
            workspace_id,
        )

    log.info("[InternalWorkspaces] Workspace=%s token rotated by admin=%s", workspace_id, admin["email"])
    return RotateTokenResponse(id=str(row["id"]), workspace_token=raw_token)


@router.patch("/{workspace_id}/tier", response_model=WorkspaceTierResponse)
async def set_workspace_tier(
    workspace_id: str,
    body: SetTierRequest,
    request: Request,
    admin: dict = Depends(get_internal_user),
) -> WorkspaceTierResponse:
    if body.tier not in WorkspaceComplianceGuard.TIER_LIMITS:
        valid = ", ".join(sorted(WorkspaceComplianceGuard.TIER_LIMITS))
        raise HTTPException(status_code=400, detail=f"Invalid tier '{body.tier}' — must be one of: {valid}")

    async with request.app.state.db_pool.acquire() as conn:
        await _get_workspace_or_404(conn, workspace_id)
        row = await conn.fetchrow(
            "UPDATE workspaces SET product_tier = $1, updated_at = NOW() "
            "WHERE id = $2 RETURNING id, product_tier",
            body.tier,
            workspace_id,
        )

    log.info("[InternalWorkspaces] Workspace=%s tier set to %s by admin=%s", workspace_id, body.tier, admin["email"])
    return WorkspaceTierResponse(id=str(row["id"]), product_tier=row["product_tier"])
