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

from core.iac_fix import IacProposal, iac_pr_option, open_fix_pr
from core.pr_branch import pr_branch_name
from core.option_catalog import OptionSpec, catalog_dict, not_available_result

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

    async def create_alert_pr(self, proposal: Optional[dict], branch_name: str, pr_body: str) -> dict:
        """Open a PR changing only the reviewed resource block (G16), after the
        re-check and terraform fmt + validate in core/iac_fix.py. It used to
        commit the alert payload's `corrected_content` over the whole file,
        and no real alert carries one -- so it would have committed an empty file."""
        iac = IacProposal.from_dict(proposal)
        address = iac.address if iac else "resource"
        result = await open_fix_pr(
            self._repo_tools(), iac, branch_name,
            pr_title=f"fix(resource-health): change {address}",
            pr_body=pr_body,
            commit_message=f"fix(resource-health): change {address} [Cloud Decoded Agent 11]",
        )
        log.info("[ResourceHealthTools] alert PR for %s: %s %s", address, result["status"],
                 result.get("pr_url") or result.get("reason", ""))
        return result

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
        catalog = option_catalog(context)
        if option_id not in catalog:
            return not_available_result(option_id, catalog)


        owner       = context.get("owner", "")
        repo        = context.get("repo", "")
        resource_id = context.get("resource_id", "resource")
        report_body = context.get("report_body", "")

        if option_id == "opt_1":
            # Only in the catalog when diagnose produced a reviewed one-block change (G16).
            return await self.create_alert_pr(
                proposal=context.get("iac_proposal"),
                branch_name=pr_branch_name("resource-health", context.get("incident_id")),
                pr_body=report_body,
            )

        if not owner or not repo:
            return {"status": "skipped",
                    "reason": "no repository for this resource -- map one in Settings → Repositories"}

        if option_id == "opt_2":
            return await self.create_alert_issue(
                owner=owner, repo=repo,
                title=context.get("issue_title", f"Resource health alert: {resource_id}"),
                body=report_body,
                labels=["resource-health", "alert"],
            )

        return {"status": "not_implemented", "option_id": option_id}


def option_catalog(context: dict) -> dict[str, OptionSpec]:
    """
    What Agent 11 can actually do. It has no live cloud actions: nothing is
    scaled, restarted or reconfigured directly.
    """
    # G16/G13: a PR only for a one-block change diagnose computed against the
    # resource's real .tf file (repo from the alert or Settings → Repositories).
    specs = iac_pr_option(context, "create_alert_pr")
    return catalog_dict(
        *specs,
        OptionSpec("opt_2", "Open an investigation issue",
                   "Creates a GitHub issue with the alert, the diagnosis and investigation steps. Nothing is changed.",
                   "low", ("create_alert_issue",), proposal=True),
    )
