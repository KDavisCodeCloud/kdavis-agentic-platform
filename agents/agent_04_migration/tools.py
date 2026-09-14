"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Agent 04 — Legacy Code & Infrastructure Migration execution tools.

These tools are called ONLY after operator approval via POST /incidents/{id}/approve.
They never execute autonomously. Governance Rule 11.
"""

import logging
from typing import Optional

import httpx

from core.repo_tools import RepoTools, get_repo_tools

log = logging.getLogger(__name__)

_GH_API = "https://api.github.com"


class MigrationTools:
    """
    Post-approval execution tools for Agent 04.
    Creates GitHub PRs and issues — never modifies files without operator approval.
    """

    def __init__(
        self,
        github_token: Optional[str] = None,
        azure_devops_token: Optional[str] = None,
        azure_devops_org: Optional[str] = None,
    ):
        # No env-var fallback -- a missing credential should raise a clear
        # error at the specific call that needed it, not silently fall back
        # to a shared server-wide secret (same discipline as CICDTools /
        # DriftTools). Credentials come from
        # core.workspace_credentials.build_agent_credentials.
        self.github_token       = github_token or ""
        self.azure_devops_token = azure_devops_token or ""
        self.azure_devops_org   = azure_devops_org or ""

    def _repo_tools(self) -> RepoTools:
        """Provider selection (Phase 2) -- GitHub or Azure DevOps, whichever
        this workspace has connected. See core.repo_tools.get_repo_tools."""
        return get_repo_tools(
            github_token=self.github_token,
            azure_devops_token=self.azure_devops_token,
            azure_devops_org=self.azure_devops_org,
        )

    # ──────────────────────────────────────────────
    # Post-approval execution tools
    # ──────────────────────────────────────────────

    async def create_migration_pr(
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
        Open a PR with the LLM-generated migrated code, against whichever
        provider (GitHub or Azure DevOps) this workspace has connected.
        Creates a feature branch, commits the file, and opens the PR via
        core.repo_tools (Phase 2) -- this used to be its own direct GitHub
        implementation.
        """
        repo_tools = self._repo_tools()

        branch_name = f"cloud-decoded/migrate-{_short_id()}"
        await repo_tools.create_branch(owner, repo, branch_name, base_branch)
        await repo_tools.push_commit(owner, repo, branch_name, {file_path: new_content}, f"chore(migration): {pr_title}")
        pr = await repo_tools.create_pr(owner, repo, branch_name, pr_title, pr_body, base=base_branch)

        log.info("[MigrationTools] Migration PR opened: %s", pr.get("pr_url"))
        return {
            "status": "pr_opened",
            "pr_url": pr.get("pr_url", ""),
            "pr_number": pr.get("pr_number"),
            "branch": branch_name,
        }

    async def create_github_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
    ) -> dict:
        """
        Create a GitHub issue with the migration plan for team tracking.
        Ref: https://docs.github.com/en/rest/issues/issues#create-an-issue
        """
        if not self.github_token:
            raise EnvironmentError("GITHUB_TOKEN not configured for this workspace")

        payload = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_GH_API}/repos/{owner}/{repo}/issues",
                headers=_gh_headers(self.github_token),
                json=payload,
            )

        if resp.status_code in (200, 201):
            issue = resp.json()
            log.info("[MigrationTools] Issue created: %s", issue.get("html_url"))
            return {
                "status": "issue_created",
                "issue_url": issue.get("html_url", ""),
                "issue_number": issue.get("number"),
            }

        raise RuntimeError(f"GitHub issue error {resp.status_code}: {resp.text[:200]}")

    # ──────────────────────────────────────────────
    # Routing
    # ──────────────────────────────────────────────

    async def execute_option(self, option: dict, context: dict) -> dict:
        """
        Dispatch to correct migration action based on approved option.
        context must include: owner, repo, file_path, migrated_code, migration_plan,
                              pr_title, pr_body, source_version, target_version
        """
        option_id = option.get("id", "")
        owner = context.get("owner", "")
        repo = context.get("repo", "")

        log.info("[MigrationTools] Executing option '%s' for %s/%s", option_id, owner, repo)

        if option_id == "hold":
            return {"status": "held", "message": "Operator chose to handle migration manually"}

        if option_id == "opt_1":
            # Create PR with migrated code
            migrated_code = context.get("migrated_code", "")
            if not migrated_code:
                return {"status": "skipped", "reason": "No migrated code was generated by the LLM"}

            return await self.create_migration_pr(
                owner=owner,
                repo=repo,
                file_path=context["file_path"],
                new_content=migrated_code,
                pr_title=context.get("pr_title", "chore: apply migration"),
                pr_body=context.get("pr_body", context.get("migration_plan", "")),
                base_branch=context.get("base_branch", "main"),
            )

        if option_id == "opt_2":
            # Post migration plan as GitHub issue
            source_v = context.get("source_version", "legacy")
            target_v = context.get("target_version", "modern")
            return await self.create_github_issue(
                owner=owner,
                repo=repo,
                title=context.get("issue_title", f"Migration: {source_v} → {target_v}"),
                body=context.get("migration_plan", "Migration plan not available"),
                labels=["migration", "technical-debt"],
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


def _short_id() -> str:
    import uuid
    return str(uuid.uuid4())[:8]
