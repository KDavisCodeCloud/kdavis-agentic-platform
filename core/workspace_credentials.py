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

import base64
import json
import logging
import os
import secrets
from typing import Optional
from uuid import UUID

import boto3
import httpx
import yaml
from botocore.exceptions import ClientError

from core.github_app import GitHubAppError, mint_installation_token
from security.encryption import decrypt

log = logging.getLogger(__name__)

# A boto3.Session built from raw assumed-role credentials has no region
# behind it -- same gotcha already documented in kdavis-finops-agent's
# core/aws_onboarding.py, confirmed live there 2026-09-11.
_DEFAULT_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

_AZURE_TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
_ARM_RESOURCE = "https://management.azure.com/"
_AZURE_DEVOPS_API = "https://dev.azure.com"

_PERMISSIONS_POLICY_ACTIONS = [
    # Agent 05 -- IAM policy minimization. Reads: iam/agents/agent_05_iam_minimizer/
    # tools.py's get_aws_policy_document, list_aws_instance_profile_roles,
    # list_lambda_execution_roles, detect_overpermissive_aws_roles. Write:
    # apply_aws_policy (DeletePolicyVersion only on the 5-version-cap eviction
    # retry path). Corrected 2026-09-17 (Settings → Policies build, Step 0/5
    # audit) -- ListInstanceProfiles/ListAttachedRolePolicies/ListRolePolicies/
    # GetRolePolicy/lambda:ListFunctions/DeletePolicyVersion were genuinely
    # missing from this policy despite every one of those calls existing in
    # tools.py since Agent 05 shipped; any real customer's role, set up
    # exactly per these instructions, would 403 on those specific read paths.
    "iam:ListPolicyVersions",
    "iam:GetPolicyVersion",
    "iam:CreatePolicyVersion",
    "iam:DeletePolicyVersion",
    "iam:ListEntitiesForPolicy",
    "iam:ListInstanceProfiles",
    "iam:ListAttachedRolePolicies",
    "iam:ListRolePolicies",
    "iam:GetRolePolicy",
    "lambda:ListFunctions",
    # Agent 06 -- FinOps cost data + quick-win waste cleanup. Confirmed by
    # the same audit: agent_06 identifies idle resources from an operator-
    # supplied billing export (see agent-reference.md), never a live
    # ec2:Describe* call -- those three were an unused over-grant, removed.
    "ce:GetCostAndUsage",
    "ec2:StopInstances",
    "ec2:DeleteVolume",
    "ec2:ReleaseAddress",
    # Agent 08 -- drift detection. Confirmed by the same audit: no EKS API
    # call and no cloudformation:DescribeStacks call exist anywhere in this
    # agent (drift's K8s path goes through the cluster's own API, not AWS
    # EKS control-plane calls) -- both were an unused over-grant, removed,
    # replaced with the S3/security-group/route-table read actions its
    # fetch_s3_bucket_state/fetch_security_group_state/fetch_route_table_state
    # (Phase 1/2, site-audit gap closure) actually call.
    "cloudformation:DescribeStackResources",
    "s3:GetBucketVersioning",
    "s3:GetEncryptionConfiguration",
    "s3:GetBucketPublicAccessBlock",
    "s3:GetBucketPolicy",
    "s3:GetReplicationConfiguration",
    "ec2:DescribeSecurityGroups",
    "ec2:DescribeRouteTables",
]


def resolve_k8s_context(cloud_provider: str) -> Optional[str]:
    """
    Maps a drift-detection payload's cloud_provider to a kubeconfig context
    name, via K8S_CONTEXT_AWS / K8S_CONTEXT_AZURE / K8S_CONTEXT_GCP env vars.

    Stopgap, not the real per-workspace multi-cluster model: today's
    KUBECONFIG_YAML (api/main.py's _write_kubeconfig_from_env) is one global
    kubeconfig for the whole platform, not per-workspace. Without this
    resolver, kubectl always uses KUBECONFIG's current-context regardless of
    which cluster an incident is actually about -- found live: an AKS
    incident's "apply directly" silently ran against EKS instead (both
    contexts happened to exist in the same file) and reported false success.
    Real per-workspace, per-cluster credential storage is tracked separately.
    """
    env_var = {"aws": "K8S_CONTEXT_AWS", "azure": "K8S_CONTEXT_AZURE", "gcp": "K8S_CONTEXT_GCP"}.get(cloud_provider)
    return os.environ.get(env_var) if env_var else None


class K8sConnectError(Exception):
    """Raised when a workspace's Kubernetes API credentials can't reach the
    cluster or lack access -- wraps the underlying API server error."""


