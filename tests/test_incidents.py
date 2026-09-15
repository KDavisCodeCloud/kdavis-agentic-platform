"""
tests/test_incidents.py
Tests for api/routes/incidents.py's approve_incident dispatch logic.

Real bug this file guards against: approve_incident used to hardcode
agents.agent_01_cicd_triage.workflow.CICDTriageWorkflow regardless of which
agent actually created the incident (row["agent_id"] was selected but never
used). Approving an Agent 05/06/08 incident silently resumed Agent 01's
LangGraph instead. _WORKFLOW_CLASSES + the agent_id lookup in approve_incident
is the fix; these tests pin the dispatch is correct per agent and fails loud
(500, not a silent fallback) for an unregistered agent_id.

Runs with pytest-asyncio (asyncio_mode = auto) + unittest.mock — no live DB.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.routes import incidents
from db.models import IncidentApproveRequest, IncidentResolveManuallyRequest


def _make_request(fetchrow_return: dict, execute_return=None, credentials_row=None, k8s_credentials_row=None) -> SimpleNamespace:
    """credentials_row backs the SECOND conn.fetchrow call -- made by
    core.workspace_credentials.build_agent_credentials() inside _resume()
    for the credentialed agents (01/02/04/05/06/08/10, _CREDENTIALED_AGENTS).
    k8s_credentials_row backs a THIRD conn.fetchrow call -- build_k8s_credentials(),
    made only for agent_02_k8s_alert/agent_08_drift_detection. Both None
    (the default) means "no credentials configured", which
    build_agent_credentials/build_k8s_credentials handle by returning
    all-None credentials -- fine for dispatch tests that only care which
    workflow class got instantiated. Harmless to always provide a third
    value even for agent types that never make a third fetchrow call."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[fetchrow_return, credentials_row, k8s_credentials_row])
    conn.execute = AsyncMock(return_value=execute_return)
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    app = SimpleNamespace(state=SimpleNamespace(db_pool=pool, checkpointer=MagicMock()))
    return SimpleNamespace(app=app), conn


def _incident_row(agent_id: str, workspace_id, cloud_provider: str = "aws") -> dict:
    return {
        "id": uuid4(),
        "workspace_id": workspace_id,
        "agent_id": agent_id,
        "execution_status": "pending_approval",
        "remediation_options": [{"id": "opt_1", "title": "Fix it", "description": "d"}],
        "estimated_duration_seconds": 30,
        "cloud_provider": cloud_provider,
    }


async def _approve(request, incident_id: str, workspace_id):
    return await incidents.approve_incident(
        incident_id,
        IncidentApproveRequest(selected_option_id="opt_1"),
        request,
        workspace={"id": workspace_id},
    )


async def _drain_background_tasks():
    """approve_incident's real-fix path is fire-and-forget (asyncio.create_task) --
    let it actually run to completion before asserting on the mocked workflow."""
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


