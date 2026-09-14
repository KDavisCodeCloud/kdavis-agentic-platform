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
  terraform     — Terraform state file / HCL configuration
  kubernetes    — K8s manifest vs live resource state
  cloudformation — CloudFormation template vs deployed stack
  generic       — any two JSON/YAML blobs

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
_MAX_KUBECTL_TIMEOUT  = 120
_MAX_HTTP_TIMEOUT     = 30


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
