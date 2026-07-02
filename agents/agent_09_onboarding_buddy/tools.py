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
Agent 09 — Context-Aware Onboarding & On-Call Buddy execution tools.

Handles two use cases:
  onboarding — answers architecture/codebase questions for new engineers using
               GitHub documentation, README files, and runbook content
  on_call    — surfaces relevant runbooks, past incident patterns, and diagnostic
               guidance when an engineer is paged

Knowledge retrieval (read-only, may run pre-HITL in the diagnose node):
  search_github_files() — searches repo for relevant docs via GitHub Search API
  get_github_file()     — reads a specific file (README, runbook, architecture doc)

Post-HITL actions (all require operator approval):
  create_knowledge_issue() — saves synthesized brief as a searchable GitHub issue
  post_slack_message()     — delivers response to Slack channel

Governance Rule 11: No content is published or saved without operator approval.
"""

import base64
import logging
import os
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_GH_API              = "https://api.github.com"
_MAX_HTTP_TIMEOUT    = 30
_MAX_FILE_CHARS      = 2_000   # per-file excerpt limit sent to LLM
_MAX_SEARCH_RESULTS  = 5


class OnboardingTools:
    """
    Knowledge retrieval and publishing tools for Agent 09.
    """

    def __init__(
        self,
        github_token: Optional[str] = None,
        slack_webhook_url: Optional[str] = None,
    ):
        self.github_token      = github_token      or os.environ.get("GITHUB_TOKEN", "")
        self.slack_webhook_url = slack_webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")

    # ──────────────────────────────────────────────
    # Knowledge retrieval (read-only)
    # ──────────────────────────────────────────────

    async def search_github_files(
        self,
        owner: str,
        repo: str,
        query: str,
        path_filter: str = "",
        max_results: int = _MAX_SEARCH_RESULTS,
    ) -> list[dict]:
        """
        Search a GitHub repository for files matching a query.
        Uses the GitHub Code Search API.
        Returns a list of {path, url} dicts (content fetched separately via get_github_file).
        Returns [] on error or missing token — never raises.
        """
        if not self.github_token:
            log.debug("[OnboardingTools] GitHub token not configured — skipping file search")
            return []

        q = f"{query} repo:{owner}/{repo}"
        if path_filter:
            q += f" path:{path_filter}"

        try:
            async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
                resp = await client.get(
                    f"{_GH_API}/search/code",
                    headers=_gh_headers(self.github_token),
                    params={"q": q, "per_page": max_results},
                )
        except httpx.RequestError as exc:
            log.warning("[OnboardingTools] GitHub search request error: %s", exc)
            return []

        if resp.status_code != 200:
            log.warning("[OnboardingTools] GitHub search error %d", resp.status_code)
            return []

        items = resp.json().get("items", [])
        return [
            {"path": item.get("path", ""), "url": item.get("html_url", "")}
            for item in items[:max_results]
        ]

    async def get_github_file(
        self,
        owner: str,
        repo: str,
        file_path: str,
        ref: str = "HEAD",
    ) -> dict:
        """
        Read a file from a GitHub repository.
        Returns {path, url, content, truncated} or {error}.
        Content is truncated at _MAX_FILE_CHARS.
        """
        if not self.github_token:
            return {"error": "GITHUB_TOKEN not configured"}

        try:
            async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
                resp = await client.get(
                    f"{_GH_API}/repos/{owner}/{repo}/contents/{file_path}",
                    headers=_gh_headers(self.github_token),
                    params={"ref": ref},
                )
        except httpx.RequestError as exc:
            return {"error": str(exc)}

        if resp.status_code != 200:
            return {"error": f"GitHub API error {resp.status_code}"}

        data = resp.json()
        raw_content = base64.b64decode(data.get("content", "")).decode(errors="replace")
        return {
            "path": data.get("path", file_path),
            "url": data.get("html_url", ""),
            "content": raw_content[:_MAX_FILE_CHARS],
            "truncated": len(raw_content) > _MAX_FILE_CHARS,
        }

    # ──────────────────────────────────────────────
    # Post-HITL publishing tools
    # ──────────────────────────────────────────────

    async def create_knowledge_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
    ) -> dict:
        """
        Save a synthesized knowledge brief as a GitHub issue.
        Issues are searchable by future team members and AI agents.
        """
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
        log.info("[OnboardingTools] Knowledge issue created: %s", issue.get("html_url"))
        return {
            "status": "issue_created",
            "issue_url": issue.get("html_url", ""),
            "issue_number": issue.get("number"),
        }

    async def post_slack_message(
        self,
        message: str,
        channel_override: Optional[str] = None,
    ) -> dict:
        """
        Post the synthesized response to a Slack channel via webhook.
        Returns skipped if SLACK_WEBHOOK_URL is not configured.
        """
        if not self.slack_webhook_url:
            return {"status": "skipped", "reason": "SLACK_WEBHOOK_URL not configured"}

        slack_payload = {"text": message}
        if channel_override:
            slack_payload["channel"] = channel_override

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    self.slack_webhook_url,
                    json=slack_payload,
                    headers={"Content-Type": "application/json"},
                )
        except httpx.RequestError as exc:
            return {"status": "failed", "reason": str(exc)}

        if resp.status_code != 200:
            return {"status": "failed", "reason": f"Slack returned {resp.status_code}"}

        log.info("[OnboardingTools] Slack message posted")
        return {"status": "ok", "channel": channel_override or "default"}

    # ──────────────────────────────────────────────
    # Routing
    # ──────────────────────────────────────────────

    async def execute_option(self, option: dict, context: dict) -> dict:
        """
        Dispatch to the approved publishing action.

        context must include:
          query_type, owner, repo, report_body, issue_title, slack_message (opt), slack_channel (opt)
        """
        option_id = option.get("id", "")
        log.info("[OnboardingTools] Executing approved option '%s'", option_id)

        if option_id == "hold":
            return {
                "status": "held",
                "message": "Synthesized response is available in the operator dashboard",
            }

        owner = context.get("owner", "")
        repo  = context.get("repo",  "")

        if option_id == "opt_1":
            # Save as GitHub issue
            if not owner or not repo:
                return {"status": "skipped", "reason": "repository not configured — cannot create knowledge issue"}

            query_type = context.get("query_type", "onboarding")
            labels = (
                ["knowledge", "on-call"]
                if query_type == "on_call"
                else ["knowledge", "onboarding"]
            )
            return await self.create_knowledge_issue(
                owner=owner,
                repo=repo,
                title=context.get("issue_title", "Knowledge Brief"),
                body=context.get("report_body", ""),
                labels=labels,
            )

        if option_id == "opt_2":
            # Post to Slack
            return await self.post_slack_message(
                message=context.get("slack_message", context.get("report_body", ""))[:3000],
                channel_override=context.get("slack_channel"),
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