class TestApproveDispatchesToCorrectWorkflow:
    # _WORKFLOW_CLASSES captures each class object into a dict at module-load
    # time, so patch.object(incidents, "SomeWorkflow") replaces the module
    # attribute but NOT the dict's already-stored reference. Tests must patch
    # the dict entries themselves (patch.dict) to actually intercept dispatch.

    async def test_agent01_incident_resumes_cicd_triage_workflow(self):
        workspace_id = uuid4()
        row = _incident_row("agent_01_cicd_triage", workspace_id)
        request, conn = _make_request(row)

        MockWorkflow = MagicMock()
        MockWorkflow.return_value.resume = AsyncMock(return_value=None)

        with patch.dict(incidents._WORKFLOW_CLASSES, {"agent_01_cicd_triage": MockWorkflow}):
            await _approve(request, str(row["id"]), workspace_id)
            await _drain_background_tasks()

        MockWorkflow.assert_called_once()
        MockWorkflow.return_value.resume.assert_awaited_once()

    async def test_agent05_incident_resumes_iam_minimize_workflow_not_agent01(self):
        # This is the regression test for the real bug: before the fix, this
        # would have resumed CICDTriageWorkflow instead.
        workspace_id = uuid4()
        row = _incident_row("agent_05_iam_minimizer", workspace_id)
        request, conn = _make_request(row)

        MockIAM = MagicMock()
        MockIAM.return_value.resume = AsyncMock(return_value=None)
        MockCICD = MagicMock()
        MockCICD.return_value.resume = AsyncMock(return_value=None)

        with patch.dict(
            incidents._WORKFLOW_CLASSES,
            {"agent_05_iam_minimizer": MockIAM, "agent_01_cicd_triage": MockCICD},
        ):
            await _approve(request, str(row["id"]), workspace_id)
            await _drain_background_tasks()

        MockIAM.assert_called_once()
        MockIAM.return_value.resume.assert_awaited_once()
        MockCICD.assert_not_called()

    async def test_agent06_and_agent08_incidents_resume_their_own_workflows(self):
        for agent_id in ("agent_06_finops", "agent_08_drift_detection"):
            workspace_id = uuid4()
            row = _incident_row(agent_id, workspace_id)
            request, conn = _make_request(row)

            MockWorkflow = MagicMock()
            MockWorkflow.return_value.resume = AsyncMock(return_value=None)

            with patch.dict(incidents._WORKFLOW_CLASSES, {agent_id: MockWorkflow}):
                await _approve(request, str(row["id"]), workspace_id)
                await _drain_background_tasks()

            MockWorkflow.assert_called_once()
            MockWorkflow.return_value.resume.assert_awaited_once()

    async def test_agent08_resume_resolves_k8s_context_from_stored_cloud_provider(self):
        # Real bug found live: resume() is a completely separate instantiation
        # from run() (webhooks.py's _run_drift_detection) and had no idea which
        # cluster an incident was about -- kubectl always fell back to
        # KUBECONFIG's default context. An AKS incident's real "Apply
        # Correction Directly" approval silently no-op'd against EKS instead.
        # cloud_provider is already persisted on the incident row; resume must
        # resolve k8s_context from it the same way run() does.
        workspace_id = uuid4()
        row = _incident_row("agent_08_drift_detection", workspace_id, cloud_provider="azure")
        request, conn = _make_request(row)

        MockWorkflow = MagicMock()
        MockWorkflow.return_value.resume = AsyncMock(return_value=None)

        with (
            patch.dict(incidents._WORKFLOW_CLASSES, {"agent_08_drift_detection": MockWorkflow}),
            patch("api.routes.incidents.resolve_k8s_context", return_value="aks-demo") as mock_resolve,
        ):
            await _approve(request, str(row["id"]), workspace_id)
            await _drain_background_tasks()

        mock_resolve.assert_called_once_with("azure")
        _, kwargs = MockWorkflow.call_args
        assert kwargs["k8s_context"] == "aks-demo"

    async def test_agent02_and_08_resume_pass_real_per_workspace_k8s_credentials(self):
        # Phase 4: agent_02_k8s_alert and agent_08_drift_detection both now
        # fetch a workspace's real cluster credentials (migration 025) on
        # resume, not just k8s_context's global-KUBECONFIG_YAML fallback.
        for agent_id in ("agent_02_k8s_alert", "agent_08_drift_detection"):
            workspace_id = uuid4()
            row = _incident_row(agent_id, workspace_id)
            k8s_row = {
                "k8s_api_url": "https://prod-cluster.example.com",
                "k8s_token_encrypted": "cipher",
                "k8s_ca_cert_encrypted": None,
            }
            request, conn = _make_request(row, k8s_credentials_row=k8s_row)

            MockWorkflow = MagicMock()
            MockWorkflow.return_value.resume = AsyncMock(return_value=None)

            with (
                patch.dict(incidents._WORKFLOW_CLASSES, {agent_id: MockWorkflow}),
                patch("core.workspace_credentials.decrypt", return_value="real_k8s_token"),
            ):
                await _approve(request, str(row["id"]), workspace_id)
                await _drain_background_tasks()

            _, kwargs = MockWorkflow.call_args
            assert kwargs["k8s_api_url"] == "https://prod-cluster.example.com"
            assert kwargs["k8s_token"] == "real_k8s_token"

    async def test_non_drift_credentialed_agent_resume_does_not_pass_k8s_context(self):
        workspace_id = uuid4()
        row = _incident_row("agent_06_finops", workspace_id, cloud_provider="azure")
        request, conn = _make_request(row)

        MockWorkflow = MagicMock()
        MockWorkflow.return_value.resume = AsyncMock(return_value=None)

        with patch.dict(incidents._WORKFLOW_CLASSES, {"agent_06_finops": MockWorkflow}):
            await _approve(request, str(row["id"]), workspace_id)
            await _drain_background_tasks()

        _, kwargs = MockWorkflow.call_args
        assert "k8s_context" not in kwargs

    async def test_agent11_is_registered_in_workflow_classes(self):
        # Regression guard for a real bug found live during the Azure Action
        # Group end-to-end verification, 2026-09-15: agent_11_resource_health
        # was missing from _WORKFLOW_CLASSES entirely (not just
        # _CREDENTIALED_AGENTS), so approving ANY real Agent 11 incident with
        # anything other than 'hold' raised a 500 "No workflow class
        # registered" -- every customer, since Agent 11 shipped. This
        # assertion exists so that gap can never silently reappear.
        assert "agent_11_resource_health" in incidents._WORKFLOW_CLASSES
        assert incidents._WORKFLOW_CLASSES["agent_11_resource_health"].__name__ == "ResourceHealthWorkflow"
        assert "agent_11_resource_health" in incidents._CREDENTIALED_AGENTS

    async def test_agent11_incident_resumes_resource_health_workflow_with_github_token(self):
        workspace_id = uuid4()
        row = _incident_row("agent_11_resource_health", workspace_id)
        credentials_row = {
            "github_pat_encrypted": "cipher",
            "github_app_installation_id": None,
            "aws_role_arn": None, "aws_external_id": None,
            "azure_tenant_id": None, "azure_client_id": None,
            "azure_client_secret_encrypted": None, "azure_subscription_id": None,
            "azure_devops_pat_encrypted": None,
        }
        request, conn = _make_request(row, credentials_row=credentials_row)

        MockWorkflow = MagicMock()
        MockWorkflow.return_value.resume = AsyncMock(return_value=None)

        with (
            patch.dict(incidents._WORKFLOW_CLASSES, {"agent_11_resource_health": MockWorkflow}),
            patch("core.workspace_credentials.decrypt", return_value="ghp_real_workspace_token"),
        ):
            await _approve(request, str(row["id"]), workspace_id)
            await _drain_background_tasks()

        MockWorkflow.assert_called_once()
        MockWorkflow.return_value.resume.assert_awaited_once()
        _, kwargs = MockWorkflow.call_args
        assert kwargs["github_token"] == "ghp_real_workspace_token"

    async def test_unknown_agent_id_raises_500_not_silent_fallback(self):
        workspace_id = uuid4()
        row = _incident_row("agent_99_does_not_exist", workspace_id)
        request, conn = _make_request(row)

        with pytest.raises(HTTPException) as exc:
            await _approve(request, str(row["id"]), workspace_id)

        assert exc.value.status_code == 500


