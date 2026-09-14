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
POST  /internal/workspaces/{id}/mcp-invite     -- provision a Supabase Auth account
                                                   for MCP OAuth 2.1 access (Phase 6,
                                                   connectivity roadmap)
POST  /internal/workspaces/{id}/purge-data     -- real data deletion (migration 027)

PATCH .../tier fills the one real gap in these admin levers: reactivate
sets stripe_subscription_status, but nothing outside a real Stripe webhook
(api/routes/stripe_billing.py's checkout/subscription handlers) ever sets
product_tier. Needed to give an owner/QA workspace Enterprise-tier access
(all 10 agents, unlimited repos/cloud providers) without a real purchase.

.../purge-data closes an operational-readiness gap found 2026-09-14:
Stripe cancellation intentionally preserves all data (see
stripe_billing.py's _handle_subscription_deleted), but nothing anywhere
could actually delete a workspace's credentials/PII on request -- a real
GDPR/CCPA gap. Only allowed once a workspace is canceled or suspended
(never against a live paying customer), and requires the caller to type
the workspace's exact company_name as a confirmation -- this is
destructive and irreversible. Nulls every credential and PII column;
keeps the workspace row and its audit_log/incident history for billing
and audit-trail integrity, matching the "archival, not hard deletion"
model already documented in docs/customer/dpa-outline.md.

PATCH .../tier also fires a best-effort email (core/email.py) to
OWNER_ALERT_EMAIL (defaults to Kelvin's own address) the moment a
workspace's tier actually changes to enterprise -- previously this was
"purely manual discovery," per knowledge/sops/customer-ops/
enterprise-mcp-invite.md, which this closes.
"""

import logging
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.middleware.auth import _hash_token
from api.middleware.internal_auth import get_internal_user
from core.compliance import WorkspaceComplianceGuard
from core.email import EmailError, enterprise_alert_html, send_email

_MCP_VALID_SCOPES = frozenset({"mcp:read", "mcp:write"})

log = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/workspaces", tags=["internal-workspaces"])

_TOKEN_PREFIX = "cd_ws_"


def _generate_raw_token() -> str:
    return f"{_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


# ── Response models ────────────────────────────────────────────────────────────

class WorkspaceSummary(BaseModel):
    id: str
    company_name: str
    contact_email: str | None = None
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


class PurgeDataRequest(BaseModel):
    confirm_company_name: str


class PurgeDataResponse(BaseModel):
    id: str
    data_purged_at: str


class McpInviteRequest(BaseModel):
    email: str
    name: str | None = None
    scopes: list[str] = ["mcp:read", "mcp:write"]


class McpInviteResponse(BaseModel):
    user_id: str
    email: str
    workspace_id: str
    scopes: list[str]
    status: str = "invited"


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _get_workspace_or_404(conn, workspace_id: str) -> dict:
    row = await conn.fetchrow(
        "SELECT id, company_name, contact_email, product_tier, stripe_subscription_status, created_at "
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
            "SELECT id, company_name, contact_email, product_tier, stripe_subscription_status, created_at "
            "FROM workspaces ORDER BY created_at DESC LIMIT 200"
        )
    return [
        WorkspaceSummary(
            id=str(r["id"]),
            company_name=r["company_name"],
            contact_email=r["contact_email"],
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
        contact_email=row["contact_email"],
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
        workspace = await _get_workspace_or_404(conn, workspace_id)
        row = await conn.fetchrow(
            "UPDATE workspaces SET product_tier = $1, updated_at = NOW() "
            "WHERE id = $2 RETURNING id, product_tier",
            body.tier,
            workspace_id,
        )

    log.info("[InternalWorkspaces] Workspace=%s tier set to %s by admin=%s", workspace_id, body.tier, admin["email"])

    if body.tier == "enterprise" and workspace["product_tier"] != "enterprise":
        await _send_enterprise_alert(workspace_id, workspace["company_name"], workspace.get("contact_email"))

    return WorkspaceTierResponse(id=str(row["id"]), product_tier=row["product_tier"])


async def _send_enterprise_alert(workspace_id: str, company_name: str, contact_email: str | None) -> None:
    """Best-effort alert to the platform owner when a workspace becomes
    Enterprise-eligible -- closes the "purely manual discovery" gap
    knowledge/sops/customer-ops/enterprise-mcp-invite.md documented.
    Never allowed to fail the tier change itself."""
    owner_email = os.environ.get("OWNER_ALERT_EMAIL", "kdav2k5@gmail.com")
    try:
        await send_email(
            to=owner_email,
            subject=f"Enterprise tier: {company_name}",
            html=enterprise_alert_html(company_name, workspace_id, contact_email),
        )
    except EmailError as exc:
        log.warning("[InternalWorkspaces] Enterprise alert email failed for workspace=%s: %s", workspace_id, exc)


_PURGEABLE_STATUSES = ("canceled", "suspended")

# Every credential + PII column across the connector shapes this workspace
# table has accumulated (migrations 004/021/022/023/024/025/026) -- nulled
# on purge. workspace_token is deliberately NOT included: a purged workspace
# still needs to 404/401 cleanly rather than match an empty-string token.
_PURGE_COLUMNS = (
    "contact_email",
    "encrypted_llm_key", "llm_provider",
    "github_pat_encrypted", "github_pat_verified_at",
    "encrypted_github_webhook_secret", "github_webhook_secret_created_at",
    "github_app_installation_id", "github_app_installed_at",
    "aws_role_arn", "aws_external_id", "aws_role_verified_at",
    "azure_tenant_id", "azure_client_id", "azure_client_secret_encrypted",
    "azure_subscription_id", "azure_verified_at",
    "azure_devops_org", "azure_devops_pat_encrypted", "azure_devops_pat_verified_at",
    "encrypted_azure_devops_webhook_secret", "azure_devops_webhook_secret_created_at",
    "k8s_api_url", "k8s_token_encrypted", "k8s_ca_cert_encrypted", "k8s_verified_at",
)


@router.post("/{workspace_id}/purge-data", response_model=PurgeDataResponse)
async def purge_workspace_data(
    workspace_id: str,
    body: PurgeDataRequest,
    request: Request,
    admin: dict = Depends(get_internal_user),
) -> PurgeDataResponse:
    async with request.app.state.db_pool.acquire() as conn:
        workspace = await _get_workspace_or_404(conn, workspace_id)

        if workspace["stripe_subscription_status"] not in _PURGEABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"Workspace must be canceled or suspended first (currently "
                       f"'{workspace['stripe_subscription_status']}') -- refusing to purge a live customer's data.",
            )
        if body.confirm_company_name != workspace["company_name"]:
            raise HTTPException(
                status_code=400,
                detail="confirm_company_name did not match this workspace's company_name -- this is "
                       "destructive and irreversible, confirm the exact name before retrying.",
            )

        set_clause = ", ".join(f"{col} = NULL" for col in _PURGE_COLUMNS)
        row = await conn.fetchrow(
            f"UPDATE workspaces SET {set_clause}, data_purged_at = NOW(), updated_at = NOW() "
            f"WHERE id = $1 RETURNING id, data_purged_at",
            workspace_id,
        )

    log.info("[InternalWorkspaces] Workspace=%s data purged by admin=%s", workspace_id, admin["email"])
    return PurgeDataResponse(id=str(row["id"]), data_purged_at=row["data_purged_at"].isoformat())


@router.post("/{workspace_id}/mcp-invite", response_model=McpInviteResponse)
async def invite_mcp_user(
    workspace_id: str,
    body: McpInviteRequest,
    request: Request,
    admin: dict = Depends(get_internal_user),
) -> McpInviteResponse:
    """
    Provisions a real Supabase Auth account for a named person at this
    workspace, so they can authenticate to the MCP server
    (mcp.theclouddecoded.com) via OAuth 2.1 instead of a shared API key --
    the "per-customer Supabase Auth account" piece mcp/auth/oauth.py's JWT
    validation has always been ready for (workspace_id/workspace_tier/
    mcp_scopes in app_metadata) but nothing in this repo ever provisioned.

    Deliberately admin-gated, not self-serve (Kelvin's decision,
    2026-09-14): Enterprise sells on a 30-90 day B2B cycle to VP-Engineering
    buyers -- provisioning happens after a deal closes. Same trust model
    as agents/internal/onboarding_agent.py's internal team invites, but not
    the same code path (that one's for THD's own team dashboard, a
    different product/Supabase project relationship).

    Two-step Supabase Admin API call, not one: invite_user_by_email's
    `options.data` only sets user_metadata (user-editable client-side) --
    the workspace_id/workspace_tier/mcp_scopes that
    validate_oauth_token() actually trusts must live in app_metadata,
    which only update_user_by_id can set. A user who could edit their own
    workspace_id would be a cross-tenant access hole.
    """
    unknown = set(body.scopes) - _MCP_VALID_SCOPES
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scope(s): {sorted(unknown)} -- must be one of {sorted(_MCP_VALID_SCOPES)}",
        )
    if not body.scopes:
        raise HTTPException(status_code=400, detail="scopes must not be empty")

    async with request.app.state.db_pool.acquire() as conn:
        workspace = await _get_workspace_or_404(conn, workspace_id)

    # Lazy import -- matches this repo's convention (internal_auth.py,
    # core/engine.py) of never importing third-party clients at module top
    # level.
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not service_key:
        log.error("[InternalWorkspaces] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured")
        raise HTTPException(status_code=500, detail="Supabase admin API is not configured on this server")

    client = create_client(url, service_key)
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")

    try:
        invite_resp = client.auth.admin.invite_user_by_email(
            body.email,
            {"data": ({"name": body.name} if body.name else {}), "redirect_to": f"{frontend_url}/dashboard"},
        )
    except Exception as exc:
        log.error("[InternalWorkspaces] Supabase invite failed for %s: %s", body.email, exc)
        raise HTTPException(status_code=502, detail=f"Supabase invite failed: {exc}") from exc

    user = getattr(invite_resp, "user", None)
    if not user:
        raise HTTPException(status_code=502, detail="Supabase invite returned no user")

    try:
        client.auth.admin.update_user_by_id(
            user.id,
            {"app_metadata": {
                "workspace_id": workspace_id,
                "workspace_tier": workspace["product_tier"],
                "mcp_scopes": body.scopes,
            }},
        )
    except Exception as exc:
        log.error("[InternalWorkspaces] Failed to link invited user %s to workspace %s: %s", user.id, workspace_id, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Invite email was sent but linking to the workspace failed: {exc}. "
                   f"The user exists in Supabase (id={user.id}) but has no workspace_id set -- fix app_metadata "
                   f"manually or delete and re-invite.",
        ) from exc

    log.info(
        "[InternalWorkspaces] MCP OAuth user invited email=%s workspace=%s scopes=%s by admin=%s",
        body.email, workspace_id, body.scopes, admin["email"],
    )
    return McpInviteResponse(user_id=str(user.id), email=body.email, workspace_id=workspace_id, scopes=body.scopes)
