"""
tests/test_agent05.py
Tests for agents/agent_05_iam_minimizer/tools.py and workflow.py.

What this file validates:
  IAMMinimizeTools — read operations:
    - get_aws_policy_document() GETs ListPolicyVersions then GetPolicyVersion
    - get_aws_policy_document() raises EnvironmentError when AWS credentials missing
    - get_azure_role_assignments() GETs the ARM role assignments endpoint
    - get_azure_role_assignments() raises EnvironmentError when AZURE_ACCESS_TOKEN missing
    - get_gcp_iam_policy() POSTs to the GCP resource manager getIamPolicy endpoint
    - get_gcp_iam_policy() raises EnvironmentError when GCP_ACCESS_TOKEN missing

  IAMMinimizeTools — write operations (post-approval only):
    - apply_aws_policy() POSTs CreatePolicyVersion with the minimized document
    - apply_aws_policy() raises EnvironmentError when AWS credentials missing
    - apply_azure_role_assignment() PUTs a new role assignment
    - apply_gcp_iam_binding() POSTs setIamPolicy for the resource
    - create_policy_pr() opens a PR with the minimized policy file (5-step flow)
    - create_policy_pr() raises EnvironmentError when GITHUB_TOKEN missing

  IAMMinimizeTools — execute_option():
    - hold → returns held without any cloud API call
    - opt_1 (aws) → dispatches to apply_aws_policy
    - opt_1 (azure) → dispatches to apply_azure_role_assignment
    - opt_1 (gcp) → dispatches to apply_gcp_iam_binding
    - opt_1 (unsupported cloud) → returns not_implemented
    - opt_2 → dispatches to create_policy_pr
    - unknown option → returns not_implemented

  helpers:
    - _summarize_permissions() flattens multi-statement policy into sorted list
    - _summarize_permissions() handles string Action and list Action
    - _summarize_permissions() deduplicates actions
    - _build_access_log_summary() converts list-of-dicts to text
    - _build_access_log_summary() truncates at max_chars
    - _detect_principal_type() detects role/user from AWS ARN
    - _detect_principal_type() detects service_account from GCP member string

  IAMMinimizeWorkflow._ingest_node():
    - Extracts principal_id, principal_name, resource_scope from payload
    - Detects principal_type from ARN structure (AWS)
    - Flattens JSON policy string in payload to dict
    - Sanitizes policy and access log via shield
    - Truncates policy at _MAX_POLICY_CHARS
    - Empty payload sets safe defaults without crash

  IAMMinimizeWorkflow._diagnose_node():
    - Calls router with task_type="iam_minimization"
    - Parses valid LLM JSON into all state fields
    - Serializes minimized_policy to JSON string in minimized_policy_str
    - Accumulates tokens from prior state
    - Sets error on parse failure
    - Calls check_budget() before LLM call
    - Includes principal_id, cloud, policy, access log in user message

  IAMMinimizeWorkflow._hitl_gate_node():
    - Calls hitl.create_incident() with correct agent_id and workspace_id
    - Builds raw_log that includes principal_id and risk_score
    - Calls interrupt() with incident_id, options, and risk_score
    - Skips incident creation when state["error"] is set
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agents.agent_05_iam_minimizer.tools import (
    IAMMinimizeTools,
    _summarize_permissions,
)
from agents.agent_05_iam_minimizer.workflow import (
    IAMMinimizeWorkflow,
    IAMMinimizeState,
    _detect_principal_type,
    _build_pr_body,
    _build_access_log_summary as _log_summary,
)


# ──────────────────────────────────────────────────────────────────────────────
# Sample data
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_AWS_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
            "Resource": "*",
        },
        {
            "Effect": "Allow",
            "Action": "logs:PutLogEvents",
            "Resource": "*",
        },
        {
            "Effect": "Allow",
            "Action": ["iam:CreatePolicy", "iam:AttachRolePolicy"],
            "Resource": "*",
        },
    ],
}

SAMPLE_MINIMIZED_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["s3:GetObject", "logs:PutLogEvents"],
            "Resource": "*",
        }
    ],
}

SAMPLE_ACCESS_LOG = [
    {"eventTime": "2026-06-01T10:00:00Z", "eventName": "s3:GetObject"},
    {"eventTime": "2026-06-01T10:01:00Z", "eventName": "logs:PutLogEvents"},
]

SAMPLE_LLM_IAM_DIAGNOSIS = json.dumps({
    "parsed_error": "AppRole has 6 permissions; only 2 were used in 30 days — iam:CreatePolicy and s3:PutObject/DeleteObject/ListBucket are unused (HIGH risk).",
    "risk_score": "HIGH",
    "permissions_removed": ["iam:createpolicy", "iam:attachrolepolicy", "s3:putobject", "s3:deleteobject", "s3:listbucket"],
    "permissions_kept": ["s3:getobject", "logs:putlogevents"],
    "minimized_policy": SAMPLE_MINIMIZED_POLICY,
    "justification": "Removed iam:* and unused s3 write actions based on 30-day CloudTrail data. Retained s3:GetObject and logs:PutLogEvents which appear in every log window.",
    "options": [
        {
            "id": "opt_1",
            "title": "Apply Minimized Policy Directly",
            "description": "Immediately update the IAM policy in AWS.",
            "impact": "MEDIUM",
            "docs_url": "https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_manage-edit.html",
        },
        {
            "id": "opt_2",
            "title": "Create PR with Minimized Policy",
            "description": "Open a GitHub PR for team review.",
            "impact": "LOW",
            "docs_url": "https://docs.github.com/en/pull-requests",
        },
        {
            "id": "hold",
            "title": "Hold — Manual Review",
            "description": "Pause for manual handling.",
            "impact": "NONE",
            "docs_url": "",
        },
    ],
    "estimated_duration_seconds": 30,
})


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_http_resp(status_code: int, body) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = json.dumps(body)[:200] if isinstance(body, (dict, list)) else str(body)[:200]
    return resp


def _make_workflow(mock_db, workspace_id, mock_router) -> IAMMinimizeWorkflow:
    with (
        patch("agents.base_agent._load_router", return_value=mock_router),
        patch.object(IAMMinimizeWorkflow, "_build_graph", return_value=MagicMock()),
    ):
        wf = IAMMinimizeWorkflow(mock_db, workspace_id, MagicMock())
    return wf


def _base_state(workspace_id: str, payload: dict | None = None, cloud: str = "aws") -> IAMMinimizeState:
    return {
        "workspace_id": workspace_id,
        "cloud_provider": cloud,
        "webhook_payload": payload or {},
        "principal_id": "",
        "principal_type": "",
        "principal_name": "",
        "resource_scope": "",
        "current_policy_summary": "",
        "access_log_summary": "",
        "repository": "",
        "incident_id": None,
        "parsed_error": None,
        "minimized_policy": None,
        "minimized_policy_str": None,
        "permissions_removed": None,
        "permissions_kept": None,
        "risk_score": None,
        "remediation_options": None,
        "estimated_duration_seconds": None,
        "tokens_used": 0,
        "selected_option": None,
        "execution_result": None,
        "error": None,
    }


def _diagnose_state(workspace_id: str) -> IAMMinimizeState:
    s = _base_state(workspace_id)
    s.update({
        "principal_id": "arn:aws:iam::123456789012:role/AppRole",
        "principal_type": "role",
        "principal_name": "AppRole",
        "resource_scope": "arn:aws:iam::123456789012:policy/AppPolicy",
        "current_policy_summary": json.dumps(SAMPLE_AWS_POLICY),
        "access_log_summary": "2026-06-01: s3:GetObject\n2026-06-01: logs:PutLogEvents",
    })
    return s


def _hitl_state(workspace_id: str) -> IAMMinimizeState:
    s = _diagnose_state(workspace_id)
    parsed = json.loads(SAMPLE_LLM_IAM_DIAGNOSIS)
    s.update({
        "parsed_error": parsed["parsed_error"],
        "risk_score": parsed["risk_score"],
        "minimized_policy": parsed["minimized_policy"],
        "minimized_policy_str": json.dumps(parsed["minimized_policy"]),
        "permissions_removed": parsed["permissions_removed"],
        "permissions_kept": parsed["permissions_kept"],
        "remediation_options": parsed["options"],
        "estimated_duration_seconds": 30,
        "tokens_used": 1200,
    })
    return s


# ──────────────────────────────────────────────────────────────────────────────
# Helper function tests
# ──────────────────────────────────────────────────────────────────────────────

class TestSummarizePermissions:
    def test_flattens_multi_statement_policy(self):
        perms = _summarize_permissions(SAMPLE_AWS_POLICY)
        assert "s3:getobject" in perms
        assert "logs:putlogevents" in perms
        assert "iam:createpolicy" in perms

    def test_handles_string_action(self):
        policy = {"Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}]}
        perms = _summarize_permissions(policy)
        assert perms == ["s3:getobject"]

    def test_deduplicates_actions(self):
        policy = {
            "Statement": [
                {"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "*"},
                {"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "arn:aws:s3:::bucket/*"},
            ]
        }
        perms = _summarize_permissions(policy)
        assert perms.count("s3:getobject") == 1

    def test_returns_sorted_list(self):
        policy = {
            "Statement": [{"Effect": "Allow", "Action": ["s3:PutObject", "ec2:DescribeInstances", "logs:PutLogEvents"], "Resource": "*"}]
        }
        perms = _summarize_permissions(policy)
        assert perms == sorted(perms)

    def test_empty_policy_returns_empty_list(self):
        assert _summarize_permissions({}) == []


class TestBuildAccessLogSummary:
    def test_converts_list_of_dicts_to_text(self):
        summary = _log_summary(SAMPLE_ACCESS_LOG)
        assert "s3:GetObject" in summary
        assert "logs:PutLogEvents" in summary

    def test_truncates_at_max_chars(self):
        big_log = [{"eventTime": "2026-06-01", "eventName": "s3:GetObject"}] * 1000
        summary = _log_summary(big_log, max_chars=100)
        assert len(summary) <= 120  # truncated + "[truncated]" suffix
        assert "[truncated]" in summary

    def test_accepts_raw_string(self):
        summary = _log_summary("s3:GetObject at 2026-06-01\nlogs:PutLogEvents at 2026-06-02")
        assert "s3:GetObject" in summary

    def test_empty_list_returns_empty_string(self):
        assert _log_summary([]) == ""


class TestDetectPrincipalType:
    def test_aws_role_arn(self):
        payload = {"principal_id": "arn:aws:iam::123456789012:role/AppRole"}
        assert _detect_principal_type(payload, "aws") == "role"

    def test_aws_user_arn(self):
        payload = {"principal_id": "arn:aws:iam::123456789012:user/alice"}
        assert _detect_principal_type(payload, "aws") == "user"

    def test_gcp_service_account_member(self):
        payload = {"principal_id": "serviceAccount:app@project.iam.gserviceaccount.com"}
        assert _detect_principal_type(payload, "gcp") == "service_account"

    def test_gcp_group_member(self):
        payload = {"principal_id": "group:devs@example.com"}
        assert _detect_principal_type(payload, "gcp") == "group"

    def test_explicit_principal_type_overrides_detection(self):
        payload = {"principal_id": "arn:aws:iam::123/role/Foo", "principal_type": "user"}
        assert _detect_principal_type(payload, "aws") == "user"


# ──────────────────────────────────────────────────────────────────────────────
# IAMMinimizeTools — read operations
# ──────────────────────────────────────────────────────────────────────────────

class TestGetAWSPolicyDocument:
    @pytest.fixture
    def tools(self):
        return IAMMinimizeTools(aws_access_key_id="AKID", aws_secret_access_key="secret")

    async def test_raises_without_aws_credentials(self):
        no_creds = IAMMinimizeTools(aws_access_key_id="")
        with pytest.raises(EnvironmentError, match="AWS_ACCESS_KEY_ID"):
            await no_creds.get_aws_policy_document("arn:aws:iam::123:policy/P")

    async def test_calls_list_then_get_policy_version(self, tools):
        # XML responses that parse_aws_* helpers can handle
        list_xml = "<ListPolicyVersionsResponse><PolicyVersions><member><IsDefaultVersion>true</IsDefaultVersion><VersionId>v3</VersionId></member></PolicyVersions></ListPolicyVersionsResponse>"
        get_xml  = "<GetPolicyVersionResponse><PolicyVersion><Document>%7B%22Version%22%3A%222012-10-17%22%7D</Document></PolicyVersion></GetPolicyVersionResponse>"

        list_resp = MagicMock(status_code=200, text=list_xml)
        get_resp  = MagicMock(status_code=200, text=get_xml)

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.get = AsyncMock(side_effect=[list_resp, get_resp])

        with patch("agents.agent_05_iam_minimizer.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.get_aws_policy_document("arn:aws:iam::123:policy/P")

        assert ctx.get.call_count == 2
        assert result["policy_arn"] == "arn:aws:iam::123:policy/P"
        assert result["version_id"] == "v3"

    async def test_raises_on_list_versions_error(self, tools):
        err_resp = MagicMock(status_code=403, text="AccessDenied")
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.get = AsyncMock(return_value=err_resp)

        with patch("agents.agent_05_iam_minimizer.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            with pytest.raises(RuntimeError, match="ListPolicyVersions error"):
                await tools.get_aws_policy_document("arn:aws:iam::123:policy/P")


class TestGetAzureRoleAssignments:
    @pytest.fixture
    def tools(self):
        return IAMMinimizeTools(azure_access_token="eyJ0...")

    async def test_raises_without_azure_token(self):
        no_token = IAMMinimizeTools(azure_access_token="")
        with pytest.raises(EnvironmentError, match="AZURE_ACCESS_TOKEN"):
            await no_token.get_azure_role_assignments("sub-123", "principal-abc")

    async def test_gets_role_assignments_endpoint(self, tools):
        assignments = [{"id": "/subscriptions/sub-123/providers/.../roleAssignments/xyz", "properties": {"principalId": "principal-abc"}}]
        resp = _make_http_resp(200, {"value": assignments})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.get = AsyncMock(return_value=resp)

        with patch("agents.agent_05_iam_minimizer.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.get_azure_role_assignments("sub-123", "principal-abc")

        assert len(result) == 1
        call_url = ctx.get.call_args.args[0]
        assert "subscriptions/sub-123" in call_url
        assert "roleAssignments" in call_url


class TestGetGCPIAMPolicy:
    @pytest.fixture
    def tools(self):
        return IAMMinimizeTools(gcp_access_token="ya29.token")

    async def test_raises_without_gcp_token(self):
        no_token = IAMMinimizeTools(gcp_access_token="")
        with pytest.raises(EnvironmentError, match="GCP_ACCESS_TOKEN"):
            await no_token.get_gcp_iam_policy("my-project")

    async def test_posts_to_get_iam_policy_endpoint(self, tools):
        policy = {"bindings": [{"role": "roles/storage.objectViewer", "members": ["serviceAccount:sa@proj.iam.gserviceaccount.com"]}], "version": 3}
        resp = _make_http_resp(200, policy)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=resp)

        with patch("agents.agent_05_iam_minimizer.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.get_gcp_iam_policy("my-project")

        assert "bindings" in result
        call_url = ctx.post.call_args.args[0]
        assert "my-project:getIamPolicy" in call_url


# ──────────────────────────────────────────────────────────────────────────────
# IAMMinimizeTools — write operations
# ──────────────────────────────────────────────────────────────────────────────

class TestApplyAWSPolicy:
    @pytest.fixture
    def tools(self):
        return IAMMinimizeTools(aws_access_key_id="AKID", aws_secret_access_key="secret")

    async def test_raises_without_credentials(self):
        no_creds = IAMMinimizeTools(aws_access_key_id="")
        with pytest.raises(EnvironmentError, match="AWS_ACCESS_KEY_ID"):
            await no_creds.apply_aws_policy("arn:aws:iam::123:policy/P", {})

    async def test_posts_create_policy_version(self, tools):
        ok_xml = "<CreatePolicyVersionResponse><PolicyVersion><VersionId>v4</VersionId></PolicyVersion></CreatePolicyVersionResponse>"
        resp = MagicMock(status_code=200, text=ok_xml)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=resp)

        with patch("agents.agent_05_iam_minimizer.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.apply_aws_policy("arn:aws:iam::123:policy/P", SAMPLE_MINIMIZED_POLICY)

        assert result["status"] == "policy_updated"
        assert result["cloud"] == "aws"
        assert result["new_version_id"] == "v4"

    async def test_raises_on_api_error(self, tools):
        err_resp = MagicMock(status_code=403, text="AccessDenied")
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=err_resp)

        with patch("agents.agent_05_iam_minimizer.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            with pytest.raises(RuntimeError, match="CreatePolicyVersion error"):
                await tools.apply_aws_policy("arn:aws:iam::123:policy/P", {})


class TestApplyAzureRoleAssignment:
    @pytest.fixture
    def tools(self):
        return IAMMinimizeTools(azure_access_token="eyJ0...")

    async def test_puts_role_assignment(self, tools):
        resp = _make_http_resp(201, {"id": "/subscriptions/sub-123/.../roleAssignments/new-id"})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.put = AsyncMock(return_value=resp)

        with patch("agents.agent_05_iam_minimizer.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.apply_azure_role_assignment(
                subscription_id="sub-123",
                principal_id="principal-abc",
                role_definition_id="/subscriptions/sub-123/providers/Microsoft.Authorization/roleDefinitions/def-id",
                scope="/subscriptions/sub-123",
            )

        assert result["status"] == "assignment_created"
        assert result["cloud"] == "azure"


class TestApplyGCPIAMBinding:
    @pytest.fixture
    def tools(self):
        return IAMMinimizeTools(gcp_access_token="ya29.token")

    async def test_posts_set_iam_policy(self, tools):
        resp = _make_http_resp(200, {"bindings": [], "version": 3})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=resp)

        with patch("agents.agent_05_iam_minimizer.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.apply_gcp_iam_binding(
                resource="my-project",
                resource_type="projects",
                policy={"bindings": [], "version": 3},
            )

        assert result["status"] == "policy_set"
        assert result["cloud"] == "gcp"
        call_url = ctx.post.call_args.args[0]
        assert "my-project:setIamPolicy" in call_url


class TestCreatePolicyPR:
    @pytest.fixture
    def tools(self):
        return IAMMinimizeTools(github_token="gh_test_token")

    async def test_opens_pr_with_policy_file(self, tools):
        ref_resp    = _make_http_resp(200, {"object": {"sha": "base_sha"}})
        branch_resp = _make_http_resp(201, {})
        file_resp   = _make_http_resp(404, {})
        put_resp    = _make_http_resp(201, {})
        pr_resp     = _make_http_resp(201, {"html_url": "https://github.com/acme/infra/pull/5", "number": 5})

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.get  = AsyncMock(side_effect=[ref_resp, file_resp])
        ctx.post = AsyncMock(side_effect=[branch_resp, pr_resp])
        ctx.put  = AsyncMock(return_value=put_resp)

        with patch("agents.agent_05_iam_minimizer.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.create_policy_pr(
                owner="acme", repo="infra",
                file_path="iam/AppRole_minimized.json",
                new_content=json.dumps(SAMPLE_MINIMIZED_POLICY, indent=2),
                pr_title="security(iam): minimize AppRole",
                pr_body="## IAM Minimization",
            )

        assert result["status"] == "pr_opened"
        assert result["pr_number"] == 5
        assert "cloud-decoded/iam-minimize-" in result["branch"]

    async def test_raises_without_github_token(self):
        no_token = IAMMinimizeTools(github_token="")
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            await no_token.create_policy_pr(
                owner="acme", repo="infra", file_path="f.json",
                new_content="{}", pr_title="t", pr_body="b",
            )


# ──────────────────────────────────────────────────────────────────────────────
# IAMMinimizeTools — execute_option()
# ──────────────────────────────────────────────────────────────────────────────

class TestExecuteOption:
    @pytest.fixture
    def tools(self):
        return IAMMinimizeTools(
            aws_access_key_id="AKID", aws_secret_access_key="secret",
            azure_access_token="eyJ0...", gcp_access_token="ya29...",
            github_token="gh_test_token",
        )

    @pytest.fixture
    def aws_context(self):
        return {
            "cloud_provider": "aws",
            "policy_arn": "arn:aws:iam::123:policy/P",
            "minimized_policy": SAMPLE_MINIMIZED_POLICY,
            "minimized_policy_str": json.dumps(SAMPLE_MINIMIZED_POLICY),
            "owner": "acme", "repo": "infra",
            "file_path": "iam/AppRole_minimized.json",
            "pr_title": "security(iam): minimize AppRole",
            "pr_body": "## Plan",
        }

    async def test_hold_returns_held_without_cloud_call(self, tools, aws_context):
        with patch.object(tools, "apply_aws_policy") as mock_apply:
            result = await tools.execute_option({"id": "hold"}, aws_context)
        assert result["status"] == "held"
        mock_apply.assert_not_called()

    async def test_opt1_aws_dispatches_to_apply_aws_policy(self, tools, aws_context):
        expected = {"status": "policy_updated", "policy_arn": "...", "new_version_id": "v4", "cloud": "aws"}
        with patch.object(tools, "apply_aws_policy", new=AsyncMock(return_value=expected)):
            result = await tools.execute_option({"id": "opt_1"}, aws_context)
        assert result["status"] == "policy_updated"

    async def test_opt1_azure_dispatches_to_apply_azure_role_assignment(self, tools):
        azure_ctx = {
            "cloud_provider": "azure",
            "subscription_id": "sub-123",
            "principal_id": "obj-abc",
            "role_definition_id": "/subscriptions/sub-123/.../def-id",
            "scope": "/subscriptions/sub-123",
            "minimized_policy": {},
        }
        expected = {"status": "assignment_created", "assignment_id": "new-id", "principal_id": "obj-abc", "cloud": "azure"}
        with patch.object(tools, "apply_azure_role_assignment", new=AsyncMock(return_value=expected)):
            result = await tools.execute_option({"id": "opt_1"}, azure_ctx)
        assert result["status"] == "assignment_created"

    async def test_opt1_gcp_dispatches_to_apply_gcp_iam_binding(self, tools):
        gcp_ctx = {
            "cloud_provider": "gcp",
            "resource": "my-project",
            "resource_type": "projects",
            "minimized_policy": {"bindings": [], "version": 3},
        }
        expected = {"status": "policy_set", "resource": "my-project", "resource_type": "projects", "cloud": "gcp"}
        with patch.object(tools, "apply_gcp_iam_binding", new=AsyncMock(return_value=expected)):
            result = await tools.execute_option({"id": "opt_1"}, gcp_ctx)
        assert result["status"] == "policy_set"

    async def test_opt1_unsupported_cloud_returns_not_implemented(self, tools):
        ctx = {"cloud_provider": "oracle", "minimized_policy": {}}
        result = await tools.execute_option({"id": "opt_1"}, ctx)
        assert result["status"] == "not_implemented"

    async def test_opt2_dispatches_to_create_policy_pr(self, tools, aws_context):
        expected = {"status": "pr_opened", "pr_url": "...", "pr_number": 5, "branch": "cloud-decoded/iam-minimize-abc"}
        with patch.object(tools, "create_policy_pr", new=AsyncMock(return_value=expected)):
            result = await tools.execute_option({"id": "opt_2"}, aws_context)
        assert result["status"] == "pr_opened"

    async def test_unknown_option_returns_not_implemented(self, tools, aws_context):
        result = await tools.execute_option({"id": "opt_99"}, aws_context)
        assert result["status"] == "not_implemented"
        assert result["option_id"] == "opt_99"


# ──────────────────────────────────────────────────────────────────────────────
# IAMMinimizeWorkflow._ingest_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestIngestNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        return _make_workflow(mock_db, workspace_id, mock_router)

    async def test_extracts_principal_and_scope_from_payload(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "principal_id": "arn:aws:iam::123456789012:role/AppRole",
            "resource_scope": "arn:aws:iam::123456789012:policy/AppPolicy",
            "current_policy": SAMPLE_AWS_POLICY,
            "access_log": SAMPLE_ACCESS_LOG,
        }, cloud="aws")

        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="sanitized")

        with patch("agents.agent_05_iam_minimizer.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["principal_id"] == "arn:aws:iam::123456789012:role/AppRole"
        assert result["resource_scope"] == "arn:aws:iam::123456789012:policy/AppPolicy"
        assert result["principal_name"] == "AppRole"

    async def test_detects_role_type_from_aws_arn(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "principal_id": "arn:aws:iam::123:role/MyRole",
            "current_policy": {},
        }, cloud="aws")
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="")

        with patch("agents.agent_05_iam_minimizer.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["principal_type"] == "role"

    async def test_parses_json_string_policy(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "principal_id": "arn:aws:iam::123:role/AppRole",
            "current_policy": json.dumps(SAMPLE_AWS_POLICY),  # string, not dict
            "access_log": [],
        }, cloud="aws")

        sanitized_texts = []

        def capture(text, context=None):
            sanitized_texts.append(text)
            return MagicMock(sanitized_text=text[:100])

        shield_mock = MagicMock()
        shield_mock.sanitize.side_effect = capture

        with patch("agents.agent_05_iam_minimizer.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        # The policy text should have been parsed from string to dict and then serialized
        assert result["error"] is None

    async def test_sanitizes_policy_and_access_log(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "principal_id": "arn:aws:iam::123:role/AppRole",
            "current_policy": SAMPLE_AWS_POLICY,
            "access_log": SAMPLE_ACCESS_LOG,
        }, cloud="aws")

        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="sanitized")

        with patch("agents.agent_05_iam_minimizer.workflow.shield", shield_mock):
            await wf._ingest_node(state)

        # Once for policy, once for access log
        assert shield_mock.sanitize.call_count == 2

    async def test_truncates_large_policy(self, wf, workspace_id):
        big_policy = {"Statement": [{"Effect": "Allow", "Action": ["s3:GetObject"] * 2000, "Resource": "*"}]}
        state = _base_state(workspace_id, {
            "principal_id": "arn:aws:iam::123:role/BigRole",
            "current_policy": big_policy,
        }, cloud="aws")

        captured_texts = []

        def capture(text, context=None):
            captured_texts.append(text)
            return MagicMock(sanitized_text=text[:8000])

        shield_mock = MagicMock()
        shield_mock.sanitize.side_effect = capture

        with patch("agents.agent_05_iam_minimizer.workflow.shield", shield_mock):
            await wf._ingest_node(state)

        # First sanitize call is for the policy; check it was truncated
        assert len(captured_texts) >= 1
        policy_text = captured_texts[0]
        assert len(policy_text) <= 8_000 + len("\n... [truncated]") + 10
        assert "[truncated]" in policy_text

    async def test_empty_payload_sets_safe_defaults(self, wf, workspace_id):
        state = _base_state(workspace_id, {})
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="")

        with patch("agents.agent_05_iam_minimizer.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["error"] is None
        assert result["principal_id"] == ""
        assert result["tokens_used"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# IAMMinimizeWorkflow._diagnose_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestDiagnoseNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        wf._router = mock_router
        mock_router.complete.return_value = SAMPLE_LLM_IAM_DIAGNOSIS
        return wf

    async def test_calls_router_with_iam_minimization_task_type(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_IAM_DIAGNOSIS, 1800)) as mock_llm, \
             patch.object(wf, "parse_llm_json", return_value=json.loads(SAMPLE_LLM_IAM_DIAGNOSIS)), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        call_kwargs = mock_llm.call_args.kwargs
        assert call_kwargs["task_type"] == "iam_minimization"

    async def test_parses_all_llm_fields(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_IAM_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_IAM_DIAGNOSIS, 1800)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(state)

        assert result["parsed_error"] == parsed["parsed_error"]
        assert result["risk_score"] == "HIGH"
        assert result["permissions_removed"] == parsed["permissions_removed"]
        assert result["permissions_kept"] == parsed["permissions_kept"]
        assert result["minimized_policy"] == parsed["minimized_policy"]
        assert result["estimated_duration_seconds"] == 30

    async def test_serializes_minimized_policy_to_json_string(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_IAM_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_IAM_DIAGNOSIS, 1800)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(state)

        assert isinstance(result["minimized_policy_str"], str)
        assert json.loads(result["minimized_policy_str"]) == parsed["minimized_policy"]

    async def test_accumulates_tokens(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        state["tokens_used"] = 400
        parsed = json.loads(SAMPLE_LLM_IAM_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_IAM_DIAGNOSIS, 1800)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(state)

        assert result["tokens_used"] == 2200

    async def test_sets_error_on_parse_failure(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=("bad json", 100)), \
             patch.object(wf, "parse_llm_json", side_effect=ValueError("JSON parse failed")):
            result = await wf._diagnose_node(state)

        assert result.get("error") is not None

    async def test_calls_check_budget_before_llm(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_IAM_DIAGNOSIS)
        order = []

        async def mock_budget(*a, **kw): order.append("budget")
        def mock_llm(*a, **kw):
            order.append("llm")
            return (SAMPLE_LLM_IAM_DIAGNOSIS, 1800)

        with patch.object(wf, "check_budget", side_effect=mock_budget), \
             patch.object(wf, "call_llm", side_effect=mock_llm), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        assert order.index("budget") < order.index("llm")

    async def test_user_message_includes_principal_and_policy(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_IAM_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_IAM_DIAGNOSIS, 1800)) as mock_llm, \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        msgs = mock_llm.call_args.kwargs["messages"]
        content = msgs[0]["content"]
        assert "arn:aws:iam::123456789012:role/AppRole" in content
        assert "AWS" in content


# ──────────────────────────────────────────────────────────────────────────────
# IAMMinimizeWorkflow._hitl_gate_node()
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
             patch("agents.agent_05_iam_minimizer.workflow.interrupt", return_value={"id": "hold"}):
            result = await wf._hitl_gate_node(state)

        mock_hitl.create_incident.assert_called_once()
        call_kwargs = mock_hitl.create_incident.call_args.kwargs
        assert call_kwargs["agent_id"] == "agent_05_iam_minimizer"
        assert call_kwargs["workspace_id"] == workspace_id

    async def test_raw_log_includes_principal_and_risk_score(self, wf, workspace_id):
        state = _hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_05_iam_minimizer.workflow.interrupt", return_value={"id": "hold"}):
            await wf._hitl_gate_node(state)

        call_kwargs = mock_hitl.create_incident.call_args.kwargs
        raw_log = call_kwargs["raw_log"]
        assert "AppRole" in raw_log or "arn:aws:iam" in raw_log
        assert "HIGH" in raw_log

    async def test_calls_interrupt_with_risk_score(self, wf, workspace_id):
        state = _hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_05_iam_minimizer.workflow.interrupt", return_value={"id": "hold"}) as mock_interrupt:
            await wf._hitl_gate_node(state)

        interrupt_arg = mock_interrupt.call_args.args[0]
        assert interrupt_arg["risk_score"] == "HIGH"
        assert "options" in interrupt_arg

    async def test_skips_incident_creation_on_error(self, wf, workspace_id):
        state = _hitl_state(workspace_id)
        state["error"] = "LLM failed"

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock()
        wf.hitl = mock_hitl

        result = await wf._hitl_gate_node(state)

        mock_hitl.create_incident.assert_not_called()
        assert result == {}

    async def test_sets_incident_id_in_state(self, wf, workspace_id):
        state = _hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_05_iam_minimizer.workflow.interrupt", return_value={"id": "opt_1"}):
            result = await wf._hitl_gate_node(state)

        assert result["incident_id"] == incident_id


# ──────────────────────────────────────────────────────────────────────────────
# _build_pr_body()
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildPrBody:
    def test_includes_principal_id_and_cloud(self):
        body = _build_pr_body(
            principal_id="arn:aws:iam::123:role/AppRole",
            principal_name="AppRole",
            risk_score="HIGH",
            permissions_removed=["iam:createpolicy", "s3:deleteobject"],
            permissions_kept=["s3:getobject"],
            cloud="aws",
        )
        assert "arn:aws:iam::123:role/AppRole" in body
        assert "AWS" in body

    def test_includes_permissions_removed_list(self):
        body = _build_pr_body(
            principal_id="arn:...",
            principal_name="Role",
            risk_score="MEDIUM",
            permissions_removed=["iam:createpolicy", "s3:deleteobject"],
            permissions_kept=["s3:getobject"],
            cloud="aws",
        )
        assert "iam:createpolicy" in body
        assert "s3:deleteobject" in body

    def test_includes_risk_score(self):
        body = _build_pr_body(
            principal_id="...", principal_name="R",
            risk_score="CRITICAL",
            permissions_removed=[], permissions_kept=[],
            cloud="gcp",
        )
        assert "CRITICAL" in body

    def test_truncates_long_removed_list(self):
        perms = [f"service:Action{i}" for i in range(50)]
        body = _build_pr_body(
            principal_id="...", principal_name="R",
            risk_score="HIGH",
            permissions_removed=perms,
            permissions_kept=[],
            cloud="aws",
        )
        assert "20 more" in body

    def test_includes_cloud_decoded_attribution(self):
        body = _build_pr_body(
            principal_id="...", principal_name="R",
            risk_score="LOW",
            permissions_removed=[], permissions_kept=[],
            cloud="azure",
        )
        assert "Cloud Decoded" in body
