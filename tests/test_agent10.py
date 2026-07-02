"""
tests/test_agent10.py
Tests for agents/agent_10_dependency_patch/tools.py and workflow.py.

What this file validates:
  _detect_ecosystem():
    - Returns ecosystem from explicit field in payload
    - Auto-detects npm from package.json filename
    - Auto-detects pip from requirements.txt
    - Auto-detects go from go.mod
    - Auto-detects maven from pom.xml
    - Auto-detects ruby from Gemfile.lock
    - Auto-detects cargo from Cargo.toml
    - Explicit field takes priority over manifest filename
    - Returns "unknown" for unrecognized manifests

  DependencyPatchTools.parse_manifest():
    - npm: parses dependencies and devDependencies from package.json
    - npm: strips caret/tilde version prefixes
    - pip: parses pinned requirements.txt entries
    - pip: skips comments, -r includes, blank lines
    - go: parses require blocks from go.mod
    - maven: parses groupId:artifactId and version from pom.xml
    - ruby: parses gem specs from Gemfile.lock
    - cargo: parses [dependencies] from Cargo.toml (simple + inline table)
    - returns [] for unknown ecosystem
    - returns [] on parse error without raising

  DependencyPatchTools.fetch_manifest():
    - returns content, path, url, sha on success
    - returns error dict when GITHUB_TOKEN missing
    - returns error dict on 404

  DependencyPatchTools.query_osv_batch():
    - returns vulnerable packages when OSV finds issues
    - excludes packages with no vulnerabilities
    - handles OSV API error gracefully (continues scan)
    - caps at _MAX_OSV_QUERIES packages
    - skips packages with empty version string

  DependencyPatchTools.create_patch_pr():
    - raises EnvironmentError when GITHUB_TOKEN missing
    - calls GitHub API in correct 5-step sequence
    - returns pr_created with pr_url and pr_number

  DependencyPatchTools.create_vulnerability_issue():
    - raises EnvironmentError when GITHUB_TOKEN missing
    - creates issue with security/vulnerability labels
    - returns issue_created with issue_url and issue_number

  DependencyPatchTools.execute_option():
    - hold → returns held without any API call
    - opt_1 → calls create_patch_pr
    - opt_1 without patched_content → returns skipped
    - opt_1 without repository → returns skipped
    - opt_2 → calls create_vulnerability_issue
    - opt_3 → calls both create_patch_pr and create_vulnerability_issue
    - opt_3 without patched_content → only creates issue
    - unknown option → returns not_implemented

  _count_severity():
    - counts packages with at least one matching severity

  DependencyPatchWorkflow._ingest_node():
    - detects ecosystem from payload
    - extracts repository, manifest_path, ref, base_branch
    - defaults ref to HEAD and base_branch to main
    - initializes all counter fields to 0 / empty

  DependencyPatchWorkflow._diagnose_node():
    - calls fetch_manifest with correct owner, repo, path, ref
    - calls parse_manifest with manifest content and ecosystem
    - calls query_osv_batch with parsed deps and ecosystem
    - calls LLM with task_type="vulnerability_analysis"
    - parses all LLM fields: patch_summary, vulnerable_packages, patched_manifest, options
    - accumulates tokens from prior state
    - sets error when manifest fetch fails
    - sets error on LLM parse failure
    - user message includes ecosystem, manifest path, vulnerability counts

  DependencyPatchWorkflow._hitl_gate_node():
    - calls hitl.create_incident with correct agent_id
    - raw_log includes ecosystem, repository, vulnerability count, severity counts
    - interrupt() includes vulnerability_count, critical_count, high_count
    - skips incident creation when state["error"] is set

  _build_vulnerability_report():
    - includes ecosystem, repository, manifest_path
    - includes severity summary line with critical/high counts
    - includes vulnerable packages table when packages present
    - includes Cloud Decoded attribution
"""

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch, call
from uuid import uuid4

import pytest

from agents.agent_10_dependency_patch.tools import (
    DependencyPatchTools,
    _parse_package_json,
    _parse_requirements_txt,
    _parse_go_mod,
    _parse_pom_xml,
    _parse_gemfile_lock,
    _parse_cargo_toml,
    _extract_severity,
    _extract_fixed_version,
)
from agents.agent_10_dependency_patch.workflow import (
    DependencyPatchWorkflow,
    PatchState,
    _detect_ecosystem,
    _count_severity,
    _build_vulnerability_report,
)


# ──────────────────────────────────────────────────────────────────────────────
# Sample data
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_REQUIREMENTS_TXT = """\
# production dependencies
requests==2.28.0
Django>=4.0,<5.0
flask~=2.3.0
cryptography==39.0.1

# dev
pytest==7.4.0
"""

SAMPLE_PACKAGE_JSON = json.dumps({
    "name": "my-app",
    "version": "1.0.0",
    "dependencies": {
        "express": "^4.18.2",
        "lodash": "~4.17.19",
    },
    "devDependencies": {
        "jest": "29.5.0",
    },
})

