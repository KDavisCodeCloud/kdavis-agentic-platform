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
Agent 10 — Dependency & Vulnerability Patching execution tools.

Supported ecosystems:
  npm   — package.json (dependencies + devDependencies)
  pip   — requirements.txt
  go    — go.mod (require blocks)
  maven — pom.xml (<dependency> elements)
  ruby  — Gemfile.lock (GEM/specs section)
  cargo — Cargo.toml ([dependencies] sections)

Read-only (runs pre-HITL inside diagnose node):
  fetch_manifest()   — reads dependency manifest from GitHub
  parse_manifest()   — parses manifest into [{name, version}] list
  query_osv_batch()  — checks OSV.dev for known vulnerabilities

Post-HITL actions (all require operator approval):
  create_patch_pr()          — opens a PR with patched manifest
  create_vulnerability_issue() — creates a GitHub tracking issue

Governance Rule 11: no PR or issue is created without operator approval.
"""

import base64
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_GH_API             = "https://api.github.com"
_OSV_API            = "https://api.osv.dev/v1"
_MAX_HTTP_TIMEOUT   = 30
_MAX_OSV_QUERIES    = 40   # cap per scan to stay within rate limits

_OSV_ECOSYSTEM_MAP = {
    "npm":   "npm",
    "pip":   "PyPI",
    "go":    "Go",
    "maven": "Maven",
    "ruby":  "RubyGems",
    "cargo": "crates.io",
}


class DependencyPatchTools:
    """Manifest fetching, vulnerability scanning, and patch publishing for Agent 10."""

    def __init__(self, github_token: Optional[str] = None):
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN", "")

    # ──────────────────────────────────────────────
    # Read-only knowledge gathering (pre-HITL)
    # ──────────────────────────────────────────────

    async def fetch_manifest(
        self,
        owner: str,
        repo: str,
        file_path: str,
        ref: str = "HEAD",
    ) -> dict:
        """
        Fetch a dependency manifest from GitHub.
        Returns {path, url, content, sha} or {error}.
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
        content = base64.b64decode(data.get("content", "")).decode(errors="replace")
        return {
            "path":    data.get("path", file_path),
            "url":     data.get("html_url", ""),
            "content": content,
            "sha":     data.get("sha", ""),
        }

    def parse_manifest(self, content: str, ecosystem: str) -> list[dict]:
        """
        Parse a dependency manifest file into a list of {name, version} dicts.
        Returns [] for unrecognized formats or parse failures.
        """
        ecosystem = ecosystem.lower()
        parsers = {
            "npm":   _parse_package_json,
            "pip":   _parse_requirements_txt,
            "go":    _parse_go_mod,
            "maven": _parse_pom_xml,
            "ruby":  _parse_gemfile_lock,
            "cargo": _parse_cargo_toml,
        }
        parser = parsers.get(ecosystem)
        if not parser:
            return []
        try:
            return parser(content)
        except Exception as exc:
            log.warning("[DependencyPatch] parse_manifest failed for %s: %s", ecosystem, exc)
            return []

    async def query_osv_batch(
        self,
        packages: list[dict],
        ecosystem: str,
    ) -> list[dict]:
        """
        Query OSV.dev for vulnerabilities in a list of packages.
        packages: [{name, version}]
        Returns only packages that have vulnerabilities:
          [{package, version, vulnerabilities: [{id, summary, severity, aliases, fixed_in}]}]
        Never raises — skips packages that fail and continues.
        """
        osv_ecosystem = _OSV_ECOSYSTEM_MAP.get(ecosystem.lower(), ecosystem)
        results = []

        for pkg in packages[:_MAX_OSV_QUERIES]:
            version = pkg.get("version", "")
            if not version:
                continue
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        f"{_OSV_API}/query",
                        json={
                            "package": {
                                "name": pkg["name"],
                                "ecosystem": osv_ecosystem,
                            },
                            "version": version,
                        },
                    )
            except httpx.RequestError as exc:
                log.warning("[DependencyPatch] OSV query failed for %s: %s", pkg["name"], exc)
                continue

            if resp.status_code != 200:
                log.warning(
                    "[DependencyPatch] OSV returned %d for %s@%s",
                    resp.status_code, pkg["name"], version,
                )
                continue

            vulns = resp.json().get("vulns", [])
            if vulns:
                results.append({
                    "package": pkg["name"],
                    "version": version,
                    "vulnerabilities": [
                        {
                            "id":       v.get("id", ""),
                            "summary":  v.get("summary", "")[:200],
                            "severity": _extract_severity(v),
                            "aliases":  v.get("aliases", [])[:5],
                            "fixed_in": _extract_fixed_version(v, pkg["name"]),
                        }
                        for v in vulns
                    ],
                })

        return results

    # ──────────────────────────────────────────────
    # Post-HITL publishing actions
    # ──────────────────────────────────────────────

    async def create_patch_pr(
        self,
        owner: str,
        repo: str,
        branch_name: str,
        file_path: str,
        file_sha: str,
        patched_content: str,
        pr_body: str,
        base_branch: str = "main",
        pr_title: str = "chore(deps): security patch — update vulnerable dependencies",
        commit_message: str = "chore(deps): update vulnerable dependencies [Cloud Decoded]",
    ) -> dict:
        """
        Open a PR that updates the manifest to patch vulnerable dependencies.
        Uses the standard 5-step GitHub flow (get HEAD SHA → create branch →
        commit file → open PR).
        Never runs package install commands — the CI pipeline handles that.
        """
        if not self.github_token:
            raise EnvironmentError("GITHUB_TOKEN not configured")

        headers = _gh_headers(self.github_token)

        async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
            # Step 1: get HEAD SHA of base branch
            ref_resp = await client.get(
                f"{_GH_API}/repos/{owner}/{repo}/git/ref/heads/{base_branch}",
                headers=headers,
            )
            if ref_resp.status_code != 200:
                raise RuntimeError(
                    f"Cannot get HEAD SHA for {base_branch}: {ref_resp.status_code}"
                )
            head_sha = ref_resp.json()["object"]["sha"]

            # Step 2: create patch branch
            branch_resp = await client.post(
                f"{_GH_API}/repos/{owner}/{repo}/git/refs",
                headers=headers,
                json={"ref": f"refs/heads/{branch_name}", "sha": head_sha},
            )
            # 422 = branch already exists; proceed
            if branch_resp.status_code not in (200, 201, 422):
                raise RuntimeError(f"Branch creation failed: {branch_resp.status_code}")

            # Step 3: commit patched manifest
            commit_resp = await client.put(
                f"{_GH_API}/repos/{owner}/{repo}/contents/{file_path}",
                headers=headers,
                json={
                    "message": commit_message,
                    "content": base64.b64encode(patched_content.encode()).decode(),
                    "sha":     file_sha,
                    "branch":  branch_name,
                },
            )
            if commit_resp.status_code not in (200, 201):
                raise RuntimeError(f"Commit failed: {commit_resp.status_code}")

            # Step 4: open PR
            pr_resp = await client.post(
                f"{_GH_API}/repos/{owner}/{repo}/pulls",
                headers=headers,
                json={
                    "title": pr_title,
                    "body":  pr_body,
                    "head":  branch_name,
                    "base":  base_branch,
                },
            )
            if pr_resp.status_code not in (200, 201):
                raise RuntimeError(
                    f"PR creation failed {pr_resp.status_code}: {pr_resp.text[:200]}"
                )

        pr = pr_resp.json()
        log.info("[DependencyPatch] Patch PR created: %s", pr.get("html_url"))
        return {
            "status":    "pr_created",
            "pr_url":    pr.get("html_url", ""),
            "pr_number": pr.get("number"),
            "branch":    branch_name,
        }

    async def create_vulnerability_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
    ) -> dict:
        """Create a GitHub issue to track vulnerabilities for manual remediation."""
        if not self.github_token:
            raise EnvironmentError("GITHUB_TOKEN not configured")

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
            raise RuntimeError(
                f"Issue creation failed {resp.status_code}: {resp.text[:200]}"
            )

        issue = resp.json()
        log.info("[DependencyPatch] Vulnerability issue created: %s", issue.get("html_url"))
        return {
            "status":       "issue_created",
            "issue_url":    issue.get("html_url", ""),
            "issue_number": issue.get("number"),
        }

    async def execute_option(self, option: dict, context: dict) -> dict:
        """
        Dispatch to the approved remediation action.

        context must include:
          owner, repo, branch_name, file_path, file_sha, patched_content,
          pr_body, pr_title, base_branch, issue_title, issue_body
        """
        option_id = option.get("id", "")
        log.info("[DependencyPatch] Executing approved option '%s'", option_id)

        if option_id == "hold":
            return {
                "status":  "held",
                "message": "Vulnerability report available in operator dashboard",
            }

        owner = context.get("owner", "")
        repo  = context.get("repo",  "")

        if not owner or not repo:
            return {"status": "skipped", "reason": "repository not configured"}

        if option_id == "opt_1":
            # Patch PR only
            if not context.get("patched_content"):
                return {
                    "status": "skipped",
                    "reason": "LLM did not generate a patched manifest — use opt_2 to create a tracking issue instead",
                }
            return await self.create_patch_pr(
                owner=owner,
                repo=repo,
                branch_name=context["branch_name"],
                file_path=context["file_path"],
                file_sha=context["file_sha"],
                patched_content=context["patched_content"],
                pr_body=context["pr_body"],
                base_branch=context.get("base_branch", "main"),
                pr_title=context.get("pr_title", "chore(deps): security patch"),
            )

        if option_id == "opt_2":
            # Vulnerability tracking issue only
            return await self.create_vulnerability_issue(
                owner=owner,
                repo=repo,
                title=context["issue_title"],
                body=context["issue_body"],
                labels=["security", "vulnerability", "dependencies"],
            )

        if option_id == "opt_3":
            # Patch PR + tracking issue
            results: dict = {}
            if context.get("patched_content"):
                pr_result = await self.create_patch_pr(
                    owner=owner,
                    repo=repo,
                    branch_name=context["branch_name"],
                    file_path=context["file_path"],
                    file_sha=context["file_sha"],
                    patched_content=context["patched_content"],
                    pr_body=context["pr_body"],
                    base_branch=context.get("base_branch", "main"),
                    pr_title=context.get("pr_title", "chore(deps): security patch"),
                )
                results["pr_url"]    = pr_result.get("pr_url")
                results["pr_number"] = pr_result.get("pr_number")
            issue_result = await self.create_vulnerability_issue(
                owner=owner,
                repo=repo,
                title=context["issue_title"],
                body=context["issue_body"],
                labels=["security", "vulnerability", "dependencies"],
            )
            results["status"]       = "pr_and_issue_created" if results.get("pr_url") else "issue_created"
            results["issue_url"]    = issue_result.get("issue_url")
            results["issue_number"] = issue_result.get("issue_number")
            return results

        return {"status": "not_implemented", "option_id": option_id}