class TestAgent04And10ResumeGetRealCredentials:
    # Real bug found while inventorying item 5's blast radius: agent_04 and
    # agent_10 were entirely missing from _CREDENTIALED_AGENTS, so this
    # resume path always instantiated their workflow with NO credentials --
    # meaning MigrationTools/DependencyPatchTools always fell back to
    # os.environ.get("GITHUB_TOKEN", "") (a shared platform-wide token --
    # a cross-tenant leak risk if ever set, a hard failure for every real
    # customer if not). This is the path that actually matters: the execute
    # node (where create_migration_pr/create_patch_pr run) fires on resume,
    # after HITL approval -- not on the initial diagnose-only run().

    async def test_agent04_and_10_resume_pass_the_workspaces_real_github_token(self):
        for agent_id in ("agent_04_migration", "agent_10_dependency_patch"):
            workspace_id = uuid4()
            row = _incident_row(agent_id, workspace_id)
            credentials_row = {
                "github_pat_encrypted": "cipher",
                "github_app_installation_id": None,
                "aws_role_arn": None, "aws_external_id": None,
                "azure_tenant_id": None, "azure_client_id": None,
                "azure_client_secret_encrypted": None, "azure_subscription_id": None,
                "azure_devops_pat_encrypted": None,
            }
            request, conn = _make_request(row, credentials_row=credentials_row)

            MockWorkflow = MagicMock()
            MockWorkflow.return_value.resume = AsyncMock(return_value=None)

            with (
                patch.dict(incidents._WORKFLOW_CLASSES, {agent_id: MockWorkflow}),
                patch("core.workspace_credentials.decrypt", return_value="ghp_real_workspace_token"),
            ):
                await _approve(request, str(row["id"]), workspace_id)
                await _drain_background_tasks()

            MockWorkflow.assert_called_once()
            _, kwargs = MockWorkflow.call_args
            assert kwargs["github_token"] == "ghp_real_workspace_token"

    async def test_agent04_and_10_resume_with_no_credentials_configured_pass_none(self):
        # No env-var fallback anymore -- an unconfigured workspace gets a
        # real None, not a silently-borrowed platform token.
        for agent_id in ("agent_04_migration", "agent_10_dependency_patch"):
            workspace_id = uuid4()
            row = _incident_row(agent_id, workspace_id)
            request, conn = _make_request(row, credentials_row=None)

            MockWorkflow = MagicMock()
            MockWorkflow.return_value.resume = AsyncMock(return_value=None)

            with patch.dict(incidents._WORKFLOW_CLASSES, {agent_id: MockWorkflow}):
                await _approve(request, str(row["id"]), workspace_id)
                await _drain_background_tasks()

            _, kwargs = MockWorkflow.call_args
            assert kwargs["github_token"] is None


