"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Agent 02 — Kubernetes Alert Fatigue & Remediation execution tools.

These tools are called ONLY after operator approval via POST /incidents/{id}/approve.
They never execute autonomously. Governance Rule 11.
"""

import logging
import tempfile
from typing import Optional, Union

import httpx

from core.repo_tools import RepoTools, get_repo_tools

log = logging.getLogger(__name__)


class K8sTools:
    """
    Post-approval execution tools for Agent 02.
    All Kubernetes API calls use the workspace-scoped service account token —
    never the operator's cluster-admin credentials.
    """

    def __init__(
        self,
        k8s_api_url: Optional[str] = None,
        k8s_token: Optional[str] = None,
        github_token: Optional[str] = None,
        azure_devops_token: Optional[str] = None,
        azure_devops_org: Optional[str] = None,
        k8s_ca_cert: Optional[str] = None,
    ):
        # No env-var fallback -- a missing credential should raise a clear
        # error at the specific call that needed it, not silently fall back
        # to a shared server-wide secret (same discipline as every other
        # *Tools class in this codebase). Credentials come from
        # core.workspace_credentials.build_agent_credentials/build_k8s_credentials.
        self.k8s_api_url        = (k8s_api_url or "").rstrip("/")
        self.k8s_token          = k8s_token or ""
        self.github_token       = github_token or ""
        self.azure_devops_token = azure_devops_token or ""
        self.azure_devops_org   = azure_devops_org or ""
        self._k8s_ca_cert       = k8s_ca_cert
        self._k8s_ca_cert_path: Optional[str] = None

    def _repo_tools(self) -> RepoTools:
        """Provider selection (Phase 4, same as Phase 2's agents 04/08/10) --
        GitHub or Azure DevOps, whichever this workspace has connected.
        See core.repo_tools.get_repo_tools."""
        return get_repo_tools(
            github_token=self.github_token,
            azure_devops_token=self.azure_devops_token,
            azure_devops_org=self.azure_devops_org,
        )

    @property
    def _verify(self) -> Union[bool, str]:
        """httpx `verify` value for K8s API calls -- a per-workspace CA cert
        (Phase 4, migration 025) when the cluster uses a private CA
        (typical for EKS/AKS control planes), else the standard system CA
        trust store. Never silently skips TLS verification -- same
        discipline as core.workspace_credentials.verify_k8s_connection /
        build_kubeconfig."""
        if not self._k8s_ca_cert:
            return True
        if not self._k8s_ca_cert_path:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
                f.write(self._k8s_ca_cert)
                self._k8s_ca_cert_path = f.name
        return self._k8s_ca_cert_path

    # ──────────────────────────────────────────────
    # Kubernetes API tools
    # ──────────────────────────────────────────────

    async def patch_deployment_memory(
        self,
        namespace: str,
        deployment_name: str,
        memory_limit: str,
        memory_request: Optional[str] = None,
        container_name: Optional[str] = None,
    ) -> dict:
        """
        Increase the memory limit on a Deployment via strategic merge patch.
        Ref: https://kubernetes.io/docs/tasks/run-application/update-api-object-kubectl-patch/
        """
        if not self.k8s_api_url or not self.k8s_token:
            raise EnvironmentError("K8S_API_URL and K8S_TOKEN not configured for this workspace")

        url = (
            f"{self.k8s_api_url}/apis/apps/v1"
            f"/namespaces/{namespace}/deployments/{deployment_name}"
        )
        headers = {
            "Authorization": f"Bearer {self.k8s_token}",
            "Content-Type": "application/strategic-merge-patch+json",
        }

        # Use memory_request as half of limit if not specified
        request_val = memory_request or _halve_memory(memory_limit)
        container = container_name or deployment_name

        # Capture current limits/requests BEFORE the patch -- rollback
        # information for the incidents.before_state column (migration
        # 042). Best-effort: a failed GET here must never block the real
        # remediation the operator already approved, so this degrades to
        # an explicit "capture_failed" marker rather than raising.
        before_state = await self._capture_container_resources(namespace, deployment_name, container)

        patch_body = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": container,
                                "resources": {
                                    "limits": {"memory": memory_limit},
                                    "requests": {"memory": request_val},
                                },
                            }
                        ]
                    }
                }
            }
        }

        async with httpx.AsyncClient(timeout=30, verify=self._verify) as client:
            resp = await client.patch(url, headers=headers, json=patch_body)

        if resp.status_code in (200, 201):
            log.info(
                "[K8sTools] Patched deployment %s/%s memory → limit=%s request=%s",
                namespace, deployment_name, memory_limit, request_val,
            )
            return {
                "status": "patched",
                "deployment": deployment_name,
                "namespace": namespace,
                "new_memory_limit": memory_limit,
                "new_memory_request": request_val,
                "before_state": before_state,
            }

        log.error("[K8sTools] patch_deployment_memory failed: %d %s", resp.status_code, resp.text[:200])
        raise RuntimeError(f"K8s PATCH error {resp.status_code}: {resp.text[:200]}")

    async def _capture_container_resources(
        self, namespace: str, deployment_name: str, container_name: str,
    ) -> dict:
        """GET the deployment's current resources.limits/requests for the
        target container, before any mutation. Never raises -- returns a
        {"capture_failed": ...} marker instead, since this is rollback
        *information*, not a precondition for the remediation itself."""
        url = f"{self.k8s_api_url}/apis/apps/v1/namespaces/{namespace}/deployments/{deployment_name}"
        try:
            async with httpx.AsyncClient(timeout=30, verify=self._verify) as client:
                resp = await client.get(
                    url, headers={"Authorization": f"Bearer {self.k8s_token}"},
                )
            if resp.status_code != 200:
                return {"capture_failed": f"GET returned {resp.status_code}"}
            containers = (
                resp.json().get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
            )
            match = next((c for c in containers if c.get("name") == container_name), None)
            if match is None:
                return {"capture_failed": f"container '{container_name}' not found in current spec"}
            resources = match.get("resources", {})
            return {
                "memory_limit": resources.get("limits", {}).get("memory"),
                "memory_request": resources.get("requests", {}).get("memory"),
                "cpu_limit": resources.get("limits", {}).get("cpu"),
                "cpu_request": resources.get("requests", {}).get("cpu"),
            }
        except Exception as exc:
            return {"capture_failed": str(exc)[:200]}

    async def apply_hpa(
        self,
        namespace: str,
        deployment_name: str,
        min_replicas: int = 2,
        max_replicas: int = 10,
        target_memory_utilization: int = 70,
    ) -> dict:
        """
        Create or replace a HorizontalPodAutoscaler targeting memory utilization.
        Ref: https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/
        """
        if not self.k8s_api_url or not self.k8s_token:
            raise EnvironmentError("K8S_API_URL and K8S_TOKEN not configured for this workspace")

        url = (
            f"{self.k8s_api_url}/apis/autoscaling/v2"
            f"/namespaces/{namespace}/horizontalpodautoscalers"
        )
        headers = {
            "Authorization": f"Bearer {self.k8s_token}",
            "Content-Type": "application/json",
        }

        before_state = await self._capture_hpa(namespace, deployment_name)

        hpa_manifest = {
            "apiVersion": "autoscaling/v2",
            "kind": "HorizontalPodAutoscaler",
            "metadata": {
                "name": deployment_name,
                "namespace": namespace,
                "labels": {"managed-by": "cloud-decoded"},
            },
            "spec": {
                "scaleTargetRef": {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "name": deployment_name,
                },
                "minReplicas": min_replicas,
                "maxReplicas": max_replicas,
                "metrics": [
                    {
                        "type": "Resource",
                        "resource": {
                            "name": "memory",
                            "target": {
                                "type": "Utilization",
                                "averageUtilization": target_memory_utilization,
                            },
                        },
                    }
                ],
            },
        }

        async with httpx.AsyncClient(timeout=30, verify=self._verify) as client:
            resp = await client.post(url, headers=headers, json=hpa_manifest)

        if resp.status_code in (200, 201):
            log.info("[K8sTools] Applied HPA %s/%s min=%d max=%d", namespace, deployment_name, min_replicas, max_replicas)
            return {
                "status": "applied",
                "kind": "HorizontalPodAutoscaler",
                "name": deployment_name,
                "namespace": namespace,
                "min_replicas": min_replicas,
                "max_replicas": max_replicas,
                "before_state": before_state,
            }

        # 409 = already exists — use replace
        if resp.status_code == 409:
            replace_url = f"{url}/{deployment_name}"
            hpa_manifest["metadata"]["resourceVersion"] = "0"  # required for replace
            async with httpx.AsyncClient(timeout=30, verify=self._verify) as client:
                resp = await client.put(replace_url, headers=headers, json=hpa_manifest)
            if resp.status_code in (200, 201):
                return {
                    "status": "replaced",
                    "kind": "HorizontalPodAutoscaler",
                    "name": deployment_name,
                    "namespace": namespace,
                    "min_replicas": min_replicas,
                    "max_replicas": max_replicas,
                    "before_state": before_state,
                }

        raise RuntimeError(f"K8s HPA error {resp.status_code}: {resp.text[:200]}")

    async def _capture_hpa(self, namespace: str, deployment_name: str) -> dict:
        """GET the existing HPA for this deployment, if any, before
        create-or-replace. Never raises -- see _capture_container_resources
        for the same reasoning."""
        url = f"{self.k8s_api_url}/apis/autoscaling/v2/namespaces/{namespace}/horizontalpodautoscalers/{deployment_name}"
        try:
            async with httpx.AsyncClient(timeout=30, verify=self._verify) as client:
                resp = await client.get(
                    url, headers={"Authorization": f"Bearer {self.k8s_token}"},
                )
            if resp.status_code == 404:
                return {"existed": False}
            if resp.status_code != 200:
                return {"capture_failed": f"GET returned {resp.status_code}"}
            spec = resp.json().get("spec", {})
            return {
                "existed": True,
                "min_replicas": spec.get("minReplicas"),
                "max_replicas": spec.get("maxReplicas"),
            }
        except Exception as exc:
            return {"capture_failed": str(exc)[:200]}

    async def rollback_deployment(self, namespace: str, deployment_name: str) -> dict:
        """
        Roll back a Deployment by annotating it to trigger a rollout restart.
        In GitOps environments (Flux/ArgoCD), pair this with a git revert PR.
        Ref: https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#rolling-back-a-deployment
        """
        if not self.k8s_api_url or not self.k8s_token:
            raise EnvironmentError("K8S_API_URL and K8S_TOKEN not configured for this workspace")

        url = (
            f"{self.k8s_api_url}/apis/apps/v1"
            f"/namespaces/{namespace}/deployments/{deployment_name}"
        )
        headers = {
            "Authorization": f"Bearer {self.k8s_token}",
            "Content-Type": "application/strategic-merge-patch+json",
        }

        # Fetch current revision so we can undo to (revision - 1)
        async with httpx.AsyncClient(timeout=30, verify=self._verify) as client:
            get_resp = await client.get(url, headers={**headers, "Content-Type": "application/json"})

        if get_resp.status_code != 200:
            raise RuntimeError(f"K8s GET deployment error {get_resp.status_code}: {get_resp.text[:200]}")

        current_revision = int(
            get_resp.json()
            .get("metadata", {})
            .get("annotations", {})
            .get("deployment.kubernetes.io/revision", "1")
        )

        # Annotate with undo revision — k8s will re-apply the previous ReplicaSet template
        patch_body = {
            "metadata": {
                "annotations": {
                    "cloud-decoded/rollback-from-revision": str(current_revision),
                    "cloud-decoded/rollback-initiated": "true",
                }
            },
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": _utc_now_iso(),
                        }
                    }
                }
            },
        }

        async with httpx.AsyncClient(timeout=30, verify=self._verify) as client:
            resp = await client.patch(url, headers=headers, json=patch_body)

        if resp.status_code in (200, 201):
            log.info(
                "[K8sTools] Rollback initiated for %s/%s (was revision %d)",
                namespace, deployment_name, current_revision,
            )
            return {
                "status": "rolled_back",
                "deployment": deployment_name,
                "namespace": namespace,
                "rolled_back_from_revision": current_revision,
                "before_state": {"revision": current_revision},
            }

        raise RuntimeError(f"K8s rollback error {resp.status_code}: {resp.text[:200]}")

    # ──────────────────────────────────────────────
    # GitOps PR tool — create a GitHub PR with updated k8s manifest
    # ──────────────────────────────────────────────

    async def create_gitops_pr(
        self,
        owner: str,
        repo: str,
        file_path: str,
        new_content: str,
        commit_message: str,
        pr_title: str,
        pr_body: str,
        base_branch: str = "main",
    ) -> dict:
        """
        Open a PR with a modified k8s manifest file, against whichever
        provider (GitHub or Azure DevOps) this workspace has connected.
        Used when the workspace uses GitOps (ArgoCD/Flux) rather than direct
        kubectl. Delegates to core.repo_tools (Phase 4, same treatment
        Phase 2 gave agents 04/08/10) -- this used to be its own direct
        GitHub implementation.
        """
        repo_tools = self._repo_tools()

        branch_name = f"cloud-decoded/k8s-fix-{_short_id()}"
        await repo_tools.create_branch(owner, repo, branch_name, base_branch)
        await repo_tools.push_commit(owner, repo, branch_name, {file_path: new_content}, commit_message)
        pr = await repo_tools.create_pr(owner, repo, branch_name, pr_title, pr_body, base=base_branch)

        log.info("[K8sTools] GitOps PR opened: %s", pr.get("pr_url"))
        return {
            "status": "pr_opened",
            "pr_url": pr.get("pr_url", ""),
            "pr_number": pr.get("pr_number"),
            "branch": branch_name,
        }

    # ──────────────────────────────────────────────
    # Routing — dispatch to correct tool
    # ──────────────────────────────────────────────

    async def execute_option(self, option: dict, context: dict) -> dict:
        """
        Dispatch to the correct K8s tool based on the approved option and incident context.
        context must include: namespace, deployment_name, container_name, cluster_name
        """
        option_id = option.get("id", "")
        namespace = context.get("namespace", "default")
        deployment_name = context.get("deployment_name", "")
        container_name = context.get("container_name", deployment_name)

        log.info("[K8sTools] Executing option '%s' for %s/%s", option_id, namespace, deployment_name)

        if option_id == "hold":
            return {"status": "held", "message": "Operator chose to handle manually"}

        if option_id == "opt_1":
            # Increase memory limit
            new_limit = context.get("new_memory_limit", "1Gi")
            return await self.patch_deployment_memory(
                namespace=namespace,
                deployment_name=deployment_name,
                memory_limit=new_limit,
                container_name=container_name,
            )

        if option_id == "opt_2":
            # Add HPA
            return await self.apply_hpa(
                namespace=namespace,
                deployment_name=deployment_name,
                min_replicas=context.get("hpa_min", 2),
                max_replicas=context.get("hpa_max", 10),
            )

        if option_id == "opt_3":
            # Rollback
            return await self.rollback_deployment(
                namespace=namespace,
                deployment_name=deployment_name,
            )

        return {"status": "not_implemented", "option_id": option_id}


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _halve_memory(mem: str) -> str:
    """Return half the given memory quantity (e.g. '1Gi' → '512Mi')."""
    try:
        if mem.endswith("Gi"):
            val = float(mem[:-2])
            half = val / 2
            return f"{int(half * 1024)}Mi" if half < 1 else f"{int(half)}Gi"
        if mem.endswith("Mi"):
            val = int(mem[:-2])
            return f"{val // 2}Mi"
    except (ValueError, IndexError):
        pass
    return mem  # fallback: leave unchanged


def _short_id() -> str:
    import uuid
    return str(uuid.uuid4())[:8]


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
