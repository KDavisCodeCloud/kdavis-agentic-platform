"""
tests/test_agent06.py
Tests for agents/agent_06_finops/tools.py and workflow.py.

What this file validates:
  FinOpsTools — read operations:
    - get_aws_cost_data() POSTs to Cost Explorer with correct payload
    - get_aws_cost_data() raises EnvironmentError when AWS credentials missing
    - get_azure_cost_data() POSTs to Azure Cost Management endpoint
    - get_azure_cost_data() raises EnvironmentError when AZURE_ACCESS_TOKEN missing
    - get_gcp_cost_data() GETs the GCP billing services endpoint
    - get_gcp_cost_data() raises EnvironmentError when GCP_ACCESS_TOKEN missing

  FinOpsTools — write operations (post-approval only):
    - stop_ec2_instances() POSTs StopInstances to EC2 API
    - stop_ec2_instances() raises EnvironmentError when AWS credentials missing
    - stop_ec2_instances() returns skipped when no instance_ids provided
    - delete_unattached_ebs_volumes() deletes each volume and returns results
    - release_elastic_ips() releases each IP and returns results
    - deallocate_azure_vms() POSTs deallocate for each VM
    - deallocate_azure_vms() raises EnvironmentError when AZURE_ACCESS_TOKEN missing
    - delete_unattached_azure_disks() DELETEs each disk
    - stop_gce_instances() POSTs stop for each GCE instance
    - create_cost_report_issue() creates GitHub issue with labels
    - create_cost_report_issue() raises EnvironmentError when GITHUB_TOKEN missing
    - post_slack_alert() POSTs to the Slack webhook URL
    - post_slack_alert() raises EnvironmentError when SLACK_WEBHOOK_URL missing

  FinOpsTools — execute_option():
    - hold → returns held without any cloud API call
    - opt_1 → dispatches to create_cost_report_issue
    - opt_2 (aws) → calls stop_ec2_instances, delete_unattached_ebs_volumes, release_elastic_ips
    - opt_2 (azure) → calls deallocate_azure_vms and delete_unattached_azure_disks
    - opt_2 (gcp) → calls stop_gce_instances
    - opt_2 with empty quick_win_resources → returns skipped
    - opt_3 → dispatches to post_slack_alert
    - unknown option → returns not_implemented

  _normalize_cost_data():
    - Parses AWS Cost Explorer ResultsByTime format correctly
    - Parses Azure Cost Management rows/columns format correctly
    - Computes correct total_spend from AWS data
    - Handles empty data without crash
    - Truncates at max_chars with [truncated] suffix
    - Accepts raw JSON string

  FinOpsWorkflow._ingest_node():
    - Extracts billing_period, account_id, repository from payload
    - Normalizes AWS cost_data into text summary and sets total_spend
    - Sanitizes cost data and resource inventory via shield
    - Empty payload sets safe defaults without crash

  FinOpsWorkflow._diagnose_node():
    - Calls router with task_type="finops_optimization"
    - Parses all LLM fields including recommendations and quick_win_resources
    - Accumulates tokens from prior state
    - Sets error on parse failure
    - Calls check_budget() before LLM call
    - Includes billing_period, cloud, total_spend in user message

  FinOpsWorkflow._hitl_gate_node():
    - Calls hitl.create_incident() with correct agent_id and workspace_id
    - raw_log includes billing period and total spend
    - interrupt() includes estimated_monthly_savings
    - Skips incident creation when state["error"] is set
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agents.agent_06_finops.tools import FinOpsTools
from agents.agent_06_finops.workflow import (
    FinOpsWorkflow,
    FinOpsState,
    _normalize_cost_data,
    _build_report_body,
)


# ──────────────────────────────────────────────────────────────────────────────
# Sample data
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_AWS_COST_EXPLORER = {
    "ResultsByTime": [
        {
            "TimePeriod": {"Start": "2026-06-01", "End": "2026-06-30"},
            "Groups": [
                {
                    "Keys": ["Amazon EC2"],
                    "Metrics": {"UnblendedCost": {"Amount": "4200.50", "Unit": "USD"}},
                },
                {
                    "Keys": ["Amazon S3"],
                    "Metrics": {"UnblendedCost": {"Amount": "320.00", "Unit": "USD"}},
                },
                {
                    "Keys": ["Amazon RDS"],
                    "Metrics": {"UnblendedCost": {"Amount": "1800.00", "Unit": "USD"}},
                },
            ],
        }
    ]
}

SAMPLE_AZURE_COST_RESPONSE = {
    "properties": {
        "columns": [
            {"name": "Cost", "type": "Number"},
            {"name": "ServiceName", "type": "String"},
        ],
        "rows": [
            [5200.0, "Virtual Machines"],
            [400.0, "Azure Storage"],
            [800.0, "Azure SQL Database"],
        ],
    }
}

SAMPLE_RESOURCE_INVENTORY = {
    "instance_ids": ["i-0abc123", "i-0def456"],
    "volume_ids": ["vol-0xyz789"],
    "allocation_ids": ["eipalloc-0abc123"],
    "vm_names": [],
    "disk_names": [],
    "instance_names": [],
}

SAMPLE_LLM_FINOPS_DIAGNOSIS = json.dumps({
    "parsed_error": "AWS spend is $6,320/mo with ~$1,240 in identifiable waste — idle EC2 instances, unattached EBS, and unused Elastic IPs account for 20% of total cost.",
    "estimated_monthly_savings": 1240.00,
    "cost_report": "## Cost Analysis\n\nTop services: EC2 ($4,200), RDS ($1,800), S3 ($320). Primary waste: 2 idle t3.large instances ($240/mo) and 1 unattached EBS volume ($12/mo).",
    "recommendations": [
        {
            "rank": 1,
            "title": "Stop 2 idle EC2 t3.large instances",
            "category": "idle_resource",
            "estimated_monthly_savings": 240.00,
            "effort": "LOW",
            "risk": "LOW",
            "description": "Instances i-0abc123 and i-0def456 have <2% CPU over 30 days.",
            "action": "stop_ec2_instances",
            "resource_ids": ["i-0abc123", "i-0def456"],
        },
        {
            "rank": 2,
            "title": "Delete unattached EBS volume vol-0xyz789",
            "category": "unattached_resource",
            "estimated_monthly_savings": 12.00,
            "effort": "LOW",
            "risk": "LOW",
            "description": "100GB gp2 volume with no attachment.",
            "action": "delete_unattached_ebs_volumes",
            "resource_ids": ["vol-0xyz789"],
        },
    ],
    "quick_win_resources": {
        "instance_ids": ["i-0abc123", "i-0def456"],
        "volume_ids": ["vol-0xyz789"],
        "allocation_ids": [],
        "vm_names": [],
        "disk_names": [],
        "instance_names": [],
    },
    "options": [
        {
            "id": "opt_1",
            "title": "Create GitHub Cost Report Issue",
            "description": "Open a GitHub issue with the full cost report.",
            "impact": "NONE",
            "docs_url": "https://docs.github.com/en/issues",
        },
        {
            "id": "opt_2",
            "title": "Apply Quick Wins",
            "description": "Stop 2 idle EC2 instances and delete 1 unattached EBS volume.",
            "impact": "MEDIUM",
            "docs_url": "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/Stop_Start.html",
        },
        {
            "id": "opt_3",
            "title": "Send Slack Alert",
            "description": "Post cost summary to Slack.",
            "impact": "NONE",
            "docs_url": "https://api.slack.com/messaging/webhooks",
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


def _make_workflow(mock_db, workspace_id, mock_router) -> FinOpsWorkflow:
    with (
        patch("agents.base_agent._load_router", return_value=mock_router),
        patch.object(FinOpsWorkflow, "_build_graph", return_value=MagicMock()),
    ):
        wf = FinOpsWorkflow(mock_db, workspace_id, MagicMock())
    return wf


def _base_state(workspace_id: str, payload: dict | None = None, cloud: str = "aws") -> FinOpsState:
    return {
        "workspace_id": workspace_id,
        "cloud_provider": cloud,
        "webhook_payload": payload or {},
        "billing_period": "",
        "account_id": "",
        "repository": "",
        "currency": "USD",
        "cost_data_summary": "",
        "resource_inventory": "",
        "total_spend": 0.0,
        "incident_id": None,
        "parsed_error": None,
        "cost_report": None,
        "recommendations": None,
        "quick_win_resources": None,
        "estimated_monthly_savings": None,
        "remediation_options": None,
        "estimated_duration_seconds": None,
        "tokens_used": 0,
        "selected_option": None,
        "execution_result": None,
        "error": None,
    }


def _diagnose_state(workspace_id: str) -> FinOpsState:
    s = _base_state(workspace_id)
    s.update({
        "billing_period": "2026-06",
        "account_id": "123456789012",
        "repository": "acme/infra",
        "currency": "USD",
        "cost_data_summary": "2026-06-01 | Amazon EC2: $4,200.50\n2026-06-01 | Amazon S3: $320.00",
        "resource_inventory": json.dumps(SAMPLE_RESOURCE_INVENTORY),
        "total_spend": 6320.50,
    })
    return s


def _hitl_state(workspace_id: str) -> FinOpsState:
    s = _diagnose_state(workspace_id)
    parsed = json.loads(SAMPLE_LLM_FINOPS_DIAGNOSIS)
    s.update({
        "parsed_error": parsed["parsed_error"],
        "cost_report": parsed["cost_report"],
        "recommendations": parsed["recommendations"],
        "quick_win_resources": parsed["quick_win_resources"],
        "estimated_monthly_savings": parsed["estimated_monthly_savings"],
        "remediation_options": parsed["options"],
        "estimated_duration_seconds": 30,
        "tokens_used": 1500,
    })
    return s


# ──────────────────────────────────────────────────────────────────────────────
# _normalize_cost_data()
# ──────────────────────────────────────────────────────────────────────────────

class TestNormalizeCostData:
    def test_parses_aws_cost_explorer_format(self):
        text, total = _normalize_cost_data(SAMPLE_AWS_COST_EXPLORER, "aws", 10_000)
        assert "Amazon EC2" in text
        assert "Amazon S3" in text
        assert "$4,200.50" in text

    def test_computes_correct_aws_total_spend(self):
        _, total = _normalize_cost_data(SAMPLE_AWS_COST_EXPLORER, "aws", 10_000)
        assert abs(total - 6320.50) < 0.01

    def test_parses_azure_cost_management_format(self):
        text, total = _normalize_cost_data(SAMPLE_AZURE_COST_RESPONSE, "azure", 10_000)
        assert "Virtual Machines" in text
        assert "$5,200.00" in text

    def test_computes_correct_azure_total_spend(self):
        _, total = _normalize_cost_data(SAMPLE_AZURE_COST_RESPONSE, "azure", 10_000)
        assert abs(total - 6400.0) < 0.01

    def test_handles_empty_data_without_crash(self):
        text, total = _normalize_cost_data({}, "aws", 10_000)
        assert total == 0.0

    def test_truncates_at_max_chars(self):
        big_data = {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": "2026-06-01", "End": "2026-06-30"},
                    "Groups": [
                        {"Keys": [f"Service{i}"], "Metrics": {"UnblendedCost": {"Amount": "100.00"}}}
                        for i in range(500)
                    ],
                }
            ]
        }
        text, _ = _normalize_cost_data(big_data, "aws", 500)
        assert len(text) <= 520
        assert "[truncated]" in text

    def test_accepts_raw_json_string(self):
        raw_str = json.dumps(SAMPLE_AWS_COST_EXPLORER)
        text, total = _normalize_cost_data(raw_str, "aws", 10_000)
        assert "Amazon EC2" in text

    def test_handles_invalid_json_string(self):
        text, total = _normalize_cost_data("not valid json", "aws", 10_000)
        assert "not valid json" in text
        assert total == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# FinOpsTools — read operations
# ──────────────────────────────────────────────────────────────────────────────

class TestGetAWSCostData:
    @pytest.fixture
    def tools(self):
        return FinOpsTools(aws_access_key_id="AKID", aws_secret_access_key="secret")

    async def test_raises_without_aws_credentials(self):
        no_creds = FinOpsTools(aws_access_key_id="")
        with pytest.raises(EnvironmentError, match="AWS_ACCESS_KEY_ID"):
            await no_creds.get_aws_cost_data("2026-06-01", "2026-06-30")

    async def test_posts_to_cost_explorer_endpoint(self, tools):
        resp = _make_http_resp(200, SAMPLE_AWS_COST_EXPLORER)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=resp)

        with patch("agents.agent_06_finops.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.get_aws_cost_data("2026-06-01", "2026-06-30")

        assert "ResultsByTime" in result
        call_url = ctx.post.call_args.args[0]
        assert "GetCostAndUsage" in call_url

    async def test_raises_on_api_error(self, tools):
        err_resp = _make_http_resp(403, {"message": "AccessDenied"})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=err_resp)

        with patch("agents.agent_06_finops.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            with pytest.raises(RuntimeError, match="AWS Cost Explorer error"):
                await tools.get_aws_cost_data("2026-06-01", "2026-06-30")


class TestGetAzureCostData:
    @pytest.fixture
    def tools(self):
        return FinOpsTools(azure_access_token="eyJ0...")

    async def test_raises_without_azure_token(self):
        no_token = FinOpsTools(azure_access_token="")
        with pytest.raises(EnvironmentError, match="AZURE_ACCESS_TOKEN"):
            await no_token.get_azure_cost_data("sub-123", "2026-06-01", "2026-06-30")

    async def test_posts_to_cost_management_endpoint(self, tools):
        resp = _make_http_resp(200, SAMPLE_AZURE_COST_RESPONSE)
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=resp)

        with patch("agents.agent_06_finops.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.get_azure_cost_data("sub-123", "2026-06-01", "2026-06-30")

        assert "properties" in result
        call_url = ctx.post.call_args.args[0]
        assert "sub-123" in call_url
        assert "CostManagement" in call_url


class TestGetGCPCostData:
    @pytest.fixture
    def tools(self):
        return FinOpsTools(gcp_access_token="ya29.token")

    async def test_raises_without_gcp_token(self):
        no_token = FinOpsTools(gcp_access_token="")
        with pytest.raises(EnvironmentError, match="GCP_ACCESS_TOKEN"):
            await no_token.get_gcp_cost_data("billing-123", "2026-06-01", "2026-06-30")

    async def test_gets_billing_services_endpoint(self, tools):
        resp = _make_http_resp(200, {"services": [{"name": "compute", "displayName": "Compute Engine"}]})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.get = AsyncMock(return_value=resp)

        with patch("agents.agent_06_finops.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.get_gcp_cost_data("billing-123", "2026-06-01", "2026-06-30")

        call_url = ctx.get.call_args.args[0]
        assert "billing-123" in call_url
        assert "services" in call_url


# ──────────────────────────────────────────────────────────────────────────────
# FinOpsTools — write operations
# ──────────────────────────────────────────────────────────────────────────────

class TestStopEC2Instances:
    @pytest.fixture
    def tools(self):
        return FinOpsTools(aws_access_key_id="AKID", aws_secret_access_key="secret")

    async def test_raises_without_credentials(self):
        no_creds = FinOpsTools(aws_access_key_id="")
        with pytest.raises(EnvironmentError, match="AWS_ACCESS_KEY_ID"):
            await no_creds.stop_ec2_instances(["i-0abc123"])

    async def test_returns_skipped_when_no_instance_ids(self, tools):
        result = await tools.stop_ec2_instances([])
        assert result["status"] == "skipped"

    async def test_posts_stop_instances_action(self, tools):
        ok_resp = MagicMock(status_code=200, text="<StopInstancesResponse>...</StopInstancesResponse>")
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=ok_resp)

        with patch("agents.agent_06_finops.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.stop_ec2_instances(["i-0abc123", "i-0def456"])

        assert result["status"] == "instances_stopped"
        assert result["instance_ids"] == ["i-0abc123", "i-0def456"]
        assert result["cloud"] == "aws"
        payload = ctx.post.call_args.kwargs.get("data", {})
        assert payload.get("Action") == "StopInstances"

    async def test_raises_on_api_error(self, tools):
        err_resp = MagicMock(status_code=403, text="AccessDenied")
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=err_resp)

        with patch("agents.agent_06_finops.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            with pytest.raises(RuntimeError, match="StopInstances error"):
                await tools.stop_ec2_instances(["i-0abc123"])


class TestDeleteUnattachedEBSVolumes:
    @pytest.fixture
    def tools(self):
        return FinOpsTools(aws_access_key_id="AKID", aws_secret_access_key="secret")

    async def test_returns_skipped_when_no_volume_ids(self, tools):
        result = await tools.delete_unattached_ebs_volumes([])
        assert result["status"] == "skipped"

    async def test_deletes_each_volume_individually(self, tools):
        ok_resp = MagicMock(status_code=200, text="<DeleteVolumeResponse/>")
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=ok_resp)

        with patch("agents.agent_06_finops.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.delete_unattached_ebs_volumes(["vol-0abc", "vol-0def"])

        assert result["status"] == "volumes_deleted"
        assert "vol-0abc" in result["deleted"]
        assert "vol-0def" in result["deleted"]
        assert ctx.post.call_count == 2


class TestReleaseElasticIPs:
    @pytest.fixture
    def tools(self):
        return FinOpsTools(aws_access_key_id="AKID", aws_secret_access_key="secret")

    async def test_returns_skipped_when_no_allocation_ids(self, tools):
        result = await tools.release_elastic_ips([])
        assert result["status"] == "skipped"

    async def test_releases_each_ip(self, tools):
        ok_resp = MagicMock(status_code=200, text="<ReleaseAddressResponse/>")
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=ok_resp)

        with patch("agents.agent_06_finops.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.release_elastic_ips(["eipalloc-0abc", "eipalloc-0def"])

        assert result["status"] == "ips_released"
        assert len(result["released"]) == 2


class TestDeallocateAzureVMs:
    @pytest.fixture
    def tools(self):
        return FinOpsTools(azure_access_token="eyJ0...")

    async def test_raises_without_azure_token(self):
        no_token = FinOpsTools(azure_access_token="")
        with pytest.raises(EnvironmentError, match="AZURE_ACCESS_TOKEN"):
            await no_token.deallocate_azure_vms(["vm-prod-01"], "rg-prod", "sub-123")

    async def test_returns_skipped_when_no_vm_names(self, tools):
        result = await tools.deallocate_azure_vms([], "rg-prod", "sub-123")
        assert result["status"] == "skipped"

    async def test_posts_deallocate_for_each_vm(self, tools):
        ok_resp = _make_http_resp(202, {})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=ok_resp)

        with patch("agents.agent_06_finops.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.deallocate_azure_vms(["vm-01", "vm-02"], "rg-prod", "sub-123")

        assert result["status"] == "vms_deallocated"
        assert "vm-01" in result["deallocated"]
        assert ctx.post.call_count == 2
        call_url = ctx.post.call_args_list[0].args[0]
        assert "deallocate" in call_url


class TestDeleteUnattachedAzureDisks:
    @pytest.fixture
    def tools(self):
        return FinOpsTools(azure_access_token="eyJ0...")

    async def test_returns_skipped_when_no_disk_names(self, tools):
        result = await tools.delete_unattached_azure_disks([], "rg-prod", "sub-123")
        assert result["status"] == "skipped"

    async def test_deletes_each_disk(self, tools):
        ok_resp = _make_http_resp(202, {})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.delete = AsyncMock(return_value=ok_resp)

        with patch("agents.agent_06_finops.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.delete_unattached_azure_disks(["disk-01"], "rg-prod", "sub-123")

        assert result["status"] == "disks_deleted"
        assert "disk-01" in result["deleted"]


class TestStopGCEInstances:
    @pytest.fixture
    def tools(self):
        return FinOpsTools(gcp_access_token="ya29.token")

    async def test_raises_without_gcp_token(self):
        no_token = FinOpsTools(gcp_access_token="")
        with pytest.raises(EnvironmentError, match="GCP_ACCESS_TOKEN"):
            await no_token.stop_gce_instances(["my-instance"], "us-central1-a", "my-project")

    async def test_returns_skipped_when_no_instance_names(self, tools):
        result = await tools.stop_gce_instances([], "us-central1-a", "my-project")
        assert result["status"] == "skipped"

    async def test_posts_stop_for_each_instance(self, tools):
        ok_resp = _make_http_resp(200, {"status": "RUNNING"})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=ok_resp)

        with patch("agents.agent_06_finops.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.stop_gce_instances(["inst-a", "inst-b"], "us-central1-a", "my-project")

        assert result["status"] == "instances_stopped"
        assert "inst-a" in result["stopped"]
        assert ctx.post.call_count == 2


class TestCreateCostReportIssue:
    @pytest.fixture
    def tools(self):
        return FinOpsTools(github_token="gh_test_token")

    async def test_raises_without_github_token(self):
        no_token = FinOpsTools(github_token="")
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            await no_token.create_cost_report_issue("acme", "infra", "title", "body")

    async def test_creates_issue_with_finops_labels(self, tools):
        issue_resp = _make_http_resp(201, {"number": 42, "html_url": "https://github.com/acme/infra/issues/42"})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=issue_resp)

        with patch("agents.agent_06_finops.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.create_cost_report_issue(
                owner="acme", repo="infra",
                title="FinOps: June 2026 Cost Report",
                body="## Analysis\n...",
                labels=["finops", "cost-optimization"],
            )

        assert result["status"] == "issue_created"
        assert result["issue_number"] == 42
        payload = ctx.post.call_args.kwargs["json"]
        assert "finops" in payload.get("labels", [])
        assert "cost-optimization" in payload.get("labels", [])


class TestPostSlackAlert:
    @pytest.fixture
    def tools(self):
        return FinOpsTools(slack_webhook_url="https://hooks.slack.com/services/T000/B000/abc123")

    async def test_raises_without_slack_webhook_url(self):
        no_url = FinOpsTools(slack_webhook_url="")
        with pytest.raises(EnvironmentError, match="SLACK_WEBHOOK_URL"):
            await no_url.post_slack_alert("test message")

    async def test_posts_to_slack_webhook(self, tools):
        ok_resp = MagicMock(status_code=200, text="ok")
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=ok_resp)

        with patch("agents.agent_06_finops.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            result = await tools.post_slack_alert("FinOps: $1,240/mo savings identified")

        assert result["status"] == "slack_sent"
        call_url = ctx.post.call_args.args[0]
        assert "hooks.slack.com" in call_url

    async def test_raises_on_slack_api_error(self, tools):
        err_resp = MagicMock(status_code=400, text="invalid_payload")
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=err_resp)

        with patch("agents.agent_06_finops.tools.httpx.AsyncClient", MagicMock(return_value=ctx)):
            with pytest.raises(RuntimeError, match="Slack webhook error"):
                await tools.post_slack_alert("test")


# ──────────────────────────────────────────────────────────────────────────────
# FinOpsTools — execute_option()
# ──────────────────────────────────────────────────────────────────────────────

class TestExecuteOption:
    @pytest.fixture
    def tools(self):
        return FinOpsTools(
            aws_access_key_id="AKID", aws_secret_access_key="secret",
            azure_access_token="eyJ0...", gcp_access_token="ya29...",
            github_token="gh_test", slack_webhook_url="https://hooks.slack.com/x",
        )

    @pytest.fixture
    def aws_context(self):
        return {
            "cloud_provider": "aws",
            "owner": "acme", "repo": "infra",
            "report_title": "FinOps June 2026",
            "report_body": "## Cost Report",
            "slack_message": "FinOps alert",
            "quick_win_resources": {
                "instance_ids": ["i-0abc123"],
                "volume_ids": ["vol-0xyz"],
                "allocation_ids": [],
            },
        }

    async def test_hold_returns_held_without_cloud_call(self, tools, aws_context):
        with patch.object(tools, "create_cost_report_issue") as mock_issue:
            result = await tools.execute_option({"id": "hold"}, aws_context)
        assert result["status"] == "held"
        mock_issue.assert_not_called()

    async def test_opt1_dispatches_to_create_cost_report_issue(self, tools, aws_context):
        expected = {"status": "issue_created", "issue_url": "...", "issue_number": 42}
        with patch.object(tools, "create_cost_report_issue", new=AsyncMock(return_value=expected)):
            result = await tools.execute_option({"id": "opt_1"}, aws_context)
        assert result["status"] == "issue_created"

    async def test_opt2_aws_calls_stop_ec2_and_delete_ebs(self, tools, aws_context):
        ec2_result  = {"status": "instances_stopped", "instance_ids": ["i-0abc123"], "cloud": "aws"}
        ebs_result  = {"status": "volumes_deleted", "deleted": ["vol-0xyz"], "errors": [], "cloud": "aws"}
        with patch.object(tools, "stop_ec2_instances", new=AsyncMock(return_value=ec2_result)) as mock_ec2, \
             patch.object(tools, "delete_unattached_ebs_volumes", new=AsyncMock(return_value=ebs_result)) as mock_ebs, \
             patch.object(tools, "release_elastic_ips", new=AsyncMock(return_value={"status": "skipped"})):
            result = await tools.execute_option({"id": "opt_2"}, aws_context)

        assert result["status"] == "quick_wins_applied"
        assert result["cloud"] == "aws"
        mock_ec2.assert_called_once_with(["i-0abc123"])
        mock_ebs.assert_called_once_with(["vol-0xyz"])

    async def test_opt2_azure_calls_deallocate_vms_and_delete_disks(self, tools):
        azure_ctx = {
            "cloud_provider": "azure",
            "subscription_id": "sub-123",
            "resource_group": "rg-prod",
            "quick_win_resources": {
                "vm_names": ["vm-prod-01"],
                "disk_names": ["orphan-disk-01"],
                "resource_group": "rg-prod",
                "subscription_id": "sub-123",
            },
        }
        vm_result   = {"status": "vms_deallocated", "deallocated": ["vm-prod-01"], "errors": [], "cloud": "azure"}
        disk_result = {"status": "disks_deleted", "deleted": ["orphan-disk-01"], "errors": [], "cloud": "azure"}
        with patch.object(tools, "deallocate_azure_vms", new=AsyncMock(return_value=vm_result)) as mock_vm, \
             patch.object(tools, "delete_unattached_azure_disks", new=AsyncMock(return_value=disk_result)):
            result = await tools.execute_option({"id": "opt_2"}, azure_ctx)

        assert result["status"] == "quick_wins_applied"
        mock_vm.assert_called_once()

    async def test_opt2_gcp_calls_stop_gce_instances(self, tools):
        gcp_ctx = {
            "cloud_provider": "gcp",
            "project": "my-project",
            "quick_win_resources": {
                "instance_names": ["idle-vm-01"],
                "zone": "us-central1-a",
                "project": "my-project",
            },
        }
        gce_result = {"status": "instances_stopped", "stopped": ["idle-vm-01"], "errors": [], "cloud": "gcp"}
        with patch.object(tools, "stop_gce_instances", new=AsyncMock(return_value=gce_result)) as mock_gce:
            result = await tools.execute_option({"id": "opt_2"}, gcp_ctx)

        assert result["status"] == "quick_wins_applied"
        mock_gce.assert_called_once()

    async def test_opt2_empty_quick_win_resources_returns_skipped(self, tools, aws_context):
        aws_context["quick_win_resources"] = {"instance_ids": [], "volume_ids": [], "allocation_ids": []}
        result = await tools.execute_option({"id": "opt_2"}, aws_context)
        assert result["status"] == "skipped"

    async def test_opt3_dispatches_to_post_slack_alert(self, tools, aws_context):
        with patch.object(tools, "post_slack_alert", new=AsyncMock(return_value={"status": "slack_sent"})) as mock_slack:
            result = await tools.execute_option({"id": "opt_3"}, aws_context)
        assert result["status"] == "slack_sent"
        mock_slack.assert_called_once_with(aws_context["slack_message"])

    async def test_unknown_option_returns_not_implemented(self, tools, aws_context):
        result = await tools.execute_option({"id": "opt_99"}, aws_context)
        assert result["status"] == "not_implemented"
        assert result["option_id"] == "opt_99"


# ──────────────────────────────────────────────────────────────────────────────
# FinOpsWorkflow._ingest_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestIngestNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        return _make_workflow(mock_db, workspace_id, mock_router)

    async def test_extracts_billing_period_and_account_id(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "billing_period": "2026-06",
            "account_id": "123456789012",
            "cost_data": SAMPLE_AWS_COST_EXPLORER,
        }, cloud="aws")
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="cost data")

        with patch("agents.agent_06_finops.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["billing_period"] == "2026-06"
        assert result["account_id"] == "123456789012"

    async def test_normalizes_aws_cost_data_and_computes_total_spend(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "billing_period": "2026-06",
            "account_id": "123456789012",
            "cost_data": SAMPLE_AWS_COST_EXPLORER,
        }, cloud="aws")
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="normalized cost data")

        with patch("agents.agent_06_finops.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert abs(result["total_spend"] - 6320.50) < 0.01

    async def test_sanitizes_cost_data_and_inventory(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "billing_period": "2026-06",
            "account_id": "123456789012",
            "cost_data": SAMPLE_AWS_COST_EXPLORER,
            "resource_inventory": SAMPLE_RESOURCE_INVENTORY,
        }, cloud="aws")
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="sanitized")

        with patch("agents.agent_06_finops.workflow.shield", shield_mock):
            await wf._ingest_node(state)

        assert shield_mock.sanitize.call_count == 2

    async def test_empty_payload_sets_safe_defaults(self, wf, workspace_id):
        state = _base_state(workspace_id, {})
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="")

        with patch("agents.agent_06_finops.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["error"] is None
        assert result["billing_period"] == ""
        assert result["total_spend"] == 0.0

    async def test_uses_subscription_id_as_account_id_for_azure(self, wf, workspace_id):
        state = _base_state(workspace_id, {
            "subscription_id": "sub-abc-123",
            "billing_period": "2026-06",
            "cost_data": {},
        }, cloud="azure")
        shield_mock = MagicMock()
        shield_mock.sanitize.return_value = MagicMock(sanitized_text="")

        with patch("agents.agent_06_finops.workflow.shield", shield_mock):
            result = await wf._ingest_node(state)

        assert result["account_id"] == "sub-abc-123"


# ──────────────────────────────────────────────────────────────────────────────
# FinOpsWorkflow._diagnose_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestDiagnoseNode:
    @pytest.fixture
    def wf(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        wf._router = mock_router
        mock_router.complete.return_value = SAMPLE_LLM_FINOPS_DIAGNOSIS
        return wf

    async def test_calls_router_with_finops_optimization_task_type(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_FINOPS_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_FINOPS_DIAGNOSIS, 1500)) as mock_llm, \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        assert mock_llm.call_args.kwargs["task_type"] == "finops_optimization"

    async def test_parses_all_llm_fields(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_FINOPS_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_FINOPS_DIAGNOSIS, 1500)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(state)

        assert result["parsed_error"] == parsed["parsed_error"]
        assert result["cost_report"] == parsed["cost_report"]
        assert len(result["recommendations"]) == 2
        assert abs(result["estimated_monthly_savings"] - 1240.0) < 0.01
        assert result["quick_win_resources"]["instance_ids"] == ["i-0abc123", "i-0def456"]

    async def test_accumulates_tokens_from_prior_state(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        state["tokens_used"] = 300
        parsed = json.loads(SAMPLE_LLM_FINOPS_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_FINOPS_DIAGNOSIS, 1500)), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            result = await wf._diagnose_node(state)

        assert result["tokens_used"] == 1800

    async def test_sets_error_on_parse_failure(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=("bad json", 100)), \
             patch.object(wf, "parse_llm_json", side_effect=ValueError("JSON parse failed")):
            result = await wf._diagnose_node(state)

        assert result.get("error") is not None

    async def test_calls_check_budget_before_llm(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_FINOPS_DIAGNOSIS)
        order = []

        async def mock_budget(*a, **kw): order.append("budget")
        def mock_llm(*a, **kw):
            order.append("llm")
            return (SAMPLE_LLM_FINOPS_DIAGNOSIS, 1500)

        with patch.object(wf, "check_budget", side_effect=mock_budget), \
             patch.object(wf, "call_llm", side_effect=mock_llm), \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        assert order.index("budget") < order.index("llm")

    async def test_user_message_includes_period_cloud_and_total_spend(self, wf, workspace_id):
        state = _diagnose_state(workspace_id)
        parsed = json.loads(SAMPLE_LLM_FINOPS_DIAGNOSIS)

        with patch.object(wf, "check_budget", new=AsyncMock()), \
             patch.object(wf, "call_llm", return_value=(SAMPLE_LLM_FINOPS_DIAGNOSIS, 1500)) as mock_llm, \
             patch.object(wf, "parse_llm_json", return_value=parsed), \
             patch.object(wf, "record_token_usage", new=AsyncMock()):
            await wf._diagnose_node(state)

        content = mock_llm.call_args.kwargs["messages"][0]["content"]
        assert "2026-06" in content
        assert "AWS" in content
        assert "6,320" in content


# ──────────────────────────────────────────────────────────────────────────────
# FinOpsWorkflow._hitl_gate_node()
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
             patch("agents.agent_06_finops.workflow.interrupt", return_value={"id": "hold"}):
            result = await wf._hitl_gate_node(state)

        call_kwargs = mock_hitl.create_incident.call_args.kwargs
        assert call_kwargs["agent_id"] == "agent_06_finops"
        assert call_kwargs["workspace_id"] == workspace_id

    async def test_raw_log_includes_billing_period_and_total_spend(self, wf, workspace_id):
        state = _hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_06_finops.workflow.interrupt", return_value={"id": "hold"}):
            await wf._hitl_gate_node(state)

        raw_log = mock_hitl.create_incident.call_args.kwargs["raw_log"]
        assert "2026-06" in raw_log
        assert "6,320" in raw_log

    async def test_interrupt_includes_estimated_monthly_savings(self, wf, workspace_id):
        state = _hitl_state(workspace_id)
        incident_id = str(uuid4())

        mock_hitl = AsyncMock()
        mock_hitl.create_incident = AsyncMock(return_value=incident_id)
        wf.hitl = mock_hitl

        with patch.object(wf, "record_token_usage", new=AsyncMock()), \
             patch("agents.agent_06_finops.workflow.interrupt", return_value={"id": "opt_1"}) as mock_interrupt:
            await wf._hitl_gate_node(state)

        interrupt_arg = mock_interrupt.call_args.args[0]
        assert interrupt_arg["estimated_monthly_savings"] == 1240.0

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
             patch("agents.agent_06_finops.workflow.interrupt", return_value={"id": "opt_1"}):
            result = await wf._hitl_gate_node(state)

        assert result["incident_id"] == incident_id


# ──────────────────────────────────────────────────────────────────────────────
# _build_report_body()
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildReportBody:
    def test_includes_billing_period_and_account(self):
        body = _build_report_body(
            billing_period="2026-06",
            account_id="123456789012",
            cloud="aws",
            total_spend=6320.50,
            currency="USD",
            estimated_monthly_savings=1240.00,
            recommendations=[],
            cost_report="",
        )
        assert "2026-06" in body
        assert "123456789012" in body
        assert "AWS" in body

    def test_includes_total_spend_and_savings(self):
        body = _build_report_body(
            billing_period="2026-06",
            account_id="123456789012",
            cloud="aws",
            total_spend=6320.50,
            currency="USD",
            estimated_monthly_savings=1240.00,
            recommendations=[],
            cost_report="",
        )
        assert "$6,320.50" in body
        assert "$1,240.00" in body

    def test_computes_annualized_savings(self):
        body = _build_report_body(
            billing_period="2026-06",
            account_id="123456789012",
            cloud="aws",
            total_spend=6320.50,
            currency="USD",
            estimated_monthly_savings=1000.00,
            recommendations=[],
            cost_report="",
        )
        assert "$12,000.00" in body  # 1000 * 12

    def test_lists_top_10_recommendations(self):
        recs = [
            {"title": f"Rec {i}", "estimated_monthly_savings": 100.0, "description": "desc"}
            for i in range(15)
        ]
        body = _build_report_body(
            billing_period="2026-06", account_id="123456789012",
            cloud="aws", total_spend=6000.0, currency="USD",
            estimated_monthly_savings=1000.0,
            recommendations=recs, cost_report="",
        )
        assert "5 more recommendations" in body

    def test_includes_cloud_decoded_attribution(self):
        body = _build_report_body(
            billing_period="2026-06", account_id="123",
            cloud="azure", total_spend=5000.0, currency="USD",
            estimated_monthly_savings=500.0,
            recommendations=[], cost_report="",
        )
        assert "Cloud Decoded" in body
