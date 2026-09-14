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
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.routes import incidents
from db.models import IncidentApproveRequest


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
