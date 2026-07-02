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
Agent 01 — CI/CD Triage execution tools.

These tools are called ONLY after operator approval via POST /incidents/{id}/approve.
They never execute autonomously. Governance Rule 11.
"""

import logging
import os
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_AZURE_DEVOPS_API = "https://dev.azure.com"


class CICDTools:
    """
    Post-approval execution tools for Agent 01.
    All methods require a workspace-scoped token — never use the operator's default token.
    """

    def __init__(self, github_token: Optional[str] = None, azure_token: Optional[str] = None):
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN", "")
        self.azure_token = azure_token or os.environ.get("AZURE_DEVOPS_TOKEN", "")

    # ──────────────────────────────────────────────
    # GitHub Actions tools
    # ──────────────────────────────────────────────

    async def rerun_github_workflow(
        self, owner: str, repo: str, run_id: int, enable_debug: bool = False
    ) -> dict:
        """
        Re-trigger a failed GitHub Actions workflow run.
        Ref: https://docs.github.com/en/rest/actions/workflow-runs#re-run-a-workflow
        """
        if not self.github_token:
            raise EnvironmentError("GITHUB_TOKEN not configured for this workspace")

        url = f"{_GITHUB_API}/repos/{owner}/{repo}/actions/runs/{run_id}/rerun"
        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        payload = {"enable_debug_logging": enable_debug}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=payload)

        if resp.status_code == 201:
            log.info("[CICDTools] Triggered rerun for %s/%s run %d", owner, repo, run_id)
            return {"status": "triggered", "run_id": run_id, "repo": f"{owner}/{repo}"}

        log.error(
            "[CICDTools] GitHub rerun failed: %d %s", resp.status_code, resp.text[:200]
        )
        raise RuntimeError(f"GitHub API error {resp.status_code}: {resp.text[:200]}")

    async def rerun_failed_jobs_only(self, owner: str, repo: str, run_id: int) -> dict:
        """
        Re-run only the failed jobs in a workflow run (not the whole run).
        Useful when only 1 of 5 matrix jobs failed.
        Ref: https://docs.github.com/en/rest/actions/workflow-runs#re-run-failed-jobs-from-a-workflow-run
        """
        if not self.github_token:
            raise EnvironmentError("GITHUB_TOKEN not configured for this workspace")

        url = f"{_GITHUB_API}/repos/{owner}/{repo}/actions/runs/{run_id}/rerun-failed-jobs"
        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json={})

        if resp.status_code == 201:
            log.info("[CICDTools] Triggered failed-jobs rerun for %s/%s run %d", owner, repo, run_id)
            return {"status": "triggered", "mode": "failed_jobs_only", "run_id": run_id}

        raise RuntimeError(f"GitHub API error {resp.status_code}: {resp.text[:200]}")

    async def post_github_pr_comment(
        self, owner: str, repo: str, pr_number: int, comment_body: str
    ) -> dict:
        """
        Post a diagnostic comment on the triggering PR.
        Used to surface the diagnosis + fix to the dev who opened the PR.
        Ref: https://docs.github.com/en/rest/issues/comments#create-an-issue-comment
        """
        if not self.github_token:
            raise EnvironmentError("GITHUB_TOKEN not configured for this workspace")

        url = f"{_GITHUB_API}/repos/{owner}/{repo}/issues/{pr_number}/comments"
        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json={"body": comment_body})

        if resp.status_code == 201:
            comment_url = resp.json().get("html_url", "")
            log.info("[CICDTools] PR comment posted: %s", comment_url)
            return {"status": "posted", "comment_url": comment_url}

        raise RuntimeError(f"GitHub PR comment error {resp.status_code}: {resp.text[:200]}")

    async def get_workflow_run_logs_url(self, owner: str, repo: str, run_id: int) -> str:
        """
        Retrieve the URL to download workflow run logs (zip).
        Used to pull log excerpts for diagnosis.
        Ref: https://docs.github.com/en/rest/actions/workflow-runs#download-workflow-run-logs
        """
        if not self.github_token:
            raise EnvironmentError("GITHUB_TOKEN not configured for this workspace")

        url = f"{_GITHUB_API}/repos/{owner}/{repo}/actions/runs/{run_id}/logs"
        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code == 302:
            return resp.headers.get("Location", "")
        if resp.status_code == 200:
            return resp.url
        raise RuntimeError(f"Could not get log URL: {resp.status_code}")

    # ──────────────────────────────────────────────
    # Azure DevOps tools
    # ──────────────────────────────────────────────

    async def retry_azure_pipeline(
        self, organization: str, project: str, build_id: int
    ) -> dict:
        """
        Re-queue a failed Azure DevOps pipeline run.
        Ref: https://learn.microsoft.com/en-us/rest/api/azure/devops/build/builds/queue
        """
        if not self.azure_token:
            raise EnvironmentError("AZURE_DEVOPS_TOKEN not configured for this workspace")

        # Get the original build's definition to re-queue
        get_url = (
            f"{_AZURE_DEVOPS_API}/{organization}/{project}/_apis/build/builds/{build_id}"
            "?api-version=7.1"
        )
        headers = {
            "Authorization": f"Basic {self.azure_token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            get_resp = await client.get(get_url, headers=headers)

        if get_resp.status_code != 200:
            raise RuntimeError(
                f"Azure DevOps get build error {get_resp.status_code}: {get_resp.text[:200]}"
            )

        build = get_resp.json()
        definition_id = build["definition"]["id"]
        source_branch = build.get("sourceBranch", "refs/heads/main")

        queue_url = (
            f"{_AZURE_DEVOPS_API}/{organization}/{project}/_apis/build/builds?api-version=7.1"
        )
        queue_payload = {
            "definition": {"id": definition_id},
            "sourceBranch": source_branch,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            queue_resp = await client.post(queue_url, headers=headers, json=queue_payload)

        if queue_resp.status_code in (200, 201):
            new_build_id = queue_resp.json().get("id")
            log.info(
                "[CICDTools] Azure DevOps pipeline re-queued: new build %d", new_build_id
            )
            return {"status": "queued", "new_build_id": new_build_id}

        raise RuntimeError(
            f"Azure DevOps queue error {queue_resp.status_code}: {queue_resp.text[:200]}"
        )

    # ──────────────────────────────────────────────
    # Routing — dispatch to correct tool based on option_id + context
    # ──────────────────────────────────────────────

    async def execute_option(self, option: dict, context: dict) -> dict:
        """
        Dispatch to the correct tool based on approved option and incident context.
        context must include: cloud_provider, owner/org, repo/project, run_id, pr_number (optional)
        """
        option_id = option.get("id", "")
        provider = context.get("cloud_provider", "github")

        log.info(
            "[CICDTools] Executing option '%s' for provider '%s'",
            option_id, provider
        )

        if option_id == "hold":
            return {"status": "held", "message": "Operator chose to stay broken / handle manually"}

        if option_id in ("opt_1", "opt_2") and provider == "github":
            # Default: re-run failed jobs
            return await self.rerun_failed_jobs_only(
                owner=context["owner"],
                repo=context["repo"],
                run_id=context["run_id"],
            )

        if option_id == "opt_3" and provider == "github" and context.get("pr_number"):
            # Post diagnostic comment to PR
            diagnosis = context.get("parsed_error", "Diagnosis not available")
            body = (
                f"## Cloud Decoded — CI/CD Triage Result\n\n"
                f"**Root cause:** {diagnosis}\n\n"
                f"**Status:** Remediation initiated. See Cloud Decoded dashboard for details."
            )
            return await self.post_github_pr_comment(
                owner=context["owner"],
                repo=context["repo"],
                pr_number=context["pr_number"],
                comment_body=body,
            )

        if provider == "azure_devops":
            return await self.retry_azure_pipeline(
                organization=context["org"],
                project=context["project"],
                build_id=context["run_id"],
            )

        # Full rerun fallback
        if provider == "github":
            return await self.rerun_github_workflow(
                owner=context["owner"],
                repo=context["repo"],
                run_id=context["run_id"],
            )

        return {"status": "not_implemented", "option_id": option_id, "provider": provider}