class TestApproveStatusTransitions:
    async def test_hold_option_sets_held_and_does_not_resume_any_workflow(self):
        workspace_id = uuid4()
        row = _incident_row("agent_01_cicd_triage", workspace_id)
        request, conn = _make_request(row)

        result = await incidents.approve_incident(
            str(row["id"]),
            IncidentApproveRequest(selected_option_id="hold"),
            request,
            workspace={"id": workspace_id},
        )

        assert result.status == "held"
        conn.execute.assert_awaited_once()  # only the status-update UPDATE, no workflow resumed

    async def test_unknown_option_id_raises_400(self):
        workspace_id = uuid4()
        row = _incident_row("agent_01_cicd_triage", workspace_id)
        request, conn = _make_request(row)

        with pytest.raises(HTTPException) as exc:
            await incidents.approve_incident(
                str(row["id"]),
                IncidentApproveRequest(selected_option_id="opt_nonexistent"),
                request,
                workspace={"id": workspace_id},
            )
        assert exc.value.status_code == 400

    async def test_already_approved_incident_raises_409(self):
        workspace_id = uuid4()
        row = _incident_row("agent_01_cicd_triage", workspace_id)
        row["execution_status"] = "executing"
        request, conn = _make_request(row)

        with pytest.raises(HTTPException) as exc:
            await _approve(request, str(row["id"]), workspace_id)
        assert exc.value.status_code == 409

    async def test_incident_not_found_raises_404(self):
        request, conn = _make_request(None)
        with pytest.raises(HTTPException) as exc:
            await _approve(request, str(uuid4()), uuid4())
        assert exc.value.status_code == 404