SAMPLE_GO_MOD = """\
module github.com/acme/backend

go 1.21

require (
\tgithub.com/pkg/errors v0.9.1
\tgolang.org/x/crypto v0.14.0
)

require github.com/stretchr/testify v1.8.4
"""

SAMPLE_POM_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <dependencies>
    <dependency>
      <groupId>org.springframework</groupId>
      <artifactId>spring-core</artifactId>
      <version>5.3.20</version>
    </dependency>
    <dependency>
      <groupId>com.google.guava</groupId>
      <artifactId>guava</artifactId>
      <version>31.0-jre</version>
    </dependency>
  </dependencies>
</project>
"""

SAMPLE_GEMFILE_LOCK = """\
GEM
  remote: https://rubygems.org/
  specs:
    rails (7.0.4)
      actioncable (= 7.0.4)
    rack (2.2.6)

PLATFORMS
  ruby
"""

SAMPLE_CARGO_TOML = """\
[package]
name = "myapp"
version = "0.1.0"

[dependencies]
serde = "1.0.160"
tokio = { version = "1.28.0", features = ["full"] }
reqwest = "0.11.18"

[dev-dependencies]
mockall = "0.11.4"
"""

SAMPLE_OSV_RESPONSE = {
    "vulns": [
        {
            "id": "GHSA-j8r2-6x86-q33q",
            "summary": "Unintended leak of Proxy-Authorization header in requests",
            "database_specific": {"severity": "HIGH"},
            "aliases": ["CVE-2023-32681"],
            "affected": [
                {
                    "package": {"name": "requests", "ecosystem": "PyPI"},
                    "ranges": [
                        {
                            "type": "ECOSYSTEM",
                            "events": [{"introduced": "0"}, {"fixed": "2.31.0"}],
                        }
                    ],
                }
            ],
        }
    ]
}

SAMPLE_LLM_RESPONSE = json.dumps({
    "parsed_error": "1 HIGH vulnerability found in requirements.txt — requests@2.28.0 has CVE-2023-32681",
    "patch_summary": (
        "One HIGH severity vulnerability was found in requests 2.28.0 (CVE-2023-32681). "
        "The patch updates requests to 2.31.0 which fixes the Proxy-Authorization header leak. "
        "No other breaking changes expected."
    ),
    "vulnerable_packages": [
        {
            "package":         "requests",
            "current_version": "2.28.0",
            "fixed_version":   "2.31.0",
            "severity":        "HIGH",
            "cve_ids":         ["CVE-2023-32681", "GHSA-j8r2-6x86-q33q"],
            "description":     "Unintended leak of Proxy-Authorization header to third-party hosts on redirect",
        }
    ],
    "patched_manifest": (
        "requests==2.31.0\n"
        "Django>=4.0,<5.0\n"
        "flask~=2.3.0\n"
        "cryptography==39.0.1\n"
    ),
    "options": [
        {
            "id":          "opt_1",
            "title":       "Create Patch PR",
            "description": "Open a PR updating requirements.txt to patch the vulnerability",
            "impact":      "LOW",
            "docs_url":    "",
        },
        {
            "id":          "opt_2",
            "title":       "Create Vulnerability Issue",
            "description": "Create a GitHub issue for tracking",
            "impact":      "NONE",
            "docs_url":    "",
        },
        {
            "id":          "opt_3",
            "title":       "Create Patch PR + Issue",
            "description": "Both: patch PR and tracking issue",
            "impact":      "LOW",
            "docs_url":    "",
        },
        {
            "id":          "hold",
            "title":       "Review Only",
            "description": "No action",
            "impact":      "NONE",
            "docs_url":    "",
        },
    ],
})


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_http_resp(status_code: int, body) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = json.dumps(body)[:300] if isinstance(body, (dict, list)) else str(body)[:300]
    return resp


def _make_workflow(mock_db, workspace_id, mock_router) -> DependencyPatchWorkflow:
    with (
        patch("agents.base_agent._load_router", return_value=mock_router),
        patch.object(DependencyPatchWorkflow, "_build_graph", return_value=MagicMock()),
    ):
        wf = DependencyPatchWorkflow(mock_db, workspace_id, MagicMock())
    return wf


def _base_state(workspace_id: str, payload: dict | None = None) -> PatchState:
    return {
        "workspace_id":          workspace_id,
        "cloud_provider":        "aws",
        "webhook_payload":       payload or {},
        "repository":            "",
        "ecosystem":             "",
        "manifest_path":         "",
        "ref":                   "HEAD",
        "base_branch":           "main",
        "manifest_content":      "",
        "manifest_sha":          "",
        "parsed_dependencies":   [],
        "dependency_count":      0,
        "vulnerability_results": [],
        "vulnerability_count":   0,
        "critical_count":        0,
        "high_count":            0,
        "tokens_used":           0,
        "incident_id":           None,
        "parsed_error":          None,
        "patch_summary":         None,
        "vulnerable_packages":   None,
        "patched_manifest":      None,
        "remediation_options":   None,
        "selected_option":       None,
        "execution_result":      None,
        "error":                 None,
    }


def _diagnose_state(workspace_id: str) -> PatchState:
    s = _base_state(workspace_id, {
        "repository":    "acme/backend",
        "ecosystem":     "pip",
        "manifest_path": "requirements.txt",
        "ref":           "main",
    })
    s.update({
        "repository":    "acme/backend",
        "ecosystem":     "pip",
        "manifest_path": "requirements.txt",
        "ref":           "main",
        "base_branch":   "main",
    })
    return s


def _hitl_state(workspace_id: str) -> PatchState:
    s = _diagnose_state(workspace_id)
    parsed = json.loads(SAMPLE_LLM_RESPONSE)
    s.update({
        "manifest_content":      SAMPLE_REQUIREMENTS_TXT,
        "manifest_sha":          "abc123sha",
        "parsed_dependencies":   [{"name": "requests", "version": "2.28.0"}],
        "dependency_count":      4,
        "vulnerability_results": [{"package": "requests", "version": "2.28.0",
                                   "vulnerabilities": [{"id": "GHSA-j8r2-6x86-q33q",
                                                        "severity": "HIGH",
                                                        "summary": "Proxy-Authorization leak",
                                                        "fixed_in": "2.31.0",
                                                        "aliases": ["CVE-2023-32681"]}]}],
        "vulnerability_count":   1,
        "critical_count":        0,
        "high_count":            1,
        "parsed_error":          parsed["parsed_error"],
        "patch_summary":         parsed["patch_summary"],
        "vulnerable_packages":   parsed["vulnerable_packages"],
        "patched_manifest":      parsed["patched_manifest"],
        "remediation_options":   parsed["options"],
        "tokens_used":           2500,
    })
    return s


def _make_context(with_patched: bool = True) -> dict:
    return {
        "owner":           "acme",
        "repo":            "backend",
        "branch_name":     "cloud-decoded/security-patch-abc12345",
        "file_path":       "requirements.txt",
        "file_sha":        "abc123sha",
        "patched_content": SAMPLE_REQUIREMENTS_TXT if with_patched else "",
        "pr_body":         "## Vulnerability Report",
        "pr_title":        "chore(deps): security patch",
        "base_branch":     "main",
        "issue_title":     "[Security] 1 vulnerable dependency in requirements.txt",
        "issue_body":      "## Vulnerability Report",
    }


# ──────────────────────────────────────────────────────────────────────────────
# _detect_ecosystem()
# ──────────────────────────────────────────────────────────────────────────────

class TestDetectEcosystem:
    def test_returns_npm_for_explicit_npm_field(self):
        assert _detect_ecosystem({"ecosystem": "npm", "manifest_path": "requirements.txt"}) == "npm"

    def test_explicit_field_takes_priority_over_filename(self):
        assert _detect_ecosystem({"ecosystem": "pip", "manifest_path": "package.json"}) == "pip"

    def test_detects_npm_from_package_json(self):
        assert _detect_ecosystem({"manifest_path": "package.json"}) == "npm"

    def test_detects_npm_from_nested_path(self):
        assert _detect_ecosystem({"manifest_path": "frontend/package.json"}) == "npm"

    def test_detects_pip_from_requirements_txt(self):
        assert _detect_ecosystem({"manifest_path": "requirements.txt"}) == "pip"

    def test_detects_go_from_go_mod(self):
        assert _detect_ecosystem({"manifest_path": "go.mod"}) == "go"

    def test_detects_maven_from_pom_xml(self):
        assert _detect_ecosystem({"manifest_path": "pom.xml"}) == "maven"

    def test_detects_ruby_from_gemfile_lock(self):
        assert _detect_ecosystem({"manifest_path": "Gemfile.lock"}) == "ruby"

    def test_detects_cargo_from_cargo_toml(self):
        assert _detect_ecosystem({"manifest_path": "Cargo.toml"}) == "cargo"

    def test_returns_unknown_for_unrecognized_manifest(self):
        assert _detect_ecosystem({"manifest_path": "deps.csv"}) == "unknown"


# ──────────────────────────────────────────────────────────────────────────────
# parse_manifest()
# ──────────────────────────────────────────────────────────────────────────────

class TestParseManifest:
    @pytest.fixture
    def tools(self):
        return DependencyPatchTools(github_token="gh_token")

    def test_npm_parses_dependencies_and_dev_dependencies(self, tools):
        result = tools.parse_manifest(SAMPLE_PACKAGE_JSON, "npm")
        names = [d["name"] for d in result]
        assert "express" in names
        assert "lodash" in names
        assert "jest" in names

    def test_npm_strips_caret_prefix(self, tools):
        result = tools.parse_manifest(SAMPLE_PACKAGE_JSON, "npm")
        express = next(d for d in result if d["name"] == "express")
        assert express["version"] == "4.18.2"

    def test_npm_strips_tilde_prefix(self, tools):
        result = tools.parse_manifest(SAMPLE_PACKAGE_JSON, "npm")
        lodash = next(d for d in result if d["name"] == "lodash")
        assert lodash["version"] == "4.17.19"

    def test_pip_parses_pinned_requirements(self, tools):
        result = tools.parse_manifest(SAMPLE_REQUIREMENTS_TXT, "pip")
        names = [d["name"] for d in result]
        assert "requests" in names
        assert "cryptography" in names

    def test_pip_skips_comments_and_blank_lines(self, tools):
        result = tools.parse_manifest(SAMPLE_REQUIREMENTS_TXT, "pip")
        names = [d["name"] for d in result]
        assert "#" not in names
        assert "" not in names

    def test_pip_extracts_correct_version(self, tools):
        result = tools.parse_manifest(SAMPLE_REQUIREMENTS_TXT, "pip")
        req = next(d for d in result if d["name"] == "requests")
        assert req["version"] == "2.28.0"

    def test_go_parses_require_block(self, tools):
        result = tools.parse_manifest(SAMPLE_GO_MOD, "go")
        names = [d["name"] for d in result]
        assert "github.com/pkg/errors" in names
        assert "golang.org/x/crypto" in names

    def test_go_parses_single_line_require(self, tools):
        result = tools.parse_manifest(SAMPLE_GO_MOD, "go")
        names = [d["name"] for d in result]
        assert "github.com/stretchr/testify" in names

    def test_maven_parses_group_and_artifact(self, tools):
        result = tools.parse_manifest(SAMPLE_POM_XML, "maven")
        names = [d["name"] for d in result]
        assert "org.springframework:spring-core" in names
        assert "com.google.guava:guava" in names

    def test_maven_extracts_version(self, tools):
        result = tools.parse_manifest(SAMPLE_POM_XML, "maven")
        spring = next(d for d in result if "spring-core" in d["name"])
        assert spring["version"] == "5.3.20"

    def test_ruby_parses_gemfile_lock_specs(self, tools):
        result = tools.parse_manifest(SAMPLE_GEMFILE_LOCK, "ruby")
        names = [d["name"] for d in result]
        assert "rails" in names
        assert "rack" in names

    def test_cargo_parses_simple_version_string(self, tools):
        result = tools.parse_manifest(SAMPLE_CARGO_TOML, "cargo")
        names = [d["name"] for d in result]
        assert "serde" in names
        assert "reqwest" in names

    def test_cargo_parses_inline_table_version(self, tools):
        result = tools.parse_manifest(SAMPLE_CARGO_TOML, "cargo")
        names = [d["name"] for d in result]
        assert "tokio" in names

    def test_returns_empty_list_for_unknown_ecosystem(self, tools):
        assert tools.parse_manifest("some content", "unknown") == []

    def test_returns_empty_list_on_invalid_json_for_npm(self, tools):
        assert tools.parse_manifest("not json", "npm") == []


# ──────────────────────────────────────────────────────────────────────────────
# DependencyPatchTools.fetch_manifest()
# ──────────────────────────────────────────────────────────────────────────────

class TestFetchManifest:
    @pytest.fixture
    def tools(self):
        return DependencyPatchTools(github_token="gh_test_token")

    async def test_returns_content_path_url_sha_on_success(self, tools):
        raw = "requests==2.31.0\nDjango>=4.0\n"
        encoded = base64.b64encode(raw.encode()).decode()
        gh_resp = _make_http_resp(200, {
            "path": "requirements.txt",
            "html_url": "https://github.com/acme/backend/blob/main/requirements.txt",
            "content": encoded,
            "sha": "abc123sha456",
        })
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__  = AsyncMock(return_value=False)
        ctx.get = AsyncMock(return_value=gh_resp)

        with patch("agents.agent_10_dependency_patch.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.fetch_manifest("acme", "backend", "requirements.txt")

        assert result["path"] == "requirements.txt"
        assert "requests" in result["content"]
        assert result["sha"] == "abc123sha456"

    async def test_returns_error_dict_when_github_token_missing(self):
        no_token = DependencyPatchTools(github_token="")
        result = await no_token.fetch_manifest("acme", "backend", "requirements.txt")
        assert "error" in result

    async def test_returns_error_dict_on_404(self, tools):
        not_found = _make_http_resp(404, {"message": "Not Found"})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__  = AsyncMock(return_value=False)
        ctx.get = AsyncMock(return_value=not_found)

        with patch("agents.agent_10_dependency_patch.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.fetch_manifest("acme", "backend", "requirements.txt")

        assert "error" in result
        assert "404" in result["error"]


# ──────────────────────────────────────────────────────────────────────────────
# DependencyPatchTools.query_osv_batch()
# ──────────────────────────────────────────────────────────────────────────────

class TestQueryOsvBatch:
    @pytest.fixture
    def tools(self):
        return DependencyPatchTools(github_token="gh_test_token")

    async def test_returns_vulnerable_packages_when_osv_finds_issues(self, tools):
        ok_resp = _make_http_resp(200, SAMPLE_OSV_RESPONSE)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__  = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=ok_resp)

        with patch("agents.agent_10_dependency_patch.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.query_osv_batch(
                [{"name": "requests", "version": "2.28.0"}], "pip"
            )

        assert len(result) == 1
        assert result[0]["package"] == "requests"
        assert result[0]["vulnerabilities"][0]["id"] == "GHSA-j8r2-6x86-q33q"

    async def test_excludes_packages_with_no_vulnerabilities(self, tools):
        empty_resp = _make_http_resp(200, {"vulns": []})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__  = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=empty_resp)

        with patch("agents.agent_10_dependency_patch.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.query_osv_batch(
                [{"name": "flask", "version": "3.0.0"}], "pip"
            )

        assert result == []

    async def test_handles_osv_api_error_gracefully(self, tools):
        err_resp = _make_http_resp(500, {"error": "internal"})
        ok_resp  = _make_http_resp(200, SAMPLE_OSV_RESPONSE)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__  = AsyncMock(return_value=False)
        ctx.post = AsyncMock(side_effect=[err_resp, ok_resp])

        with patch("agents.agent_10_dependency_patch.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.query_osv_batch(
                [{"name": "broken", "version": "1.0"}, {"name": "requests", "version": "2.28.0"}],
                "pip",
            )

        assert len(result) == 1
        assert result[0]["package"] == "requests"

    async def test_skips_packages_with_empty_version(self, tools):
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__  = AsyncMock(return_value=False)
        ctx.post = AsyncMock()

        with patch("agents.agent_10_dependency_patch.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            await tools.query_osv_batch([{"name": "unpinned", "version": ""}], "pip")

        ctx.post.assert_not_called()

    async def test_extracts_fixed_version_from_osv_response(self, tools):
        ok_resp = _make_http_resp(200, SAMPLE_OSV_RESPONSE)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__  = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=ok_resp)

        with patch("agents.agent_10_dependency_patch.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.query_osv_batch([{"name": "requests", "version": "2.28.0"}], "pip")

        assert result[0]["vulnerabilities"][0]["fixed_in"] == "2.31.0"


# ──────────────────────────────────────────────────────────────────────────────
# DependencyPatchTools.create_patch_pr()
# ──────────────────────────────────────────────────────────────────────────────

class TestCreatePatchPr:
    @pytest.fixture
    def tools(self):
        return DependencyPatchTools(github_token="gh_test_token")

    async def test_raises_without_github_token(self):
        no_token = DependencyPatchTools(github_token="")
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            await no_token.create_patch_pr(
                "acme", "backend", "patch-branch", "requirements.txt",
                "sha123", "new content", "PR body"
            )

    async def test_returns_pr_created_with_url_and_number(self, tools):
        ref_resp    = _make_http_resp(200, {"object": {"sha": "headsha123"}})
        branch_resp = _make_http_resp(201, {})
        commit_resp = _make_http_resp(201, {})
        pr_resp     = _make_http_resp(201, {
            "number": 42,
            "html_url": "https://github.com/acme/backend/pull/42",
        })
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__  = AsyncMock(return_value=False)
        ctx.get  = AsyncMock(return_value=ref_resp)
        ctx.post = AsyncMock(side_effect=[branch_resp, pr_resp])
        ctx.put  = AsyncMock(return_value=commit_resp)

        with patch("agents.agent_10_dependency_patch.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.create_patch_pr(
                "acme", "backend",
                "cloud-decoded/security-patch-abc",
                "requirements.txt", "sha123",
                "requests==2.31.0\n", "PR body",
            )

        assert result["status"] == "pr_created"
        assert result["pr_number"] == 42
        assert "acme/backend" in result["pr_url"]


# ──────────────────────────────────────────────────────────────────────────────
# DependencyPatchTools.create_vulnerability_issue()
# ──────────────────────────────────────────────────────────────────────────────

class TestCreateVulnerabilityIssue:
    @pytest.fixture
    def tools(self):
        return DependencyPatchTools(github_token="gh_test_token")

    async def test_raises_without_github_token(self):
        no_token = DependencyPatchTools(github_token="")
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            await no_token.create_vulnerability_issue("acme", "backend", "title", "body")

    async def test_creates_issue_with_security_labels(self, tools):
        issue_resp = _make_http_resp(201, {
            "number": 77,
            "html_url": "https://github.com/acme/backend/issues/77",
        })
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__  = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=issue_resp)

        with patch("agents.agent_10_dependency_patch.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.create_vulnerability_issue(
                "acme", "backend",
                "[Security] vulnerable deps",
                "## Report",
                labels=["security", "vulnerability", "dependencies"],
            )

        assert result["status"] == "issue_created"
        payload = ctx.post.call_args.kwargs["json"]
        assert "security" in payload.get("labels", [])

    async def test_returns_issue_url_and_number(self, tools):
        issue_resp = _make_http_resp(201, {
            "number": 88,
            "html_url": "https://github.com/acme/backend/issues/88",
        })
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__  = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=issue_resp)

        with patch("agents.agent_10_dependency_patch.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.create_vulnerability_issue(
                "acme", "backend", "title", "body"
            )

        assert result["issue_number"] == 88
        assert "issues/88" in result["issue_url"]


# ──────────────────────────────────────────────────────────────────────────────
# DependencyPatchTools.execute_option()
# ──────────────────────────────────────────────────────────────────────────────

class TestExecuteOption:
    @pytest.fixture
    def tools(self):
        return DependencyPatchTools(github_token="gh_test_token")

    async def test_hold_returns_held_without_any_api_call(self, tools):
        with patch.object(tools, "create_patch_pr") as mock_pr:
            result = await tools.execute_option({"id": "hold"}, _make_context())
        assert result["status"] == "held"
        mock_pr.assert_not_called()

    async def test_opt1_calls_create_patch_pr(self, tools):
        expected = {"status": "pr_created", "pr_url": "https://github.com/acme/backend/pull/42", "pr_number": 42, "branch": "b"}
        with patch.object(tools, "create_patch_pr", new=AsyncMock(return_value=expected)):
            result = await tools.execute_option({"id": "opt_1"}, _make_context())
        assert result["status"] == "pr_created"

    async def test_opt1_without_patched_content_returns_skipped(self, tools):
        result = await tools.execute_option({"id": "opt_1"}, _make_context(with_patched=False))
        assert result["status"] == "skipped"
        assert "patched" in result["reason"].lower() or "LLM" in result["reason"]

    async def test_opt1_without_repository_returns_skipped(self, tools):
        ctx = {**_make_context(), "owner": "", "repo": ""}
        result = await tools.execute_option({"id": "opt_1"}, ctx)
        assert result["status"] == "skipped"

    async def test_opt2_calls_create_vulnerability_issue(self, tools):
        expected = {"status": "issue_created", "issue_url": "https://github.com/acme/backend/issues/5", "issue_number": 5}
        with patch.object(tools, "create_vulnerability_issue", new=AsyncMock(return_value=expected)):
            result = await tools.execute_option({"id": "opt_2"}, _make_context())
        assert result["status"] == "issue_created"

    async def test_opt3_calls_both_pr_and_issue(self, tools):
        pr_result    = {"status": "pr_created", "pr_url": "...", "pr_number": 10, "branch": "b"}
        issue_result = {"status": "issue_created", "issue_url": "...", "issue_number": 11}
        with patch.object(tools, "create_patch_pr", new=AsyncMock(return_value=pr_result)), \
             patch.object(tools, "create_vulnerability_issue", new=AsyncMock(return_value=issue_result)):
            result = await tools.execute_option({"id": "opt_3"}, _make_context())
        assert result["status"] == "pr_and_issue_created"
        assert result["pr_number"] == 10
        assert result["issue_number"] == 11

    async def test_opt3_without_patched_content_only_creates_issue(self, tools):
        issue_result = {"status": "issue_created", "issue_url": "...", "issue_number": 12}
        with patch.object(tools, "create_patch_pr", new=AsyncMock()) as mock_pr, \
             patch.object(tools, "create_vulnerability_issue", new=AsyncMock(return_value=issue_result)):
            result = await tools.execute_option({"id": "opt_3"}, _make_context(with_patched=False))
        mock_pr.assert_not_called()
        assert result["issue_number"] == 12

    async def test_unknown_option_returns_not_implemented(self, tools):
        result = await tools.execute_option({"id": "opt_99"}, _make_context())
        assert result["status"] == "not_implemented"


# ──────────────────────────────────────────────────────────────────────────────
# _count_severity()
# ──────────────────────────────────────────────────────────────────────────────

class TestCountSeverity:
    def test_counts_packages_with_matching_severity(self):
        results = [
            {"package": "a", "vulnerabilities": [{"severity": "CRITICAL"}, {"severity": "HIGH"}]},
            {"package": "b", "vulnerabilities": [{"severity": "HIGH"}]},
            {"package": "c", "vulnerabilities": [{"severity": "LOW"}]},
        ]
        assert _count_severity(results, "CRITICAL") == 1
        assert _count_severity(results, "HIGH") == 2
        assert _count_severity(results, "LOW") == 1
        assert _count_severity(results, "MEDIUM") == 0

    def test_counts_each_package_at_most_once_per_severity(self):
        results = [
            {"package": "a", "vulnerabilities": [{"severity": "HIGH"}, {"severity": "HIGH"}]},
        ]
        assert _count_severity(results, "HIGH") == 1

    def test_returns_zero_for_empty_results(self):
        assert _count_severity([], "CRITICAL") == 0


# ──────────────────────────────────────────────────────────────────────────────
# DependencyPatchWorkflow._ingest_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestIngestNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        return _make_workflow(mock_db, workspace_id, mock_router)

    async def test_detects_ecosystem_from_payload(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "repository": "acme/backend",
            "ecosystem":  "npm",
            "manifest_path": "package.json",
        })
        result = await wf._ingest_node(state)
        assert result["ecosystem"] == "npm"

    async def test_extracts_repository_manifest_path_ref_base_branch(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "repository":    "acme/backend",
            "manifest_path": "requirements.txt",
            "ref":           "develop",
            "base_branch":   "develop",
        })
        result = await wf._ingest_node(state)
        assert result["repository"]    == "acme/backend"
        assert result["manifest_path"] == "requirements.txt"
        assert result["ref"]           == "develop"
        assert result["base_branch"]   == "develop"

    async def test_defaults_ref_to_head_and_base_branch_to_main(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "repository":    "acme/backend",
            "manifest_path": "requirements.txt",
        })
        result = await wf._ingest_node(state)
        assert result["ref"]         == "HEAD"
        assert result["base_branch"] == "main"

    async def test_initializes_counters_to_zero(self, wf, workspace_id):
        state = _base_state(workspace_id, {"repository": "acme/backend"})
        result = await wf._ingest_node(state)
        assert result["dependency_count"]    == 0
        assert result["vulnerability_count"] == 0
        assert result["critical_count"]      == 0
        assert result["high_count"]          == 0


# ──────────────────────────────────────────────────────────────────────────────
# DependencyPatchWorkflow._diagnose_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestDiagnoseNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        return _make_workflow(mock_db, workspace_id, mock_router)

    def _osv_results(self):
        return [{
            "package": "requests",
            "version": "2.28.0",
            "vulnerabilities": [
                {"id": "GHSA-j8r2-6x86-q33q", "severity": "HIGH",
                 "summary": "Proxy header leak", "fixed_in": "2.31.0", "aliases": ["CVE-2023-32681"]}
            ],
        }]

    def _manifest_data(self):
        return {
            "path":    "requirements.txt",
            "url":     "https://github.com/acme/backend/blob/main/requirements.txt",
            "content": SAMPLE_REQUIREMENTS_TXT,
            "sha":     "abc123sha",
        }

    async def test_calls_fetch_manifest_with_correct_args(self, wf, workspace_id):
        state  = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_RESPONSE)

        with patch.object(wf._tools, "fetch_manifest", new=AsyncMock(return_value=self._manifest_data())) as mock_fetch, \
             patch.object(wf._tools, "query_osv_batch", new=AsyncMock(return_value=[])), \
             patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_RESPONSE, 2000)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        mock_fetch.assert_called_once_with("acme", "backend", "requirements.txt", "main")

    async def test_calls_query_osv_batch_with_parsed_deps_and_ecosystem(self, wf, workspace_id):
        state  = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_RESPONSE)

        with patch.object(wf._tools, "fetch_manifest", new=AsyncMock(return_value=self._manifest_data())), \
             patch.object(wf._tools, "query_osv_batch", new=AsyncMock(return_value=[])) as mock_osv, \
             patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_RESPONSE, 2000)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        mock_osv.assert_called_once()
        assert mock_osv.call_args.args[1] == "pip"

    async def test_calls_llm_with_vulnerability_analysis_task_type(self, wf, workspace_id):
        state  = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_RESPONSE)

        with patch.object(wf._tools, "fetch_manifest", new=AsyncMock(return_value=self._manifest_data())), \
             patch.object(wf._tools, "query_osv_batch", new=AsyncMock(return_value=[])), \
             patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_RESPONSE, 2000)) as mock_llm, \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        assert mock_llm.call_args.kwargs["task_type"] == "vulnerability_analysis"

    async def test_parses_all_llm_fields(self, wf, workspace_id):
        state  = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_RESPONSE)

        with patch.object(wf._tools, "fetch_manifest", new=AsyncMock(return_value=self._manifest_data())), \
             patch.object(wf._tools, "query_osv_batch", new=AsyncMock(return_value=self._osv_results())), \
             patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_RESPONSE, 2000)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(state)

        assert "HIGH" in result["parsed_error"]
        assert "requests" in result["patch_summary"]
        assert len(result["vulnerable_packages"]) == 1
        assert "requests==2.31.0" in result["patched_manifest"]
        assert len(result["remediation_options"]) == 4

    async def test_accumulates_tokens_from_prior_state(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        state["tokens_used"] = 500
        parsed = json.loads(SAMPLE_LLM_RESPONSE)

        with patch.object(wf._tools, "fetch_manifest", new=AsyncMock(return_value=self._manifest_data())), \
             patch.object(wf._tools, "query_osv_batch", new=AsyncMock(return_value=[])), \
             patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_RESPONSE, 2000)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(state)

        assert result["tokens_used"] == 2500

    async def test_sets_error_when_manifest_fetch_fails(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)

        with patch.object(wf._tools, "fetch_manifest", new=AsyncMock(return_value={"error": "404"})):
            result = await wf._diagnose_node(state)

        assert result.get("error") is not None
        assert "404" in result["error"]

    async def test_sets_error_on_llm_parse_failure(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)

        with patch.object(wf._tools, "fetch_manifest", new=AsyncMock(return_value=self._manifest_data())), \
             patch.object(wf._tools, "query_osv_batch", new=AsyncMock(return_value=[])), \
             patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=("bad json", 100)), \
             patch.object(wf, "parse_llm_json", side_effect=ValueError("bad json")):
            result = await wf._diagnose_node(state)

        assert result.get("error") is not None

    async def test_user_message_includes_ecosystem_manifest_and_vuln_counts(self, wf, workspace_id):
        state  = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_RESPONSE)

        with patch.object(wf._tools, "fetch_manifest", new=AsyncMock(return_value=self._manifest_data())), \
             patch.object(wf._tools, "query_osv_batch", new=AsyncMock(return_value=self._osv_results())), \
             patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_RESPONSE, 2000)) as mock_llm, \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        content = mock_llm.call_args.kwargs["messages"][0]["content"]
        assert "pip" in content
        assert "requirements.txt" in content
        assert "Vulnerable packages found: 1" in content

    async def test_sets_error_for_invalid_repository_format(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "repository":    "no-slash-here",
            "manifest_path": "requirements.txt",
        })
        state.update({"repository": "no-slash-here", "manifest_path": "requirements.txt",
                      "ecosystem": "pip", "ref": "HEAD"})
        result = await wf._diagnose_node(state)
        assert result.get("error") is not None


# ──────────────────────────────────────────────────────────────────────────────
# DependencyPatchWorkflow._hitl_gate_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestHITLGateNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        return _make_workflow(mock_db, workspace_id, mock_router)

    async def test_calls_create_incident_with_correct_agent_id(self, wf, workspace_id):
        state       = _hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_10_dependency_patch.workflow.interrupt", return_value={"id": "hold"}):
            await wf._hitl_gate_node(state)

        call_kwargs = mock_hitl.create_incident.call_args.kwargs
        assert call_kwargs["agent_id"]    == "agent_10_dependency_patch"
        assert call_kwargs["workspace_id"] == workspace_id

    async def test_raw_log_includes_ecosystem_repo_and_severity_counts(self, wf, workspace_id):
        state       = _hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_10_dependency_patch.workflow.interrupt", return_value={"id": "hold"}):
            await wf._hitl_gate_node(state)

        raw_log = mock_hitl.create_incident.call_args.kwargs["raw_log"]
        assert "PIP" in raw_log
        assert "acme/backend" in raw_log
        assert "1" in raw_log   # vulnerability_count
        assert "HIGH" in raw_log

    async def test_interrupt_includes_vulnerability_count_critical_and_high(self, wf, workspace_id):
        state       = _hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_10_dependency_patch.workflow.interrupt", return_value={"id": "opt_1"}) as mock_interrupt:
            await wf._hitl_gate_node(state)

        interrupt_arg = mock_interrupt.call_args.args[0]
        assert interrupt_arg["vulnerability_count"] == 1
        assert interrupt_arg["critical_count"]      == 0
        assert interrupt_arg["high_count"]          == 1

    async def test_skips_incident_creation_on_error_state(self, wf, workspace_id):
        state         = _hitl_state(workspace_id)
        state["error"] = "Manifest fetch failed: 404"

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock()
        wf.hitl = mock_hitl

        result = await wf._hitl_gate_node(state)

        mock_hitl.create_incident.assert_not_called()
        assert result == {}


# ──────────────────────────────────────────────────────────────────────────────
# _build_vulnerability_report()
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildVulnerabilityReport:
    def _report(self, **kwargs):
        defaults = dict(
            ecosystem="pip",
            repository="acme/backend",
            manifest_path="requirements.txt",
            dependency_count=10,
            vulnerability_count=1,
            critical_count=0,
            high_count=1,
            vulnerable_packages=[{
                "package": "requests",
                "current_version": "2.28.0",
                "fixed_version": "2.31.0",
                "severity": "HIGH",
                "cve_ids": ["CVE-2023-32681"],
                "description": "Proxy-Authorization header leak",
            }],
            patch_summary="Update requests to 2.31.0 to fix CVE-2023-32681.",
        )
        defaults.update(kwargs)
        return _build_vulnerability_report(**defaults)

    def test_includes_ecosystem_repository_and_manifest_path(self):
        report = self._report()
        assert "pip" in report
        assert "acme/backend" in report
        assert "requirements.txt" in report

    def test_includes_severity_summary_with_critical_and_high_counts(self):
        report = self._report(critical_count=2, high_count=3)
        assert "CRITICAL" in report
        assert "HIGH" in report
        assert "2" in report
        assert "3" in report

    def test_includes_vulnerable_packages_table(self):
        report = self._report()
        assert "requests" in report
        assert "2.28.0" in report
        assert "2.31.0" in report
        assert "CVE-2023-32681" in report

    def test_includes_cloud_decoded_attribution(self):
        report = self._report()
        assert "Cloud Decoded" in report

    def test_no_packages_table_when_none_found(self):
        report = self._report(vulnerable_packages=[], vulnerability_count=0, high_count=0)
        assert "Vulnerable Packages" not in report
