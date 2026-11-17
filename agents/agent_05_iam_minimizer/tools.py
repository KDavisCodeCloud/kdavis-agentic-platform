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

from core.cloud_errors import classify_aws_client_error, raise_if_azure_permission_error
from core.pr_branch import pr_branch_name
from core.option_catalog import OptionSpec, catalog_dict, not_available_result

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
    # Managed identity detection (Phase 3, 2026-09-14) — always safe, no approval needed
    # ──────────────────────────────────────────────

    async def list_azure_managed_identities(self, subscription_id: str) -> dict:
        """
        List every user-assigned managed identity in an Azure subscription.
        System-assigned identities are tied 1:1 to the resource that hosts
        them and can't outlive it, so they're out of scope for "orphaned
        identity" detection the way a standalone user-assigned identity
        can be -- created, attached to a VM/App Service, then left behind
        after that resource is deleted or repointed at a different
        identity.
        Ref: https://learn.microsoft.com/en-us/rest/api/managedidentity/user-assigned-identities/list-by-subscription

        Returns {"status": "ok", "identities": [{"id", "name",
        "principal_id", "resource_group"}, ...]} or {"error": ...}.
        """
        if not self.azure_access_token:
            return {"error": "AZURE_ACCESS_TOKEN not configured for this workspace"}

        url = (
            f"{_ARM_API}/subscriptions/{subscription_id}"
            f"/providers/Microsoft.ManagedIdentity/userAssignedIdentities?api-version=2023-01-31"
        )
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(url, headers=_azure_headers(self.azure_access_token))
            except httpx.RequestError as exc:
                return {"error": f"Could not reach Azure Managed Identity API: {exc}"}

        if resp.status_code != 200:
            return {"error": f"Could not list managed identities ({resp.status_code}): {resp.text[:300]}"}

        identities = []
        for item in resp.json().get("value", []):
            props = item.get("properties", {})
            identities.append({
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "principal_id": props.get("principalId", ""),
                "resource_group": _resource_group_from_id(item.get("id", "")),
            })
        return {"status": "ok", "identities": identities}

    async def detect_orphaned_managed_identities(self, subscription_id: str) -> dict:
        """
        Cross-references every user-assigned managed identity in the
        subscription against its role assignments (reusing
        get_azure_role_assignments) and flags any identity with zero
        assignments at all -- created, possibly once wired up, now doing
        nothing. An orphaned identity is a live credential no IaC
        definition, and no one, is tracking the blast radius of.

        Returns {"status": "ok", "checked": N, "orphaned": [{"id", "name",
        "principal_id", "resource_group"}, ...]} or {"error": ...}.
        """
        listed = await self.list_azure_managed_identities(subscription_id)
        if "error" in listed:
            return listed

        orphaned = []
        for identity in listed["identities"]:
            principal_id = identity.get("principal_id", "")
            if not principal_id:
                continue
            assignments = await self.get_azure_role_assignments(subscription_id, principal_id)
            if not assignments:
                orphaned.append(identity)

        return {"status": "ok", "checked": len(listed["identities"]), "orphaned": orphaned}

    async def detect_overpermissive_managed_identities(
        self, subscription_id: str, expected_role_definition_ids: dict,
    ) -> dict:
        """
        For every user-assigned managed identity in the subscription,
        compares its ACTUAL role assignments against the roles its IaC
        definition says it should have (expected_role_definition_ids,
        keyed by principal_id -- e.g. built from a Terraform/Bicep
        azurerm_role_assignment / Microsoft.Authorization/roleAssignments
        resource list). Flags any identity holding a role assignment not
        present in its expected set as broader-than-defined.

        Identities with no entry in expected_role_definition_ids are
        SKIPPED, not flagged -- this check is scoped to identities the
        caller actually has an IaC definition for. Use
        detect_orphaned_managed_identities for identities with no IaC
        definition and no role assignments at all.

        Returns {"status": "ok", "checked": N, "overpermissive": [{"id",
        "name", "principal_id", "resource_group",
        "extra_role_definition_ids": [...]}, ...]} or {"error": ...}.
        """
        listed = await self.list_azure_managed_identities(subscription_id)
        if "error" in listed:
            return listed

        overpermissive = []
        checked = 0
        for identity in listed["identities"]:
            principal_id = identity.get("principal_id", "")
            if principal_id not in expected_role_definition_ids:
                continue
            checked += 1
            expected = set(expected_role_definition_ids[principal_id])
            assignments = await self.get_azure_role_assignments(subscription_id, principal_id)
            actual = {a.get("properties", {}).get("roleDefinitionId", "") for a in assignments}
            actual.discard("")
            extra = actual - expected
            if extra:
                overpermissive.append({**identity, "extra_role_definition_ids": sorted(extra)})

        return {"status": "ok", "checked": checked, "overpermissive": overpermissive}

    async def list_aws_instance_profile_roles(self) -> dict:
        """
        Lists every EC2 IAM instance profile and the role(s) attached to
        it -- AWS equivalent of a managed identity, Phase 3.
        Ref: https://docs.aws.amazon.com/IAM/latest/APIReference/API_ListInstanceProfiles.html

        Returns {"status": "ok", "instance_profiles": [{"name", "arn",
        "role_names": [...]}, ...]} or {"error": ...}.
        """
        if not self.aws_session:
            return {"error": "AWS role not connected for this workspace"}

        iam = self.aws_session.client("iam")
        profiles = []
        try:
            paginator = iam.get_paginator("list_instance_profiles")
            for page in paginator.paginate():
                for profile in page.get("InstanceProfiles", []):
                    profiles.append({
                        "name": profile.get("InstanceProfileName", ""),
                        "arn": profile.get("Arn", ""),
                        "role_names": [r.get("RoleName", "") for r in profile.get("Roles", [])],
                    })
        except ClientError as exc:
            return {"error": f"Could not list EC2 instance profiles: {exc}"}

        return {"status": "ok", "instance_profiles": profiles}

    async def list_lambda_execution_roles(self) -> dict:
        """
        Lists every Lambda function's execution role ARN, deduplicated by
        role -- the serverless-compute equivalent of a managed identity,
        Phase 3.
        Ref: https://docs.aws.amazon.com/lambda/latest/api/API_ListFunctions.html

        Returns {"status": "ok", "execution_roles": [{"role_arn",
        "function_names": [...]}, ...]} or {"error": ...}.
        """
        if not self.aws_session:
            return {"error": "AWS role not connected for this workspace"}

        lambda_client = self.aws_session.client("lambda")
        roles: dict = {}
        try:
            paginator = lambda_client.get_paginator("list_functions")
            for page in paginator.paginate():
                for fn in page.get("Functions", []):
                    role_arn = fn.get("Role", "")
                    if not role_arn:
                        continue
                    roles.setdefault(role_arn, []).append(fn.get("FunctionName", ""))
        except ClientError as exc:
            return {"error": f"Could not list Lambda functions: {exc}"}

        return {
            "status": "ok",
            "execution_roles": [{"role_arn": arn, "function_names": names} for arn, names in roles.items()],
        }

    async def detect_overpermissive_aws_roles(
        self, role_arns: list, expected_actions: dict,
    ) -> dict:
        """
        For each given IAM role ARN (sourced from
        list_aws_instance_profile_roles / list_lambda_execution_roles),
        fetches its attached-managed-policy actions plus inline-policy
        actions (reusing _summarize_permissions, the same flattening this
        file already uses for policy-minimization diagnosis) and compares
        against the actions its IaC definition says it should have
        (expected_actions, keyed by role name). Flags any role holding an
        action not present in its expected set as broader-than-defined --
        the AWS equivalent of detect_overpermissive_managed_identities.

        Roles with no entry in expected_actions are SKIPPED, not flagged
        -- scoped to roles the caller actually has an IaC definition for.

        Returns {"status": "ok", "checked": N, "overpermissive":
        [{"role_name", "role_arn", "extra_actions": [...]}, ...]} or
        {"error": ...}.
        """
        if not self.aws_session:
            return {"error": "AWS role not connected for this workspace"}

        iam = self.aws_session.client("iam")
        overpermissive = []
        checked = 0

        for role_arn in role_arns:
            role_name = role_arn.split("/")[-1]
            if role_name not in expected_actions:
                continue
            checked += 1
            expected = {a.lower() for a in expected_actions[role_name]}

            try:
                actual: set = set()
                attached = iam.list_attached_role_policies(RoleName=role_name)["AttachedPolicies"]
                for pol in attached:
                    versions = iam.list_policy_versions(PolicyArn=pol["PolicyArn"])["Versions"]
                    version_id = next(v["VersionId"] for v in versions if v["IsDefaultVersion"])
                    doc = iam.get_policy_version(
                        PolicyArn=pol["PolicyArn"], VersionId=version_id
                    )["PolicyVersion"]["Document"]
                    if isinstance(doc, str):
                        from urllib.parse import unquote
                        doc = json.loads(unquote(doc))
                    actual |= set(_summarize_permissions(doc))

                for policy_name in iam.list_role_policies(RoleName=role_name)["PolicyNames"]:
                    inline_doc = iam.get_role_policy(RoleName=role_name, PolicyName=policy_name)["PolicyDocument"]
                    actual |= set(_summarize_permissions(inline_doc))
            except ClientError as exc:
                return {"error": f"Could not fetch policies for role {role_name}: {exc}"}

            extra = actual - expected
            if extra:
                overpermissive.append({"role_name": role_name, "role_arn": role_arn, "extra_actions": sorted(extra)})

        return {"status": "ok", "checked": checked, "overpermissive": overpermissive}

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
                permission_error = classify_aws_client_error(exc, "iam:CreatePolicyVersion")
                if permission_error:
                    raise permission_error from exc
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

    async def list_flagged_azure_assignments(self, subscription_id: str, principal_id: str) -> list[dict]:
        """
        The identity's live assignments that opt_1 would delete: a privileged
        built-in role (Owner, Contributor, User Access Administrator, RBAC
        Administrator) at the subscription scope itself. Read-only. Computed at
        diagnose time so the approval card can list each one by id.
        """
        if not self.azure_access_token:
            raise EnvironmentError("AZURE_ACCESS_TOKEN not configured for this workspace")
        sub = _subscription_guid(subscription_id)
        if not sub or not principal_id:
            raise ValueError("subscription_id and principal_id are required to list role assignments")
        sub_scope = f"/subscriptions/{sub}"
        async with httpx.AsyncClient(timeout=30) as client:
            current = await _list_azure_assignments(client, _azure_headers(self.azure_access_token),
                                                    sub_scope, principal_id)
        return flag_overprivileged_azure_assignments(current, sub_scope)

    async def remove_flagged_azure_assignments(
        self,
        subscription_id: str,
        principal_id: str,
        keep: list[dict],
        remove: list[dict],
    ) -> dict:
        """
        Break-It Lab G5, narrowed per Kelvin 2026-11-17: create the minimized
        assignment(s), then delete ONLY the assignments listed on the approval
        card (`remove`, from list_flagged_azure_assignments at diagnose time).
        Every other assignment the identity holds is left untouched.

          1. Resolve each keep entry {"role", "scope"}; refuse if one of them is
             itself a flagged (privileged, subscription-scope) assignment.
          2. Create each keep assignment that doesn't already exist.
          3. Only after 1-2 succeed, delete each `remove` id that is still
             present AND still privileged at subscription scope. An id that is
             gone or whose role/scope no longer matches is reported, not deleted.

        Raises (nothing deleted) if keep or remove is empty or keep can't be resolved.
        Ref: https://learn.microsoft.com/en-us/rest/api/authorization/role-assignments
        """
        if not self.azure_access_token:
            raise EnvironmentError("AZURE_ACCESS_TOKEN not configured for this workspace")
        sub = _subscription_guid(subscription_id)
        if not sub or not principal_id:
            raise ValueError("subscription_id and principal_id are required to change role assignments")
        if not keep:
            raise ValueError(
                "The analysis did not produce a minimized role assignment set (role + scope); "
                "nothing was created or removed"
            )
        remove_ids = {str(r.get("id", "")).lower() for r in remove or [] if r.get("id")}
        if not remove_ids:
            raise ValueError("No over-privileged assignment was flagged for removal; nothing was changed")

        sub_scope = f"/subscriptions/{sub}"
        headers = _azure_headers(self.azure_access_token)
        api = {"api-version": "2022-04-01"}

        async with httpx.AsyncClient(timeout=30) as client:
            # 1. resolve the keep set
            wanted: list[tuple[str, str]] = []  # (roleDefinitionId, scope)
            for entry in keep:
                scope = str(entry.get("scope", "")).rstrip("/")
                if not scope.lower().startswith(sub_scope.lower()):
                    raise ValueError(f"keep scope {scope!r} is not inside {sub_scope}; nothing was changed")
                role_def = await _resolve_azure_role(client, headers, sub_scope, str(entry.get("role", "")))
                if _is_flagged(role_def, scope, sub_scope):
                    raise ValueError(
                        f"the minimized set still contains {_role_label(role_def)} at the subscription scope; "
                        "nothing was changed"
                    )
                wanted.append((role_def, scope))

            current = await _list_azure_assignments(client, headers, sub_scope, principal_id)

            # 2. create what's missing
            created, kept_existing = [], []
            for role_def, scope in wanted:
                match = next((a for a in current if _same_role(a["roleDefinitionId"], role_def)
                              and a["scope"].rstrip("/").lower() == scope.lower()), None)
                if match:
                    kept_existing.append(match["id"])
                    continue
                import uuid as _uuid
                url = f"{_ARM_API}{scope}/providers/Microsoft.Authorization/roleAssignments/{_uuid.uuid4()}"
                resp = await client.put(url, params=api, headers=headers, json={
                    "properties": {"roleDefinitionId": role_def, "principalId": principal_id},
                })
                if resp.status_code not in (200, 201):
                    raise_if_azure_permission_error(resp.status_code, resp.text,
                                                    "Microsoft.Authorization/roleAssignments/write")
                    raise RuntimeError(f"Azure role assignment create error {resp.status_code}: {resp.text[:200]}; "
                                       "nothing was removed")
                created.append(resp.json().get("id", url.replace(_ARM_API, "")))

            # 3. delete exactly the flagged ids that are still flagged
            by_id = {a["id"].lower(): a for a in current}
            removed, already_gone, changed = [], [], []
            for rid in sorted(remove_ids):
                a = by_id.get(rid)
                if a is None:
                    already_gone.append(rid)
                    continue
                if not _is_flagged(a["roleDefinitionId"], a["scope"], sub_scope):
                    changed.append(a["id"])
                    continue
                resp = await client.delete(f"{_ARM_API}{a['id']}", params=api, headers=headers)
                if resp.status_code not in (200, 204):
                    raise_if_azure_permission_error(resp.status_code, resp.text,
                                                    "Microsoft.Authorization/roleAssignments/delete")
                    raise RuntimeError(
                        f"Azure role assignment delete error {resp.status_code} on {a['id']}: {resp.text[:200]} "
                        f"(created={created}, removed so far={removed})"
                    )
                removed.append(a["id"])
            untouched = [a["id"] for a in current if a["id"] not in removed]

        log.info("[IAMTools] Azure flagged assignments for %s: created=%d kept=%d removed=%d gone=%d changed=%d",
                 principal_id, len(created), len(kept_existing), len(removed), len(already_gone), len(changed))
        return {
            "status": "assignments_removed" if (removed or created) else "no_change",
            "cloud": "azure",
            "principal_id": principal_id,
            "created": created,
            "kept_existing": kept_existing,
            "removed": removed,
            "already_gone": already_gone,
            "not_removed_changed_since_analysis": changed,
            "untouched": untouched,
        }

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
        branch_name: str,
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
        Run the approved option. Only ids in option_catalog(context) run, and
        each runs exactly the calls its catalog entry declares.

        context: cloud_provider, policy_arn / subscription_id / principal_id /
        resource, minimized_policy (dict), minimized_policy_str, azure_remove
        (the flagged assignments listed on the card), owner, repo,
        file_path, pr_title, pr_body
        """
        option_id = option.get("id", "")
        cloud = context.get("cloud_provider", "aws")
        catalog = option_catalog(context)

        log.info("[IAMTools] Executing approved option '%s' for cloud=%s", option_id, cloud)

        if option_id == "hold":
            return {"status": "held", "message": "Operator chose to apply policy changes manually"}
        if option_id not in catalog:
            return not_available_result(option_id, catalog)

        if option_id == "opt_1":
            minimized = context.get("minimized_policy", {})
            if cloud == "aws":
                return await self.apply_aws_policy(
                    policy_arn=context["policy_arn"],
                    minimized_document=minimized,
                )
            if cloud == "azure":
                return await self.remove_flagged_azure_assignments(
                    subscription_id=context.get("subscription_id", ""),
                    principal_id=context["principal_id"],
                    keep=azure_keep_set(minimized),
                    remove=context.get("azure_remove") or [],
                )
            return await self.apply_gcp_iam_binding(
                resource=context["resource"],
                resource_type=context.get("resource_type", "projects"),
                policy=minimized,
            )

        # opt_2
        return await self.create_policy_pr(
            owner=context.get("owner", ""),
            repo=context.get("repo", ""),
            file_path=context.get("file_path", "iam/minimized_policy.json"),
            new_content=context.get("minimized_policy_str", "{}"),
            pr_title=context.get("pr_title", "security(iam): apply minimized policy"),
            pr_body=context.get("pr_body", ""),
            branch_name=pr_branch_name("iam-minimize", context.get("incident_id")),
            base_branch=context.get("base_branch", "main"),
        )


def option_catalog(context: dict) -> dict[str, OptionSpec]:
    """What Agent 05 can actually do, per cloud."""
    cloud = context.get("cloud_provider", "aws")
    if cloud == "azure":
        # G5 (narrowed): offered only when diagnose found privileged assignments to remove,
        # and the card names each one. No "replace everything" option — see DECISIONS.md.
        flagged = context.get("azure_remove") or []
        opt_1 = OptionSpec(
            "opt_1", "Remove the over-privileged role assignment(s)",
            "Creates the minimized role assignment(s) from this analysis if they don't already exist, then "
            "deletes exactly these assignments and nothing else:\n"
            + "\n".join(f"• {f['role']} at {f['scope']} (assignment {f['id']})" for f in flagged)
            + "\nEvery other assignment this identity holds is left untouched. Nothing is deleted if the "
            "create step fails; an assignment whose role or scope changed since this analysis is skipped.",
            "high", ("remove_flagged_azure_assignments",),
        ) if flagged else None
    elif cloud in ("gcp", "google"):
        opt_1 = OptionSpec(
            "opt_1", "Replace the project IAM policy with the minimized policy",
            "Calls setIamPolicy with the minimized policy, replacing the resource's entire IAM policy.",
            "high", ("apply_gcp_iam_binding",),
        )
    elif cloud == "aws":
        opt_1 = OptionSpec(
            "opt_1", "Apply the minimized policy as a new default version",
            "Creates a new version of the customer-managed IAM policy with the minimized document and makes it "
            "the default. Previous versions are kept, so it can be rolled back.",
            "high", ("apply_aws_policy",),
        )
    else:
        opt_1 = None  # no direct-apply code for this cloud
    return catalog_dict(
        *([opt_1] if opt_1 else []),
        OptionSpec(
            "opt_2", "Open a PR with the minimized policy",
            "Commits the minimized policy document to a new branch and opens a pull request. No live change.",
            "low", ("create_policy_pr",), proposal=True,
        ),
    )


def azure_keep_set(minimized: dict | str | None) -> list[dict]:
    """
    The minimized Azure assignment set as [{"role": name-or-id, "scope": ARM scope}].
    Accepts {"role_assignments": [...]} (the format the diagnose request asks
    for) or a single {"roleDefinitionId"/"role", "scope"} object.
    """
    if isinstance(minimized, str):
        try:
            minimized = json.loads(minimized)
        except (json.JSONDecodeError, ValueError):
            return []
    if not isinstance(minimized, dict):
        return []
    entries = minimized.get("role_assignments") or minimized.get("roleAssignments")
    if entries is None:
        entries = [minimized]
    out = []
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            continue
        role = (e.get("role") or e.get("role_definition_id") or e.get("roleDefinitionId")
                or e.get("role_definition_name") or e.get("roleDefinitionName") or e.get("roleName") or "")
        scope = e.get("scope") or ""
        if role and scope:
            out.append({"role": str(role), "scope": str(scope)})
    return out


# Built-in roles that grant write or access management over everything at their scope.
# Role definition GUIDs are fixed across tenants.
# Ref: https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles
_AZURE_PRIVILEGED_ROLES = {
    "8e3af657-a8ff-443c-a75c-2fe8c4bcb635": "Owner",
    "b24988ac-6180-42a0-ab63-f8f86f70ec4b": "Contributor",
    "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9": "User Access Administrator",
    "f58310d9-a9f6-439a-9e8d-f62e7b41a168": "Role Based Access Control Administrator",
}


def _role_guid(role_definition_id: str) -> str:
    return role_definition_id.rstrip("/").split("/")[-1].lower()


def _role_label(role_definition_id: str) -> str:
    return _AZURE_PRIVILEGED_ROLES.get(_role_guid(role_definition_id), _role_guid(role_definition_id))


def _is_flagged(role_definition_id: str, scope: str, sub_scope: str) -> bool:
    """A privileged built-in role assigned at the subscription scope itself."""
    return (_role_guid(role_definition_id) in _AZURE_PRIVILEGED_ROLES
            and scope.rstrip("/").lower() == sub_scope.rstrip("/").lower())


def flag_overprivileged_azure_assignments(assignments: list[dict], sub_scope: str) -> list[dict]:
    """[{"id", "role", "scope"}] for each assignment opt_1 would delete."""
    return [
        {"id": a["id"], "role": _role_label(a["roleDefinitionId"]), "scope": a["scope"]}
        for a in assignments
        if _is_flagged(a["roleDefinitionId"], a["scope"], sub_scope)
    ]


def _subscription_guid(value: str) -> str:
    v = (value or "").strip().strip("/")
    if v.lower().startswith("subscriptions/"):
        v = v.split("/")[1]
    return v


def _same_role(a: str, b: str) -> bool:
    return a.rstrip("/").split("/")[-1].lower() == b.rstrip("/").split("/")[-1].lower()


async def _resolve_azure_role(client, headers: dict, sub_scope: str, role: str) -> str:
    """A roleDefinitionId for a role name or id; raises if it can't be resolved."""
    if not role:
        raise ValueError("keep entry has no role; nothing was changed")
    if "/roleDefinitions/" in role:
        return f"{sub_scope}/providers/Microsoft.Authorization/roleDefinitions/{role.rstrip('/').split('/')[-1]}"
    resp = await client.get(
        f"{_ARM_API}{sub_scope}/providers/Microsoft.Authorization/roleDefinitions",
        params={"api-version": "2022-04-01", "$filter": f"roleName eq '{role}'"}, headers=headers,
    )
    if resp.status_code != 200:
        raise_if_azure_permission_error(resp.status_code, resp.text, "Microsoft.Authorization/roleDefinitions/read")
        raise RuntimeError(f"Azure role definition lookup error {resp.status_code}: {resp.text[:200]}")
    found = resp.json().get("value", [])
    if not found:
        raise ValueError(f"Azure role {role!r} not found; nothing was changed")
    return found[0]["id"]