# ──────────────────────────────────────────────
# Manifest parsers (pure Python, no shell)
# ──────────────────────────────────────────────

def _parse_package_json(content: str) -> list[dict]:
    data = json.loads(content)
    deps: dict = {}
    deps.update(data.get("dependencies", {}))
    deps.update(data.get("devDependencies", {}))
    result = []
    for name, ver_spec in deps.items():
        # strip leading ^ ~ >= <= < > = and whitespace
        version = re.sub(r"^[\^~>=<\s]+", "", str(ver_spec)).strip()
        result.append({"name": name, "version": version})
    return result


def _parse_requirements_txt(content: str) -> list[dict]:
    result = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-", ".")):
            continue
        # requests==2.28.0  |  Django>=4.0  |  flask~=2.3.0
        match = re.match(r"^([A-Za-z0-9_\-\.]+)\s*[=~!<>]+\s*([^\s;#,]+)", line)
        if match:
            version = match.group(2).lstrip("=")
            result.append({"name": match.group(1), "version": version})
        else:
            pkg = re.match(r"^([A-Za-z0-9_\-\.]+)", line)
            if pkg:
                result.append({"name": pkg.group(1), "version": ""})
    return result


def _parse_go_mod(content: str) -> list[dict]:
    result = []
    in_require = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "require (":
            in_require = True
            continue
        if stripped == ")" and in_require:
            in_require = False
            continue
        # single-line: require github.com/pkg/errors v0.9.1
        target = stripped if in_require else (
            stripped[len("require "):] if stripped.startswith("require ") else ""
        )
        if not target:
            continue
        match = re.match(r"^(\S+)\s+v([^\s//]+)", target)
        if match:
            result.append({"name": match.group(1), "version": match.group(2)})
    return result


