"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Per-workspace target-system credentials for Agents 01 (CI/CD), 05 (IAM),
06 (FinOps), and 08 (Drift) -- the four agents whose real remediation
actually calls out to GitHub, AWS, or Azure. Mirrors the AWS/Azure
onboarding shape already proven live in kdavis-finops-agent's
core/aws_onboarding.py + core/azure_onboarding.py, applied here to
workspaces (migration 022) instead of a satellite product's own tenant
table.

Two differences from that proven pattern, both deliberate:

- Azure: this module does a direct OAuth2 client-credentials POST to
  login.microsoftonline.com instead of using the azure-identity SDK.
  Every one of these four agents' tools.py already builds raw httpx
  Bearer-token requests against management.azure.com
  (_azure_headers(token)) -- minting the token the same low-level way
  keeps one dependency footprint instead of adding azure-identity +
  azure-mgmt-resource to a repo that doesn't otherwise use them.
- AWS: build_permissions_policy() here is scoped to what THESE FOUR
  AGENTS need (IAM policy read/write, Cost Explorer, EC2 waste actions,
  CloudFormation/EKS describe) -- a different, broader policy than
  kdavis-finops-agent's read-only one, because this platform's agents
  write, not just read. Update this list if a new AWS call is added to
  any of agents 01/05/06/08.
"""

import logging
import os
import secrets
from typing import Optional
from uuid import UUID

import boto3
import httpx
from botocore.exceptions import ClientError

from security.encryption import decrypt

log = logging.getLogger(__name__)

# A boto3.Session built from raw assumed-role credentials has no region
# behind it -- same gotcha already documented in kdavis-finops-agent's
# core/aws_onboarding.py, confirmed live there 2026-09-11.
_DEFAULT_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

_AZURE_TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
_ARM_RESOURCE = "https://management.azure.com/"

_PERMISSIONS_POLICY_ACTIONS = [
    # Agent 05 -- IAM policy minimization
    "iam:ListPolicyVersions",
    "iam:GetPolicyVersion",
    "iam:CreatePolicyVersion",
    "iam:ListEntitiesForPolicy",
    # Agent 06 -- FinOps cost data + quick-win waste cleanup
    "ce:GetCostAndUsage",
    "ec2:DescribeInstances",
    "ec2:DescribeVolumes",
    "ec2:DescribeAddresses",
    "ec2:StopInstances",
    "ec2:DeleteVolume",
    "ec2:ReleaseAddress",
    # Agent 08 -- drift detection against CloudFormation/EKS
    "cloudformation:DescribeStacks",
    "cloudformation:DescribeStackResources",
    "eks:DescribeCluster",
    "eks:ListClusters",
]


def generate_external_id() -> str:
    return secrets.token_urlsafe(24)


def build_trust_policy(platform_aws_account_id: str, external_id: str) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": f"arn:aws:iam::{platform_aws_account_id}:root"},
                "Action": "sts:AssumeRole",
                "Condition": {"StringEquals": {"sts:ExternalId": external_id}},
            }
        ],
    }


def build_permissions_policy() -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": _PERMISSIONS_POLICY_ACTIONS,
                "Resource": "*",
            }
        ],
    }


class AssumeRoleError(Exception):
    """Raised when a workspace's AWS role can't be assumed -- wraps the AWS error message."""


def _assume_role(role_arn: str, external_id: str, session_name: str) -> dict:
    sts = boto3.client("sts")
    try:
        response = sts.assume_role(
            RoleArn=role_arn,
            ExternalId=external_id,
            RoleSessionName=session_name,
        )
    except ClientError as exc:
        raise AssumeRoleError(str(exc)) from exc
    return response["Credentials"]


def verify_role(role_arn: str, external_id: str) -> None:
    """Raises AssumeRoleError if the role can't be assumed. Verification only --
    every real call assumes fresh, nothing is cached."""
    _assume_role(role_arn, external_id, session_name="clouddecoded-verify")


def assume_role_session(role_arn: str, external_id: str) -> boto3.Session:
    """Assumes the role fresh and returns a boto3.Session from the temp
    credentials. Never cache these -- they expire (default 1 hour)."""
    creds = _assume_role(role_arn, external_id, session_name="clouddecoded-agent")
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=_DEFAULT_REGION,
    )


class AzureConnectError(Exception):
    """Raised when a workspace's Azure Service Principal can't authenticate
    or lacks access -- wraps the underlying Azure error message."""


async def get_azure_bearer_token(
    tenant_id: str, client_id: str, client_secret: str, resource: str = _ARM_RESOURCE
) -> str:
    """Standard OAuth2 client-credentials flow -- returns a fresh ARM bearer
    token for the exact same Authorization: Bearer <token> shape every
    agent's tools.py already builds via its own _azure_headers(token)."""
    url = _AZURE_TOKEN_URL.format(tenant_id=tenant_id)
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": f"{resource}.default",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(url, data=data)
        except httpx.RequestError as exc:
            raise AzureConnectError(f"Could not reach Azure token endpoint: {exc}") from exc

    if resp.status_code != 200:
        raise AzureConnectError(f"Azure token request failed ({resp.status_code}): {resp.text[:200]}")

    token = resp.json().get("access_token")
    if not token:
        raise AzureConnectError("Azure token response had no access_token")
    return token


