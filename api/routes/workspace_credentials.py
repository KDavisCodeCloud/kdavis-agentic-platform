"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Lets a workspace connect its own GitHub, AWS, and Azure credentials for
Agents 01/05/06/08's real remediation actions (migration 022). Verify-then-
store pattern, modeled directly on kdavis-finops-agent/api/routes/tenants.py's
PATCH /tenants/{id}/aws-role and /azure-credentials -- the proven, already-
working template in this product line.

PATCH /workspace/credentials/github          -- verify + store a GitHub PAT
POST  /workspace/credentials/aws-role/setup  -- generate a trust policy to paste into AWS
PATCH /workspace/credentials/aws-role        -- verify + store the resulting role ARN
PATCH /workspace/credentials/azure           -- verify + store an Azure Service Principal

All gated by the same customer-facing X-Workspace-Token auth as every other
workspace route -- a real paying customer uses the same routes Kelvin does.
"""

import logging
import os
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from api.middleware.auth import _hash_token, get_workspace, get_workspace_or_member
from core.audit import write_audit_event
from core.github_app import build_install_url, sign_workspace_state, verify_workspace_state
from core.workspace_credentials import (
    AssumeRoleError,
    AzureConnectError,
    AzureDevOpsConnectError,
    K8sConnectError,
    build_permissions_policy,
    build_trust_policy,
    generate_external_id,
    verify_azure_devops_pat,
    verify_k8s_connection,
    verify_role,
    verify_service_principal,
)
from security.encryption import encrypt

log = logging.getLogger(__name__)
router = APIRouter(prefix="/workspace/credentials", tags=["workspace-credentials"])

# Same env var + /dashboard?connected=<provider> redirect convention already
# used by api/routes/content.py's LinkedIn/X OAuth callbacks.
_FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")


# ── Request / response models ─────────────────────────────────────────────────

class ConnectGithubRequest(BaseModel):
    github_pat: str = Field(..., min_length=1)


class ConnectGithubResponse(BaseModel):
    status: str = "verified"
    webhook_secret: str | None = Field(
        default=None,
        description="Only present the first time a webhook secret is minted for this "
        "workspace -- save it now, register it as the webhook's secret, it will not be shown again.",
    )


class AwsRoleSetupResponse(BaseModel):
    external_id: str
    trust_policy: dict
    permissions_policy: dict
    instructions: str


class ConnectAwsRoleRequest(BaseModel):
    role_arn: str = Field(..., min_length=1)


class ConnectAzureRequest(BaseModel):
    azure_tenant_id: str = Field(..., min_length=1)
    client_id: str = Field(..., min_length=1)
    client_secret: str = Field(..., min_length=1)
    subscription_id: str = Field(..., min_length=1)
    # 24-gap-closure Phase 5 -- captured at connection time, not
    # generated: an SP client secret's expiry is chosen in Azure AD when
    # the customer creates it, we only ever record what they tell us.
    # Optional so a workspace that connected before this phase, or a
    # customer who genuinely doesn't know it yet, isn't blocked -- no
    # expiry captured just means no 14-day warning/expired-incident ever
    # fires for that credential, same as today's behavior.
    client_secret_expires_at: datetime | None = None


class ConnectAzureDevOpsRequest(BaseModel):
    org: str = Field(..., min_length=1)
    pat: str = Field(..., min_length=1)
    # 24-gap-closure Phase 5 -- same rationale as client_secret_expires_at
    # above: a PAT's expiry is chosen at creation in Azure DevOps.
    pat_expires_at: datetime | None = None


class ConnectAzureDevOpsResponse(BaseModel):
    status: str = "verified"
    webhook_secret: str | None = Field(
        default=None,
        description="Only present the first time a webhook secret is minted for this "
        "workspace -- save it now, register it as the Azure DevOps service hook's Basic "
        "auth password, it will not be shown again.",
    )


class ConnectK8sRequest(BaseModel):
    api_url: str = Field(..., min_length=1)
    token: str = Field(..., min_length=1)
    ca_cert: str | None = Field(
        default=None,
        description="PEM-encoded cluster CA certificate. Required for most real clusters "
        "(EKS/AKS control planes typically use a private CA) -- omit only if the API server "
        "is fronted by a publicly-trusted certificate.",
    )


class CredentialStatusResponse(BaseModel):
    id: str
    status: str = "verified"


class ConnectionsStatusResponse(BaseModel):
    github_connected: bool
    github_via_legacy_pat: bool
    aws_connected: bool
    azure_connected: bool
    azure_devops_connected: bool
    k8s_connected: bool
    llm_configured: bool
    llm_provider: str | None
    # None for a token-authenticated caller (full-trust, same as every
    # other route in this file) -- only set for a member-session caller.
    # Onboarding completeness build, item 4: the frontend needs this to
    # decide whether to show the Workspace Token card's rotate action.
    member_role: str | None = None
    # 24-gap-closure Phase 4 -- the Members & Security panel needs these
    # to decide whether to show the Enterprise-only "require MFA" toggle
    # and what state it's currently in.
    product_tier: str | None = None
    require_mfa: bool = False
    # 24-gap-closure Phase 7 follow-up (Kelvin's item 7) -- lets the
    # dashboard show a non-dismissible banner when missing, since
    # credential-expiry (Phase 5) and payment-failure (Phase 7)
    # notifications both depend on a contact_email existing.
    has_contact_email: bool = False


class WorkspaceTokenStatusResponse(BaseModel):
    last4: str | None
    rotated_at: str | None
    last_used_at: str | None = None
    expires_at: str | None = None
    # 24-gap-closure Phase 5 -- present (non-null) only while a prior
    # token is still inside its 72h rotation grace window, so a page
    # reload still shows the banner correctly, not just the response
    # from the rotate call itself in that one session.
    grace_period_ends_at: str | None = None


# 24-gap-closure Phase 5 -- every place the workspace token appears in a
# URL a customer pastes into an external system. Returned on every
# rotation so the frontend can render it as a checklist -- the customer
# needs to know exactly what to go update, not just that "some alert
# sources" might need it.
_ALERT_SOURCE_CHECKLIST = (
    "GitHub webhook (if using the legacy PAT path, not the GitHub App)",
    "Azure Monitor Action Group webhook",
    "AWS SNS topic subscription (CloudWatch/EventBridge alarms)",
    "Azure DevOps service hook",
    "Any other custom webhook URL registered with this token",
)


class RotateWorkspaceTokenResponse(BaseModel):
    workspace_token: str
    last4: str
    rotated_at: str
    grace_period_ends_at: str
    alert_source_checklist: list[str] = Field(default_factory=lambda: list(_ALERT_SOURCE_CHECKLIST))


class SetTokenExpiryRequest(BaseModel):
    # 24-gap-closure Phase 4 -- optional expiry. None clears it (never
    # expires), matching the nullable column's own default.
    expires_at: str | None = None


class SetTokenExpiryResponse(BaseModel):
    expires_at: str | None


# Onboarding completeness build, item 4. Deliberately admin-only (not
# admin-or-approver like incidents.py's _APPROVAL_ROLES) -- rotating the
# one credential that authenticates every other request this workspace
# makes is more sensitive than approving a remediation. A token-
# authenticated caller (no member_role at all) is always permitted, same
# full-trust model every other route in this file already has.
_TOKEN_ADMIN_ROLES = frozenset({"admin"})


def _caller_is_workspace_admin(workspace: dict) -> bool:
    member_role = workspace.get("member_role")
    if member_role is None:
        return True
    return member_role in _TOKEN_ADMIN_ROLES


def _generate_raw_workspace_token() -> str:
    # Same shape as api/routes/internal_workspaces.py's _generate_raw_token
    # (cd_ws_ prefix + secrets.token_urlsafe(32)) -- not imported from there
    # since that module's helper is private to it; duplicating one line is
    # simpler and safer than reaching into another route file's underscore-
    # prefixed internals.
    return f"cd_ws_{secrets.token_urlsafe(32)}"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status", response_model=ConnectionsStatusResponse)
async def get_connections_status(
    workspace: dict = Depends(get_workspace_or_member),
) -> ConnectionsStatusResponse:
    """
    Read-only connection state for the Connections settings page.

    Widened from get_workspace to get_workspace_or_member as part of the
    onboarding completeness build (item 4): this was the ONLY entry point
    into ConnectionsPanel.tsx, and it accepted only the raw workspace
    token -- a logged-in member (Phase A/B/C's Supabase-session dashboard
    login) got a 401 the moment they opened Connections at all, before
    this fix. One more instance of GAPS.md #22's own flagged follow-up
    ("rolling get_workspace_or_member out further is mechanical... not
    done blind across every route") -- necessary here because item 4's
    self-serve token UI has to actually be reachable by a logged-in admin,
    not just a raw-token holder.

    github_via_legacy_pat: true only when GitHub access is still the retired
    PAT path with no App installation on top of it -- surfaced so the
    dashboard can nudge these workspaces to migrate (GAPS.md: legacy PAT
    workspaces had no prompted migration to the App).
    """
    has_app = bool(workspace.get("github_app_installation_id"))
    has_pat = bool(workspace.get("github_pat_verified_at"))
    return ConnectionsStatusResponse(
        github_connected=has_app or has_pat,
        github_via_legacy_pat=has_pat and not has_app,
        aws_connected=bool(workspace.get("aws_role_verified_at")),
        azure_connected=bool(workspace.get("azure_verified_at")),
        azure_devops_connected=bool(workspace.get("azure_devops_pat_verified_at")),
        k8s_connected=bool(workspace.get("k8s_verified_at")),
        llm_configured=bool(workspace.get("encrypted_llm_key")),
        llm_provider=workspace.get("llm_provider"),
        member_role=workspace.get("member_role"),
        product_tier=workspace.get("product_tier"),
        require_mfa=bool(workspace.get("require_mfa")),
        has_contact_email=bool(workspace.get("contact_email")),
    )


@router.get("/token", response_model=WorkspaceTokenStatusResponse)
async def get_workspace_token_status(
    workspace: dict = Depends(get_workspace_or_member),
) -> WorkspaceTokenStatusResponse:
    """
    Onboarding completeness build, item 4. There is no raw token to
    "reveal" here -- workspaces.workspace_token stores only a SHA-256
    hash (see db/migrations/040_workspace_token_display_metadata.sql's
    own comment), the same one-way property as a password. This returns
    the masked-display hint (last4, set only at issuance/rotation time)
    and when the current token was last rotated, nothing more.
    """
    if not _caller_is_workspace_admin(workspace):
        raise HTTPException(status_code=403, detail="Only a workspace admin can view token details")

    rotated_at = workspace.get("workspace_token_rotated_at")
    last_used_at = workspace.get("workspace_token_last_used_at")
    expires_at = workspace.get("workspace_token_expires_at")
    grace_ends_at = workspace.get("previous_workspace_token_expires_at")
    from datetime import datetime, timezone
    if grace_ends_at is not None and grace_ends_at <= datetime.now(timezone.utc):
        grace_ends_at = None  # window already closed -- don't show a stale banner
    return WorkspaceTokenStatusResponse(
        last4=workspace.get("workspace_token_last4"),
        rotated_at=rotated_at.isoformat() if rotated_at else None,
        last_used_at=last_used_at.isoformat() if last_used_at else None,
        expires_at=expires_at.isoformat() if expires_at else None,
        grace_period_ends_at=grace_ends_at.isoformat() if grace_ends_at else None,
    )


@router.post("/token/rotate", response_model=RotateWorkspaceTokenResponse)
async def rotate_workspace_token_self_serve(
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
) -> RotateWorkspaceTokenResponse:
    """
    Onboarding completeness build, item 4 -- self-serve equivalent of
    api/routes/internal_workspaces.py's admin-only rotate-token (that one
    stays THD-team-only, gated by get_internal_user; this is the
    customer-facing path, gated by workspace-admin role).

    24-gap-closure Phase 5: the old token now stays valid for a real 72h
    grace window (previous_workspace_token_hash/_expires_at, checked as a
    fallback in api/middleware/auth.py's _get_workspace_by_token) rather
    than stopping the moment this commits -- an alert source that hasn't
    been updated with the new token yet keeps working during the window
    instead of silently breaking. `previous_workspace_token_hash =
    workspace_token` in the UPDATE below reads the PRE-update value
    (standard SQL UPDATE semantics -- every SET expression sees the old
    row), so no separate read-then-write is needed to capture it.

    Returns the new raw token exactly once, same "shown once" contract as
    every other token-issuing endpoint in this codebase.
    """
    if not _caller_is_workspace_admin(workspace):
        raise HTTPException(status_code=403, detail="Only a workspace admin can rotate the workspace token")

    raw_token = _generate_raw_workspace_token()
    token_hash = _hash_token(raw_token)
    last4 = raw_token[-4:]

    async with request.app.state.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE workspaces SET "
            "previous_workspace_token_hash = workspace_token, "
            "previous_workspace_token_expires_at = NOW() + INTERVAL '72 hours', "
            "workspace_token = $1, workspace_token_last4 = $2, "
            "workspace_token_rotated_at = NOW(), workspace_token_last_used_at = NULL, "
            "updated_at = NOW() "
            "WHERE id = $3 "
            "RETURNING workspace_token_rotated_at, previous_workspace_token_expires_at",
            token_hash,
            last4,
            workspace["id"],
        )

    await write_audit_event(
        workspace_id=str(workspace["id"]),
        action="workspace_token_rotated",
        status="success",
        metadata={"member_role": workspace.get("member_role") or "token"},
    )

    log.info("[WorkspaceCredentials] Workspace=%s rotated its own token", workspace["id"])
    return RotateWorkspaceTokenResponse(
        workspace_token=raw_token,
        last4=last4,
        rotated_at=row["workspace_token_rotated_at"].isoformat(),
        grace_period_ends_at=row["previous_workspace_token_expires_at"].isoformat(),
    )


@router.patch("/token/expiry", response_model=SetTokenExpiryResponse)
async def set_workspace_token_expiry(
    body: SetTokenExpiryRequest,
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
) -> SetTokenExpiryResponse:
    """
    24-gap-closure Phase 4 -- optional workspace-token expiry, admin-only
    same as rotate. expires_at=None clears any existing expiry (token
    never expires again, the pre-Phase-4 default for every workspace).
    A caller-supplied expires_at in the past is rejected outright rather
    than silently accepted and immediately locking the workspace out.
    """
    if not _caller_is_workspace_admin(workspace):
        raise HTTPException(status_code=403, detail="Only a workspace admin can set token expiry")

    expires_dt = None
    if body.expires_at is not None:
        from datetime import datetime, timezone
        try:
            expires_dt = datetime.fromisoformat(body.expires_at)
        except ValueError:
            raise HTTPException(status_code=400, detail="expires_at must be a valid ISO 8601 timestamp")
        if expires_dt.tzinfo is None:
            expires_dt = expires_dt.replace(tzinfo=timezone.utc)
        if expires_dt <= datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="expires_at must be in the future")

    async with request.app.state.db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE workspaces SET workspace_token_expires_at = $1, updated_at = NOW() WHERE id = $2",
            expires_dt, workspace["id"],
        )

    await write_audit_event(
        workspace_id=str(workspace["id"]),
        action="workspace_token_expiry_changed",
        status="success",
        metadata={"expires_at": expires_dt.isoformat() if expires_dt else None},
    )

    return SetTokenExpiryResponse(expires_at=expires_dt.isoformat() if expires_dt else None)


@router.patch("/github", response_model=ConnectGithubResponse)
async def connect_github(
    body: ConnectGithubRequest,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> ConnectGithubResponse:
    """
    Retired as of the item 4 GitHub App migration (decided 2026-09-13):
    PATs are no longer accepted for new connections -- GitHub Apps give
    fine-grained, revocable, auditable access with short-lived tokens and
    a per-installation webhook secret instead of one long-lived PAT plus a
    shared secret. Use GET /workspace/credentials/github-app/install-url
    instead. A workspace that already stored a PAT before this migration
    keeps working (core/workspace_credentials.py's build_agent_credentials
    still reads it as a legacy fallback) -- this route just stops minting
    new ones.
    """
    raise HTTPException(
        status_code=410,
        detail="PAT-based GitHub connection is retired. Call "
               "GET /workspace/credentials/github-app/install-url and install the "
               "Cloud Decoded GitHub App instead.",
    )


@router.get("/github-app/install-url")
async def get_github_app_install_url(
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> dict:
    """Returns a one-time install URL for this workspace. The signed state
    param ties GitHub's install-callback redirect back to this exact
    workspace without needing an auth header (the callback is a plain
    browser redirect GitHub controls, not an authenticated API call)."""
    async with request.app.state.db_pool.acquire() as conn:
        app_row = await conn.fetchrow("SELECT app_slug FROM github_app_config WHERE id = 'singleton'")

    if not app_row:
        raise HTTPException(status_code=503, detail="GitHub App not registered yet on this platform")

    state = sign_workspace_state(str(workspace["id"]))
    return {"install_url": build_install_url(app_row["app_slug"], state)}


@router.get("/github-app/callback")
async def github_app_install_callback(request: Request, installation_id: str, state: str):
    """
    Public route -- GitHub redirects the customer's own browser here after
    they click "Install" (this is the App's configured setup_url), with no
    auth header we control. The signed `state` param (minted by
    get_github_app_install_url) is the only thing tying this redirect back
    to a real workspace; verify it instead of trusting installation_id alone.

    Returns a real browser redirect back into the dashboard, not bare JSON --
    this is the customer's actual browser navigating here (GitHub's setup_url
    flow), not an API call a frontend can read a JSON body from. A JSON
    response would just render as a blank page. Same /dashboard?connected=X
    convention api/routes/content.py's LinkedIn/X OAuth callbacks already use.
    """
    workspace_id = verify_workspace_state(state)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="Invalid or expired state -- restart the install flow")

    async with request.app.state.db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE workspaces SET github_app_installation_id = $1, github_app_installed_at = NOW() "
            "WHERE id = $2",
            installation_id,
            workspace_id,
        )

    log.info("[WorkspaceCredentials] GitHub App installed workspace=%s installation=%s", workspace_id, installation_id)
    return RedirectResponse(f"{_FRONTEND_URL}/dashboard?connected=github")


@router.post("/aws-role/setup", response_model=AwsRoleSetupResponse)
async def setup_aws_role(
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> AwsRoleSetupResponse:
    platform_aws_account_id = os.environ.get("CLOUD_DECODED_AWS_ACCOUNT_ID")
    if not platform_aws_account_id:
        raise HTTPException(status_code=500, detail="CLOUD_DECODED_AWS_ACCOUNT_ID not configured on this server")

    external_id = generate_external_id()
    workspace_id = workspace["id"]

    async with request.app.state.db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE workspaces SET aws_external_id = $1 WHERE id = $2",
            external_id,
            workspace_id,
        )

    log.info("[WorkspaceCredentials] AWS role setup started workspace=%s", workspace_id)
    return AwsRoleSetupResponse(
        external_id=external_id,
        trust_policy=build_trust_policy(platform_aws_account_id, external_id),
        permissions_policy=build_permissions_policy(),
        instructions=(
            "In AWS: create an IAM role using trust_policy as its trust relationship, "
            "and attach permissions_policy as an inline policy. Then call "
            "PATCH /workspace/credentials/aws-role with the role's ARN."
        ),
    )


@router.patch("/aws-role", response_model=CredentialStatusResponse)
async def connect_aws_role(
    body: ConnectAwsRoleRequest,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> CredentialStatusResponse:
    """
    24-gap-closure Phase 5 note: unlike connect_azure/connect_azure_devops
    below, there is no *_expires_at captured here by design. This role is
    assumed via AWS STS AssumeRole against the trust policy set up in
    setup_aws_role -- there is no client secret or PAT with a fixed
    lifetime the customer chose; the trust relationship itself doesn't
    expire the way an Azure SP client secret or a PAT does. Nothing to
    capture, nothing for core/credential_expiry.py to ever check for AWS.
    """
    workspace_id = workspace["id"]

    async with request.app.state.db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT aws_external_id FROM workspaces WHERE id = $1", workspace_id)

    if not row or not row["aws_external_id"]:
        raise HTTPException(
            status_code=400,
            detail="Call POST /workspace/credentials/aws-role/setup first to get an external ID",
        )

    try:
        verify_role(body.role_arn, row["aws_external_id"])
    except AssumeRoleError as exc:
        raise HTTPException(status_code=400, detail=f"Could not assume role: {exc}") from exc

    async with request.app.state.db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE workspaces
            SET aws_role_arn = $1, aws_role_verified_at = NOW(),
                cloud_providers = array_append(
                    array_remove(COALESCE(cloud_providers, '{}'), 'aws'), 'aws'
                )
            WHERE id = $2
            """,
            body.role_arn,
            workspace_id,
        )

    log.info("[WorkspaceCredentials] AWS role verified workspace=%s", workspace_id)
    return CredentialStatusResponse(id=str(workspace_id))


