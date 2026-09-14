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

AzureDevOpsRepoTools (item 5) implements the same five operations against
the Azure DevOps Git REST API (api-version=7.1), authenticated with a
per-workspace PAT (core/workspace_credentials.py's build_agent_credentials,
migration 024) instead of GitHub's App installation token -- Azure DevOps
has no equivalent App/OAuth flow available without a separate Marketplace
publisher-verification process, so a PAT is the correct mechanism here, not
a stopgap. One interface adaptation, documented on the class itself:
Azure DevOps addresses a repo as org/project/repository (three parts) where
GitHub uses owner/repo (two) -- the org is bound once at construction
(a workspace's PAT is already scoped to one org), and `owner` in every
RepoTools call is read as the Azure DevOps *project* name.

get_repo_tools() (Phase 2, connectivity gap roadmap) is the provider-
selection factory every credentialed agent that writes to a repo
(agents 04/08/10) now goes through, replacing three separate hand-rolled
copies of the same 5-step GitHub flow this module already centralizes.
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


_ADO_API = "https://dev.azure.com"
_ADO_API_VERSION = "7.1"
_ADO_NULL_OBJECT_ID = "0000000000000000000000000000000000000000"


def _ado_headers(pat: str) -> dict:
    basic = base64.b64encode(f":{pat}".encode()).decode()
    return {"Authorization": f"Basic {basic}", "Content-Type": "application/json"}


class AzureDevOpsRepoTools(RepoTools):
    """
    org: the Azure DevOps organization this PAT is scoped to -- bound once
    here rather than passed per call, since a workspace's stored PAT
    (migration 024) already belongs to exactly one org.
    pat: a workspace's stored Azure DevOps Personal Access Token
    (core/workspace_credentials.py's build_agent_credentials), scoped to
    Code (Read & Write) on that org. Never a fresh short-lived token like
    GitHubRepoTools' installation token -- Azure DevOps PATs are the
    credential itself, decrypted per-call, never persisted beyond the
    request (same discipline as every other credential in this codebase).

    Every RepoTools `owner` parameter is read as the Azure DevOps *project*
    name -- see this module's docstring for why.
    """

    def __init__(self, org: str, pat: str):
        if not org:
            raise ValueError("AzureDevOpsRepoTools requires a non-empty org")
        if not pat:
            raise ValueError("AzureDevOpsRepoTools requires a non-empty pat")
        self._org = org
        self._pat = pat

    def _repo_url(self, project: str, repo: str) -> str:
        return f"{_ADO_API}/{self._org}/{project}/_apis/git/repositories/{repo}"

    async def read_file(self, owner: str, repo: str, path: str, ref: str) -> Optional[str]:
        async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{self._repo_url(owner, repo)}/items",
                headers=_ado_headers(self._pat),
                params={
                    "path": path,
                    "versionDescriptor.version": ref,
                    "includeContent": "true",
                    "api-version": _ADO_API_VERSION,
                },
            )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise RuntimeError(f"Could not read {path}@{ref}: {resp.status_code}")
        body = resp.json()
        if body.get("isFolder"):
            raise RuntimeError(f"{path} is a directory, not a file")
        return body.get("content")

    async def list_files(self, owner: str, repo: str, path: str, ref: str) -> list[str]:
        async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{self._repo_url(owner, repo)}/items",
                headers=_ado_headers(self._pat),
                params={
                    "scopePath": path,
                    "recursionLevel": "OneLevel",
                    "versionDescriptor.version": ref,
                    "api-version": _ADO_API_VERSION,
                },
            )
        if resp.status_code == 404:
            return []
        if resp.status_code != 200:
            raise RuntimeError(f"Could not list {path}@{ref}: {resp.status_code}")
        entries = resp.json().get("value", [])
        return [
            entry["path"] for entry in entries
            if entry.get("gitObjectType") == "blob" and entry.get("path") != path
        ]

    async def _ref_object_id(self, client: httpx.AsyncClient, owner: str, repo: str, branch: str) -> Optional[str]:
        resp = await client.get(
            f"{self._repo_url(owner, repo)}/refs",
            headers=_ado_headers(self._pat),
            params={"filter": f"heads/{branch}", "api-version": _ADO_API_VERSION},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Could not look up ref '{branch}': {resp.status_code}")
        matches = resp.json().get("value", [])
        return matches[0]["objectId"] if matches else None

    async def create_branch(self, owner: str, repo: str, name: str, from_ref: str) -> None:
        async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
            if await self._ref_object_id(client, owner, repo, name) is not None:
                return  # idempotent -- branch already exists

            head_sha = await self._ref_object_id(client, owner, repo, from_ref)
            if not head_sha:
                raise RuntimeError(f"Could not get HEAD ref for '{from_ref}'")

            resp = await client.post(
                f"{self._repo_url(owner, repo)}/refs",
                headers=_ado_headers(self._pat),
                params={"api-version": _ADO_API_VERSION},
                json=[{"name": f"refs/heads/{name}", "oldObjectId": _ADO_NULL_OBJECT_ID, "newObjectId": head_sha}],
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Could not create branch '{name}': {resp.status_code}")
            result = resp.json().get("value", [{}])[0]
            if not result.get("success", False):
                raise RuntimeError(f"Could not create branch '{name}': {result.get('customMessage', 'unknown error')}")

    async def push_commit(self, owner: str, repo: str, branch: str, files: dict[str, str], message: str) -> str:
        async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
            old_object_id = await self._ref_object_id(client, owner, repo, branch)
            if not old_object_id:
                raise RuntimeError(f"Could not find branch '{branch}' to push to")

            changes = []
            for path, content in files.items():
                exists = await self.read_file(owner, repo, path, branch) is not None
                changes.append({
                    "changeType": "edit" if exists else "add",
                    "item": {"path": path},
                    "newContent": {"content": content, "contentType": "rawtext"},
                })

            resp = await client.post(
                f"{self._repo_url(owner, repo)}/pushes",
                headers=_ado_headers(self._pat),
                params={"api-version": _ADO_API_VERSION},
                json={
                    "refUpdates": [{"name": f"refs/heads/{branch}", "oldObjectId": old_object_id}],
                    "commits": [{"comment": message, "changes": changes}],
                },
            )
            if resp.status_code not in (200, 201):
                raise RuntimeError(f"Could not push commit to '{branch}': {resp.status_code} {resp.text[:200]}")
            commits = resp.json().get("commits", [])

        return commits[0]["commitId"] if commits else ""

    async def create_pr(
        self, owner: str, repo: str, branch: str, title: str, body: str,
        base: str = "main", reviewers: Optional[list[str]] = None,
    ) -> dict:
        if reviewers:
            # Azure DevOps PR reviewers are addressed by resolved identity
            # descriptor/GUID, not a login string or email -- unlike GitHub's
            # simple `reviewers: [login, ...]`. No identity-resolution API is
            # wired up here, so this degrades gracefully (PR still opens)
            # rather than silently dropping reviewers or guessing an ID that
            # would 404. Add identity resolution before relying on this.
            log.warning(
                "[AzureDevOpsRepoTools] reviewers=%s requested but not settable -- "
                "Azure DevOps needs resolved identity IDs, not login names; PR opened without reviewers",
                reviewers,
            )

        async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{self._repo_url(owner, repo)}/pullrequests",
                headers=_ado_headers(self._pat),
                params={"api-version": _ADO_API_VERSION},
                json={
                    "sourceRefName": f"refs/heads/{branch}",
                    "targetRefName": f"refs/heads/{base}",
                    "title": title,
                    "description": body,
                },
            )
            if resp.status_code not in (200, 201):
                raise RuntimeError(f"Could not open PR: {resp.status_code} {resp.text[:200]}")
            pr = resp.json()

        pr_id = pr.get("pullRequestId")
        pr_url = f"{_ADO_API}/{self._org}/{owner}/_git/{repo}/pullrequest/{pr_id}" if pr_id else ""
        log.info("[AzureDevOpsRepoTools] PR created: %s", pr_url)
        return {"pr_url": pr_url, "pr_number": pr_id}


class NoRepoCredentialError(Exception):
    """Raised when a workspace has neither GitHub nor Azure DevOps
    credentials configured -- surfaced with a clear, actionable message
    rather than a generic AttributeError from a None RepoTools."""


def get_repo_tools(
    github_token: Optional[str] = None,
    azure_devops_token: Optional[str] = None,
    azure_devops_org: Optional[str] = None,
) -> RepoTools:
    """
    Provider-selection factory. GitHub takes priority when a workspace
    somehow has both configured -- matches build_agent_credentials' own
    GitHub-App-over-legacy-PAT priority convention; in practice a workspace
    connects one provider, not both.

    Raises NoRepoCredentialError (not a bare RuntimeError from deep inside
    a *Tools() method) when neither is configured, so a caller's error
    message actually tells the operator what to do.
    """
    if github_token:
        return GitHubRepoTools(github_token)
    if azure_devops_token and azure_devops_org:
        return AzureDevOpsRepoTools(azure_devops_org, azure_devops_token)
    raise NoRepoCredentialError(
        "No repository credential configured for this workspace -- connect "
        "GitHub (the Cloud Decoded GitHub App) or Azure DevOps (a Personal "
        "Access Token) before this action can run."
    )
