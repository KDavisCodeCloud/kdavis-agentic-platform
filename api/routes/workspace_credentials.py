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

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.middleware.auth import get_workspace
from core.github_app import build_install_url, sign_workspace_state, verify_workspace_state
from core.workspace_credentials import (
    AssumeRoleError,
    AzureConnectError,
    build_permissions_policy,
    build_trust_policy,
    generate_external_id,
    verify_role,
    verify_service_principal,
)
from security.encryption import encrypt

log = logging.getLogger(__name__)
router = APIRouter(prefix="/workspace/credentials", tags=["workspace-credentials"])


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


class CredentialStatusResponse(BaseModel):
    id: str
    status: str = "verified"


class ConnectionsStatusResponse(BaseModel):
    github_connected: bool
    aws_connected: bool
    azure_connected: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status", response_model=ConnectionsStatusResponse)
async def get_connections_status(
    workspace: dict = Depends(get_workspace),
) -> ConnectionsStatusResponse:
    """
    Read-only connection state for the Connections settings page. get_workspace
    (api/middleware/auth.py) already selects every *_verified_at column used
    here, so this needs no extra DB query.
    """
    return ConnectionsStatusResponse(
        github_connected=bool(workspace.get("github_pat_verified_at")),
        aws_connected=bool(workspace.get("aws_role_verified_at")),
        azure_connected=bool(workspace.get("azure_verified_at")),
    )


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
async def github_app_install_callback(request: Request, installation_id: str, state: str) -> dict:
    """
    Public route -- GitHub redirects the customer's own browser here after
    they click "Install" (this is the App's configured setup_url), with no
    auth header we control. The signed `state` param (minted by
    get_github_app_install_url) is the only thing tying this redirect back
    to a real workspace; verify it instead of trusting installation_id alone.
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
    return {"status": "installed"}


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
                cloud_providers = array_append(
                    array_remove(COALESCE(cloud_providers, '{}'), 'azure'), 'azure'
                )
            WHERE id = $5
            """,
            body.azure_tenant_id,
            body.client_id,
            encrypt(body.client_secret),
            body.subscription_id,
            workspace_id,
        )

    log.info("[WorkspaceCredentials] Azure Service Principal verified workspace=%s", workspace_id)
    return CredentialStatusResponse(id=str(workspace_id))