def _parse_pom_xml(content: str) -> list[dict]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    result = []
    for dep in root.findall(".//m:dependency", ns) or root.findall(".//dependency"):
        group    = (dep.findtext("m:groupId",    namespaces=ns) or dep.findtext("groupId")    or "").strip()
        artifact = (dep.findtext("m:artifactId", namespaces=ns) or dep.findtext("artifactId") or "").strip()
        version  = (dep.findtext("m:version",    namespaces=ns) or dep.findtext("version")    or "").strip()
        if group and artifact:
            # Skip Maven property placeholders like ${spring.version}
            ver = version if not version.startswith("${") else ""
            result.append({"name": f"{group}:{artifact}", "version": ver})
    return result


def _parse_gemfile_lock(content: str) -> list[dict]:
    result = []
    in_specs = False
    for line in content.splitlines():
        if line.strip() == "specs:":
            in_specs = True
            continue
        if in_specs:
            if line and not line[0].isspace():
                in_specs = False
                continue
            # "    gem_name (1.2.3)"  — 4-space indent for top-level gems
            match = re.match(r"^ {4}([A-Za-z0-9_\-\.]+)\s+\(([^\)]+)\)$", line)
            if match:
                version = match.group(2).split(",")[0].strip()
                result.append({"name": match.group(1), "version": version})
    return result