async def verify_service_principal(tenant_id: str, client_id: str, client_secret: str, subscription_id: str) -> None:
    """Raises AzureConnectError if the Service Principal can't authenticate
    or lacks access. Mints a token, then one cheap ARM read to confirm it
    actually has access to the subscription."""
    token = await get_azure_bearer_token(tenant_id, client_id, client_secret)

    url = f"{_ARM_RESOURCE}subscriptions/{subscription_id}?api-version=2022-12-01"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        except httpx.RequestError as exc:
            raise AzureConnectError(f"Could not verify subscription access: {exc}") from exc

    if resp.status_code != 200:
        raise AzureConnectError(f"Could not verify access ({resp.status_code}): {resp.text[:200]}")


# ── Per-call credential fetch for agents 01/05/06/08 ────────────────────────

async def build_agent_credentials(conn, workspace_id: str) -> dict:
    """Fetches and decrypts a workspace's stored target-system credentials,
    returning ready-to-use objects for each agent's *Tools() constructor.
    Any credential not configured for this workspace comes back None --
    tools.py methods raise their own ValueError when a specific call
    actually needs a credential that's missing, rather than this function
    guessing which credentials a given incident will need.

    Mirrors agents/base_agent.py's _decrypt_byok: decrypt per-call, never
    persist plaintext beyond the request.
    """
    row = await conn.fetchrow(
        "SELECT github_pat_encrypted, aws_role_arn, aws_external_id, "
        "azure_tenant_id, azure_client_id, azure_client_secret_encrypted, "
        "azure_subscription_id FROM workspaces WHERE id = $1",
        UUID(workspace_id) if isinstance(workspace_id, str) else workspace_id,
    )

    credentials: dict[str, Optional[object]] = {
        "github_token": None,
        "aws_session": None,
        "azure_access_token": None,
    }
    if not row:
        return credentials

    if row["github_pat_encrypted"]:
        credentials["github_token"] = decrypt(row["github_pat_encrypted"])

    if row["aws_role_arn"] and row["aws_external_id"]:
        credentials["aws_session"] = assume_role_session(row["aws_role_arn"], row["aws_external_id"])

    if row["azure_tenant_id"] and row["azure_client_id"] and row["azure_client_secret_encrypted"]:
        credentials["azure_access_token"] = await get_azure_bearer_token(
            row["azure_tenant_id"],
            row["azure_client_id"],
            decrypt(row["azure_client_secret_encrypted"]),
        )

    return credentials
