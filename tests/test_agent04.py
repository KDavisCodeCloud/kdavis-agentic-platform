"""
tests/test_agent04.py
Tests for agents/agent_04_migration/tools.py and agents/agent_04_migration/workflow.py.

What this file validates:
  MigrationTools:
    - create_migration_pr() opens a PR via 5-step GitHub API flow
    - create_migration_pr() raises EnvironmentError when GITHUB_TOKEN is missing
    - create_migration_pr() raises RuntimeError when GitHub ref endpoint returns non-200
    - create_github_issue() POSTs to the correct GitHub issues endpoint
    - create_github_issue() raises EnvironmentError when GITHUB_TOKEN is missing
    - create_github_issue() includes labels when provided
    - execute_option("hold") returns held status without any GitHub API call
    - execute_option("opt_1") dispatches to create_migration_pr with migrated code
    - execute_option("opt_1") skips and returns skipped when migrated_code is empty
    - execute_option("opt_2") dispatches to create_github_issue with migration plan
    - execute_option(unknown_id) returns not_implemented

  Language / type detection helpers:
    - _detect_language(".py") → "python"
    - _detect_language(".tf") → "hcl"
    - _detect_language(".yaml") → "yaml"
    - _detect_language("Dockerfile") → "dockerfile"
    - _detect_language(".unknown") → "unknown"
    - _detect_source_type("hcl") → "terraform"
    - _detect_source_type("dockerfile") → "docker"
    - _detect_source_type("yaml", deployment.yaml) → "kubernetes"
    - _detect_source_type("yaml", compose.yaml) → "docker"
    - _detect_source_type("python") → "code"

  MigrationWorkflow._ingest_node():
    - Extracts repository, file_path, source_version, target_version from payload
    - Detects source_language from file extension
    - Detects source_type from language / filename
    - Accepts explicit source_type/source_language override in payload
    - Truncates file_content at _MAX_CODE_CHARS with [truncated] suffix
    - Sanitizes file_content via DataSanitizationShield
    - Empty payload sets safe zero-value defaults without crash

  MigrationWorkflow._diagnose_node():
    - Calls router.complete() with task_type="code_migration"
    - Parses valid LLM JSON into parsed_error, migration_plan, migrated_code, options
    - Accumulates tokens from previous state["tokens_used"]
    - Handles LLM JSON parse error → sets state["error"]
    - Calls budget.assert_budget_available() before the LLM call
    - Includes repository, file_path, source/target versions in user message

  MigrationWorkflow._hitl_gate_node():
    - Calls hitl.create_incident() with correct agent_id and workspace_id
    - Calls interrupt() with incident_id and options
    - Sets state["incident_id"] from create_incident() return value
    - Skips incident creation and returns early when state["error"] is set
"""

import json
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import uuid4

import pytest

from agents.agent_04_migration.tools import MigrationTools
from agents.agent_04_migration.workflow import (
    MigrationWorkflow,
    MigrationState,
    _detect_language,
    _detect_source_type,
    _build_pr_body,
)


# ──────────────────────────────────────────────────────────────────────────────
# Sample data
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_MIGRATION_DIAGNOSIS = json.dumps({
    "parsed_error": "Flask routes.py uses deprecated Flask 1.x patterns; migration to FastAPI required.",
    "migrated_code": "# Migrated by Cloud Decoded Agent 04 — flask → fastapi\nfrom fastapi import FastAPI\napp = FastAPI()\n\n@app.get('/health')\nasync def health():\n    return {'status': 'ok'}\n",
    "migration_plan": (
        "## Summary\nMigrate Flask routes to FastAPI async patterns.\n\n"
        "## Breaking Changes\n- `jsonify()` removed; return dicts directly.\n\n"
        "## Steps\n1. Install FastAPI: `pip install fastapi uvicorn`\n"
        "2. Replace `@app.route` with `@app.get` / `@app.post`\n"
        "3. Add `async` to route handlers\n\n"
        "## Testing\nRun `pytest tests/` and `uvicorn app:app --reload`\n\n"
        "## Rollback\nRevert branch and redeploy."
    ),
    "options": [
        {
            "id": "opt_1",
            "title": "Create Migration PR",
            "description": "Open a GitHub PR with the migrated FastAPI code.",
            "impact": "LOW",
            "docs_url": "https://docs.github.com/en/pull-requests",
        },
        {
            "id": "opt_2",
            "title": "Create Tracking Issue",
            "description": "Open a GitHub issue with the migration plan.",
            "impact": "NONE",
            "docs_url": "https://docs.github.com/en/issues",
        },
        {
            "id": "hold",
            "title": "Hold — Manual Review",
            "description": "Pause for manual handling.",
            "impact": "NONE",
            "docs_url": "",
        },
    ],
    "estimated_duration_seconds": 300,
})


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_gh_resp(status_code: int, body) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = json.dumps(body)[:200] if isinstance(body, (dict, list)) else str(body)[:200]
    return resp


