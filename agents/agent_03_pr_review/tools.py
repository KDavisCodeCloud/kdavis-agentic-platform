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
Agent 03 — PR Review execution tools.

These tools are called ONLY after operator approval via POST /incidents/{id}/approve.
They never execute autonomously. Governance Rule 11.
"""

import logging
import os
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_GH_API = "https://api.github.com"

# Valid GitHub PR review events
REVIEW_EVENT_COMMENT = "COMMENT"
REVIEW_EVENT_REQUEST_CHANGES = "REQUEST_CHANGES"
REVIEW_EVENT_APPROVE = "APPROVE"


class PRReviewTools:
    """
    Post-approval execution tools for Agent 03.
    Only posts reviews/comments to GitHub PRs — never modifies code.
    """

    def __init__(self, github_token: Optional[str] = None):
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN", "")

    # ──────────────────────────────────────────────
    # Read-only helpers (used by ingest — not post-approval)
    # ──────────────────────────────────────────────

    async def get_pr_files(self, owner: str, repo: str, pr_number: int) -> list[dict]:
        """
        Fetch changed files for a PR (up to 300).
        Each item: {filename, status, additions, deletions, changes, patch}.
        Ref: https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files
        """
        if not self.github_token:
            raise EnvironmentError("GITHUB_TOKEN not configured for this workspace")

        headers = _gh_headers(self.github_token)
        url = f"{_GH_API}/repos/{owner}/{repo}/pulls/{pr_number}/files"
        files: list[dict] = []

        # Paginate — max 3 pages (300 files) to stay within LLM context limits
        for page in range(1, 4):
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers=headers, params={"per_page": 100, "page": page})

            if resp.status_code != 200:
                raise RuntimeError(f"GitHub files API error {resp.status_code}: {resp.text[:200]}")

            batch = resp.json()
            if not batch:
                break
            files.extend(batch)
            if len(batch) < 100:
                break

        log.info("[PRReviewTools] Fetched %d changed files for %s/%s PR#%d", len(files), owner, repo, pr_number)
        return files

    # ──────────────────────────────────────────────
    # Post-approval execution tools
    # ──────────────────────────────────────────────

    async def post_pr_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        event: str,
        commit_id: Optional[str] = None,
        inline_comments: Optional[list[dict]] = None,
    ) -> dict:
        """
        Submit a GitHub PR review.
        event: "COMMENT" | "REQUEST_CHANGES" | "APPROVE"
        inline_comments: list of {path, line, body} for file-level annotations (optional).
        Ref: https://docs.github.com/en/rest/pulls/reviews#create-a-review-for-a-pull-request
        """
        if not self.github_token:
            raise EnvironmentError("GITHUB_TOKEN not configured for this workspace")

        if event not in (REVIEW_EVENT_COMMENT, REVIEW_EVENT_REQUEST_CHANGES, REVIEW_EVENT_APPROVE):
            raise ValueError(f"Invalid review event: {event}")

        url = f"{_GH_API}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        payload: dict = {"body": body, "event": event}

        if commit_id:
            payload["commit_id"] = commit_id

        if inline_comments:
            # Convert to GitHub's comment format: {path, line, body}
            payload["comments"] = [
                {"path": c["path"], "line": c["line"], "body": c["body"]}
                for c in inline_comments
                if "path" in c and "line" in c and "body" in c
            ]

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=_gh_headers(self.github_token), json=payload)

        if resp.status_code in (200, 201):
            review_data = resp.json()
            log.info(
                "[PRReviewTools] Review posted on %s/%s PR#%d — event=%s id=%s",
                owner, repo, pr_number, event, review_data.get("id"),
            )
            return {
                "status": "review_posted",
                "review_id": review_data.get("id"),
                "review_url": review_data.get("html_url", ""),
                "event": event,
            }

        log.error("[PRReviewTools] post_pr_review failed: %d %s", resp.status_code, resp.text[:200])
        raise RuntimeError(f"GitHub review API error {resp.status_code}: {resp.text[:200]}")

    async def post_pr_comment(
        self, owner: str, repo: str, pr_number: int, body: str
    ) -> dict:
        """
        Post a plain issue comment on a PR (not a formal review).
        Ref: https://docs.github.com/en/rest/issues/comments#create-an-issue-comment
        """
        if not self.github_token:
            raise EnvironmentError("GITHUB_TOKEN not configured for this workspace")

        url = f"{_GH_API}/repos/{owner}/{repo}/issues/{pr_number}/comments"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=_gh_headers(self.github_token), json={"body": body})

        if resp.status_code in (200, 201):
            comment_url = resp.json().get("html_url", "")
            log.info("[PRReviewTools] Comment posted: %s", comment_url)
            return {"status": "comment_posted", "comment_url": comment_url}

        raise RuntimeError(f"GitHub comment API error {resp.status_code}: {resp.text[:200]}")

    # ──────────────────────────────────────────────
    # Routing
    # ──────────────────────────────────────────────

    async def execute_option(self, option: dict, context: dict) -> dict:
        """
        Dispatch to correct review action based on approved option.
        context must include: owner, repo, pr_number, review_body, head_sha
        """
        option_id = option.get("id", "")
        owner = context["owner"]
        repo = context["repo"]
        pr_number = context["pr_number"]
        review_body = context.get("review_body", "")
        head_sha = context.get("head_sha")
        inline_comments = context.get("inline_comments")

        log.info("[PRReviewTools] Executing option '%s' on %s/%s PR#%d", option_id, owner, repo, pr_number)

        if option_id == "hold":
            return {"status": "held", "message": "Operator chose to review manually"}

        if option_id == "opt_1":
            # Request changes — blocks the PR from merging
            return await self.post_pr_review(
                owner, repo, pr_number,
                body=review_body,
                event=REVIEW_EVENT_REQUEST_CHANGES,
                commit_id=head_sha,
                inline_comments=inline_comments,
            )

        if option_id == "opt_2":
            # Post as comment — informational, does not block merge
            return await self.post_pr_review(
                owner, repo, pr_number,
                body=review_body,
                event=REVIEW_EVENT_COMMENT,
                commit_id=head_sha,
            )

        if option_id == "opt_3":
            # Approve with comments
            return await self.post_pr_review(
                owner, repo, pr_number,
                body=review_body,
                event=REVIEW_EVENT_APPROVE,
                commit_id=head_sha,
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
