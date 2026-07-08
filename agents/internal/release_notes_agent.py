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
release_notes_agent — turns a completed deploy into release notes.
Triggers on deploy.yml completion (CI wiring is out of scope here — this
module takes a DeploySummary and produces markdown + a releases-table
row; the caller decides when and how to invoke it and where to persist
the result).

Product attribution is inferred from changed file paths using the same
directory convention CLAUDE.md's FOLDER STRUCTURE lays out
(agents/products/{id}/, dashboard/product_template/ instances, etc.) —
a best-effort heuristic, not a guarantee; pass explicit products_affected
when the caller already knows it.

Obsidian push is intentionally not wired here. obsidian/vault_sync.py
currently only exposes push_sop() (SOPs subpath) — CLAUDE.md's vault
folder spec calls for a separate /KDavis Platform/Releases/{version}.md
path that doesn't exist yet there. Rather than extend a file another
session owns, to_obsidian_sink() takes an injectable write callable so
wiring it up later is a one-line change, not a rewrite.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional

# path-prefix -> product_id, used only as a fallback when the caller
# doesn't supply products_affected explicitly.
_PRODUCT_PATH_PATTERNS = [
    re.compile(r"^agents/products/([^/]+)/"),
    re.compile(r"^dashboard/product_template/.*?/([^/]+)/"),
]


def infer_products_affected(changed_files: list[str]) -> list[str]:
    found: set[str] = set()
    for path in changed_files:
        for pattern in _PRODUCT_PATH_PATTERNS:
            match = pattern.match(path)
            if match:
                found.add(match.group(1))
    return sorted(found)


def infer_prompt_version_bumps(changed_files: list[str]) -> list[str]:
    """Any changed file under prompts/**/v*.md is a version bump by
    definition — prompt-version-check.yml already enforces that a PR
    touching prompts/** can't merge without one."""
    return sorted(f for f in changed_files if re.match(r"^prompts/.+/v[\d.]+\.md$", f))


def infer_new_agents_deployed(changed_files: list[str]) -> list[str]:
    """A new agents/internal/*.py or agents/products/*/agent.py file in
    this diff, with no corresponding prior version — approximated here
    as any added agents/internal/{name}.py or agents/products/{id}/agent.py."""
    found: set[str] = set()
    for path in changed_files:
        match = re.match(r"^agents/internal/([a-z0-9_]+)\.py$", path)
        if match and match.group(1) != "__init__":
            found.add(match.group(1))
        match = re.match(r"^agents/products/([^/]+)/agent\.py$", path)
        if match:
            found.add(match.group(1))
    return sorted(found)


@dataclass(frozen=True)
class DeploySummary:
    version: str
    deployed_at: date
    changed_files: list[str]
    commit_messages: list[str]
    products_affected: Optional[list[str]] = None
    prompt_version_bumps: Optional[list[str]] = None
    new_agents_deployed: Optional[list[str]] = None


@dataclass
class ReleaseNote:
    version: str
    deployed_at: date
    what_changed: list[str]
    products_affected: list[str]
    prompt_version_bumps: list[str]
    new_agents_deployed: list[str]

    def to_row(self) -> dict:
        return {
            "version": self.version,
            "date": self.deployed_at.isoformat(),
            "what_changed": self.what_changed,
            "products_affected": self.products_affected,
            "prompt_version_bumps": self.prompt_version_bumps,
            "new_agents_deployed": self.new_agents_deployed,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Release {self.version}",
            f"Date: {self.deployed_at.isoformat()}",
            "",
            "## What changed",
        ]
        lines += [f"- {msg}" for msg in self.what_changed] or ["- (no commit messages recorded)"]
        lines += ["", "## Products affected"]
        lines += [f"- {p}" for p in self.products_affected] or ["- none"]
        if self.prompt_version_bumps:
            lines += ["", "## Prompt version bumps"]
            lines += [f"- {p}" for p in self.prompt_version_bumps]
        if self.new_agents_deployed:
            lines += ["", "## New agents deployed"]
            lines += [f"- {a}" for a in self.new_agents_deployed]
        return "\n".join(lines) + "\n"


class ReleaseNotesAgent:
    def build(self, summary: DeploySummary) -> ReleaseNote:
        return ReleaseNote(
            version=summary.version,
            deployed_at=summary.deployed_at,
            what_changed=list(summary.commit_messages),
            products_affected=(
                summary.products_affected
                if summary.products_affected is not None
                else infer_products_affected(summary.changed_files)
            ),
            prompt_version_bumps=(
                summary.prompt_version_bumps
                if summary.prompt_version_bumps is not None
                else infer_prompt_version_bumps(summary.changed_files)
            ),
            new_agents_deployed=(
                summary.new_agents_deployed
                if summary.new_agents_deployed is not None
                else infer_new_agents_deployed(summary.changed_files)
            ),
        )

    def publish(
        self,
        note: ReleaseNote,
        obsidian_sink: Optional[Callable[[str, str], str]] = None,
    ) -> dict:
        """obsidian_sink(markdown, version) -> path written. Left unset by
        default — see module docstring for why vault_sync.py isn't called
        directly yet."""
        markdown = note.to_markdown()
        result = {"row": note.to_row(), "markdown": markdown, "vault_path": None}
        if obsidian_sink is not None:
            result["vault_path"] = obsidian_sink(markdown, note.version)
        return result