def _make_workflow(mock_db, workspace_id, mock_router) -> MigrationWorkflow:
    with (
        patch("agents.base_agent._load_router", return_value=mock_router),
        patch.object(MigrationWorkflow, "_build_graph", return_value=MagicMock()),
    ):
        wf = MigrationWorkflow(mock_db, workspace_id, MagicMock())
    return wf


def _base_ingest_state(workspace_id: str, payload: dict | None = None) -> MigrationState:
    return {
        "workspace_id": workspace_id,
        "cloud_provider": "github",
        "webhook_payload": payload or {},
        "source_type": "",
        "source_language": "",
        "repository": "",
        "file_path": "",
        "source_version": "",
        "target_version": "",
        "migration_context": "",
        "code_excerpt": "",
        "incident_id": None,
        "parsed_error": None,
        "migration_plan": None,
        "migrated_code": None,
        "remediation_options": None,
        "estimated_duration_seconds": None,
        "tokens_used": 0,
        "selected_option": None,
        "execution_result": None,
        "error": None,
    }


def _base_diagnose_state(workspace_id: str) -> MigrationState:
    s = _base_ingest_state(workspace_id)
    s.update({
        "source_type": "code",
        "source_language": "python",
        "repository": "acme/backend",
        "file_path": "src/api/routes.py",
        "source_version": "flask",
        "target_version": "fastapi",
        "migration_context": "Migrating to async FastAPI",
        "code_excerpt": "from flask import Flask, jsonify\napp = Flask(__name__)\n\n@app.route('/health')\ndef health():\n    return jsonify({'status': 'ok'})\n",
    })
    return s


def _base_hitl_state(workspace_id: str) -> MigrationState:
    s = _base_diagnose_state(workspace_id)
    s.update({
        "parsed_error": "Flask routes.py uses deprecated Flask 1.x patterns.",
        "migration_plan": "## Steps\n1. Replace @app.route with @app.get",
        "migrated_code": "from fastapi import FastAPI\napp = FastAPI()",
        "remediation_options": [
            {"id": "opt_1", "title": "Create PR", "description": "...", "impact": "LOW", "docs_url": ""},
            {"id": "opt_2", "title": "Create Issue", "description": "...", "impact": "NONE", "docs_url": ""},
            {"id": "hold", "title": "Hold", "description": "...", "impact": "NONE", "docs_url": ""},
        ],
        "estimated_duration_seconds": 300,
        "tokens_used": 1500,
    })
    return s


# ──────────────────────────────────────────────────────────────────────────────
# Language detection
# ──────────────────────────────────────────────────────────────────────────────

class TestDetectLanguage:
    def test_python_extension(self):
        assert _detect_language("src/api/routes.py") == "python"

    def test_terraform_extension(self):
        assert _detect_language("infra/main.tf") == "hcl"

    def test_yaml_extension(self):
        assert _detect_language("k8s/deployment.yaml") == "yaml"

    def test_yml_extension(self):
        assert _detect_language("docker-compose.yml") == "yaml"

    def test_dockerfile_exact_name(self):
        assert _detect_language("Dockerfile") == "dockerfile"

    def test_dockerfile_with_extension(self):
        assert _detect_language("Dockerfile.prod") == "dockerfile"

    def test_unknown_extension(self):
        assert _detect_language("script.xyz") == "unknown"

    def test_javascript_extension(self):
        assert _detect_language("src/index.js") == "javascript"

    def test_typescript_extension(self):
        assert _detect_language("src/api.ts") == "typescript"

    def test_shell_extension(self):
        assert _detect_language("scripts/deploy.sh") == "shell"