class TestApproveRejectRoleGate:
    """
    Membership plan, Phase C (RBAC). A member session needs role 'admin'
    or 'approver' to approve/reject; 'viewer' is rejected. A token-
    authenticated caller (no member_role key at all) is unaffected --
    same full-trust model the workspace token already had.
    """

    def _member_workspace(self, workspace_id, role):
        return {"id": workspace_id, "member_id": str(uuid4()), "member_role": role, "member_email": "x@acme.com"}

    async def test_viewer_cannot_approve(self):
        workspace_id = uuid4()
        row = _incident_row("agent_01_cicd_triage", workspace_id)
        request, conn = _make_request(row)

        with pytest.raises(HTTPException) as exc:
            await incidents.approve_incident(
                str(row["id"]),
                IncidentApproveRequest(selected_option_id="opt_1"),
                request,
                workspace=self._member_workspace(workspace_id, "viewer"),
            )
        assert exc.value.status_code == 403

    async def test_approver_can_approve(self):
        workspace_id = uuid4()
        row = _incident_row("agent_01_cicd_triage", workspace_id)
        request, conn = _make_request(row)

        MockWorkflow = MagicMock()
        MockWorkflow.return_value.resume = AsyncMock(return_value=None)
        with patch.dict(incidents._WORKFLOW_CLASSES, {"agent_01_cicd_triage": MockWorkflow}):
            result = await incidents.approve_incident(
                str(row["id"]),
                IncidentApproveRequest(selected_option_id="opt_1"),
                request,
                workspace=self._member_workspace(workspace_id, "approver"),
            )
            await _drain_background_tasks()

        assert result.selected_option_id == "opt_1"

    async def test_admin_can_approve(self):
        workspace_id = uuid4()
        row = _incident_row("agent_01_cicd_triage", workspace_id)
        request, conn = _make_request(row)

        MockWorkflow = MagicMock()
        MockWorkflow.return_value.resume = AsyncMock(return_value=None)
        with patch.dict(incidents._WORKFLOW_CLASSES, {"agent_01_cicd_triage": MockWorkflow}):
            result = await incidents.approve_incident(
                str(row["id"]),
                IncidentApproveRequest(selected_option_id="opt_1"),
                request,
                workspace=self._member_workspace(workspace_id, "admin"),
            )
            await _drain_background_tasks()

        assert result.selected_option_id == "opt_1"

    async def test_token_auth_unaffected(self):
        workspace_id = uuid4()
        row = _incident_row("agent_01_cicd_triage", workspace_id)
        request, conn = _make_request(row)

        MockWorkflow = MagicMock()
        MockWorkflow.return_value.resume = AsyncMock(return_value=None)
        with patch.dict(incidents._WORKFLOW_CLASSES, {"agent_01_cicd_triage": MockWorkflow}):
            result = await incidents.approve_incident(
                str(row["id"]),
                IncidentApproveRequest(selected_option_id="opt_1"),
                request,
                workspace={"id": workspace_id},  # no member_role key -- token path
            )
            await _drain_background_tasks()

        assert result.selected_option_id == "opt_1"

    async def test_viewer_cannot_reject(self):
        workspace_id = uuid4()
        row = _incident_row("agent_01_cicd_triage", workspace_id)
        request, conn = _make_request(row)

        with pytest.raises(HTTPException) as exc:
            await incidents.reject_incident(
                str(row["id"]),
                incidents.IncidentRejectRequest(reason="not needed"),
                request,
                workspace=self._member_workspace(workspace_id, "viewer"),
            )
        assert exc.value.status_code == 403