@router.patch("/azure", response_model=CredentialStatusResponse)
async def connect_azure(
    body: ConnectAzureRequest,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> CredentialStatusResponse:
    try:
        await verify_service_principal(body.azure_tenant_id, body.client_id, body.client_secret, body.subscription_id)
    except AzureConnectError as exc:
        raise HTTPException(status_code=400, detail=f"Could not verify Service Principal: {exc}") from exc

    workspace_id = workspace["id"]

    async with request.app.state.db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE workspaces
            SET azure_tenant_id = $1, azure_client_id = $2,
                azure_client_secret_encrypted = $3, azure_subscription_id = $4,
                azure_verified_at = NOW(),
                azure_client_secret_expires_at = $5,
                azure_client_secret_expiry_warned_at = NULL,
                cloud_providers = array_append(
                    array_remove(COALESCE(cloud_providers, '{}'), 'azure'), 'azure'
                )
            WHERE id = $6
            """,
            body.azure_tenant_id,
            body.client_id,
            encrypt(body.client_secret),
            body.subscription_id,
            body.client_secret_expires_at,
            workspace_id,
        )

    log.info("[WorkspaceCredentials] Azure Service Principal verified workspace=%s", workspace_id)
    return CredentialStatusResponse(id=str(workspace_id))


@router.patch("/azure-devops", response_model=ConnectAzureDevOpsResponse)
async def connect_azure_devops(
    body: ConnectAzureDevOpsRequest,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> ConnectAzureDevOpsResponse:
    """
    Verify-then-store a workspace's Azure DevOps PAT (item 5, migration 024).
    No App/OAuth flow exists for this provider yet (see core/repo_tools.py's
    module docstring for why) -- a PAT is the real, documented mechanism,
    not a stopgap, so this route is not scheduled to be retired the way
    PATCH /workspace/credentials/github was.

    Mints a per-workspace webhook secret on first connect, same idempotent
    pattern GitHub's PAT route used before its retirement -- closes
    api/routes/webhooks.py's azure_devops_webhook "no per-workspace secret
    yet, fails open" gap.
    """
    try:
        await verify_azure_devops_pat(body.org, body.pat)
    except AzureDevOpsConnectError as exc:
        raise HTTPException(status_code=400, detail=f"Could not verify Azure DevOps access: {exc}") from exc

    workspace_id = workspace["id"]

    async with request.app.state.db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT encrypted_azure_devops_webhook_secret FROM workspaces WHERE id = $1", workspace_id
        )

        webhook_secret_raw = None
        if existing and existing["encrypted_azure_devops_webhook_secret"]:
            # Already minted on a prior connect -- reconnecting (e.g. a
            # rotated PAT) must not silently invalidate an already-registered
            # Azure DevOps service hook's secret.
            await conn.execute(
                "UPDATE workspaces SET azure_devops_org = $1, azure_devops_pat_encrypted = $2, "
                "azure_devops_pat_verified_at = NOW(), azure_devops_pat_expires_at = $3, "
                "azure_devops_pat_expiry_warned_at = NULL WHERE id = $4",
                body.org,
                encrypt(body.pat),
                body.pat_expires_at,
                workspace_id,
            )
        else:
            webhook_secret_raw = secrets.token_urlsafe(32)
            await conn.execute(
                "UPDATE workspaces SET azure_devops_org = $1, azure_devops_pat_encrypted = $2, "
                "azure_devops_pat_verified_at = NOW(), encrypted_azure_devops_webhook_secret = $3, "
                "azure_devops_webhook_secret_created_at = NOW(), azure_devops_pat_expires_at = $4, "
                "azure_devops_pat_expiry_warned_at = NULL WHERE id = $5",
                body.org,
                encrypt(body.pat),
                encrypt(webhook_secret_raw),
                body.pat_expires_at,
                workspace_id,
            )

    log.info("[WorkspaceCredentials] Azure DevOps PAT verified workspace=%s org=%s", workspace_id, body.org)
    return ConnectAzureDevOpsResponse(webhook_secret=webhook_secret_raw)


@router.patch("/k8s", response_model=CredentialStatusResponse)
async def connect_k8s(
    body: ConnectK8sRequest,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> CredentialStatusResponse:
    """
    Verify-then-store a workspace's Kubernetes cluster credentials
    (Phase 4, migration 025) -- a service-account bearer token plus the
    cluster's API server URL, same shape Agents 02/08 already expect
    (core.workspace_credentials.build_k8s_credentials). Replaces the global
    KUBECONFIG_YAML + K8S_CONTEXT_* stopgap for any workspace that connects
    its own cluster here.
    """
    try:
        await verify_k8s_connection(body.api_url, body.token, body.ca_cert)
    except K8sConnectError as exc:
        raise HTTPException(status_code=400, detail=f"Could not verify cluster access: {exc}") from exc

    workspace_id = workspace["id"]

    async with request.app.state.db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE workspaces
            SET k8s_api_url = $1, k8s_token_encrypted = $2, k8s_ca_cert_encrypted = $3,
                k8s_verified_at = NOW()
            WHERE id = $4
            """,
            body.api_url,
            encrypt(body.token),
            encrypt(body.ca_cert) if body.ca_cert else None,
            workspace_id,
        )

    log.info("[WorkspaceCredentials] Kubernetes cluster verified workspace=%s", workspace_id)
    return CredentialStatusResponse(id=str(workspace_id))