class TestDetectSourceType:
    def test_hcl_is_terraform(self):
        assert _detect_source_type("infra/main.tf", "hcl") == "terraform"

    def test_dockerfile_is_docker(self):
        assert _detect_source_type("Dockerfile", "dockerfile") == "docker"

    def test_deployment_yaml_is_kubernetes(self):
        assert _detect_source_type("k8s/deployment.yaml", "yaml") == "kubernetes"

    def test_service_yaml_is_kubernetes(self):
        assert _detect_source_type("manifests/service.yaml", "yaml") == "kubernetes"

    def test_compose_yaml_is_docker(self):
        assert _detect_source_type("docker-compose.yaml", "yaml") == "docker"

    def test_generic_yaml_is_yaml(self):
        assert _detect_source_type("config/settings.yaml", "yaml") == "yaml"

    def test_python_is_code(self):
        assert _detect_source_type("src/routes.py", "python") == "code"

    def test_go_is_code(self):
        assert _detect_source_type("main.go", "go") == "code"


# ──────────────────────────────────────────────────────────────────────────────
# MigrationTools — create_migration_pr()
# ──────────────────────────────────────────────────────────────────────────────

class TestMigrationToolsCreatePR:
    @pytest.fixture
    def tools(self):
        return MigrationTools(github_token="gh_test_token")

    async def test_opens_pr_with_5_step_flow(self, tools):
        ref_resp    = _make_gh_resp(200, {"object": {"sha": "base_sha_abc"}})
        branch_resp = _make_gh_resp(201, {"ref": "refs/heads/cloud-decoded/migrate-xxxxxxxx"})
        file_resp   = _make_gh_resp(200, {"sha": "file_sha_def"})
        put_resp    = _make_gh_resp(201, {"content": {}})
        pr_resp     = _make_gh_resp(201, {"html_url": "https://github.com/acme/backend/pull/99", "number": 99})

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.get  = AsyncMock(side_effect=[ref_resp, file_resp])
        ctx.post = AsyncMock(side_effect=[branch_resp, pr_resp])
        ctx.put  = AsyncMock(return_value=put_resp)

        with patch("agents.agent_04_migration.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.create_migration_pr(
                owner="acme", repo="backend", file_path="src/api/routes.py",
                new_content="from fastapi import FastAPI",
                pr_title="chore: migrate routes.py", pr_body="## Plan\nMigrate Flask to FastAPI",
            )

        assert result["status"] == "pr_opened"
        assert result["pr_number"] == 99
        assert "github.com" in result["pr_url"]
        assert "cloud-decoded/migrate-" in result["branch"]

    async def test_raises_without_github_token(self):
        no_token = MigrationTools(github_token="")
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            await no_token.create_migration_pr(
                owner="acme", repo="backend", file_path="src/routes.py",
                new_content="code", pr_title="title", pr_body="body",
            )

    async def test_raises_on_github_ref_error(self, tools):
        err_resp = _make_gh_resp(404, {"message": "Not Found"})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.get = AsyncMock(return_value=err_resp)

        with patch("agents.agent_04_migration.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            with pytest.raises(RuntimeError, match="GitHub get ref error"):
                await tools.create_migration_pr(
                    owner="acme", repo="backend", file_path="src/routes.py",
                    new_content="code", pr_title="title", pr_body="body",
                )

    async def test_commits_without_file_sha_for_new_files(self, tools):
        """When the file doesn't yet exist (404), omit sha from the commit payload."""
        ref_resp    = _make_gh_resp(200, {"object": {"sha": "base_sha"}})
        branch_resp = _make_gh_resp(201, {})
        file_resp   = _make_gh_resp(404, {"message": "Not Found"})
        put_resp    = _make_gh_resp(201, {})
        pr_resp     = _make_gh_resp(201, {"html_url": "https://github.com/acme/backend/pull/100", "number": 100})

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.get  = AsyncMock(side_effect=[ref_resp, file_resp])
        ctx.post = AsyncMock(side_effect=[branch_resp, pr_resp])
        ctx.put  = AsyncMock(return_value=put_resp)

        with patch("agents.agent_04_migration.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.create_migration_pr(
                owner="acme", repo="backend", file_path="new_file.py",
                new_content="new content", pr_title="chore: add file", pr_body="body",
            )

        # commit payload should not contain "sha" key
        put_call_payload = ctx.put.call_args.kwargs["json"]
        assert "sha" not in put_call_payload
        assert result["status"] == "pr_opened"


# ──────────────────────────────────────────────────────────────────────────────
# MigrationTools — create_github_issue()
# ──────────────────────────────────────────────────────────────────────────────

class TestMigrationToolsCreateIssue:
    @pytest.fixture
    def tools(self):
        return MigrationTools(github_token="gh_test_token")

    async def test_posts_to_correct_endpoint(self, tools):
        issue_resp = _make_gh_resp(201, {
            "number": 77,
            "html_url": "https://github.com/acme/backend/issues/77",
        })
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=issue_resp)

        with patch("agents.agent_04_migration.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.create_github_issue(
                owner="acme", repo="backend",
                title="Migration: flask → fastapi",
                body="## Steps\n1. Replace @app.route",
            )

        assert result["status"] == "issue_created"
        assert result["issue_number"] == 77
        call_url = ctx.post.call_args.args[0]
        assert "repos/acme/backend/issues" in call_url

    async def test_raises_without_github_token(self):
        no_token = MigrationTools(github_token="")
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            await no_token.create_github_issue(
                owner="acme", repo="backend", title="title", body="body",
            )

    async def test_includes_labels_in_payload(self, tools):
        issue_resp = _make_gh_resp(201, {"number": 78, "html_url": "https://github.com/acme/backend/issues/78"})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=issue_resp)

        with patch("agents.agent_04_migration.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            await tools.create_github_issue(
                owner="acme", repo="backend",
                title="Migration plan",
                body="body",
                labels=["migration", "technical-debt"],
            )

        payload = ctx.post.call_args.kwargs["json"]
        assert payload.get("labels") == ["migration", "technical-debt"]

    async def test_raises_on_github_api_error(self, tools):
        err_resp = _make_gh_resp(422, {"message": "Unprocessable Entity"})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=err_resp)

        with patch("agents.agent_04_migration.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            with pytest.raises(RuntimeError, match="GitHub issue error"):
                await tools.create_github_issue(
                    owner="acme", repo="backend", title="t", body="b",
                )


# ──────────────────────────────────────────────────────────────────────────────
# MigrationTools — execute_option()
# ──────────────────────────────────────────────────────────────────────────────

class TestMigrationToolsExecuteOption:
    @pytest.fixture
    def tools(self):
        return MigrationTools(github_token="gh_test_token")

    @pytest.fixture
    def base_context(self):
        return {
            "owner": "acme",
            "repo": "backend",
            "file_path": "src/api/routes.py",
            "migrated_code": "from fastapi import FastAPI\napp = FastAPI()",
            "migration_plan": "## Steps\n1. Replace @app.route",
            "source_version": "flask",
            "target_version": "fastapi",
            "pr_title": "chore(migrate): routes.py — flask → fastapi",
            "pr_body": "## Plan",
            "issue_title": "Migration: flask → fastapi",
        }

    async def test_hold_returns_held_without_api_call(self, tools, base_context):
        with patch.object(tools, "create_migration_pr") as mock_pr, \
             patch.object(tools, "create_github_issue") as mock_issue:
            result = await tools.execute_option({"id": "hold"}, base_context)

        assert result["status"] == "held"
        mock_pr.assert_not_called()
        mock_issue.assert_not_called()

    async def test_opt1_dispatches_to_create_pr(self, tools, base_context):
        expected = {"status": "pr_opened", "pr_url": "https://github.com/acme/backend/pull/99", "pr_number": 99, "branch": "cloud-decoded/migrate-abc12345"}
        with patch.object(tools, "create_migration_pr", new=AsyncMock(return_value=expected)) as mock_pr:
            result = await tools.execute_option({"id": "opt_1"}, base_context)

        assert result["status"] == "pr_opened"
        mock_pr.assert_called_once()
        call_kwargs = mock_pr.call_args.kwargs
        assert call_kwargs["file_path"] == "src/api/routes.py"
        assert "fastapi" in call_kwargs["new_content"]

    async def test_opt1_skips_when_no_migrated_code(self, tools, base_context):
        base_context["migrated_code"] = ""
        result = await tools.execute_option({"id": "opt_1"}, base_context)
        assert result["status"] == "skipped"
        assert "No migrated code" in result["reason"]

    async def test_opt2_dispatches_to_create_issue(self, tools, base_context):
        expected = {"status": "issue_created", "issue_url": "https://github.com/acme/backend/issues/77", "issue_number": 77}
        with patch.object(tools, "create_github_issue", new=AsyncMock(return_value=expected)) as mock_issue:
            result = await tools.execute_option({"id": "opt_2"}, base_context)

        assert result["status"] == "issue_created"
        mock_issue.assert_called_once()
        call_kwargs = mock_issue.call_args.kwargs
        assert call_kwargs["labels"] == ["migration", "technical-debt"]

    async def test_unknown_option_returns_not_implemented(self, tools, base_context):
        result = await tools.execute_option({"id": "opt_99"}, base_context)
        assert result["status"] == "not_implemented"
        assert result["option_id"] == "opt_99"


# ──────────────────────────────────────────────────────────────────────────────
# MigrationWorkflow._ingest_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestIngestNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        return _make_workflow(mock_db, workspace_id, mock_router)

    async def test_extracts_payload_fields(self, wf, workspace_id):
        state = _base_ingest_state(workspace_id, {
            "repository": "acme/backend",
            "file_path": "src/api/routes.py",
            "file_content": "from flask import Flask",
            "source_version": "flask",
            "target_version": "fastapi",
            "migration_context": "Migrating to async FastAPI",
        })

        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="from flask import Flask")

        with patch("agents.agent_04_migration.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["repository"] == "acme/backend"
        assert result["file_path"] == "src/api/routes.py"
        assert result["source_version"] == "flask"
        assert result["target_version"] == "fastapi"
        assert result["migration_context"] == "Migrating to async FastAPI"

    async def test_detects_python_language_from_extension(self, wf, workspace_id):
        state = _base_ingest_state(workspace_id, {
            "file_path": "src/routes.py",
            "file_content": "code",
        })
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="code")

        with patch("agents.agent_04_migration.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["source_language"] == "python"
        assert result["source_type"] == "code"

    async def test_detects_terraform_type_from_extension(self, wf, workspace_id):
        state = _base_ingest_state(workspace_id, {
            "file_path": "infra/main.tf",
            "file_content": "terraform {}",
        })
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="terraform {}")

        with patch("agents.agent_04_migration.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["source_language"] == "hcl"
        assert result["source_type"] == "terraform"

    async def test_detects_kubernetes_type_from_yaml_filename(self, wf, workspace_id):
        state = _base_ingest_state(workspace_id, {
            "file_path": "k8s/deployment.yaml",
            "file_content": "apiVersion: extensions/v1beta1",
        })
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="apiVersion: extensions/v1beta1")

        with patch("agents.agent_04_migration.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["source_language"] == "yaml"
        assert result["source_type"] == "kubernetes"

    async def test_payload_override_takes_precedence_over_detection(self, wf, workspace_id):
        state = _base_ingest_state(workspace_id, {
            "file_path": "something.yaml",
            "file_content": "data: value",
            "source_type": "terraform",
            "source_language": "hcl",
        })
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="data: value")

        with patch("agents.agent_04_migration.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["source_type"] == "terraform"
        assert result["source_language"] == "hcl"

    async def test_truncates_large_file_content(self, wf, workspace_id):
        large_code = "x = 1\n" * 5_000  # ~30KB
        state = _base_ingest_state(workspace_id, {
            "file_path": "bigfile.py",
            "file_content": large_code,
        })

        captured_sanitize_arg = {}

        def capture_sanitize(text, context=None):
            captured_sanitize_arg["text"] = text
            return MagicMock(sanitized_text=text[:10_000])

        shield_mock = MagicMock()
        shield_mock.sanitize.side_effect = capture_sanitize

        with patch("agents.agent_04_migration.workflow.shield", shield_mock):
            await wf._ingest_node(state)

        assert len(captured_sanitize_arg["text"]) <= 10_000 + len("\n... [truncated]") + 10
        assert "[truncated]" in captured_sanitize_arg["text"]

    async def test_empty_payload_sets_safe_defaults(self, wf, workspace_id):
        state = _base_ingest_state(workspace_id, {})
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="")

        with patch("agents.agent_04_migration.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["error"] is None
        assert result["repository"] == ""
        assert result["file_path"] == ""
        assert result["tokens_used"] == 0

    async def test_sanitizes_file_content_via_shield(self, wf, workspace_id):
        state = _base_ingest_state(workspace_id, {
            "file_path": "src/config.py",
            "file_content": "API_KEY = 'sk-prod-secret-123'",
        })
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="API_KEY = '<REDACTED>'")

        with patch("agents.agent_04_migration.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        shield_mock.sanitize.assert_called_once()
        assert result["code_excerpt"] == "API_KEY = '<REDACTED>'"


# ──────────────────────────────────────────────────────────────────────────────
# MigrationWorkflow._diagnose_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestDiagnoseNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        wf._router = mock_router
        mock_router.complete.return_value = SAMPLE_MIGRATION_DIAGNOSIS
        return wf

    async def test_calls_router_with_code_migration_task_type(self, wf, workspace_id):
        state = _base_diagnose_state(workspace_id)
        budget_mock = MagicMock()
        budget_mock.assert_budget_available = AsyncMock()

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_MIGRATION_DIAGNOSIS, 2000)) as mock_llm, \
             patch.object(wf, "parse_llm_json", return_value=json.loads(SAMPLE_MIGRATION_DIAGNOSIS)), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        mock_llm.assert_called_once()
        call_kwargs = mock_llm.call_args.kwargs
        assert call_kwargs["task_type"] == "code_migration"

    async def test_parses_llm_json_into_state_fields(self, wf, workspace_id):
        state = _base_diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_MIGRATION_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_MIGRATION_DIAGNOSIS, 2000)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(state)

        assert result["parsed_error"] == parsed["parsed_error"]
        assert result["migration_plan"] == parsed["migration_plan"]
        assert result["migrated_code"] == parsed["migrated_code"]
        assert result["remediation_options"] == parsed["options"]
        assert result["estimated_duration_seconds"] == 300

    async def test_accumulates_tokens_from_prior_state(self, wf, workspace_id):
        state = _base_diagnose_state(workspace_id)
        state["tokens_used"] = 500
        parsed = json.loads(SAMPLE_MIGRATION_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_MIGRATION_DIAGNOSIS, 2000)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(state)

        assert result["tokens_used"] == 2500  # 500 prior + 2000 from LLM

    async def test_sets_error_on_parse_failure(self, wf, workspace_id):
        state = _base_diagnose_state(workspace_id)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=("not valid json", 100)), \
             patch.object(wf, "parse_llm_json", side_effect=ValueError("JSON parse failed")):
            result = await wf._diagnose_node(state)

        assert result.get("error") is not None
        assert "JSON parse" in result["error"]

    async def test_calls_check_budget_before_llm(self, wf, workspace_id):
        state = _base_diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_MIGRATION_DIAGNOSIS)
        call_order = []

        async def mock_budget(*args, **kwargs):
            call_order.append("budget")

        def mock_llm(*args, **kwargs):
            call_order.append("llm")
            return (SAMPLE_MIGRATION_DIAGNOSIS, 2000)

        with patch.object(wf, "check_budget", side_effect=mock_budget), \
             patch.object(wf, "call_llm", side_effect=mock_llm), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        assert call_order.index("budget") < call_order.index("llm")

    async def test_user_message_includes_repository_and_file_path(self, wf, workspace_id):
        state = _base_diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_MIGRATION_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_MIGRATION_DIAGNOSIS, 2000)) as mock_llm, \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        call_kwargs = mock_llm.call_args.kwargs
        messages = call_kwargs["messages"]
        user_content = messages[0]["content"]
        assert "acme/backend" in user_content
        assert "src/api/routes.py" in user_content
        assert "flask" in user_content
        assert "fastapi" in user_content