def _parse_cargo_toml(content: str) -> list[dict]:
    result = []
    in_deps = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped in ("[dependencies]", "[dev-dependencies]", "[build-dependencies]"):
            in_deps = True
            continue
        if stripped.startswith("[") and in_deps:
            in_deps = False
            continue
        if not in_deps:
            continue
        # serde = "1.0.160"
        m = re.match(r'^([A-Za-z0-9_\-]+)\s*=\s*"([^"]+)"', stripped)
        if m:
            result.append({"name": m.group(1), "version": m.group(2)})
            continue
        # serde = { version = "1.0", features = ["derive"] }
        m2 = re.match(r'^([A-Za-z0-9_\-]+)\s*=\s*\{[^}]*version\s*=\s*"([^"]+)"', stripped)
        if m2:
            result.append({"name": m2.group(1), "version": m2.group(2)})
    return result


# ──────────────────────────────────────────────
# OSV helpers
# ──────────────────────────────────────────────

def _extract_severity(vuln: dict) -> str:
    """
    Extract severity category from an OSV vulnerability record.
    Prefers GitHub Advisory database_specific.severity (CRITICAL/HIGH/MEDIUM/LOW).
    Falls back to UNKNOWN when not available.
    """
    return vuln.get("database_specific", {}).get("severity", "UNKNOWN").upper()


def _extract_fixed_version(vuln: dict, package_name: str) -> str:
    """Return the earliest fixed version for a package from an OSV record."""
    for affected in vuln.get("affected", []):
        pkg = affected.get("package", {})
        if pkg.get("name", "").lower() != package_name.lower():
            continue
        for rng in affected.get("ranges", []):
            for event in rng.get("events", []):
                if "fixed" in event:
                    return event["fixed"]
    return ""


def _gh_headers(token: str) -> dict:
    return {
        "Authorization":      f"Bearer {token}",
        "Accept":             "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
