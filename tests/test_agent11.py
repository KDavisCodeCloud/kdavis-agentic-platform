"""
tests/test_agent11.py
Tests for agents/agent_11_resource_health/tools.py and workflow.py.

What this file validates:
  ResourceHealthTools:
    - create_alert_pr delegates to core.repo_tools (same 5-step flow as
      Agent 08's create_drift_pr)
    - create_alert_issue is a direct GitHub API call (no RepoTools --
      RepoTools has no create_issue method), raises EnvironmentError
      without a GitHub token
    - execute_option: hold -> held, opt_1 -> PR, opt_2 -> issue,
      unknown -> not_implemented, missing repo -> skipped

  ResourceHealthWorkflow:
    - _ingest_node parses Azure Monitor Common Alert Schema and an
      already-SNS-unwrapped CloudWatch alarm, classifies domain
      heuristically, falls back safely on an unrecognized payload
    - _diagnose_node calls the router with task_type="resource_health_triage"
      and parses parsed_error/options/estimated_duration_seconds
    - _hitl_gate_node creates an incident and pauses via interrupt()
    - _execute_node dispatches to the approved option
    - credential wiring: github_token/azure_devops_token/org reach
      ResourceHealthTools; aws_session/azure_access_token/k8s_* are
      accepted-but-unused (uniform **creds spreading from webhooks.py)
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agents.agent_11_resource_health.tools import ResourceHealthTools
from agents.agent_11_resource_health.workflow import ResourceHealthWorkflow, ResourceHealthState
from core.repo_tools import NoRepoCredentialError


def _make_workflow(mock_db, workspace_id, mock_router) -> ResourceHealthWorkflow:
    with (
        patch("agents.base_agent._load_router", return_value=mock_router),
        patch.object(ResourceHealthWorkflow, "_build_graph", return_value=MagicMock()),
    ):
        wf = ResourceHealthWorkflow(mock_db, workspace_id, MagicMock())
    return wf


def _base_state(workspace_id: str, payload: dict | None = None) -> ResourceHealthState:
    return {
        "workspace_id": workspace_id,
        "cloud_provider": "azure",
        "webhook_payload": payload or {},
        "alert_source": "azure_monitor",
        "domain": "compute",
        "resource_id": "acme-prod-vm",
        "resource_type": "Microsoft.Compute/virtualMachines",
        "severity": "Sev2",
        "alert_name": "High CPU",
        "log_excerpt": "Alert Rule: High CPU\nResource: acme-prod-vm",
        "incident_id": None,
        "parsed_error": None,
        "remediation_options": None,
        "estimated_duration_seconds": None,
        "tokens_used": 0,
        "selected_option": None,
        "execution_result": None,
        "error": None,
    }


AZURE_ALERT_PAYLOAD = {
    "data": {
        "essentials": {
            "alertRule": "High CPU",
            "severity": "Sev2",
            "targetResourceType": "Microsoft.Compute/virtualMachines",
            "alertTargetIDs": ["/subscriptions/x/resourceGroups/acme-rg/providers/Microsoft.Compute/virtualMachines/acme-prod-vm"],
            "monitorCondition": "Fired",
            "description": "CPU exceeded 90% for 5 minutes",
        }
    }
}

AWS_CLOUDWATCH_PAYLOAD = {
    "cloudwatch_alarm": {
        "AlarmName": "acme-prod-ec2-cpu-high",
        "NewStateValue": "ALARM",
        "NewStateReason": "Threshold Crossed: CPUUtilization > 90 for 5 datapoints",
        "Trigger": {
            "MetricName": "CPUUtilization",
            "Namespace": "AWS/EC2",
            "Dimensions": [{"name": "InstanceId", "value": "i-0a1b2c3d4e5f67890"}],
        },
    }
}

# Phase 2 (scale-readiness build) fixtures -- realistic Metric Alert shape
# (data.alertContext.condition.allOf), the structured fields real Azure DTU/
# CPU/etc. threshold alerts actually carry, previously never read at all.
AZURE_METRIC_ALERT_PAYLOAD = {
    "data": {
        "essentials": {
            "alertRule": "DTU high",
            "severity": "Sev2",
            "targetResourceType": "Microsoft.Sql/servers/databases",
            "alertTargetIDs": [
                "/subscriptions/x/resourceGroups/production-rg/providers/Microsoft.Sql/servers/prod-sql-01/databases/appdb"
            ],
            "monitorCondition": "Fired",
            "description": "DTU percentage exceeded threshold",
        },
        "alertContext": {
            "condition": {
                "allOf": [
                    {"metricName": "dtu_consumption_percent", "metricValue": 90.5, "threshold": 80, "operator": "GreaterThan"}
                ]
            }
        },
    }
}

# Realistic bracket-format NewStateReason, matching what CloudWatch actually
# sends for a metric-threshold alarm (the original AWS_CLOUDWATCH_PAYLOAD
# above uses a simplified reason string that doesn't match this format --
# kept as-is to also prove the parser fails safe on an unparseable reason).
AWS_CLOUDWATCH_METRIC_PAYLOAD = {
    "cloudwatch_alarm": {
        "AlarmName": "prod-rds-cpu-high",
        "AWSAccountId": "402916653765",
        "AlarmArn": "arn:aws:cloudwatch:us-east-1:402916653765:alarm:prod-rds-cpu-high",
        "NewStateValue": "ALARM",
        "NewStateReason": "Threshold Crossed: 1 datapoint [95.0 (15/09/26 01:00:00)] was greater than the threshold (80.0).",
        "Trigger": {
            "MetricName": "CPUUtilization",
            "Namespace": "AWS/RDS",
            "Dimensions": [{"name": "DBInstanceIdentifier", "value": "prod-db-01"}],
        },
    }
}


# ──────────────────────────────────────────────────────────────────────────────
# ResourceHealthWorkflow credential wiring
# ──────────────────────────────────────────────────────────────────────────────

class TestResourceHealthWorkflowCredentialWiring:
    def test_github_and_azure_devops_credentials_reach_tools(self):
        mock_db = MagicMock()
        with (
            patch("agents.base_agent._load_router", return_value=MagicMock()),
            patch.object(ResourceHealthWorkflow, "_build_graph", return_value=MagicMock()),
        ):
            wf = ResourceHealthWorkflow(
                mock_db, str(uuid4()), MagicMock(),
                github_token="gh_real", azure_devops_token="ado_pat_real", azure_devops_org="acme-org",
            )
        assert wf._tools.github_token == "gh_real"
        assert wf._tools.azure_devops_token == "ado_pat_real"
        assert wf._tools.azure_devops_org == "acme-org"

    def test_unused_creds_accepted_without_error(self):
        """aws_session/azure_access_token/k8s_* are accepted for uniform
        **creds spreading from webhooks.py but genuinely unused -- this
        agent has no live cloud-mutation path."""
        mock_db = MagicMock()
        with (
            patch("agents.base_agent._load_router", return_value=MagicMock()),
            patch.object(ResourceHealthWorkflow, "_build_graph", return_value=MagicMock()),
        ):
            ResourceHealthWorkflow(  # must not raise
                mock_db, str(uuid4()), MagicMock(),
                aws_session=MagicMock(), azure_access_token="tok",
                k8s_api_url="url", k8s_token="tok", k8s_ca_cert="cert",
            )


# ──────────────────────────────────────────────────────────────────────────────
# ResourceHealthTools
# ──────────────────────────────────────────────────────────────────────────────

class TestCreateAlertPr:
    async def test_delegates_to_repo_tools(self):
        tools = ResourceHealthTools(github_token="gh_real")
        fake_repo_tools = AsyncMock()
        fake_repo_tools.create_branch = AsyncMock()
        fake_repo_tools.push_commit = AsyncMock()
        fake_repo_tools.create_pr = AsyncMock(return_value={"pr_url": "https://github.com/acme/infra/pull/9", "pr_number": 9})

        with patch.object(tools, "_repo_tools", return_value=fake_repo_tools):
            result = await tools.create_alert_pr(
                owner="acme", repo="infra", branch_name="resource-health/acme-prod-vm",
                file_path="terraform/vm.tf", corrected_content="...", pr_body="fix",
            )

        fake_repo_tools.create_branch.assert_awaited_once()
        fake_repo_tools.push_commit.assert_awaited_once()
        fake_repo_tools.create_pr.assert_awaited_once()
        assert result["status"] == "pr_created"
        assert result["pr_number"] == 9

    async def test_raises_no_repo_credential_error_when_unconfigured(self):
        tools = ResourceHealthTools()  # no github_token, no azure_devops_token
        with pytest.raises(NoRepoCredentialError):
            await tools.create_alert_pr(
                owner="acme", repo="infra", branch_name="b", file_path="f.tf",
                corrected_content="...", pr_body="fix",
            )


class TestCreateAlertIssue:
    async def test_raises_without_github_token(self):
        tools = ResourceHealthTools(github_token=None)
        with pytest.raises(EnvironmentError):
            await tools.create_alert_issue(owner="acme", repo="infra", title="t", body="b")

    async def test_creates_issue_on_success(self):
        tools = ResourceHealthTools(github_token="gh_real")
        resp = MagicMock(status_code=201)
        resp.json.return_value = {"html_url": "https://github.com/acme/infra/issues/5", "number": 5}

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=resp)

        with patch("agents.agent_11_resource_health.tools.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = ctx
            result = await tools.create_alert_issue(owner="acme", repo="infra", title="Alert", body="body", labels=["x"])

        assert result["status"] == "issue_created"
        assert result["issue_number"] == 5

    async def test_raises_runtime_error_on_api_failure(self):
        tools = ResourceHealthTools(github_token="gh_real")
        resp = MagicMock(status_code=422, text="Validation Failed")

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=ctx)
        ctx.__aexit__ = AsyncMock(return_value=False)
        ctx.post = AsyncMock(return_value=resp)

        with patch("agents.agent_11_resource_health.tools.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = ctx
            with pytest.raises(RuntimeError):
                await tools.create_alert_issue(owner="acme", repo="infra", title="t", body="b")


class TestExecuteOption:
    async def test_hold_returns_held_without_any_call(self):
        tools = ResourceHealthTools(github_token="gh_real")
        with patch.object(tools, "create_alert_pr") as mock_pr, patch.object(tools, "create_alert_issue") as mock_issue:
            result = await tools.execute_option({"id": "hold"}, {})
        mock_pr.assert_not_called()
        mock_issue.assert_not_called()
        assert result["status"] == "held"

    async def test_opt_1_calls_create_alert_pr(self):
        tools = ResourceHealthTools(github_token="gh_real")
        with patch.object(tools, "create_alert_pr", new=AsyncMock(return_value={"status": "pr_created"})) as mock_pr:
            result = await tools.execute_option(
                {"id": "opt_1"}, {"owner": "acme", "repo": "infra", "resource_id": "vm-1"},
            )
        mock_pr.assert_awaited_once()
        assert result["status"] == "pr_created"

    async def test_opt_2_calls_create_alert_issue(self):
        tools = ResourceHealthTools(github_token="gh_real")
        with patch.object(tools, "create_alert_issue", new=AsyncMock(return_value={"status": "issue_created"})) as mock_issue:
            result = await tools.execute_option(
                {"id": "opt_2"}, {"owner": "acme", "repo": "infra", "resource_id": "vm-1"},
            )
        mock_issue.assert_awaited_once()
        assert result["status"] == "issue_created"

    async def test_missing_repo_returns_skipped(self):
        tools = ResourceHealthTools(github_token="gh_real")
        result = await tools.execute_option({"id": "opt_1"}, {"resource_id": "vm-1"})
        assert result["status"] == "skipped"

    async def test_unknown_option_returns_not_implemented(self):
        tools = ResourceHealthTools(github_token="gh_real")
        result = await tools.execute_option(
            {"id": "opt_99"}, {"owner": "acme", "repo": "infra", "resource_id": "vm-1"},
        )
        assert result["status"] == "not_implemented"


# ──────────────────────────────────────────────────────────────────────────────
# ResourceHealthWorkflow._ingest_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestIngestNode:
    async def test_parses_azure_monitor_payload(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_state(workspace_id, AZURE_ALERT_PAYLOAD)

        result = await wf._ingest_node(state)

        assert result["alert_source"] == "azure_monitor"
        assert result["domain"] == "compute"
        assert result["severity"] == "Sev2"
        assert "acme-prod-vm" in result["resource_id"]

    async def test_parses_aws_cloudwatch_payload(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_state(workspace_id, AWS_CLOUDWATCH_PAYLOAD)

        result = await wf._ingest_node(state)

        assert result["alert_source"] == "aws_cloudwatch"
        assert result["domain"] == "compute"
        assert result["resource_id"] == "i-0a1b2c3d4e5f67890"
        assert result["severity"] == "ALARM"

    async def test_unknown_format_falls_back_safely(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_state(workspace_id, {"something": "unrecognized"})

        result = await wf._ingest_node(state)

        assert result["alert_source"] == "unknown"
        assert result["error"] is None

    async def test_classifies_iam_domain_from_guardduty_namespace(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        payload = {
            "cloudwatch_alarm": {
                "AlarmName": "guardduty-finding", "NewStateValue": "ALARM", "NewStateReason": "",
                "Trigger": {"MetricName": "FindingCount", "Namespace": "AWS/GuardDuty", "Dimensions": []},
            }
        }
        state = _base_state(workspace_id, payload)
        result = await wf._ingest_node(state)
        assert result["domain"] == "iam"

    async def test_classifies_networking_domain_from_azure_resource_type(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        payload = {
            "data": {"essentials": {
                "alertRule": "NSG issue", "severity": "Sev1",
                "targetResourceType": "Microsoft.Network/networkSecurityGroups",
                "alertTargetIDs": [], "monitorCondition": "Fired",
            }}
        }
        state = _base_state(workspace_id, payload)
        result = await wf._ingest_node(state)
        assert result["domain"] == "networking"


# ──────────────────────────────────────────────────────────────────────────────
# ResourceHealthWorkflow._ingest_node() -- structured resource/metric
# extraction (Phase 2, scale-readiness build). Asserts resource_name,
# metric_name, and metric_current_value are populated correctly -- not
# just that parsed_error ends up non-empty, which a purely prose-based
# pipeline could satisfy without ever extracting anything real.
# ──────────────────────────────────────────────────────────────────────────────

class TestIngestNodeStructuredResourceExtraction:
    async def test_azure_metric_alert_extracts_resource_and_metric_fields(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_state(workspace_id, AZURE_METRIC_ALERT_PAYLOAD)

        result = await wf._ingest_node(state)

        assert result["resource_name"] == "appdb"
        assert result["resource_group"] == "production-rg"
        assert result["metric_name"] == "dtu_consumption_percent"
        assert result["metric_current_value"] == 90.5
        assert result["metric_threshold"] == 80.0

    async def test_azure_non_metric_alert_leaves_metric_fields_none(self, mock_db, workspace_id, mock_router):
        """Activity Log / Service Health alerts have no alertContext.condition
        -- must not crash, must not fabricate metric data, but resource
        name/group still come from the ARM ID regardless of alert type."""
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_state(workspace_id, AZURE_ALERT_PAYLOAD)  # no alertContext at all

        result = await wf._ingest_node(state)

        assert result["metric_name"] is None
        assert result["metric_current_value"] is None
        assert result["metric_threshold"] is None
        assert result["resource_name"] == "acme-prod-vm"
        assert result["resource_group"] == "acme-rg"

    async def test_aws_cloudwatch_extracts_metric_and_account(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_state(workspace_id, AWS_CLOUDWATCH_METRIC_PAYLOAD)

        result = await wf._ingest_node(state)

        assert result["resource_name"] == "prod-db-01"
        assert result["resource_group"] == "402916653765"
        assert result["metric_name"] == "CPUUtilization"
        assert result["metric_current_value"] == 95.0
        assert result["metric_threshold"] == 80.0

    async def test_aws_account_id_falls_back_to_arn_when_no_direct_field(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        payload = {
            "cloudwatch_alarm": {
                "AlarmName": "x", "NewStateValue": "ALARM",
                "AlarmArn": "arn:aws:cloudwatch:us-east-1:999888777666:alarm:x",
                "NewStateReason": "",
                "Trigger": {"MetricName": "M", "Namespace": "AWS/EC2", "Dimensions": [{"name": "InstanceId", "value": "i-abc"}]},
            }
        }
        state = _base_state(workspace_id, payload)
        result = await wf._ingest_node(state)
        assert result["resource_group"] == "999888777666"

    async def test_aws_unparseable_reason_leaves_metric_fields_none(self, mock_db, workspace_id, mock_router):
        """The original fixture's NewStateReason ('Threshold Crossed:
        CPUUtilization > 90 for 5 datapoints') doesn't match the bracket
        format real CloudWatch sends -- must fail safe, not crash or
        fabricate numbers."""
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_state(workspace_id, AWS_CLOUDWATCH_PAYLOAD)

        result = await wf._ingest_node(state)

        assert result["metric_current_value"] is None
        assert result["metric_threshold"] is None

    def test_parse_arm_resource_handles_malformed_id(self):
        from agents.agent_11_resource_health.workflow import _parse_arm_resource
        assert _parse_arm_resource("unknown") == ("unknown", "unknown")
        assert _parse_arm_resource("") == ("unknown", "unknown")
        assert _parse_arm_resource("not-an-arm-id") == ("not-an-arm-id", "unknown")


# ──────────────────────────────────────────────────────────────────────────────
# ResourceHealthWorkflow._diagnose_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestDiagnoseNode:
    async def test_calls_router_with_resource_health_triage_task(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_state(workspace_id)

        with patch.object(wf.budget, "assert_budget_available", return_value=None):
            await wf._diagnose_node(state)

        call_args = mock_router.complete.call_args
        task_type = call_args.kwargs.get("task_type") or call_args.args[0]
        assert task_type == "resource_health_triage"

    async def test_parses_valid_llm_response(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_state(workspace_id)

        with patch.object(wf.budget, "assert_budget_available", return_value=None):
            result = await wf._diagnose_node(state)

        assert result.get("parsed_error") is not None
        assert len(result.get("remediation_options", [])) >= 2

    async def test_handles_llm_json_parse_error(self, mock_db, workspace_id, mock_router):
        mock_router.complete.return_value = "Not valid JSON at all."
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_state(workspace_id)

        with patch.object(wf.budget, "assert_budget_available", return_value=None):
            result = await wf._diagnose_node(state)

        assert result.get("error") is not None

    async def test_includes_resource_id_and_domain_in_message(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_state(workspace_id)
        state["resource_id"] = "acme-prod-storage"
        state["domain"] = "storage"

        with patch.object(wf.budget, "assert_budget_available", return_value=None):
            await wf._diagnose_node(state)

        call_args = mock_router.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[1]
        combined = " ".join(m["content"] for m in messages)
        assert "acme-prod-storage" in combined
        assert "storage" in combined


# ──────────────────────────────────────────────────────────────────────────────
# ResourceHealthWorkflow._hitl_gate_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestHITLGateNode:
    async def test_creates_incident_and_pauses(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_state(workspace_id)
        state["parsed_error"] = "High CPU on acme-prod-vm"
        state["remediation_options"] = [{"id": "opt_1"}]

        incident_uuid = uuid4()
        mock_db.fetchrow.return_value = {"id": incident_uuid}

        with patch("agents.agent_11_resource_health.workflow.interrupt") as mock_interrupt:
            mock_interrupt.return_value = {"id": "opt_1"}
            result = await wf._hitl_gate_node(state)

        mock_db.fetchrow.assert_called_once()
        assert "INSERT INTO incidents" in mock_db.fetchrow.call_args.args[0]
        mock_interrupt.assert_called_once()
        assert result["incident_id"] == str(incident_uuid)

    async def test_skips_when_error_set(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_state(workspace_id)
        state["error"] = "LLM parse failed upstream"

        result = await wf._hitl_gate_node(state)

        assert result == {}
        mock_db.fetchrow.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# ResourceHealthWorkflow._execute_node()
# ──────────────────────────────────────────────────────────────────────────────

class TestExecuteNode:
    async def test_dispatches_to_tools_execute_option(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_state(workspace_id)
        state["incident_id"] = str(uuid4())
        state["selected_option"] = {"id": "opt_2"}
        state["webhook_payload"] = {"owner": "acme", "repo": "infra"}

        with patch.object(wf._tools, "execute_option", new=AsyncMock(return_value={"status": "issue_created"})) as mock_exec:
            result = await wf._execute_node(state)

        mock_exec.assert_awaited_once()
        option_arg = mock_exec.call_args.args[0]
        assert option_arg["id"] == "opt_2"
        assert result["execution_result"]["status"] == "issue_created"

    async def test_no_selected_option_returns_skipped(self, mock_db, workspace_id, mock_router):
        wf = _make_workflow(mock_db, workspace_id, mock_router)
        state = _base_state(workspace_id)
        state["selected_option"] = None

        result = await wf._execute_node(state)

        assert result["execution_result"]["status"] == "skipped"