# ──────────────────────────────────────────────────────────────────────────────
# MigrationWorkflow._hitl_gate_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestHITLGateNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        return _make_workflow(mock_db, workspace_id, mock_router)

    async def test_calls_create_incident_with_correct_agent_id(self, wf, workspace_id):
        state = _base_hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_04_migration.workflow.interrupt", return_value={"id": "hold"}):
            result = await wf._hitl_gate_node(state)

        mock_hitl.create_incident.assert_called_once()
        call_kwargs = mock_hitl.create_incident.call_args.kwargs
        assert call_kwargs["agent_id"] == "agent_04_migration"
        assert call_kwargs["workspace_id"] == workspace_id

    async def test_sets_incident_id_in_state(self, wf, workspace_id):
        state = _base_hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_04_migration.workflow.interrupt", return_value={"id": "opt_1"}):
            result = await wf._hitl_gate_node(state)

        assert result["incident_id"] == incident_id

    async def test_calls_interrupt_with_incident_id_and_options(self, wf, workspace_id):
        state = _base_hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_04_migration.workflow.interrupt", return_value={"id": "hold"}) as mock_interrupt:
            await wf._hitl_gate_node(state)

        mock_interrupt.assert_called_once()
        interrupt_arg = mock_interrupt.call_args.args[0]
        assert interrupt_arg["incident_id"] == incident_id
        assert "options" in interrupt_arg

    async def test_skips_incident_creation_when_error_is_set(self, wf, workspace_id):
        state = _base_hitl_state(workspace_id)
        state["error"] = "LLM parse failed"

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock()
        wf.hitl = mock_hitl

        result = await wf._hitl_gate_node(state)

        mock_hitl.create_incident.assert_not_called()
        assert result == {}

    async def test_passes_parsed_error_to_create_incident(self, wf, workspace_id):
        state = _base_hitl_state(workspace_id)
        state["parsed_error"] = "Flask routes.py requires migration"
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_04_migration.workflow.interrupt", return_value={"id": "hold"}):
            await wf._hitl_gate_node(state)

        call_kwargs = mock_hitl.create_incident.call_args.kwargs
        assert call_kwargs["parsed_error"] == "Flask routes.py requires migration"


# ──────────────────────────────────────────────────────────────────────────────
# _build_pr_body()
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildPrBody:
    def test_includes_file_path_in_body(self):
        body = _build_pr_body(
            migration_plan="## Steps\n1. Replace Flask",
            source_version="flask",
            target_version="fastapi",
            file_path="src/api/routes.py",
        )
        assert "src/api/routes.py" in body

    def test_includes_source_and_target_versions(self):
        body = _build_pr_body(
            migration_plan="plan",
            source_version="terraform 0.12",
            target_version="terraform 1.x",
            file_path="infra/main.tf",
        )
        assert "terraform 0.12" in body
        assert "terraform 1.x" in body

    def test_includes_migration_plan_content(self):
        plan = "## Steps\n1. Do this\n2. Do that"
        body = _build_pr_body(
            migration_plan=plan,
            source_version="flask",
            target_version="fastapi",
            file_path="routes.py",
        )
        assert plan in body

    def test_includes_cloud_decoded_attribution(self):
        body = _build_pr_body(
            migration_plan="plan",
            source_version="a",
            target_version="b",
            file_path="f.py",
        )
        assert "Cloud Decoded" in body
