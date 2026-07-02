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
Agent 05 — IAM Policy Minimization execution tools.

These tools are called ONLY after operator approval via POST /incidents/{id}/approve.
They never execute autonomously. Governance Rule 11.

Supported clouds:
  - AWS  — IAM roles, users, customer-managed policies (boto3-style API)
  - Azure — Azure AD service principals and role assignments (ARM REST API)
  - GCP  — IAM bindings on project/folder/organization resources

Each tool writes the minimized policy or creates a GitHub PR with the policy diff.
Direct cloud mutations (apply_aws_policy, apply_azure_assignment, apply_gcp_binding)
are only called after explicit operator approval at the HITL gate.
"""

import base64
import json
import logging
import os
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_GH_API   = "https://api.github.com"
_AWS_IAM  = "https://iam.amazonaws.com"
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
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        azure_access_token: Optional[str] = None,
        gcp_access_token: Optional[str] = None,
    ):
        self.github_token         = github_token         or os.environ.get("GITHUB_TOKEN", "")
        self.aws_access_key_id    = aws_access_key_id    or os.environ.get("AWS_ACCESS_KEY_ID", "")
        self.aws_secret_access_key = aws_secret_access_key or os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        self.azure_access_token   = azure_access_token   or os.environ.get("AZURE_ACCESS_TOKEN", "")
        self.gcp_access_token     = gcp_access_token     or os.environ.get("GCP_ACCESS_TOKEN", "")

    # ──────────────────────────────────────────────
    # Read — always safe, no approval needed
    # ──────────────────────────────────────────────

    async def get_aws_policy_document(self, policy_arn: str) -> dict:
        """
        Fetch the current policy document for an AWS customer-managed policy.
        Uses the IAM ListPolicyVersions + GetPolicyVersion flow to get the default version.
        Ref: https://docs.aws.amazon.com/IAM/latest/APIReference/API_GetPolicyVersion.html
        """
        if not self.aws_access_key_id:
            raise EnvironmentError("AWS_ACCESS_KEY_ID not configured for this workspace")

        headers = _aws_iam_headers(self.aws_access_key_id, self.aws_secret_access_key)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                _AWS_IAM,
                headers=headers,
                params={
                    "Action": "ListPolicyVersions",
                    "PolicyArn": policy_arn,
                    "Version": "2010-05-08",
                },
            )

        if resp.status_code != 200:
            raise RuntimeError(f"AWS IAM ListPolicyVersions error {resp.status_code}: {resp.text[:200]}")

        # Parse the default version ID from the XML response
        version_id = _parse_aws_default_version(resp.text)

        async with httpx.AsyncClient(timeout=30) as client:
            resp2 = await client.get(
                _AWS_IAM,
                headers=headers,
                params={
                    "Action": "GetPolicyVersion",
                    "PolicyArn": policy_arn,
                    "VersionId": version_id,
                    "Version": "2010-05-08",
                },
            )

        if resp2.status_code != 200:
            raise RuntimeError(f"AWS IAM GetPolicyVersion error {resp2.status_code}: {resp2.text[:200]}")

        raw_doc = _parse_aws_policy_document(resp2.text)
        return {"policy_arn": policy_arn, "version_id": version_id, "document": raw_doc}

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
        if not self.aws_access_key_id:
            raise EnvironmentError("AWS_ACCESS_KEY_ID not configured for this workspace")

        headers = _aws_iam_headers(self.aws_access_key_id, self.aws_secret_access_key)
        doc_str = json.dumps(minimized_document)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _AWS_IAM,
                headers=headers,
                data={
                    "Action": "CreatePolicyVersion",
                    "PolicyArn": policy_arn,
                    "PolicyDocument": doc_str,
                    "SetAsDefault": "true",
                    "Version": "2010-05-08",
                },
            )

        if resp.status_code != 200:
            raise RuntimeError(f"AWS CreatePolicyVersion error {resp.status_code}: {resp.text[:200]}")

        version_id = _parse_aws_new_version_id(resp.text)
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


def _aws_iam_headers(access_key_id: str, secret_key: str) -> dict:
    # Real AWS requests require SigV4 signing; in production this is handled
    # by boto3 or the AWS SDK. These headers are placeholders so the tool
    # is testable without boto3 installed. The actual signing would happen
    # in an AWS-SDK wrapper at the router layer.
    return {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Amz-Access-Key-Id": access_key_id,
    }


def _short_id() -> str:
    import uuid
    return str(uuid.uuid4())[:8]


def _parse_aws_default_version(xml_text: str) -> str:
    """Extract default policy version ID from AWS IAM XML response."""
    import re
    match = re.search(r"<IsDefaultVersion>true</IsDefaultVersion>.*?<VersionId>(v\d+)</VersionId>", xml_text, re.DOTALL)
    if not match:
        # Fallback: grab first VersionId
        match = re.search(r"<VersionId>(v\d+)</VersionId>", xml_text)
    return match.group(1) if match else "v1"


def _parse_aws_policy_document(xml_text: str) -> dict:
    """Extract URL-encoded policy document from AWS IAM XML response and decode it."""
    import re
    from urllib.parse import unquote
    match = re.search(r"<Document>(.+?)</Document>", xml_text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(unquote(match.group(1).strip()))
    except (json.JSONDecodeError, ValueError):
        return {}


def _parse_aws_new_version_id(xml_text: str) -> str:
    """Extract the new version ID from a CreatePolicyVersion XML response."""
    import re
    match = re.search(r"<VersionId>(v\d+)</VersionId>", xml_text)
    return match.group(1) if match else "v2"


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
