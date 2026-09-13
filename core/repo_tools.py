"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

RepoTools -- provider-agnostic repository read/write interface, decided as
part of item 5's design (Azure DevOps) but built now so item 4's GitHub App
migration lands behind it from day one instead of needing a second rewrite
when Azure DevOps support is added later.

Five operations, exactly as decided:
  read_file(path, ref)                        -- pull IaC from a branch
  list_files(path, ref)                        -- enumerate a directory
  create_branch(name, from_ref)                -- branch before any write
  push_commit(branch, files, message)          -- write the proposed change
  create_pr(branch, title, body, reviewers)    -- surface for HITL approval

GitHubRepoTools lifts the real, already-working logic out of
agents/agent_08_drift_detection/tools.py's create_drift_pr (5-step
get-HEAD-SHA -> create-branch -> get-file-SHA -> commit -> open-PR) rather
than rewriting it -- that flow is unchanged, just reshaped behind this
interface and given a fresh installation token per call instead of a raw
stored PAT header.
"""

import base64
import logging
from abc import ABC, abstractmethod
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_GH_API = "https://api.github.com"
_MAX_HTTP_TIMEOUT = 30


class RepoTools(ABC):
    """Provider-agnostic repo read/write interface. One implementation per
    provider (GitHub, Azure DevOps, ...); agents code against this, never
    against a provider's raw REST shape directly."""

    @abstractmethod
    async def read_file(self, owner: str, repo: str, path: str, ref: str) -> Optional[str]:
        """Returns file content as text, or None if it doesn't exist at ref."""

    @abstractmethod
    async def list_files(self, owner: str, repo: str, path: str, ref: str) -> list[str]:
        """Returns paths of files directly under `path` at ref."""

    @abstractmethod
    async def create_branch(self, owner: str, repo: str, name: str, from_ref: str) -> None:
        """Creates `name` pointing at `from_ref`'s current commit. Idempotent --
        does not raise if the branch already exists."""

    @abstractmethod
    async def push_commit(self, owner: str, repo: str, branch: str, files: dict[str, str], message: str) -> str:
        """Commits `files` (path -> content) to `branch`. Returns the new commit sha."""

    @abstractmethod
    async def create_pr(
        self, owner: str, repo: str, branch: str, title: str, body: str,
        base: str = "main", reviewers: Optional[list[str]] = None,
    ) -> dict:
        """Opens a PR from branch -> base. Returns {"pr_url", "pr_number"}."""


def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


class GitHubRepoTools(RepoTools):
    """
    token: a GitHub App installation access token (core/github_app.py's
    mint_installation_token), NOT a stored PAT -- short-lived (~1hr),
    minted fresh per call site, never persisted.
    """

    def __init__(self, token: str):
        if not token:
            raise ValueError("GitHubRepoTools requires a non-empty installation token")
        self._token = token

    async def read_file(self, owner: str, repo: str, path: str, ref: str) -> Optional[str]:
        async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{_GH_API}/repos/{owner}/{repo}/contents/{path}",
                headers=_gh_headers(self._token),
                params={"ref": ref},
            )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise RuntimeError(f"Could not read {path}@{ref}: {resp.status_code}")
        body = resp.json()
        if isinstance(body, list):
            raise RuntimeError(f"{path} is a directory, not a file")
        return base64.b64decode(body["content"]).decode()

    async def list_files(self, owner: str, repo: str, path: str, ref: str) -> list[str]:
        async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{_GH_API}/repos/{owner}/{repo}/contents/{path}",
                headers=_gh_headers(self._token),
                params={"ref": ref},
            )
        if resp.status_code == 404:
            return []
        if resp.status_code != 200:
            raise RuntimeError(f"Could not list {path}@{ref}: {resp.status_code}")
        body = resp.json()
        if not isinstance(body, list):
            raise RuntimeError(f"{path} is a file, not a directory")
        return [entry["path"] for entry in body if entry.get("type") == "file"]

    async def create_branch(self, owner: str, repo: str, name: str, from_ref: str) -> None:
        async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
            ref_resp = await client.get(
                f"{_GH_API}/repos/{owner}/{repo}/git/refs/heads/{from_ref}",
                headers=_gh_headers(self._token),
            )
            if ref_resp.status_code != 200:
                raise RuntimeError(f"Could not get HEAD ref for '{from_ref}': {ref_resp.status_code}")
            head_sha = ref_resp.json()["object"]["sha"]

            branch_resp = await client.post(
                f"{_GH_API}/repos/{owner}/{repo}/git/refs",
                headers=_gh_headers(self._token),
                json={"ref": f"refs/heads/{name}", "sha": head_sha},
            )
            # 422 = ref already exists -- idempotent, not an error here.
            if branch_resp.status_code not in (200, 201, 422):
                raise RuntimeError(f"Could not create branch '{name}': {branch_resp.status_code}")

    async def push_commit(self, owner: str, repo: str, branch: str, files: dict[str, str], message: str) -> str:
        last_sha = ""
        async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
            for path, content in files.items():
                file_sha = None
                file_resp = await client.get(
                    f"{_GH_API}/repos/{owner}/{repo}/contents/{path}",
                    headers=_gh_headers(self._token),
                    params={"ref": branch},
                )
                if file_resp.status_code == 200:
                    file_sha = file_resp.json().get("sha")

                commit_body: dict = {
                    "message": message,
                    "content": base64.b64encode(content.encode()).decode(),
                    "branch": branch,
                }
                if file_sha:
                    commit_body["sha"] = file_sha

                commit_resp = await client.put(
                    f"{_GH_API}/repos/{owner}/{repo}/contents/{path}",
                    headers=_gh_headers(self._token),
                    json=commit_body,
                )
                if commit_resp.status_code not in (200, 201):
                    raise RuntimeError(f"Could not commit {path}: {commit_resp.status_code}")
                last_sha = commit_resp.json().get("commit", {}).get("sha", "")

        return last_sha

    async def create_pr(
        self, owner: str, repo: str, branch: str, title: str, body: str,
        base: str = "main", reviewers: Optional[list[str]] = None,
    ) -> dict:
        async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
            pr_resp = await client.post(
                f"{_GH_API}/repos/{owner}/{repo}/pulls",
                headers=_gh_headers(self._token),
                json={"title": title, "body": body, "head": branch, "base": base},
            )
            if pr_resp.status_code not in (200, 201):
                raise RuntimeError(f"Could not open PR: {pr_resp.status_code}")
            pr = pr_resp.json()

            if reviewers:
                await client.post(
                    f"{_GH_API}/repos/{owner}/{repo}/pulls/{pr['number']}/requested_reviewers",
                    headers=_gh_headers(self._token),
                    json={"reviewers": reviewers},
                )

        log.info("[GitHubRepoTools] PR created: %s", pr.get("html_url"))
        return {"pr_url": pr.get("html_url", ""), "pr_number": pr.get("number")}
