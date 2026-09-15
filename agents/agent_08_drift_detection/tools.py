"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Agent 08 — Drift Detection & Auto-Correction execution tools.

All write operations execute ONLY after operator approval via POST /incidents/{id}/approve.
No correction is applied autonomously. Governance Rule 11.

Supported drift sources:
  terraform      — Terraform state file / HCL configuration
  kubernetes     — K8s manifest vs live resource state
  cloudformation — CloudFormation template vs deployed stack
  arm_bicep      — ARM/Bicep template vs deployed resource (same generic
                   JSON-diff path as terraform/cloudformation)
  generic        — any two JSON/YAML blobs

Domain coverage (all use the generic desired/actual-state diff path except
where a dedicated fetch helper exists): IAM/RBAC/Policy, Networking,
Storage, Compute. Dedicated live-state fetchers exist for: Azure App
Service content/config (fetch_app_service_state), S3 + Azure Blob storage
security config (fetch_s3_bucket_state, fetch_azure_blob_storage_state --
Phase 1, site-audit gap closure), and AWS Security Group + Azure NSG +
AWS/Azure route tables (fetch_security_group_state, fetch_nsg_state,
fetch_route_table_state, fetch_azure_route_table_state -- Phase 2).
Database-as-a-service resources are out of scope. GCP: payload shape
only, no collection built (see sop.md).

Correction options:
  opt_1 — Create Remediation PR (for all drift sources — goes through code review)
  opt_2 — Apply directly: kubectl apply for K8s; create PR for Terraform/CF (safer for IaC)
  opt_3 — Create drift-tracking issue only (no correction)
  hold  — No automated action