class TestResolveIncidentManually:
    """
    "I'll handle this myself" -- the fourth HITL card option. Not a custom
    execution path: confirms the endpoint never resumes any workflow
    (no agent, no checkpointer, no credential lookup at all -- only two
    conn.execute calls, the incidents UPDATE and the audit_events INSERT),
    and that a real audit_events row is written (the feature's entire
    reason for existing -- "queryable for the customer's own reporting").
    """

    def _member_workspace(self, workspace_id, role):
        return {"id": workspace_id, "member_id": str(uuid4()), "member_role": role, "member_email": "x@acme.com"}

    async def test_resolves_with_note_updates_status_and_writes_audit_event(self):
        workspace_id = uuid4()
        row = _incident_row("agent_06_finops", workspace_id)
        request, conn = _make_request(row)

        result = await incidents.resolve_incident_manually(
            str(row["id"]),
            IncidentResolveManuallyRequest(resolution_note="Rotated the key manually in the AWS console."),
            request,
            workspace={"id": workspace_id},
        )

        assert result.status == "resolved_manually"
        assert result.resolution_note == "Rotated the key manually in the AWS console."
        assert result.resolved_at is not None

        # Exactly two writes: the incidents UPDATE, then the audit_events INSERT.
        # No workflow class instantiated, no checkpointer touched -- this
        # path never dispatches to _WORKFLOW_CLASSES at all.
        assert conn.execute.await_count == 2
        update_call, audit_call = conn.execute.await_args_list

        update_sql = update_call.args[0]
        assert "UPDATE incidents" in update_sql
        assert "resolved_manually" in update_sql
        assert update_call.args[1] == "Rotated the key manually in the AWS console."

        audit_sql = audit_call.args[0]
        assert "INSERT INTO audit_events" in audit_sql
        assert audit_call.args[1] == workspace_id
        assert audit_call.args[2] == "agent_06_finops"       # incident's own agent_id
        assert audit_call.args[3] == row["id"]
        assert json.loads(audit_call.args[4]) == {"resolution_note": "Rotated the key manually in the AWS console."}

    async def test_resolves_with_no_note(self):
        workspace_id = uuid4()
        row = _incident_row("agent_01_cicd_triage", workspace_id)
        request, conn = _make_request(row)

        result = await incidents.resolve_incident_manually(
            str(row["id"]),
            IncidentResolveManuallyRequest(),
            request,
            workspace={"id": workspace_id},
        )

        assert result.status == "resolved_manually"
        assert result.resolution_note is None

        _, audit_call = conn.execute.await_args_list
        assert json.loads(audit_call.args[4]) == {}

    async def test_blank_note_normalizes_to_none_not_empty_string(self):
        workspace_id = uuid4()
        row = _incident_row("agent_01_cicd_triage", workspace_id)
        request, conn = _make_request(row)

        result = await incidents.resolve_incident_manually(
            str(row["id"]),
            IncidentResolveManuallyRequest(resolution_note="   "),
            request,
            workspace={"id": workspace_id},
        )

        assert result.resolution_note is None
        update_call, audit_call = conn.execute.await_args_list
        assert update_call.args[1] is None
        assert json.loads(audit_call.args[4]) == {}

    async def test_incident_not_found_raises_404(self):
        request, conn = _make_request(None)
        with pytest.raises(HTTPException) as exc:
            await incidents.resolve_incident_manually(
                str(uuid4()),
                IncidentResolveManuallyRequest(),
                request,
                workspace={"id": uuid4()},
            )
        assert exc.value.status_code == 404

    async def test_already_resolved_incident_raises_409(self):
        workspace_id = uuid4()
        row = _incident_row("agent_01_cicd_triage", workspace_id)
        row["execution_status"] = "executed"
        request, conn = _make_request(row)

        with pytest.raises(HTTPException) as exc:
            await incidents.resolve_incident_manually(
                str(row["id"]),
                IncidentResolveManuallyRequest(),
                request,
                workspace={"id": workspace_id},
            )
        assert exc.value.status_code == 409

    async def test_viewer_cannot_resolve_manually(self):
        workspace_id = uuid4()
        row = _incident_row("agent_01_cicd_triage", workspace_id)
        request, conn = _make_request(row)

        with pytest.raises(HTTPException) as exc:
            await incidents.resolve_incident_manually(
                str(row["id"]),
                IncidentResolveManuallyRequest(),
                request,
                workspace=self._member_workspace(workspace_id, "viewer"),
            )
        assert exc.value.status_code == 403

    async def test_approver_can_resolve_manually(self):
        workspace_id = uuid4()
        row = _incident_row("agent_01_cicd_triage", workspace_id)
        request, conn = _make_request(row)

        result = await incidents.resolve_incident_manually(
            str(row["id"]),
            IncidentResolveManuallyRequest(),
            request,
            workspace=self._member_workspace(workspace_id, "approver"),
        )
        assert result.status == "resolved_manually"

    async def test_admin_can_resolve_manually(self):
        workspace_id = uuid4()
        row = _incident_row("agent_01_cicd_triage", workspace_id)
        request, conn = _make_request(row)

        result = await incidents.resolve_incident_manually(
            str(row["id"]),
            IncidentResolveManuallyRequest(),
            request,
            workspace=self._member_workspace(workspace_id, "admin"),
        )
        assert result.status == "resolved_manually"

    async def test_token_auth_unaffected(self):
        workspace_id = uuid4()
        row = _incident_row("agent_01_cicd_triage", workspace_id)
        request, conn = _make_request(row)

        result = await incidents.resolve_incident_manually(
            str(row["id"]),
            IncidentResolveManuallyRequest(),
            request,
            workspace={"id": workspace_id},  # no member_role key -- token path
        )
        assert result.status == "resolved_manually"
