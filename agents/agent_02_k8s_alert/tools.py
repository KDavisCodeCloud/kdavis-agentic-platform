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
Agent 02 — Kubernetes Alert Fatigue & Remediation execution tools.

These tools are called ONLY after operator approval via POST /incidents/{id}/approve.
They never execute autonomously. Governance Rule 11.
"""

import json
import logging
import os
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_GH_API = "https://api.github.com"


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
    ):
        self.k8s_api_url = (k8s_api_url or os.environ.get("K8S_API_URL", "")).rstrip("/")
        self.k8s_token = k8s_token or os.environ.get("K8S_TOKEN", "")
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN", "")

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

        async with httpx.AsyncClient(timeout=30) as client:
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
            }

        log.error("[K8sTools] patch_deployment_memory failed: %d %s", resp.status_code, resp.text[:200])
        raise RuntimeError(f"K8s PATCH error {resp.status_code}: {resp.text[:200]}")

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

        async with httpx.AsyncClient(timeout=30) as client:
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
            }

        # 409 = already exists — use replace
        if resp.status_code == 409:
            replace_url = f"{url}/{deployment_name}"
            hpa_manifest["metadata"]["resourceVersion"] = "0"  # required for replace
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.put(replace_url, headers=headers, json=hpa_manifest)
            if resp.status_code in (200, 201):
                return {
                    "status": "replaced",
                    "kind": "HorizontalPodAutoscaler",
                    "name": deployment_name,
                    "namespace": namespace,
                    "min_replicas": min_replicas,
                    "max_replicas": max_replicas,
                }

        raise RuntimeError(f"K8s HPA error {resp.status_code}: {resp.text[:200]}")

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
        async with httpx.AsyncClient(timeout=30) as client:
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

        async with httpx.AsyncClient(timeout=30) as client:
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
        Create a GitHub PR with a modified k8s manifest file.
        Used when the workspace uses GitOps (ArgoCD/Flux) rather than direct kubectl.
        Ref: https://docs.github.com/en/rest/contents/contents#create-or-update-file-contents
        """
        if not self.github_token:
            raise EnvironmentError("GITHUB_TOKEN not configured for this workspace")

        import base64

        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        # 1. Get the current file SHA (required for PATCH)
        file_url = f"{_GH_API}/repos/{owner}/{repo}/contents/{file_path}"
        async with httpx.AsyncClient(timeout=30) as client:
            get_resp = await client.get(file_url, headers=headers)

        file_sha = get_resp.json().get("sha") if get_resp.status_code == 200 else None

        # 2. Create a feature branch
        branch_name = f"cloud-decoded/k8s-fix-{_short_id()}"
        ref_url = f"{_GH_API}/repos/{owner}/{repo}/git/refs"
        main_sha_url = f"{_GH_API}/repos/{owner}/{repo}/git/ref/heads/{base_branch}"

        async with httpx.AsyncClient(timeout=30) as client:
            main_resp = await client.get(main_sha_url, headers=headers)

        main_sha = main_resp.json()["object"]["sha"]

        async with httpx.AsyncClient(timeout=30) as client:
            branch_resp = await client.post(
                ref_url,
                headers=headers,
                json={"ref": f"refs/heads/{branch_name}", "sha": main_sha},
            )

        if branch_resp.status_code not in (200, 201):
            raise RuntimeError(f"Failed to create branch: {branch_resp.status_code} {branch_resp.text[:200]}")

        # 3. Commit the updated file
        encoded = base64.b64encode(new_content.encode()).decode()
        put_payload = {
            "message": commit_message,
            "content": encoded,
            "branch": branch_name,
        }
        if file_sha:
            put_payload["sha"] = file_sha

        async with httpx.AsyncClient(timeout=30) as client:
            put_resp = await client.put(
                f"{_GH_API}/repos/{owner}/{repo}/contents/{file_path}",
                headers=headers,
                json=put_payload,
            )

        if put_resp.status_code not in (200, 201):
            raise RuntimeError(f"Failed to commit file: {put_resp.status_code} {put_resp.text[:200]}")

        # 4. Open the PR
        pr_url = f"{_GH_API}/repos/{owner}/{repo}/pulls"
        async with httpx.AsyncClient(timeout=30) as client:
            pr_resp = await client.post(
                pr_url,
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
            log.info("[K8sTools] GitOps PR opened: %s", pr_data.get("html_url"))
            return {
                "status": "pr_opened",
                "pr_url": pr_data.get("html_url", ""),
                "pr_number": pr_data.get("number"),
                "branch": branch_name,
            }

        raise RuntimeError(f"GitHub PR error {pr_resp.status_code}: {pr_resp.text[:200]}")

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