async def verify_k8s_connection(api_url: str, token: str, ca_cert: Optional[str] = None) -> None:
    """Raises K8sConnectError if the cluster's API server can't be reached
    or the token lacks access. One cheap authenticated read (the API
    discovery endpoint) confirms both connectivity and that the token
    actually has some RBAC access, not just that the URL resolves.

    ca_cert (PEM), if given, is used for TLS verification -- most real
    clusters (EKS/AKS control planes especially) use a private CA a
    customer must supply. If omitted, falls back to the standard system CA
    trust store, same as any normal HTTPS client -- never silently skips
    verification."""
    verify: bool | str = True
    if ca_cert:
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
            f.write(ca_cert)
            verify = f.name
        try:
            await _verify_k8s_connection(api_url, token, verify)
        finally:
            os.unlink(verify)
    else:
        await _verify_k8s_connection(api_url, token, verify)


async def _verify_k8s_connection(api_url: str, token: str, verify) -> None:
    async with httpx.AsyncClient(timeout=15, verify=verify) as client:
        try:
            resp = await client.get(
                f"{api_url.rstrip('/')}/api",
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.RequestError as exc:
            raise K8sConnectError(f"Could not reach Kubernetes API server: {exc}") from exc

    if resp.status_code != 200:
        raise K8sConnectError(f"Could not verify cluster access ({resp.status_code}): {resp.text[:200]}")


def build_kubeconfig(api_url: str, token: str, ca_cert: Optional[str] = None) -> str:
    """Generates a minimal single-cluster kubeconfig YAML for kubectl
    subprocess use (agent_08_drift_detection's DriftTools) -- a bearer
    token plus optional CA cert is enough; no client certs needed.

    Omits certificate-authority-data when ca_cert is None rather than
    setting insecure-skip-tls-verify -- kubectl then verifies against the
    system trust store, consistent with verify_k8s_connection's own
    fallback above. Never silently skip TLS verification."""
    cluster: dict = {"server": api_url}
    if ca_cert:
        cluster["certificate-authority-data"] = base64.b64encode(ca_cert.encode()).decode()

    config = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [{"name": "workspace-cluster", "cluster": cluster}],
        "users": [{"name": "workspace-user", "user": {"token": token}}],
        "contexts": [{
            "name": "workspace-context",
            "context": {"cluster": "workspace-cluster", "user": "workspace-user"},
        }],
        "current-context": "workspace-context",
    }
    return yaml.safe_dump(config)


async def get_workspace_slack_webhook_url(conn, workspace_id: str) -> Optional[str]:
    """
    Resolves this workspace's stored Slack webhook URL (migration 037's
    workspace_notification_channels, channel_type='slack') -- the same
    per-workspace Slack connection api/routes/workspace_notifications.py
    lets a customer configure and core/notifications.py's
    notify_incident_channels() already sends platform incident alerts
    through. Agent 09 (Onboarding Buddy)'s post_slack_message reuses this
    rather than a separate credential, since it's the same underlying
    resource (this workspace's Slack) -- added as part of the Settings →
    Policies build's credential-leak fix (agent_09 previously fell back
    to a platform-wide SLACK_WEBHOOK_URL env var).

    Returns None if no enabled Slack channel is configured -- callers
    (agent_09) already handle a missing slack_webhook_url as "post
    unavailable," same as no GITHUB_TOKEN.
    """
    row = await conn.fetchrow(
        "SELECT config_encrypted FROM workspace_notification_channels "
        "WHERE workspace_id = $1 AND channel_type = 'slack' AND enabled = true",
        UUID(workspace_id) if isinstance(workspace_id, str) else workspace_id,
    )
    if not row or not row["config_encrypted"]:
        return None
    config = json.loads(decrypt(row["config_encrypted"]))
    return config.get("webhook_url")


async def build_k8s_credentials(conn, workspace_id: str) -> dict:
    """Fetches and decrypts a workspace's stored Kubernetes cluster
    credentials (migration 025). Separate from build_agent_credentials()
    (not merged into its uniform dict) -- only agents 02/08 touch
    Kubernetes, matching the existing precedent of resolve_k8s_context
    being its own call rather than a build_agent_credentials() key."""
    row = await conn.fetchrow(
        "SELECT k8s_api_url, k8s_token_encrypted, k8s_ca_cert_encrypted FROM workspaces WHERE id = $1",
        UUID(workspace_id) if isinstance(workspace_id, str) else workspace_id,
    )

    credentials: dict[str, Optional[str]] = {"k8s_api_url": None, "k8s_token": None, "k8s_ca_cert": None}
    if not row or not row["k8s_api_url"] or not row["k8s_token_encrypted"]:
        return credentials

    credentials["k8s_api_url"] = row["k8s_api_url"]
    credentials["k8s_token"] = decrypt(row["k8s_token_encrypted"])
    if row["k8s_ca_cert_encrypted"]:
        credentials["k8s_ca_cert"] = decrypt(row["k8s_ca_cert_encrypted"])

    return credentials


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


