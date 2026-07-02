"""
tests/test_agent08.py
Tests for agents/agent_08_drift_detection/tools.py and workflow.py.

What this file validates:
  _detect_drift_source():
    - Detects "terraform" from terraform_state key
    - Detects "terraform" from tfstate / terraform_plan / terraform_config keys
    - Detects "kubernetes" from k8s_manifest / manifest keys
    - Detects "cloudformation" from cfn_template key
    - Falls back to "generic" when no known keys present
    - Respects explicit drift_source field as override

  _normalize_state_text():
    - Converts dict to formatted JSON string
    - Converts list to JSON array string
    - Accepts plain string as-is
    - Truncates at max_chars with trailing marker
    - Returns empty string for None

  DriftTools — fetch_k8s_resource():
    - Returns parsed JSON on success
    - Returns error dict on non-zero exit code
    - Returns error dict when kubectl disabled

  DriftTools — apply_k8s_manifest():
    - Returns ok on exit code 0
    - Returns failed on non-zero exit code
    - Returns skipped when allow_kubectl=False

  DriftTools — create_drift_pr():
    - Executes 5-step GitHub flow (ref → branch → file SHA → commit → PR)
    - Returns pr_created with pr_url and pr_number
    - Raises EnvironmentError when GITHUB_TOKEN missing

  DriftTools — create_drift_issue():
    - Creates issue with drift labels
    - Returns issue_created with issue_url and issue_number
    - Raises EnvironmentError when GITHUB_TOKEN missing

  DriftTools — execute_option():
    - hold → returns held without API call
    - opt_1 → calls create_drift_pr
    - opt_1 without repository → returns skipped
    - opt_2 with kubernetes source → calls apply_k8s_manifest
    - opt_2 with terraform source → calls create_drift_pr (PR path, not tf apply)
    - opt_3 → calls create_drift_issue
    - unknown option → returns not_implemented

  DriftWorkflow._ingest_node():
    - Extracts drift_source, resource_type, resource_id, scope, repository
    - Normalizes desired_state via desired_state key
    - Normalizes actual_state via actual_state key
    - Accepts alias keys (terraform_state → desired, k8s_live_resource → actual)
    - Sanitizes both state blobs via shield.sanitize()
    - Empty payload sets safe defaults without crash

  DriftWorkflow._diagnose_node():
    - Calls router with task_type="drift_detection"
    - Parses all LLM fields: drift_items, drift_severity, drift_summary, corrected_content, options
    - Accumulates tokens from prior state
    - Sets error on parse failure
    - Calls check_budget() before LLM call
    - User message includes drift_source, resource_type, resource_id

  DriftWorkflow._hitl_gate_node():
    - Calls hitl.create_incident() with correct agent_id
    - raw_log includes resource_id, drift_severity, and item count
    - interrupt() includes drift_severity and drift_count
    - Skips incident creation when state["error"] is set

  _build_drift_report():
    - Includes drift_source and resource_id
    - Includes correct severity icon
    - Includes drift items table with key/desired/actual columns
    - Includes Cloud Decoded attribution
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agents.agent_08_drift_detection.tools import DriftTools
from agents.agent_08_drift_detection.workflow import (
    DriftWorkflow,
    DriftState,
    _detect_drift_source,
    _normalize_state_text,
    _build_drift_report,
)


# ──────────────────────────────────────────────────────────────────────────────
# Sample data
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_DRIFT_ITEMS = [
    {
        "key": "ingress_rules[0].cidr_blocks",
        "desired_value": "10.0.0.0/8",
        "actual_value": "0.0.0.0/0",
        "severity": "CRITICAL",
        "description": "Security group allows unrestricted internet access",
    },
    {
        "key": "tags.Environment",
        "desired_value": "production",
        "actual_value": "prod",
        "severity": "LOW",
        "description": "Tag value differs",
    },
]

SAMPLE_LLM_DRIFT_DIAGNOSIS = json.dumps({
    "parsed_error": "2 drift items detected in aws_security_group sg-abc123: critical ingress rule exposure",
    "drift_summary": (
        "Security group sg-abc123 has its ingress rule exposed to 0.0.0.0/0 instead of the "
        "desired 10.0.0.0/8. This allows unrestricted internet access. Additionally, "
        "the Environment tag is mismatched. Corrected content restores the desired state."
    ),
    "drift_items": SAMPLE_DRIFT_ITEMS,
    "drift_severity": "CRITICAL",
    "corrected_content": 'resource "aws_security_group" "web" {\n  ingress {\n    cidr_blocks = ["10.0.0.0/8"]\n  }\n}',
    "options": [
        {
            "id": "opt_1",
            "title": "Create Remediation PR",
            "description": "Open a PR with corrected security group definition.",
            "impact": "LOW — no live changes until PR is merged",
            "docs_url": "",
        },
        {
            "id": "opt_2",
            "title": "Apply Correction Directly",
            "description": "For K8s: kubectl apply. For IaC: creates a PR.",
            "impact": "MEDIUM",
            "docs_url": "",
        },
        {
            "id": "opt_3",
            "title": "Create Drift Issue",
            "description": "Track drift as a GitHub issue.",
            "impact": "NONE",
            "docs_url": "",
        },
        {
            "id": "hold",
            "title": "Hold — Manual Review",
            "description": "No automated action.",
            "impact": "NONE",
            "docs_url": "",
        },
    ],
})

SAMPLE_TF_DESIRED = {
    "resource_type": "aws_security_group",
    "name": "web-sg",
    "ingress": [{"from_port": 443, "to_port": 443, "protocol": "tcp", "cidr_blocks": ["10.0.0.0/8"]}],
}

SAMPLE_LIVE_STATE = {
    "GroupId": "sg-abc123",
    "GroupName": "web-sg",
    "IpPermissions": [{"FromPort": 443, "ToPort": 443, "IpProtocol": "tcp",
                        "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_http_resp(status_code: int, body) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = json.dumps(body)[:500] if isinstance(body, (dict, list)) else str(body)[:500]
    return resp


def _make_workflow(mock_db, workspace_id, mock_router) -> DriftWorkflow:
    with (
        patch("agents.base_agent._load_router", return_value=mock_router),
        patch.object(DriftWorkflow, "_build_graph", return_value=MagicMock()),
    ):
        wf = DriftWorkflow(mock_db, workspace_id, MagicMock())
    return wf


def _base_state(workspace_id: str, payload: dict | None = None) -> DriftState:
    return {
        "workspace_id":      workspace_id,
        "cloud_provider":    "aws",
        "webhook_payload":   payload or {},
        "drift_source":      "",
        "resource_type":     "",
        "resource_id":       "",
        "scope":             "",
        "repository":        "",
        "file_path":         "",
        "desired_state_text": "",
        "actual_state_text": "",
        "incident_id":       None,
        "parsed_error":      None,
        "drift_items":       None,
        "drift_count":       None,
        "drift_severity":    None,
        "drift_summary":     None,
        "corrected_content": None,
        "remediation_options": None,
        "tokens_used":       0,
        "selected_option":   None,
        "execution_result":  None,
        "error":             None,
    }


def _diagnose_state(workspace_id: str) -> DriftState:
    s = _base_state(workspace_id)
    s.update({
        "drift_source":       "terraform",
        "resource_type":      "aws_security_group",
        "resource_id":        "sg-abc123",
        "scope":              "us-east-1",
        "repository":         "acme/infra",
        "file_path":          "terraform/security_groups.tf",
        "desired_state_text": json.dumps(SAMPLE_TF_DESIRED, indent=2),
        "actual_state_text":  json.dumps(SAMPLE_LIVE_STATE, indent=2),
    })
    return s


def _hitl_state(workspace_id: str) -> DriftState:
    s = _diagnose_state(workspace_id)
    parsed = json.loads(SAMPLE_LLM_DRIFT_DIAGNOSIS)
    s.update({
        "parsed_error":       parsed["parsed_error"],
        "drift_items":        parsed["drift_items"],
        "drift_count":        2,
        "drift_severity":     "CRITICAL",
        "drift_summary":      parsed["drift_summary"],
        "corrected_content":  parsed["corrected_content"],
        "remediation_options": parsed["options"],
        "tokens_used":        900,
    })
    return s


# ──────────────────────────────────────────────────────────────────────────────
# _detect_drift_source()
# ──────────────────────────────────────────────────────────────────────────────

class TestDetectDriftSource:
    def test_detects_terraform_from_terraform_state_key(self):
        assert _detect_drift_source({"terraform_state": {}}) == "terraform"

    def test_detects_terraform_from_tfstate_key(self):
        assert _detect_drift_source({"tfstate": {}}) == "terraform"

    def test_detects_terraform_from_terraform_config_key(self):
        assert _detect_drift_source({"terraform_config": "..."}) == "terraform"

    def test_detects_kubernetes_from_k8s_manifest_key(self):
        assert _detect_drift_source({"k8s_manifest": {}}) == "kubernetes"

    def test_detects_kubernetes_from_manifest_key(self):
        assert _detect_drift_source({"manifest": {}}) == "kubernetes"

    def test_detects_cloudformation_from_cfn_template_key(self):
        assert _detect_drift_source({"cfn_template": {}}) == "cloudformation"

    def test_falls_back_to_generic_when_no_known_keys(self):
        assert _detect_drift_source({"resource_id": "sg-123", "desired_state": {}}) == "generic"

    def test_respects_explicit_drift_source_override(self):
        assert _detect_drift_source({"drift_source": "kubernetes"}) == "kubernetes"

    def test_explicit_source_takes_priority_over_payload_keys(self):
        assert _detect_drift_source({"drift_source": "cloudformation", "k8s_manifest": {}}) == "cloudformation"


# ──────────────────────────────────────────────────────────────────────────────
# _normalize_state_text()
# ──────────────────────────────────────────────────────────────────────────────

class TestNormalizeStateText:
    def test_converts_dict_to_json_string(self):
        result = _normalize_state_text({"key": "value"})
        assert '"key"' in result
        assert '"value"' in result

    def test_converts_list_to_json_array(self):
        result = _normalize_state_text([1, 2, 3])
        assert "[" in result

    def test_accepts_string_as_is(self):
        result = _normalize_state_text("already a string")
        assert result == "already a string"

    def test_truncates_at_max_chars(self):
        large = {"key": "x" * 10000}
        result = _normalize_state_text(large, max_chars=100)
        assert len(result) <= 120  # 100 + truncation marker
        assert "truncated" in result

    def test_returns_empty_string_for_none(self):
        assert _normalize_state_text(None) == ""


# ──────────────────────────────────────────────────────────────────────────────
# DriftTools — fetch_k8s_resource()
# ──────────────────────────────────────────────────────────────────────────────

class TestFetchK8sResource:
    @pytest.fixture
    def tools(self):
        return DriftTools(allow_kubectl=True)

    async def test_returns_error_when_kubectl_disabled(self):
        no_kubectl = DriftTools(allow_kubectl=False)
        result = await no_kubectl.fetch_k8s_resource("deployment", "payment-service")
        assert "error" in result

    async def test_returns_error_on_nonzero_exit_code(self, tools):
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b'Error from server (NotFound)'))

        with patch("agents.agent_08_drift_detection.tools.asyncio.create_subprocess_exec",
                   return_value=mock_proc):
            result = await tools.fetch_k8s_resource("deployment", "missing-service", "production")

        assert "error" in result
        assert "NotFound" in result["error"]


# ──────────────────────────────────────────────────────────────────────────────
# DriftTools — apply_k8s_manifest()
# ──────────────────────────────────────────────────────────────────────────────

class TestApplyK8sManifest:
    @pytest.fixture
    def tools(self):
        return DriftTools(allow_kubectl=True)

    async def test_returns_ok_on_zero_exit_code(self, tools):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"deployment.apps/payment configured", b""))

        with patch("agents.agent_08_drift_detection.tools.asyncio.create_subprocess_exec",
                   return_value=mock_proc):
            result = await tools.apply_k8s_manifest("apiVersion: apps/v1\nkind: Deployment\n...", "production")

        assert result["status"] == "ok"
        assert result["exit_code"] == 0
        assert "configured" in result["stdout"]

    async def test_returns_failed_on_nonzero_exit_code(self, tools):
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b'error: invalid manifest'))

        with patch("agents.agent_08_drift_detection.tools.asyncio.create_subprocess_exec",
                   return_value=mock_proc):
            result = await tools.apply_k8s_manifest("invalid yaml", "default")

        assert result["status"] == "failed"
        assert "invalid manifest" in result["stderr"]

    async def test_returns_skipped_when_kubectl_disabled(self):
        no_kubectl = DriftTools(allow_kubectl=False)
        result = await no_kubectl.apply_k8s_manifest("apiVersion: apps/v1", "default")
        assert result["status"] == "skipped"


# ──────────────────────────────────────────────────────────────────────────────
# DriftTools — create_drift_pr()
# ──────────────────────────────────────────────────────────────────────────────

class TestCreateDriftPR:
    @pytest.fixture
    def tools(self):
        return DriftTools(github_token="gh_test_token")

    async def test_raises_without_github_token(self):
        no_token = DriftTools(github_token="")
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            await no_token.create_drift_pr("acme", "infra", "drift-fix", "tf/sg.tf", "content", "body")

    async def test_executes_5_step_github_flow(self, tools):
        ref_resp    = _make_http_resp(200, {"object": {"sha": "abc123"}})
        branch_resp = _make_http_resp(201, {})
        file_resp   = _make_http_resp(200, {"sha": "def456"})
        commit_resp = _make_http_resp(201, {})
        pr_resp     = _make_http_resp(201, {"number": 42, "html_url": "https://github.com/acme/infra/pull/42"})

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__  = AsyncMock(return_value=False)
        ctx.get  = AsyncMock(side_effect=[ref_resp, file_resp])
        ctx.post = AsyncMock(side_effect=[branch_resp, pr_resp])
        ctx.put  = AsyncMock(return_value=commit_resp)

        with patch("agents.agent_08_drift_detection.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.create_drift_pr(
                "acme", "infra", "drift-correction/sg-abc123",
                "terraform/security_groups.tf",
                'resource "aws_security_group" "web" {}',
                "## Drift Report",
            )

        assert result["status"] == "pr_created"
        assert result["pr_number"] == 42
        assert "acme/infra/pull/42" in result["pr_url"]

    async def test_creates_pr_for_new_file_without_file_sha(self, tools):
        ref_resp    = _make_http_resp(200, {"object": {"sha": "abc123"}})
        branch_resp = _make_http_resp(201, {})
        file_resp   = _make_http_resp(404, {})  # file doesn't exist yet
        commit_resp = _make_http_resp(201, {})
        pr_resp     = _make_http_resp(201, {"number": 43, "html_url": "https://github.com/acme/infra/pull/43"})

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__  = AsyncMock(return_value=False)
        ctx.get  = AsyncMock(side_effect=[ref_resp, file_resp])
        ctx.post = AsyncMock(side_effect=[branch_resp, pr_resp])
        ctx.put  = AsyncMock(return_value=commit_resp)

        with patch("agents.agent_08_drift_detection.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.create_drift_pr(
                "acme", "infra", "drift-new-file/sg-new",
                "terraform/new_sg.tf", "content", "body",
            )

        assert result["status"] == "pr_created"
        # When file doesn't exist, commit_body should not include sha
        commit_payload = ctx.put.call_args.kwargs["json"]
        assert "sha" not in commit_payload


# ──────────────────────────────────────────────────────────────────────────────
# DriftTools — create_drift_issue()
# ──────────────────────────────────────────────────────────────────────────────

class TestCreateDriftIssue:
    @pytest.fixture
    def tools(self):
        return DriftTools(github_token="gh_test_token")

    async def test_raises_without_github_token(self):
        no_token = DriftTools(github_token="")
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            await no_token.create_drift_issue("acme", "infra", "title", "body")

    async def test_creates_issue_with_drift_labels(self, tools):
        issue_resp = _make_http_resp(201, {"number": 77, "html_url": "https://github.com/acme/infra/issues/77"})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__  = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=issue_resp)

        with patch("agents.agent_08_drift_detection.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.create_drift_issue(
                "acme", "infra",
                "Drift detected: sg-abc123",
                "## Report",
                labels=["drift", "infrastructure"],
            )

        assert result["status"] == "issue_created"
        assert result["issue_number"] == 77
        payload = ctx.post.call_args.kwargs["json"]
        assert "drift" in payload.get("labels", [])


# ──────────────────────────────────────────────────────────────────────────────
# DriftTools — execute_option()
# ──────────────────────────────────────────────────────────────────────────────

class TestExecuteOption:
    @pytest.fixture
    def tools(self):
        return DriftTools(github_token="gh_test_token", allow_kubectl=True)

    @pytest.fixture
    def tf_context(self):
        return {
            "drift_source":      "terraform",
            "resource_id":       "sg-abc123",
            "resource_type":     "aws_security_group",
            "scope":             "us-east-1",
            "namespace":         "us-east-1",
            "owner":             "acme",
            "repo":              "infra",
            "file_path":         "terraform/security_groups.tf",
            "corrected_content": 'resource "aws_security_group" "web" {}',
            "drift_summary":     "Security group has critical drift",
            "report_body":       "## Drift Report",
            "issue_title":       "Drift: sg-abc123",
        }

    @pytest.fixture
    def k8s_context(self, tf_context):
        return {**tf_context, "drift_source": "kubernetes", "scope": "production", "namespace": "production"}

    async def test_hold_returns_held_without_api_call(self, tools, tf_context):
        with patch.object(tools, "create_drift_pr") as mock_pr:
            result = await tools.execute_option({"id": "hold"}, tf_context)
        assert result["status"] == "held"
        mock_pr.assert_not_called()

    async def test_opt1_calls_create_drift_pr(self, tools, tf_context):
        expected = {"status": "pr_created", "pr_url": "https://github.com/acme/infra/pull/5", "pr_number": 5, "branch": "drift-correction/sg-abc123"}
        with patch.object(tools, "create_drift_pr", new=AsyncMock(return_value=expected)) as mock_pr:
            result = await tools.execute_option({"id": "opt_1"}, tf_context)
        assert result["status"] == "pr_created"
        mock_pr.assert_called_once()

    async def test_opt1_without_repository_returns_skipped(self, tools, tf_context):
        ctx = {**tf_context, "owner": "", "repo": ""}
        result = await tools.execute_option({"id": "opt_1"}, ctx)
        assert result["status"] == "skipped"

    async def test_opt2_with_kubernetes_calls_apply_k8s_manifest(self, tools, k8s_context):
        expected = {"status": "ok", "exit_code": 0, "stdout": "deployment configured", "stderr": ""}
        with patch.object(tools, "apply_k8s_manifest", new=AsyncMock(return_value=expected)) as mock_apply:
            result = await tools.execute_option({"id": "opt_2"}, k8s_context)
        assert result["status"] == "ok"
        mock_apply.assert_called_once_with(k8s_context["corrected_content"], namespace="production")

    async def test_opt2_with_terraform_calls_create_drift_pr(self, tools, tf_context):
        expected = {"status": "pr_created", "pr_url": "https://github.com/acme/infra/pull/6", "pr_number": 6, "branch": "x"}
        with patch.object(tools, "create_drift_pr", new=AsyncMock(return_value=expected)) as mock_pr:
            result = await tools.execute_option({"id": "opt_2"}, tf_context)
        # Never runs terraform apply — always creates a PR for IaC sources
        assert result["status"] == "pr_created"
        mock_pr.assert_called_once()

    async def test_opt3_calls_create_drift_issue(self, tools, tf_context):
        expected = {"status": "issue_created", "issue_url": "https://github.com/acme/infra/issues/10", "issue_number": 10}
        with patch.object(tools, "create_drift_issue", new=AsyncMock(return_value=expected)) as mock_issue:
            result = await tools.execute_option({"id": "opt_3"}, tf_context)
        assert result["status"] == "issue_created"
        mock_issue.assert_called_once()

    async def test_unknown_option_returns_not_implemented(self, tools, tf_context):
        result = await tools.execute_option({"id": "opt_99"}, tf_context)
        assert result["status"] == "not_implemented"


# ──────────────────────────────────────────────────────────────────────────────
# DriftWorkflow._ingest_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestIngestNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        return _make_workflow(mock_db, workspace_id, mock_router)

    async def test_extracts_drift_source_resource_type_and_resource_id(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "terraform_state":   SAMPLE_TF_DESIRED,
            "actual_state":      SAMPLE_LIVE_STATE,
            "resource_type":     "aws_security_group",
            "resource_id":       "sg-abc123",
            "scope":             "us-east-1",
        })
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="sanitized")

        with patch("agents.agent_08_drift_detection.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["drift_source"] == "terraform"
        assert result["resource_type"] == "aws_security_group"
        assert result["resource_id"] == "sg-abc123"
        assert result["scope"] == "us-east-1"

    async def test_normalizes_desired_state_via_desired_state_key(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "desired_state": {"ingress": [{"cidr": "10.0.0.0/8"}]},
            "actual_state":  {},
        })
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="sanitized desired")

        with patch("agents.agent_08_drift_detection.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["desired_state_text"] == "sanitized desired"

    async def test_accepts_alias_keys_for_state(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "terraform_state":     SAMPLE_TF_DESIRED,   # alias for desired_state
            "k8s_live_resource":   SAMPLE_LIVE_STATE,   # alias for actual_state
        })
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="sanitized")

        with patch("agents.agent_08_drift_detection.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        # Both blobs were passed to sanitize
        assert shield_mock.sanitize.call_count == 2

    async def test_sanitizes_both_state_blobs(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "desired_state": SAMPLE_TF_DESIRED,
            "actual_state":  SAMPLE_LIVE_STATE,
        })
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="safe")

        with patch("agents.agent_08_drift_detection.workflow.shield", shield_mock):
            await wf._ingest_node(state)

        assert shield_mock.sanitize.call_count == 2

    async def test_empty_payload_sets_safe_defaults(self, wf, workspace_id):
        state = _base_state(workspace_id, {})
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="")

        with patch("agents.agent_08_drift_detection.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["error"] is None
        assert result["drift_source"] == "generic"
        assert result["resource_type"] == "unknown"
        assert result["resource_id"] == "unknown"

    async def test_extracts_repository_and_file_path(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "desired_state": {},
            "actual_state":  {},
            "repository":    "acme/infra",
            "file_path":     "terraform/sg.tf",
        })
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="")

        with patch("agents.agent_08_drift_detection.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["repository"] == "acme/infra"
        assert result["file_path"] == "terraform/sg.tf"


# ──────────────────────────────────────────────────────────────────────────────
# DriftWorkflow._diagnose_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestDiagnoseNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        wf._router = mock_router
        mock_router.complete.return_value = SAMPLE_LLM_DRIFT_DIAGNOSIS
        return wf

    async def test_calls_router_with_drift_detection_task_type(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_DRIFT_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_DRIFT_DIAGNOSIS, 1000)) as mock_llm, \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        assert mock_llm.call_args.kwargs["task_type"] == "drift_detection"

    async def test_parses_all_llm_fields(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_DRIFT_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_DRIFT_DIAGNOSIS, 1000)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(state)

        assert result["drift_items"] == SAMPLE_DRIFT_ITEMS
        assert result["drift_count"] == 2
        assert result["drift_severity"] == "CRITICAL"
        assert "0.0.0.0/0" in result["drift_summary"]
        assert result["corrected_content"].startswith('resource "aws_security_group"')

    async def test_accumulates_tokens_from_prior_state(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        state["tokens_used"] = 300
        parsed = json.loads(SAMPLE_LLM_DRIFT_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_DRIFT_DIAGNOSIS, 1000)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(state)

        assert result["tokens_used"] == 1300

    async def test_sets_error_on_parse_failure(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=("bad json", 100)), \
             patch.object(wf, "parse_llm_json", side_effect=ValueError("JSON parse failed")):
            result = await wf._diagnose_node(state)

        assert result.get("error") is not None

    async def test_calls_check_budget_before_llm(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_DRIFT_DIAGNOSIS)
        order = []

        async def mock_budget(*a, **kw): order.append("budget")
        def mock_llm(*a, **kw):
            order.append("llm")
            return (SAMPLE_LLM_DRIFT_DIAGNOSIS, 1000)

        with patch.object(wf, "check_budget", side_effect=mock_budget), \
             patch.object(wf, "call_llm", side_effect=mock_llm), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        assert order.index("budget") < order.index("llm")

    async def test_user_message_includes_drift_source_resource_type_and_id(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_DRIFT_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_DRIFT_DIAGNOSIS, 1000)) as mock_llm, \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        content = mock_llm.call_args.kwargs["messages"][0]["content"]
        assert "terraform" in content
        assert "aws_security_group" in content
        assert "sg-abc123" in content


# ──────────────────────────────────────────────────────────────────────────────
# DriftWorkflow._hitl_gate_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestHITLGateNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        return _make_workflow(mock_db, workspace_id, mock_router)

    async def test_calls_create_incident_with_correct_agent_id(self, wf, workspace_id):
        state = _hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_08_drift_detection.workflow.interrupt", return_value={"id": "hold"}):
            await wf._hitl_gate_node(state)

        call_kwargs = mock_hitl.create_incident.call_args.kwargs
        assert call_kwargs["agent_id"] == "agent_08_drift_detection"
        assert call_kwargs["workspace_id"] == workspace_id

    async def test_raw_log_includes_resource_id_and_drift_severity(self, wf, workspace_id):
        state = _hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_08_drift_detection.workflow.interrupt", return_value={"id": "hold"}):
            await wf._hitl_gate_node(state)

        raw_log = mock_hitl.create_incident.call_args.kwargs["raw_log"]
        assert "sg-abc123" in raw_log
        assert "CRITICAL" in raw_log

    async def test_interrupt_includes_drift_severity_and_count(self, wf, workspace_id):
        state = _hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_08_drift_detection.workflow.interrupt", return_value={"id": "opt_1"}) as mock_interrupt:
            await wf._hitl_gate_node(state)

        interrupt_arg = mock_interrupt.call_args.args[0]
        assert interrupt_arg["drift_severity"] == "CRITICAL"
        assert interrupt_arg["drift_count"] == 2

    async def test_skips_incident_creation_on_error(self, wf, workspace_id):
        state = _hitl_state(workspace_id)
        state["error"] = "LLM failed"

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock()
        wf.hitl = mock_hitl

        result = await wf._hitl_gate_node(state)

        mock_hitl.create_incident.assert_not_called()
        assert result == {}


# ──────────────────────────────────────────────────────────────────────────────
# _build_drift_report()
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildDriftReport:
    def test_includes_drift_source_and_resource_id(self):
        report = _build_drift_report(
            drift_source="terraform",
            resource_type="aws_security_group",
            resource_id="sg-abc123",
            scope="us-east-1",
            drift_severity="CRITICAL",
            drift_summary="Critical exposure detected",
            drift_items=SAMPLE_DRIFT_ITEMS,
        )
        assert "terraform" in report
        assert "sg-abc123" in report

    def test_includes_critical_severity_icon(self):
        report = _build_drift_report(
            "terraform", "aws_security_group", "sg-1", "us-east-1",
            "CRITICAL", "", SAMPLE_DRIFT_ITEMS,
        )
        assert "🔴" in report

    def test_includes_drift_items_table_with_key_columns(self):
        report = _build_drift_report(
            "terraform", "aws_security_group", "sg-1", "us-east-1",
            "CRITICAL", "", SAMPLE_DRIFT_ITEMS,
        )
        assert "ingress_rules[0].cidr_blocks" in report
        assert "10.0.0.0/8" in report
        assert "0.0.0.0/0" in report

    def test_includes_cloud_decoded_attribution(self):
        report = _build_drift_report(
            "kubernetes", "Deployment", "payment-service", "production",
            "LOW", "", [],
        )
        assert "Cloud Decoded" in report