"""

import asyncio
import json
import logging
import shlex
import tempfile
from typing import Optional

import httpx
from botocore.exceptions import ClientError

from core.repo_tools import RepoTools, get_repo_tools
from core.workspace_credentials import build_kubeconfig

log = logging.getLogger(__name__)

_GH_API               = "https://api.github.com"
_ARM_API              = "https://management.azure.com"
_MAX_KUBECTL_TIMEOUT  = 120
_MAX_HTTP_TIMEOUT     = 30

# Shared between fetch_security_group_state (AWS) and fetch_nsg_state
# (Azure) -- the highest-value management/DB ports to flag when exposed
# to the open internet (0.0.0.0/0, ::/0, or Azure's "*"/"Internet"/"Any").
_SENSITIVE_PORTS = {
    22:    "SSH",
    3389:  "RDP",
    3306:  "MySQL",
    5432:  "PostgreSQL",
    6379:  "Redis",
    9200:  "Elasticsearch",
    27017: "MongoDB",
    5601:  "Kibana",
}


class DriftTools:
    """
    Post-approval correction tools for Agent 08.
    Read-only helpers (fetch_k8s_resource) may run during ingest.
    Write helpers (apply, create_drift_pr) execute only post-HITL.
    """

    def __init__(
        self,
        github_token: Optional[str] = None,
        allow_kubectl: bool = True,
        aws_session=None,
        azure_access_token: Optional[str] = None,
        k8s_context: Optional[str] = None,
        azure_devops_token: Optional[str] = None,
        azure_devops_org: Optional[str] = None,
        k8s_api_url: Optional[str] = None,
        k8s_token: Optional[str] = None,
        k8s_ca_cert: Optional[str] = None,
    ):
        # No env-var fallback for github_token/aws_session -- per-workspace
        # now (core/workspace_credentials.py).
        self.github_token       = github_token or ""
        self.allow_kubectl      = allow_kubectl
        self.aws_session        = aws_session
        # ARM bearer token -- minted fresh per call by
        # core.workspace_credentials.build_agent_credentials(), never cached
        # or re-derived here, same discipline as every other credential in
        # this class. Used by fetch_app_service_state() (Phase B, App
        # Service content/config drift).
        self.azure_access_token = azure_access_token or ""
        self.azure_devops_token = azure_devops_token or ""
        self.azure_devops_org   = azure_devops_org or ""
        # Which kubeconfig context to target -- the global-KUBECONFIG_YAML
        # stopgap (core.workspace_credentials.resolve_k8s_context). Without
        # this, kubectl silently uses KUBECONFIG's current-context for every
        # cluster regardless of which one an incident is actually about --
        # found live: an AKS incident's "apply directly" reported
        # exit_code=0 "unchanged" because it had applied against EKS (the
        # kubeconfig's default context) the whole time, doing nothing to the
        # actually-broken pod.
        self.k8s_context   = k8s_context
        # Real per-workspace cluster credentials (Phase 4, migration 025) --
        # take priority over the global stopgap above when present. Built
        # once here, written to a temp kubeconfig lazily on first kubectl
        # call (not every DriftTools construction needs one).
        self._kubeconfig_content = (
            build_kubeconfig(k8s_api_url, k8s_token, k8s_ca_cert) if k8s_api_url and k8s_token else None
        )
        self._kubeconfig_path: Optional[str] = None

    def _repo_tools(self) -> RepoTools:
        """Provider selection (Phase 2) -- GitHub or Azure DevOps, whichever
        this workspace has connected. See core.repo_tools.get_repo_tools."""
        return get_repo_tools(
            github_token=self.github_token,
            azure_devops_token=self.azure_devops_token,
            azure_devops_org=self.azure_devops_org,
        )

    @property
    def _cluster_flag(self) -> str:
        """--kubeconfig <per-workspace file> when this workspace has its own
        cluster credentials (Phase 4); otherwise --context <name> against
        the platform's global KUBECONFIG_YAML stopgap; otherwise nothing
        (kubectl's own default, only ever true for local dev)."""
        if self._kubeconfig_content:
            if not self._kubeconfig_path:
                with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                    f.write(self._kubeconfig_content)
                    self._kubeconfig_path = f.name
            return f" --kubeconfig {self._kubeconfig_path}"
        if self.k8s_context:
            return f" --context {self.k8s_context}"
        return ""

    # ──────────────────────────────────────────────
    # Optional state fetchers (pre-HITL, read-only)
    # ──────────────────────────────────────────────

    async def fetch_k8s_resource(
        self,
        resource_type: str,
        name: str,
        namespace: str = "default",
    ) -> dict:
        """
        Fetch live K8s resource state via kubectl get -o json.
        Returns the parsed JSON object, or {"error": ...} on failure.
        """
        if not self.allow_kubectl:
            return {"error": "kubectl disabled for this workspace"}

        cmd = f"kubectl{self._cluster_flag} get {resource_type} {name} -n {namespace} -o json"
        try:
            proc = await asyncio.create_subprocess_exec(
                *shlex.split(cmd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=30
            )
        except asyncio.TimeoutError:
            return {"error": "kubectl get timed out after 30s"}
        except (OSError, ValueError) as exc:
            return {"error": str(exc)}

        if proc.returncode != 0:
            return {"error": stderr_bytes.decode(errors="replace").strip()[:500]}

        try:
            return json.loads(stdout_bytes)
        except json.JSONDecodeError as exc:
            return {"error": f"kubectl returned invalid JSON: {exc}"}

    async def fetch_cloudformation_stack(self, stack_name: str) -> dict:
        """
        Fetch CloudFormation stack resource summary via a real boto3 call,
        using this workspace's assumed-role session.
        Returns {"resources": [...], "status": "ok"} or {"error": ...}.
        """
        if not self.aws_session:
            return {"error": "AWS role not connected for this workspace"}

        cfn = self.aws_session.client("cloudformation")
        try:
            resources = cfn.describe_stack_resources(StackName=stack_name)["StackResources"]
            return {"resources": resources, "status": "ok"}
        except ClientError as exc:
            return {"error": str(exc)}

    async def fetch_app_service_state(
        self, app_name: str, resource_group: str, subscription_id: str,
    ) -> dict:
        """
        Fetch an Azure App Service's live app settings (ARM API) and
        deployed file listing (Kudu VFS API), for the Phase B "App Service
        content/config drift" check -- missing uploaded files, wrong app
        settings, bad JSON, expected-vs-actual file paths, all fall out of
        comparing this against a desired_state built from the connected
        repo's build output.

        Both calls use the same ARM bearer token
        (core.workspace_credentials.get_azure_bearer_token) -- Kudu accepts
        Azure AD tokens issued for the ARM resource the same App Service's
        portal/CLI access uses. This is documented Azure behavior but has
        not been live-verified against a real App Service in this
        codebase yet; if it 403s in practice, the fallback is Kudu's own
        Basic Auth (publish-profile credentials), which would need a
        different credential shape than what's stored today.

        Returns {"app_settings": {...}, "files": [...], "status": "ok"} or
        {"error": ...}.
        """
        if not self.azure_access_token:
            return {"error": "Azure Service Principal not connected for this workspace"}

        headers = {"Authorization": f"Bearer {self.azure_access_token}"}
        arm_base = (
            f"https://management.azure.com/subscriptions/{subscription_id}"
            f"/resourceGroups/{resource_group}/providers/Microsoft.Web/sites/{app_name}"
        )

        async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
            try:
                settings_resp = await client.post(
                    f"{arm_base}/config/appsettings/list?api-version=2022-03-01",
                    headers=headers,
                )
                files_resp = await client.get(
                    f"https://{app_name}.scm.azurewebsites.net/api/vfs/site/wwwroot/",
                    headers=headers,
                )
            except httpx.RequestError as exc:
                return {"error": f"Could not reach Azure App Service APIs: {exc}"}

        if settings_resp.status_code != 200:
            return {"error": f"Could not fetch app settings ({settings_resp.status_code}): {settings_resp.text[:300]}"}
        if files_resp.status_code != 200:
            return {"error": f"Could not fetch deployed file listing ({files_resp.status_code}): {files_resp.text[:300]}"}

        return {
            "app_settings": settings_resp.json().get("properties", {}),
            "files": [
                {"name": f.get("name"), "size": f.get("size"), "mtime": f.get("mtime")}
                for f in files_resp.json()
            ],
            "status": "ok",
        }

    async def fetch_s3_bucket_state(self, bucket_name: str) -> dict:
        """
        Fetch an S3 bucket's live security configuration for the Phase 1
        storage-drift check -- versioning, default encryption, Public
        Access Block, bucket policy (flagged for public/wildcard-principal
        statements), and cross-region replication. Same read-only,
        error-dict-on-failure shape as fetch_cloudformation_stack() above.

        Encryption / Public Access Block / policy / replication are each
        independently optional on S3 -- a bucket with none configured
        returns a specific ClientError code (NotFound / NotConfigured),
        not a real failure. Only a ClientError with a DIFFERENT code (bad
        credentials, bucket doesn't exist, etc.) is treated as fatal.

        Returns {"status": "ok", "bucket_name": ..., "versioning": {...},
        "encryption": {...} | None, "public_access_block": {...} | None,
        "policy": {...} | None, "replication": {"status": ...},
        "findings": [...]} or {"error": ...}.
        """
        if not self.aws_session:
            return {"error": "AWS role not connected for this workspace"}

        s3 = self.aws_session.client("s3")
        findings: list[str] = []

        try:
            versioning_resp = s3.get_bucket_versioning(Bucket=bucket_name)
        except ClientError as exc:
            return {"error": f"Could not fetch bucket versioning for {bucket_name}: {exc}"}
        versioning_status = versioning_resp.get("Status", "Disabled")
        if versioning_status != "Enabled":
            findings.append(f"Versioning is not enabled (status={versioning_status})")

        try:
            encryption = s3.get_bucket_encryption(Bucket=bucket_name).get("ServerSideEncryptionConfiguration")
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ServerSideEncryptionConfigurationNotFoundError":
                return {"error": f"Could not fetch bucket encryption for {bucket_name}: {exc}"}
            encryption = None
        if encryption is None:
            findings.append("No default server-side encryption configured")

        try:
            pab = s3.get_public_access_block(Bucket=bucket_name).get("PublicAccessBlockConfiguration")
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "NoSuchPublicAccessBlockConfiguration":
                return {"error": f"Could not fetch Public Access Block for {bucket_name}: {exc}"}
            pab = None
        if pab is None:
            findings.append("No Public Access Block configuration -- bucket may be publicly reachable")
        elif not all(pab.get(k, False) for k in (
            "BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"
        )):
            findings.append("Public Access Block configured but not fully locked down")

        try:
            policy_resp = s3.get_bucket_policy(Bucket=bucket_name)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "NoSuchBucketPolicy":
                return {"error": f"Could not fetch bucket policy for {bucket_name}: {exc}"}
            policy_resp = None
        policy_document = None
        if policy_resp:
            try:
                policy_document = json.loads(policy_resp.get("Policy", "{}"))
            except json.JSONDecodeError:
                policy_document = {}
            if _s3_policy_allows_public_access(policy_document):
                findings.append("Bucket policy contains a statement allowing public (wildcard principal) access")

        try:
            s3.get_bucket_replication(Bucket=bucket_name)
            replication_status = "configured"
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ReplicationConfigurationNotFoundError":
                return {"error": f"Could not fetch bucket replication for {bucket_name}: {exc}"}
            replication_status = "not_configured"

        return {
            "status": "ok",
            "bucket_name": bucket_name,
            "versioning": {"status": versioning_status},
            "encryption": encryption,
            "public_access_block": pab,
            "policy": policy_document,
            "replication": {"status": replication_status},
            "findings": findings,
        }

    async def fetch_azure_blob_storage_state(
        self, storage_account_name: str, resource_group: str, subscription_id: str,
    ) -> dict:
        """
        Fetch an Azure Storage account's live blob-security configuration
        for the Phase 1 storage-drift check -- encryption-at-rest, public
        network access / blob public access, soft delete (blob service
        delete retention policy), and replication SKU
        (LRS/ZRS/GRS/RA-GRS). Two ARM REST calls, same bearer-token /
        error-dict-on-failure shape as fetch_app_service_state() above:
        the storage account resource itself (encryption, public access,
        SKU) and its blob service sub-resource (soft delete).

        Returns {"status": "ok", "storage_account_name": ...,
        "encryption": {...}, "public_network_access": str,
        "allow_blob_public_access": bool, "soft_delete": {...},
        "replication_sku": str, "findings": [...]} or {"error": ...}.
        """
        if not self.azure_access_token:
            return {"error": "Azure Service Principal not connected for this workspace"}

        headers = {"Authorization": f"Bearer {self.azure_access_token}"}
        account_url = (
            f"{_ARM_API}/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Storage/storageAccounts/{storage_account_name}?api-version=2023-01-01"
        )
        blob_service_url = (
            f"{_ARM_API}/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Storage/storageAccounts/{storage_account_name}"
            f"/blobServices/default?api-version=2023-01-01"
        )

        async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
            try:
                account_resp = await client.get(account_url, headers=headers)
                blob_resp = await client.get(blob_service_url, headers=headers)
            except httpx.RequestError as exc:
                return {"error": f"Could not reach Azure Storage APIs: {exc}"}

        if account_resp.status_code != 200:
            return {"error": f"Could not fetch storage account ({account_resp.status_code}): {account_resp.text[:300]}"}
        if blob_resp.status_code != 200:
            return {"error": f"Could not fetch blob service properties ({blob_resp.status_code}): {blob_resp.text[:300]}"}

        account = account_resp.json()
        properties = account.get("properties", {})
        blob_properties = blob_resp.json().get("properties", {})

        encryption = properties.get("encryption", {})
        public_network_access = properties.get("publicNetworkAccess", "Enabled")
        allow_blob_public_access = properties.get("allowBlobPublicAccess", True)
        soft_delete = blob_properties.get("deleteRetentionPolicy", {})
        replication_sku = account.get("sku", {}).get("name", "unknown")

        findings: list[str] = []
        if not encryption.get("services", {}).get("blob", {}).get("enabled", False):
            findings.append("Blob service encryption at rest is not enabled")
        if public_network_access != "Disabled":
            findings.append(f"Public network access is not disabled (publicNetworkAccess={public_network_access})")
        if allow_blob_public_access:
            findings.append("allowBlobPublicAccess is true -- anonymous container/blob access is possible")
        if not soft_delete.get("enabled", False):
            findings.append("Soft delete is not enabled for blob service")
        if replication_sku in ("Standard_LRS", "Premium_LRS"):
            findings.append(f"Replication SKU is {replication_sku} -- no geo-redundancy configured")

        return {
            "status": "ok",
            "storage_account_name": storage_account_name,
            "encryption": encryption,
            "public_network_access": public_network_access,
            "allow_blob_public_access": allow_blob_public_access,
            "soft_delete": soft_delete,
            "replication_sku": replication_sku,
            "findings": findings,
        }

    async def fetch_security_group_state(self, group_id: str) -> dict:
        """
        Fetch an AWS Security Group's live inbound/outbound rules for the
        Phase 2 networking-drift check. Flags any rule exposing a
        sensitive management/DB port (see _SENSITIVE_PORTS) to an
        overpermissive CIDR (0.0.0.0/0 or ::/0) -- the highest-value,
        most commonly misconfigured networking pattern.

        Returns {"status": "ok", "group_id": ..., "group_name": ...,
        "ip_permissions": [...], "ip_permissions_egress": [...],
        "findings": [...]} or {"error": ...}.
        """
        if not self.aws_session:
            return {"error": "AWS role not connected for this workspace"}

        ec2 = self.aws_session.client("ec2")
        try:
            resp = ec2.describe_security_groups(GroupIds=[group_id])
        except ClientError as exc:
            return {"error": f"Could not fetch security group {group_id}: {exc}"}

        groups = resp.get("SecurityGroups", [])
        if not groups:
            return {"error": f"Security group {group_id} not found"}
        group = groups[0]

        return {
            "status": "ok",
            "group_id": group_id,
            "group_name": group.get("GroupName", ""),
            "ip_permissions": group.get("IpPermissions", []),
            "ip_permissions_egress": group.get("IpPermissionsEgress", []),
            "findings": _find_overpermissive_sg_rules(group.get("IpPermissions", [])),
        }

    async def fetch_route_table_state(self, route_table_id: str) -> dict:
        """
        Fetch an AWS VPC route table's live routes for networking-drift
        comparison against the Terraform/CloudFormation definition --
        Phase 2 expansion once Security Group checks are live-verified.

        Returns {"status": "ok", "route_table_id": ..., "routes": [...]}
        or {"error": ...}.
        """
        if not self.aws_session:
            return {"error": "AWS role not connected for this workspace"}

        ec2 = self.aws_session.client("ec2")
        try:
            resp = ec2.describe_route_tables(RouteTableIds=[route_table_id])
        except ClientError as exc:
            return {"error": f"Could not fetch route table {route_table_id}: {exc}"}

        tables = resp.get("RouteTables", [])
        if not tables:
            return {"error": f"Route table {route_table_id} not found"}

        return {
            "status": "ok",
            "route_table_id": route_table_id,
            "routes": tables[0].get("Routes", []),
        }

    async def fetch_nsg_state(
        self, nsg_name: str, resource_group: str, subscription_id: str,
    ) -> dict:
        """
        Fetch an Azure Network Security Group's live security rules for
        the Phase 2 networking-drift check. Evaluates EFFECTIVE exposure,
        not each rule in isolation: sorts inbound rules by priority
        ascending (Azure evaluates lower-priority-number rules first and
        stops at the first match) and flags a sensitive management/DB
        port only when the FIRST matching rule for an open source
        ("*"/"Internet"/"Any") is an Allow -- matching the real-world
        checks in this product's own azure-nsg-misconfiguration blog
        post: rule priority evaluation, RDP/SSH open to Any, management
        ports on production resources.

        Returns {"status": "ok", "nsg_name": ..., "security_rules": [...],
        "findings": [...]} or {"error": ...}.
        """
        if not self.azure_access_token:
            return {"error": "Azure Service Principal not connected for this workspace"}

        headers = {"Authorization": f"Bearer {self.azure_access_token}"}
        url = (
            f"{_ARM_API}/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Network/networkSecurityGroups/{nsg_name}?api-version=2023-05-01"
        )

        async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
            try:
                resp = await client.get(url, headers=headers)
            except httpx.RequestError as exc:
                return {"error": f"Could not reach Azure Network API: {exc}"}

        if resp.status_code != 200:
            return {"error": f"Could not fetch NSG {nsg_name} ({resp.status_code}): {resp.text[:300]}"}

        rules = resp.json().get("properties", {}).get("securityRules", [])

        return {
            "status": "ok",
            "nsg_name": nsg_name,
            "security_rules": rules,
            "findings": _find_overpermissive_nsg_rules(rules),
        }

    async def fetch_azure_route_table_state(
        self, route_table_name: str, resource_group: str, subscription_id: str,
    ) -> dict:
        """
        Fetch an Azure route table's live routes for networking-drift
        comparison -- the Azure equivalent of fetch_route_table_state()
        above, Phase 2 expansion.

        Returns {"status": "ok", "route_table_name": ..., "routes": [...]}
        or {"error": ...}.
        """
        if not self.azure_access_token:
            return {"error": "Azure Service Principal not connected for this workspace"}

        headers = {"Authorization": f"Bearer {self.azure_access_token}"}
        url = (
            f"{_ARM_API}/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Network/routeTables/{route_table_name}?api-version=2023-05-01"
        )

        async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
            try:
                resp = await client.get(url, headers=headers)
            except httpx.RequestError as exc:
                return {"error": f"Could not reach Azure Network API: {exc}"}

        if resp.status_code != 200:
            return {"error": f"Could not fetch route table {route_table_name} ({resp.status_code}): {resp.text[:300]}"}

        return {
            "status": "ok",
            "route_table_name": route_table_name,
            "routes": resp.json().get("properties", {}).get("routes", []),
        }

    # ──────────────────────────────────────────────
    # Correction tools (post-HITL only)
    # ──────────────────────────────────────────────

    async def _run_kubectl(self, cmd: str, manifest_yaml: str) -> dict:
        try:
            proc = await asyncio.create_subprocess_exec(
                *shlex.split(cmd),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=manifest_yaml.encode()),
                timeout=_MAX_KUBECTL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return {"status": "failed", "exit_code": None, "stdout": "", "stderr": f"timed out after {_MAX_KUBECTL_TIMEOUT}s"}
        except (OSError, ValueError) as exc:
            return {"status": "failed", "exit_code": None, "stdout": "", "stderr": str(exc)}

        stdout = stdout_bytes.decode(errors="replace").strip()
        stderr = stderr_bytes.decode(errors="replace").strip()
        ok = proc.returncode == 0
        return {
            "status": "ok" if ok else "failed",
            "exit_code": proc.returncode,
            "stdout": stdout[:2000],
            "stderr": stderr[:500],
        }

    async def apply_k8s_manifest(
        self,
        manifest_yaml: str,
        namespace: str = "default",
    ) -> dict:
        """
        Apply a Kubernetes manifest to restore desired state.
        Pipes manifest YAML via stdin — NEVER shell=True.
        """
        if not self.allow_kubectl:
            return {"status": "skipped", "reason": "kubectl disabled for this workspace"}

        log.info("[DriftTools] Applying K8s manifest to namespace=%s context=%s", namespace, self.k8s_context or "(default)")
        result = await self._run_kubectl(f"kubectl{self._cluster_flag} apply -f - -n {namespace}", manifest_yaml)

        if result["status"] == "ok":
            log.info("[DriftTools] kubectl apply exit_code=0 stdout=%s", result["stdout"])
            return result

        # Most Pod spec fields (command, env, image only excepted) are
        # immutable once a Pod is created -- confirmed live against a real
        # EKS cluster, the API server rejects the patch with exactly this
        # message. `kubectl apply --force` (delete+recreate in one client
        # call) timed out on Fargate because pod deprovisioning outlives
        # kubectl's internal wait, so do the two steps explicitly instead,
        # with our own bounded --timeout on the delete.
        if "pod updates may not change fields" in result["stderr"]:
            log.warning("[DriftTools] Pod spec change rejected as immutable -- deleting and recreating")
            delete_result = await self._run_kubectl(
                f"kubectl{self._cluster_flag} delete -f - -n {namespace} --wait=true --timeout={_MAX_KUBECTL_TIMEOUT}s",
                manifest_yaml,
            )
            if delete_result["status"] != "ok":
                log.warning("[DriftTools] kubectl delete (immutable-field fallback) exit_code=%s stderr=%s",
                            delete_result["exit_code"], delete_result["stderr"])
                return delete_result
            result = await self._run_kubectl(f"kubectl{self._cluster_flag} apply -f - -n {namespace}", manifest_yaml)
            if result["status"] == "ok":
                log.info("[DriftTools] kubectl apply (post-delete recreate) exit_code=0 stdout=%s", result["stdout"])
                return result

        # stderr is the only place the real reason a real apply failed shows
        # up -- execution_result isn't persisted anywhere (see core/hitl.py's
        # mark_executed), so the log line is the only record once this
        # returns. Found live: a bare exit_code with no stderr logged made a
        # real failure undiagnosable after the fact.
        log.warning("[DriftTools] kubectl apply exit_code=%s stderr=%s", result["exit_code"], result["stderr"])
        return result

    async def create_drift_pr(
        self,
        owner: str,
        repo: str,
        branch_name: str,
        file_path: str,
        corrected_content: str,
        pr_body: str,
        base_branch: str = "main",
        pr_title: Optional[str] = None,
    ) -> dict:
        """
        Open a PR with the corrected IaC/manifest content, against whichever
        provider (GitHub or Azure DevOps) this workspace has connected.
        Delegates the 5-step branch/commit/PR flow to core.repo_tools
        (Phase 2) -- this used to be its own direct GitHub implementation;
        that logic is what core.repo_tools.GitHubRepoTools was lifted from.
        """
        repo_tools = self._repo_tools()

        await repo_tools.create_branch(owner, repo, branch_name, base_branch)
        await repo_tools.push_commit(
            owner, repo, branch_name,
            {file_path: corrected_content},
            f"fix(drift): restore {file_path} to desired state [Cloud Decoded Agent 08]",
        )
        title = pr_title or f"fix(drift): restore {file_path} to desired state"
        pr = await repo_tools.create_pr(owner, repo, branch_name, title, pr_body, base=base_branch)

        log.info("[DriftTools] Drift remediation PR created: %s", pr.get("pr_url"))
        return {
            "status": "pr_created",
            "pr_url": pr.get("pr_url", ""),
            "pr_number": pr.get("pr_number"),
            "branch": branch_name,
        }

    async def create_drift_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
    ) -> dict:
        """Create a GitHub issue documenting the detected drift."""
        if not self.github_token:
            raise EnvironmentError("GITHUB_TOKEN not configured for this workspace")

        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels

        async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{_GH_API}/repos/{owner}/{repo}/issues",
                headers=_gh_headers(self.github_token),
                json=payload,
            )

        if resp.status_code not in (200, 201):
            raise RuntimeError(f"GitHub issue error {resp.status_code}: {resp.text[:200]}")

        issue = resp.json()
        log.info("[DriftTools] Drift issue created: %s", issue.get("html_url"))
        return {
            "status": "issue_created",
            "issue_url": issue.get("html_url", ""),
            "issue_number": issue.get("number"),
        }

    # ──────────────────────────────────────────────
    # Routing
    # ──────────────────────────────────────────────

    async def execute_option(self, option: dict, context: dict) -> dict:
        """
        Dispatch to the approved correction action.

        context must include:
          drift_source, resource_id, resource_type, scope,
          corrected_content, desired_state_text, drift_summary,
          owner, repo, file_path, namespace (for K8s)
        """
        option_id = option.get("id", "")
        log.info("[DriftTools] Executing approved option '%s'", option_id)

        if option_id == "hold":
            return {"status": "held", "message": "Operator chose to correct drift manually"}

        drift_source  = context.get("drift_source", "generic")
        owner         = context.get("owner", "")
        repo          = context.get("repo", "")
        resource_id   = context.get("resource_id", "resource")
        report_body   = context.get("report_body", "")

        if option_id == "opt_1":
            # Remediation PR — always safe; goes through code review
            if not owner or not repo:
                return {"status": "skipped", "reason": "repository not configured — cannot create PR"}

            branch_name = f"drift-correction/{resource_id.replace('/', '-').replace(':', '-')}"[:100]
            return await self.create_drift_pr(
                owner=owner,
                repo=repo,
                branch_name=branch_name,
                file_path=context.get("file_path", f"infra/{resource_id}"),
                corrected_content=context.get("corrected_content", ""),
                pr_body=report_body,
            )

        if option_id == "opt_2":
            # Direct application — kubectl for K8s; PR fallback for IaC sources
            if drift_source == "kubernetes":
                manifest = context.get("corrected_content", "")
                namespace = context.get("scope", context.get("namespace", "default"))
                return await self.apply_k8s_manifest(manifest, namespace=namespace)

            # For Terraform/CloudFormation: creating a PR is still the safe path
            # (never run terraform apply or aws cloudformation deploy autonomously)
            if not owner or not repo:
                return {"status": "skipped", "reason": "repository not configured — cannot create correction PR"}

            branch_name = f"drift-auto-fix/{resource_id.replace('/', '-').replace(':', '-')}"[:100]
            return await self.create_drift_pr(
                owner=owner,
                repo=repo,
                branch_name=branch_name,
                file_path=context.get("file_path", f"infra/{resource_id}"),
                corrected_content=context.get("corrected_content", ""),
                pr_body=report_body,
                pr_title=f"fix(drift-auto): restore {resource_id} to desired state",
            )

        if option_id == "opt_3":
            # Create tracking issue only
            if not owner or not repo:
                return {"status": "skipped", "reason": "repository not configured — cannot create issue"}

            return await self.create_drift_issue(
                owner=owner,
                repo=repo,
                title=context.get("issue_title", f"Drift detected: {resource_id}"),
                body=report_body,
                labels=["drift", "infrastructure"],
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


def _s3_policy_allows_public_access(document: dict) -> bool:
    """
    True if any Allow statement's Principal is the wildcard "*" (any AWS
    principal) or includes {"AWS": "*"} -- the same public-bucket-policy
    signal AWS's own S3 console and Access Analyzer surface.
    """
    for stmt in document.get("Statement", []):
        if stmt.get("Effect") != "Allow":
            continue
        principal = stmt.get("Principal")
        if principal == "*":
            return True
        if isinstance(principal, dict):
            aws_principal = principal.get("AWS")
            if aws_principal == "*" or (isinstance(aws_principal, list) and "*" in aws_principal):
                return True
    return False


_OPEN_CIDRS = {"0.0.0.0/0", "::/0"}


def _find_overpermissive_sg_rules(ip_permissions: list) -> list[str]:
    """
    Flags any AWS Security Group inbound rule that opens a sensitive
    management/DB port (_SENSITIVE_PORTS) -- or all ports/protocols
    (IpProtocol "-1") -- to 0.0.0.0/0 or ::/0.
    """
    findings = []
    for perm in ip_permissions:
        from_port = perm.get("FromPort")
        to_port = perm.get("ToPort")
        open_ranges = [r["CidrIp"] for r in perm.get("IpRanges", []) if r.get("CidrIp") in _OPEN_CIDRS]
        open_ranges += [r["CidrIpv6"] for r in perm.get("Ipv6Ranges", []) if r.get("CidrIpv6") in _OPEN_CIDRS]
        if not open_ranges:
            continue
        if perm.get("IpProtocol") == "-1":
            findings.append(f"All traffic (all ports) open to {'/'.join(open_ranges)}")
            continue
        for port, name in _SENSITIVE_PORTS.items():
            if from_port is not None and to_port is not None and from_port <= port <= to_port:
                findings.append(f"{name} (port {port}) open to {'/'.join(open_ranges)}")
    return findings


_OPEN_NSG_SOURCES = {"*", "internet", "any"}


def _nsg_rule_matches_port(props: dict, port: int) -> bool:
    ranges = props.get("destinationPortRanges") or [props.get("destinationPortRange", "")]
    for r in ranges:
        r = str(r)
        if r == "*":
            return True
        if "-" in r:
            lo, hi = r.split("-", 1)
            try:
                if int(lo) <= port <= int(hi):
                    return True
            except ValueError:
                continue
        elif r.isdigit() and int(r) == port:
            return True
    return False


def _nsg_rule_matches_open_source(props: dict) -> bool:
    prefixes = props.get("sourceAddressPrefixes") or [props.get("sourceAddressPrefix", "")]
    return any(str(p).lower() in _OPEN_NSG_SOURCES for p in prefixes)


def _find_overpermissive_nsg_rules(rules: list) -> list[str]:
    """
    Effective-rule evaluation for Azure NSGs: for each sensitive port,
    finds the lowest-priority (first-evaluated) Inbound rule whose port
    range and source together could match traffic from the public
    internet, and flags it only if that first match is an Allow -- a
    lower-priority Deny for the same port/source correctly suppresses the
    finding, matching Azure's real evaluation order (ascending priority,
    first match wins).
    """
    inbound = sorted(
        (r for r in rules if r.get("properties", {}).get("direction") == "Inbound"),
        key=lambda r: r.get("properties", {}).get("priority", 65000),
    )
    findings = []
    for port, name in _SENSITIVE_PORTS.items():
        for rule in inbound:
            props = rule.get("properties", {})
            if not _nsg_rule_matches_port(props, port):
                continue
            if not _nsg_rule_matches_open_source(props):
                continue
            if props.get("access") == "Allow":
                findings.append(
                    f"{name} (port {port}) reachable from the internet via rule "
                    f"'{rule.get('name', '?')}' (priority {props.get('priority')})"
                )
            break  # first match at this port wins, regardless of allow/deny
    return findings