class AzureDevOpsConnectError(Exception):
    """Raised when a workspace's Azure DevOps PAT can't authenticate against
    its org, or lacks access -- wraps the underlying Azure DevOps error."""


async def verify_azure_devops_pat(org: str, pat: str) -> None:
    """Raises AzureDevOpsConnectError if the PAT can't authenticate against
    `org`. Azure DevOps PATs use HTTP Basic auth with an empty username --
    ref: https://learn.microsoft.com/en-us/azure/devops/integrate/how-to/authorize-with-pat
    One cheap read (list projects) confirms both that the token is valid and
    that it actually has access to this specific org, same verify-then-store
    discipline as verify_role / verify_service_principal above."""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(
                f"{_AZURE_DEVOPS_API}/{org}/_apis/projects?api-version=7.1",
                auth=("", pat),
            )
        except httpx.RequestError as exc:
            raise AzureDevOpsConnectError(f"Could not reach Azure DevOps: {exc}") from exc

    if resp.status_code != 200:
        raise AzureDevOpsConnectError(
            f"Could not verify access to org '{org}' ({resp.status_code}): {resp.text[:200]}"
        )


async def mint_github_app_token(conn, installation_id: str) -> str:
    """Fresh ~1hr installation token for `installation_id`, using the
    platform's single GitHub App identity (github_app_config, migration 023).
    Raises GitHubAppError if the App hasn't been registered yet."""
    app_row = await conn.fetchrow(
        "SELECT app_id, private_key_encrypted FROM github_app_config WHERE id = 'singleton'"
    )
    if not app_row:
        raise GitHubAppError("GitHub App not registered yet -- POST /internal/github-app/register first")

    private_key_pem = decrypt(app_row["private_key_encrypted"])
    return await mint_installation_token(app_row["app_id"], private_key_pem, installation_id)


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

    github_token: GitHub App installations (github_app_installation_id) take
    priority over a legacy stored PAT (github_pat_encrypted) -- as of the
    item 4 GitHub App migration, PATs are a read-only legacy fallback for
    whatever workspace connected before the App existed; nothing new is
    ever stored there. A fresh installation token is minted per call, same
    discipline as AWS role assumption / Azure token minting below -- never
    cached beyond the request.

    azure_devops_token: a workspace's stored Azure DevOps PAT (migration 024),
    decrypted per-call same as every other credential here. Distinct from
    azure_access_token -- that's an ARM bearer token from an Azure Service
    Principal (agents 05/06/08's cloud-resource path); this is a Personal
    Access Token scoped to one Azure DevOps org's repos (agent 01's
    CI/CD-triage-for-Azure-DevOps path, CICDTools.azure_token; agents
    04/08/10's core.repo_tools.get_repo_tools() provider selection, Phase 2).

    azure_devops_org: returned alongside azure_devops_token -- unlike GitHub
    (a token alone is enough to address any repo the App/PAT can reach),
    Azure DevOps addresses a repo as org/project/repo, and the org isn't
    derivable from the PAT itself. get_repo_tools() needs both together to
    construct an AzureDevOpsRepoTools.
    """
    row = await conn.fetchrow(
        "SELECT github_pat_encrypted, github_app_installation_id, aws_role_arn, aws_external_id, "
        "azure_tenant_id, azure_client_id, azure_client_secret_encrypted, "
        "azure_subscription_id, azure_devops_pat_encrypted, azure_devops_org "
        "FROM workspaces WHERE id = $1",
        UUID(workspace_id) if isinstance(workspace_id, str) else workspace_id,
    )

    credentials: dict[str, Optional[object]] = {
        "github_token": None,
        "aws_session": None,
        "azure_access_token": None,
        "azure_devops_token": None,
        "azure_devops_org": None,
    }
    if not row:
        return credentials

    if row["github_app_installation_id"]:
        credentials["github_token"] = await mint_github_app_token(conn, row["github_app_installation_id"])
    elif row["github_pat_encrypted"]:
        credentials["github_token"] = decrypt(row["github_pat_encrypted"])

    if row["aws_role_arn"] and row["aws_external_id"]:
        credentials["aws_session"] = assume_role_session(row["aws_role_arn"], row["aws_external_id"])

    if row["azure_tenant_id"] and row["azure_client_id"] and row["azure_client_secret_encrypted"]:
        credentials["azure_access_token"] = await get_azure_bearer_token(
            row["azure_tenant_id"],
            row["azure_client_id"],
            decrypt(row["azure_client_secret_encrypted"]),
        )

    if row["azure_devops_pat_encrypted"]:
        credentials["azure_devops_token"] = decrypt(row["azure_devops_pat_encrypted"])
        credentials["azure_devops_org"] = row["azure_devops_org"]

    return credentials