async def _list_azure_assignments(client, headers: dict, sub_scope: str, principal_id: str) -> list[dict]:
    resp = await client.get(
        f"{_ARM_API}{sub_scope}/providers/Microsoft.Authorization/roleAssignments",
        params={"api-version": "2022-04-01", "$filter": f"principalId eq '{principal_id}'"}, headers=headers,
    )
    if resp.status_code != 200:
        raise_if_azure_permission_error(resp.status_code, resp.text, "Microsoft.Authorization/roleAssignments/read")
        raise RuntimeError(f"Azure role assignment list error {resp.status_code}: {resp.text[:200]}")
    return [
        {"id": a["id"], "scope": a["properties"]["scope"], "roleDefinitionId": a["properties"]["roleDefinitionId"]}
        for a in resp.json().get("value", [])
        if a.get("properties", {}).get("principalId", principal_id) == principal_id
    ]


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


def _resource_group_from_id(resource_id: str) -> str:
    """
    Extracts the resource group name from a full ARM resource id
    (.../resourceGroups/<name>/...) -- used by
    list_azure_managed_identities so callers don't have to re-parse it.
    Returns "" if the id doesn't contain a resourceGroups segment.
    """
    parts = resource_id.split("/")
    for i, part in enumerate(parts):
        if part.lower() == "resourcegroups" and i + 1 < len(parts):
            return parts[i + 1]
    return ""
