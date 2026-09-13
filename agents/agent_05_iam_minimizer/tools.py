"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Agent 05 — IAM Policy Minimization execution tools.

These tools are called ONLY after operator approval via POST /incidents/{id}/approve.
They never execute autonomously. Governance Rule 11.

Supported clouds:
  - AWS  — IAM roles, users, customer-managed policies (real boto3 calls,
    using a per-workspace assumed-role session -- see
    core/workspace_credentials.py)
  - Azure — Azure AD service principals and role assignments (ARM REST API)
  - GCP  — IAM bindings on project/folder/organization resources (out of
    scope for per-workspace credential storage -- still env-var-backed)

Each tool writes the minimized policy or creates a GitHub PR with the policy diff.
Direct cloud mutations (apply_aws_policy, apply_azure_assignment, apply_gcp_binding)
are only called after explicit operator approval at the HITL gate.
"""

import base64
import json
import logging
import os
from typing import Optional

import boto3
import httpx
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)

_GH_API   = "https://api.github.com"
_ARM_API  = "https://management.azure.com"
_GCP_CRM  = "https://cloudresourcemanager.googleapis.com"


class IAMMinimizeTools:
    """
    Post-approval execution tools for Agent 05.

    Reads cloud IAM state (always safe), then applies minimized policies
    only after operator approval.
    """

    def __init__(
        self,
        github_token: Optional[str] = None,
        aws_session: Optional[boto3.Session] = None,
        azure_access_token: Optional[str] = None,
        gcp_access_token: Optional[str] = None,
    ):
        # No env-var fallback for github_token/aws_session/azure_access_token --
        # these are per-workspace now (core/workspace_credentials.py). A missing
        # credential raises a clear error at the specific call that needed it,
        # rather than silently defaulting to a shared server-wide secret. GCP
        # is out of scope for per-workspace storage -- still env-backed.
        self.github_token       = github_token or ""
        self.aws_session        = aws_session
        self.azure_access_token = azure_access_token or ""
        self.gcp_access_token   = gcp_access_token or os.environ.get("GCP_ACCESS_TOKEN", "")

    # ──────────────────────────────────────────────
    # Read — always safe, no approval needed
    # ──────────────────────────────────────────────

    async def get_aws_policy_document(self, policy_arn: str) -> dict:
        """
        Fetch the current policy document for an AWS customer-managed policy.
        Uses the IAM ListPolicyVersions + GetPolicyVersion flow to get the default version.
        Ref: https://docs.aws.amazon.com/IAM/latest/APIReference/API_GetPolicyVersion.html
        """
        if not self.aws_session:
            raise EnvironmentError("AWS role not connected for this workspace")

        from urllib.parse import unquote

        iam = self.aws_session.client("iam")
        try:
            versions = iam.list_policy_versions(PolicyArn=policy_arn)["Versions"]
            version_id = next(v["VersionId"] for v in versions if v["IsDefaultVersion"])
            version = iam.get_policy_version(PolicyArn=policy_arn, VersionId=version_id)
        except ClientError as exc:
            raise RuntimeError(f"AWS IAM error fetching policy {policy_arn}: {exc}") from exc

        document = version["PolicyVersion"]["Document"]
        # boto3 returns the Document as a URL-encoded JSON string, same as the
        # raw REST API -- unlike most boto3 responses, this one isn't pre-parsed.
        if isinstance(document, str):
            document = json.loads(unquote(document))

        return {"policy_arn": policy_arn, "version_id": version_id, "document": document}

    async def get_azure_role_assignments(self, subscription_id: str, principal_id: str) -> list:
        """
        List Azure role assignments for a given service principal within a subscription.
        Ref: https://learn.microsoft.com/en-us/rest/api/authorization/role-assignments/list
        """
        if not self.azure_access_token:
            raise EnvironmentError("AZURE_ACCESS_TOKEN not configured for this workspace")

        url = (
            f"{_ARM_API}/subscriptions/{subscription_id}"
            f"/providers/Microsoft.Authorization/roleAssignments"
            f"?api-version=2022-04-01"
            f"&$filter=principalId eq '{principal_id}'"
        )
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=_azure_headers(self.azure_access_token))

        if resp.status_code != 200:
            raise RuntimeError(f"Azure role assignments error {resp.status_code}: {resp.text[:200]}")

        return resp.json().get("value", [])

    async def get_gcp_iam_policy(self, resource: str, resource_type: str = "projects") -> dict:
        """
        Get the IAM policy for a GCP project, folder, or organization.
        resource: project ID, folder ID (folders/12345), or org ID (organizations/12345)
        Ref: https://cloud.google.com/resource-manager/reference/rest/v3/projects/getIamPolicy
        """
        if not self.gcp_access_token:
            raise EnvironmentError("GCP_ACCESS_TOKEN not configured for this workspace")

        url = f"{_GCP_CRM}/v3/{resource_type}/{resource}:getIamPolicy"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                headers=_gcp_headers(self.gcp_access_token),
                json={"options": {"requestedPolicyVersion": 3}},
            )

        if resp.status_code != 200:
            raise RuntimeError(f"GCP getIamPolicy error {resp.status_code}: {resp.text[:200]}")

        return resp.json()

    # ──────────────────────────────────────────────
    # Write — post-approval only
    # ──────────────────────────────────────────────

    async def apply_aws_policy(
        self,
        policy_arn: str,
        minimized_document: dict,
    ) -> dict:
        """
        Create a new policy version with the minimized document and set it as default.
        Deletes the oldest non-default version if already at 5-version limit.
        Ref: https://docs.aws.amazon.com/IAM/latest/APIReference/API_CreatePolicyVersion.html
        """
        if not self.aws_session:
            raise EnvironmentError("AWS role not connected for this workspace")

        iam = self.aws_session.client("iam")
        doc_str = json.dumps(minimized_document)

        try:
            result = iam.create_policy_version(
                PolicyArn=policy_arn, PolicyDocument=doc_str, SetAsDefault=True
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "LimitExceeded":
                raise RuntimeError(f"AWS CreatePolicyVersion error for {policy_arn}: {exc}") from exc
            # IAM allows at most 5 versions per policy -- delete the oldest
            # non-default version and retry, matching this method's own
            # documented behavior.
            versions = iam.list_policy_versions(PolicyArn=policy_arn)["Versions"]
            oldest = min(
                (v for v in versions if not v["IsDefaultVersion"]),
                key=lambda v: v["CreateDate"],
            )
            iam.delete_policy_version(PolicyArn=policy_arn, VersionId=oldest["VersionId"])
            result = iam.create_policy_version(
                PolicyArn=policy_arn, PolicyDocument=doc_str, SetAsDefault=True
            )

        version_id = result["PolicyVersion"]["VersionId"]
        log.info("[IAMTools] AWS policy %s updated — new version %s", policy_arn, version_id)
        return {
            "status": "policy_updated",
            "policy_arn": policy_arn,
            "new_version_id": version_id,
            "cloud": "aws",
        }

    async def apply_azure_role_assignment(
        self,
        subscription_id: str,
        principal_id: str,
        role_definition_id: str,
        scope: str,
    ) -> dict:
        """
        Create a new (minimized) Azure role assignment.
        The caller is responsible for removing the over-privileged assignment separately.
        Ref: https://learn.microsoft.com/en-us/rest/api/authorization/role-assignments/create
        """
        if not self.azure_access_token:
            raise EnvironmentError("AZURE_ACCESS_TOKEN not configured for this workspace")

        import uuid as _uuid
        assignment_name = str(_uuid.uuid4())
        url = f"{_ARM_API}{scope}/providers/Microsoft.Authorization/roleAssignments/{assignment_name}?api-version=2022-04-01"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.put(
                url,
                headers=_azure_headers(self.azure_access_token),
                json={
                    "properties": {
                        "roleDefinitionId": role_definition_id,
                        "principalId": principal_id,
                    }
                },
            )

        if resp.status_code in (200, 201):
            log.info("[IAMTools] Azure role assignment created: %s", assignment_name)
            return {
                "status": "assignment_created",
                "assignment_id": assignment_name,
                "principal_id": principal_id,
                "cloud": "azure",
            }

        raise RuntimeError(f"Azure role assignment error {resp.status_code}: {resp.text[:200]}")

    async def apply_gcp_iam_binding(
        self,
        resource: str,
        resource_type: str,
        policy: dict,
    ) -> dict:
        """
        Set the IAM policy for a GCP resource (replaces the entire policy).
        The caller should pass the minimized policy returned by the LLM.
        Ref: https://cloud.google.com/resource-manager/reference/rest/v3/projects/setIamPolicy
        """
        if not self.gcp_access_token:
            raise EnvironmentError("GCP_ACCESS_TOKEN not configured for this workspace")

        url = f"{_GCP_CRM}/v3/{resource_type}/{resource}:setIamPolicy"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                headers=_gcp_headers(self.gcp_access_token),
                json={"policy": policy},
            )

        if resp.status_code == 200:
            log.info("[IAMTools] GCP IAM policy set for %s/%s", resource_type, resource)
            return {
                "status": "policy_set",
                "resource": resource,
                "resource_type": resource_type,
                "cloud": "gcp",
            }

        raise RuntimeError(f"GCP setIamPolicy error {resp.status_code}: {resp.text[:200]}")

    async def create_policy_pr(
        self,
        owner: str,
        repo: str,
        file_path: str,
        new_content: str,
        pr_title: str,
        pr_body: str,
        base_branch: str = "main",
    ) -> dict:
        """
        Open a GitHub PR with the minimized IAM policy as a JSON/YAML file.
        Uses the same 5-step GitHub API flow as Agents 03 and 04.
        """
        if not self.github_token:
            raise EnvironmentError("GITHUB_TOKEN not configured for this workspace")

        headers = _gh_headers(self.github_token)

        # 1. Get HEAD SHA of base branch
        async with httpx.AsyncClient(timeout=30) as client:
            ref_resp = await client.get(
                f"{_GH_API}/repos/{owner}/{repo}/git/ref/heads/{base_branch}",
                headers=headers,
            )

        if ref_resp.status_code != 200:
            raise RuntimeError(f"GitHub get ref error {ref_resp.status_code}: {ref_resp.text[:200]}")

        base_sha = ref_resp.json()["object"]["sha"]

        # 2. Create feature branch
        branch_name = f"cloud-decoded/iam-minimize-{_short_id()}"
        async with httpx.AsyncClient(timeout=30) as client:
            branch_resp = await client.post(
                f"{_GH_API}/repos/{owner}/{repo}/git/refs",
                headers=headers,
                json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
            )

        if branch_resp.status_code not in (200, 201):
            raise RuntimeError(f"GitHub create branch error {branch_resp.status_code}: {branch_resp.text[:200]}")

        # 3. Get current file SHA
        file_url = f"{_GH_API}/repos/{owner}/{repo}/contents/{file_path}"
        async with httpx.AsyncClient(timeout=30) as client:
            file_resp = await client.get(file_url, headers=headers, params={"ref": base_branch})

        file_sha = file_resp.json().get("sha") if file_resp.status_code == 200 else None

        # 4. Commit minimized policy file
        put_payload = {
            "message": f"security(iam): minimize policy — {pr_title}",
            "content": base64.b64encode(new_content.encode()).decode(),
            "branch": branch_name,
        }
        if file_sha:
            put_payload["sha"] = file_sha

        async with httpx.AsyncClient(timeout=30) as client:
            put_resp = await client.put(file_url, headers=headers, json=put_payload)

        if put_resp.status_code not in (200, 201):
            raise RuntimeError(f"GitHub commit file error {put_resp.status_code}: {put_resp.text[:200]}")

        # 5. Open PR
        async with httpx.AsyncClient(timeout=30) as client:
            pr_resp = await client.post(
                f"{_GH_API}/repos/{owner}/{repo}/pulls",
                headers=headers,
                json={
                    "title": pr_title,
                    "body": pr_body,
                    "head": branch_name,
                    "base": base_branch,
                },
            )

        if pr_resp.status_code in (200, 201):
            pr_data = pr_resp.json()
            log.info("[IAMTools] Policy PR opened: %s", pr_data.get("html_url"))
            return {
                "status": "pr_opened",
                "pr_url": pr_data.get("html_url", ""),
                "pr_number": pr_data.get("number"),
                "branch": branch_name,
            }

        raise RuntimeError(f"GitHub PR error {pr_resp.status_code}: {pr_resp.text[:200]}")

    # ──────────────────────────────────────────────
    # Routing
    # ──────────────────────────────────────────────

    async def execute_option(self, option: dict, context: dict) -> dict:
        """
        Dispatch to the correct post-approval action.

        context must include:
          cloud_provider, principal_id / policy_arn / resource,
          minimized_policy (dict or str), minimized_policy_str (JSON string),
          owner, repo, file_path, pr_title, pr_body
        """
        option_id = option.get("id", "")
        cloud = context.get("cloud_provider", "aws")

        log.info("[IAMTools] Executing approved option '%s' for cloud=%s", option_id, cloud)

        if option_id == "hold":
            return {"status": "held", "message": "Operator chose to apply policy changes manually"}

        if option_id == "opt_1":
            # Apply minimized policy directly to the cloud provider
            minimized = context.get("minimized_policy", {})

            if cloud == "aws":
                return await self.apply_aws_policy(
                    policy_arn=context["policy_arn"],
                    minimized_document=minimized,
                )

            if cloud == "azure":
                return await self.apply_azure_role_assignment(
                    subscription_id=context["subscription_id"],
                    principal_id=context["principal_id"],
                    role_definition_id=context["role_definition_id"],
                    scope=context.get("scope", f"/subscriptions/{context['subscription_id']}"),
                )

            if cloud in ("gcp", "google"):
                return await self.apply_gcp_iam_binding(
                    resource=context["resource"],
                    resource_type=context.get("resource_type", "projects"),
                    policy=minimized,
                )

            return {"status": "not_implemented", "cloud": cloud, "reason": "Unsupported cloud provider for direct apply"}

        if option_id == "opt_2":
            # Create a GitHub PR with the policy diff as a file
            return await self.create_policy_pr(
                owner=context.get("owner", ""),
                repo=context.get("repo", ""),
                file_path=context.get("file_path", "iam/minimized_policy.json"),
                new_content=context.get("minimized_policy_str", "{}"),
                pr_title=context.get("pr_title", "security(iam): apply minimized policy"),
                pr_body=context.get("pr_body", ""),
                base_branch=context.get("base_branch", "main"),
            )

        return {"status": "not_implemented", "option_id": option_id}


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _azure_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _gcp_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _short_id() -> str:
    import uuid
    return str(uuid.uuid4())[:8]


def _summarize_permissions(policy_document: dict) -> list[str]:
    """
    Flatten all Action values from an IAM policy document into a sorted list.
    Handles both string and list Action values, and multiple Statement blocks.
    """
    actions = []
    for stmt in policy_document.get("Statement", []):
        action = stmt.get("Action", [])
        if isinstance(action, str):
            action = [action]
        actions.extend(action)
    return sorted(set(a.lower() for a in actions))
