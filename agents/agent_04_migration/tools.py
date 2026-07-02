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
Agent 04 — Legacy Code & Infrastructure Migration execution tools.

These tools are called ONLY after operator approval via POST /incidents/{id}/approve.
They never execute autonomously. Governance Rule 11.
"""

import base64
import logging
import os
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_GH_API = "https://api.github.com"


class MigrationTools:
    """
    Post-approval execution tools for Agent 04.
    Creates GitHub PRs and issues — never modifies files without operator approval.
    """

    def __init__(self, github_token: Optional[str] = None):
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN", "")

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
        Open a GitHub PR with the LLM-generated migrated code.
        Creates a feature branch, commits the file, and opens the PR.
        Ref: https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request
        """
        if not self.github_token:
            raise EnvironmentError("GITHUB_TOKEN not configured for this workspace")

        headers = _gh_headers(self.github_token)

        # 1. Get HEAD SHA of base branch
        ref_url = f"{_GH_API}/repos/{owner}/{repo}/git/ref/heads/{base_branch}"
        async with httpx.AsyncClient(timeout=30) as client:
            ref_resp = await client.get(ref_url, headers=headers)

        if ref_resp.status_code != 200:
            raise RuntimeError(f"GitHub get ref error {ref_resp.status_code}: {ref_resp.text[:200]}")

        base_sha = ref_resp.json()["object"]["sha"]

        # 2. Create feature branch
        branch_name = f"cloud-decoded/migrate-{_short_id()}"
        async with httpx.AsyncClient(timeout=30) as client:
            branch_resp = await client.post(
                f"{_GH_API}/repos/{owner}/{repo}/git/refs",
                headers=headers,
                json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
            )

        if branch_resp.status_code not in (200, 201):
            raise RuntimeError(f"GitHub create branch error {branch_resp.status_code}: {branch_resp.text[:200]}")

        # 3. Get current file SHA (if it exists — required for update)
        file_url = f"{_GH_API}/repos/{owner}/{repo}/contents/{file_path}"
        async with httpx.AsyncClient(timeout=30) as client:
            file_resp = await client.get(file_url, headers=headers, params={"ref": base_branch})

        file_sha = file_resp.json().get("sha") if file_resp.status_code == 200 else None

        # 4. Commit the migrated file
        put_payload = {
            "message": f"chore(migration): {pr_title}",
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
            log.info("[MigrationTools] Migration PR opened: %s", pr_data.get("html_url"))
            return {
                "status": "pr_opened",
                "pr_url": pr_data.get("html_url", ""),
                "pr_number": pr_data.get("number"),
                "branch": branch_name,
            }

        raise RuntimeError(f"GitHub PR error {pr_resp.status_code}: {pr_resp.text[:200]}")

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
