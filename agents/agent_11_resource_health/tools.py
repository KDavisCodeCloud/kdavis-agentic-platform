"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Agent 11 — Cloud Resource Health Monitoring execution tools.

All write operations execute ONLY after operator approval via POST
/incidents/{id}/approve. No correction is applied autonomously. Governance
Rule 11.

Unlike Agent 08 (which corrects config drift by applying/PR-ing corrected
IaC), Agent 11 diagnoses *runtime* alerts (a resource going down, a
performance threshold breach, a security finding) -- there usually isn't
a "corrected content" to apply, so the write-side tools here are
deliberately narrow: open a remediation PR when the fix genuinely is an
IaC change (e.g. tighten an NSG rule), or open a tracking/investigation
issue when it isn't (performance alerts, anything requiring human
judgment). No live cloud-mutation API calls (no "restart this VM", no
"scale this out") are built in this pass -- see GAPS.md for why that's a
deliberate scope boundary, not an oversight.

Correction options:
  opt_1 — Create Remediation PR (only when the diagnosis names a real IaC change)
  opt_2 — Create Investigation/Tracking Issue (default for anything requiring judgment)
  hold  — No automated action
"""

import logging
from typing import Optional

import httpx

from core.repo_tools import RepoTools, get_repo_tools

log = logging.getLogger(__name__)

_GH_API           = "https://api.github.com"
_MAX_HTTP_TIMEOUT = 30


def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


class ResourceHealthTools:
    def __init__(
        self,
        github_token: Optional[str] = None,
        azure_devops_token: Optional[str] = None,
        azure_devops_org: Optional[str] = None,
    ):
        # No env-var fallback -- per-workspace only (core/workspace_credentials.py).
        self.github_token       = github_token or ""
        self.azure_devops_token = azure_devops_token or ""
        self.azure_devops_org   = azure_devops_org or ""

    def _repo_tools(self) -> RepoTools:
        """Provider selection -- GitHub or Azure DevOps, whichever this
        workspace has connected. See core.repo_tools.get_repo_tools."""
        return get_repo_tools(
            github_token=self.github_token,
            azure_devops_token=self.azure_devops_token,
            azure_devops_org=self.azure_devops_org,
        )

    async def create_alert_pr(
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
        """Open a PR with the proposed IaC fix, against whichever provider
        this workspace has connected. Same 5-step flow as Agent 08's
        create_drift_pr, deliberately not shared as a base-class method --
        each agent's tools.py stays self-contained in this codebase."""
        repo_tools = self._repo_tools()

        await repo_tools.create_branch(owner, repo, branch_name, base_branch)
        await repo_tools.push_commit(
            owner, repo, branch_name,
            {file_path: corrected_content},
            f"fix(resource-health): {file_path} [Cloud Decoded Agent 11]",
        )
        title = pr_title or f"fix(resource-health): address alert in {file_path}"
        pr = await repo_tools.create_pr(owner, repo, branch_name, title, pr_body, base=base_branch)

        log.info("[ResourceHealthTools] Remediation PR created: %s", pr.get("pr_url"))
        return {
            "status": "pr_created",
            "pr_url": pr.get("pr_url", ""),
            "pr_number": pr.get("pr_number"),
            "branch": branch_name,
        }

    async def create_alert_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
    ) -> dict:
        """Open a tracking/investigation issue -- the only option ever
        offered for alerts requiring human judgment (credential exposure,
        unusual auth, potential exfiltration).

        GitHub only -- RepoTools has no create_issue method and no
        Azure DevOps work-item creation exists anywhere in this codebase
        yet, so this mirrors Agent 08's create_drift_issue exactly: a
        direct GitHub API call, same GitHub-only limitation, not routed
        through RepoTools' provider abstraction. An Azure DevOps
        workspace gets EnvironmentError here, same as Agent 08 today."""
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
        log.info("[ResourceHealthTools] Investigation issue created: %s", issue.get("html_url"))
        return {
            "status": "issue_created",
            "issue_url": issue.get("html_url", ""),
            "issue_number": issue.get("number"),
        }

    async def execute_option(self, option: dict, context: dict) -> dict:
        """
        Dispatch to the approved action.

        context must include: owner, repo, file_path, corrected_content,
        report_body, resource_id (for branch naming).
        """
        option_id = option.get("id", "")
        log.info("[ResourceHealthTools] Executing approved option '%s'", option_id)

        if option_id == "hold":
            return {"status": "held", "message": "Operator chose to investigate/correct manually"}

        owner       = context.get("owner", "")
        repo        = context.get("repo", "")
        resource_id = context.get("resource_id", "resource")
        report_body = context.get("report_body", "")

        if not owner or not repo:
            return {"status": "skipped", "reason": "repository not configured — cannot create PR/issue"}

        if option_id == "opt_1":
            branch_name = f"resource-health/{resource_id.replace('/', '-').replace(':', '-')}"[:100]
            return await self.create_alert_pr(
                owner=owner, repo=repo, branch_name=branch_name,
                file_path=context.get("file_path", f"infra/{resource_id}"),
                corrected_content=context.get("corrected_content", ""),
                pr_body=report_body,
            )

        if option_id == "opt_2":
            return await self.create_alert_issue(
                owner=owner, repo=repo,
                title=context.get("issue_title", f"Resource health alert: {resource_id}"),
                body=report_body,
                labels=["resource-health", "alert"],
            )

        return {"status": "not_implemented", "option_id": option_id}
