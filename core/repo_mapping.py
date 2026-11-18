"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Where a cloud resource's IaC lives (G13, migration 063).

Resolution order for one resource:
  1. owner/repo in the alert payload itself (explicit always wins)
  2. the longest workspace rule whose prefix the resource ID starts with
     (case-insensitive: Azure resource IDs are)
  3. the workspace default rule
  4. nothing -- the agent offers no PR option and says why
"""

import re
from dataclasses import dataclass
from typing import Optional

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class RepoTarget:
    owner: str
    repo: str
    base_branch: str
    iac_path: str
    source: str  # "alert" | "rule" | "default"

    @property
    def repository(self) -> str:
        return f"{self.owner}/{self.repo}"


def validate_mapping(repository: str, iac_path: str, base_branch: str, match_prefix: Optional[str]) -> None:
    """Raises ValueError with an operator-facing reason."""
    if not _REPO.match(repository or ""):
        raise ValueError(f"repository must be 'owner/repo', got {repository!r}")
    path = (iac_path or "").strip()
    if not path.endswith(".tf"):
        raise ValueError("iac_path must be a repo-relative .tf file")
    if path.startswith("/") or ".." in path.split("/"):
        raise ValueError("iac_path must be relative to the repo root, without '..'")
    if not (base_branch or "").strip():
        raise ValueError("base_branch is required")
    if match_prefix is not None and not match_prefix.strip():
        raise ValueError("a rule's resource prefix can't be blank (leave it out for the workspace default)")


def match_rule(rules: list[dict], resource_id: str) -> Optional[dict]:
    """Longest matching prefix rule, else the default rule (match_prefix None)."""
    rid = (resource_id or "").lower()
    prefixed = [r for r in rules if r.get("match_prefix") and rid.startswith(r["match_prefix"].lower())]
    if prefixed:
        return max(prefixed, key=lambda r: len(r["match_prefix"]))
    return next((r for r in rules if not r.get("match_prefix")), None)


def target_from_alert(payload: dict) -> Optional[RepoTarget]:
    owner, repo = payload.get("owner") or "", payload.get("repo") or ""
    if not (owner and repo):
        return None
    return RepoTarget(owner, repo, payload.get("base_branch") or "main",
                      payload.get("file_path") or "", "alert")


async def resolve_repo_target(db, workspace_id, resource_id: str, payload: dict) -> Optional[RepoTarget]:
    explicit = target_from_alert(payload or {})
    if explicit:
        return explicit
    # db: the agent's pool or connection (both support fetch), same as HITLGate.
    rows = await db.fetch(
        "SELECT match_prefix, repository, base_branch, iac_path FROM workspace_repo_mappings "
        "WHERE workspace_id = $1",
        workspace_id,
    )
    rule = match_rule([dict(r) for r in rows], resource_id)
    if not rule:
        return None
    owner, _, repo = rule["repository"].partition("/")
    return RepoTarget(owner, repo, rule["base_branch"], rule["iac_path"],
                      "rule" if rule.get("match_prefix") else "default")
