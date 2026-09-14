"""
tests/test_webhooks.py
Tests for api/routes/webhooks.py's aks_alert_webhook cloud_provider labeling.

Real bug this file guards against: aks_alert_webhook always scheduled
_run_k8s_alert_triage with cloud_provider="azure" regardless of payload
format ("azure" if is_azure_monitor else "azure"). Since this route also
accepts Prometheus AlertManager payloads (which can be watching any
cluster, including a real EKS cluster), this mislabeled AWS-sourced K8s
alerts. Fixed to "azure" if is_azure_monitor else "aws".

Runs with pytest-asyncio (asyncio_mode = auto) + unittest.mock — no live DB.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import BackgroundTasks

from api.routes import webhooks


def _make_request(workspace_row: dict, body: dict) -> SimpleNamespace:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=workspace_row)
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    app = SimpleNamespace(state=SimpleNamespace(db_pool=pool))
    payload_bytes = json.dumps(body).encode()
    request = SimpleNamespace(app=app, body=AsyncMock(return_value=payload_bytes))
    return request


def _workspace_row():
    return {
        "id": uuid4(),
        "stripe_subscription_status": "active",
        "product_tier": "enterprise",
        "encrypted_llm_key": None,
        "company_name": "Test Co",
    }


class TestAksAlertWebhookCloudProviderLabeling:
    async def test_prometheus_payload_tags_cloud_provider_aws(self):
        body = {"alerts": [{"status": "firing", "labels": {"alertname": "CrashLoopBackOff"}}]}
        request = _make_request(_workspace_row(), body)
        bg = BackgroundTasks()

        result = await webhooks.aks_alert_webhook(request, bg, token="ws-token")

        assert result["status"] == "accepted"
        assert len(bg.tasks) == 1
        task = bg.tasks[0]
        # BackgroundTask stores positional args on .args
        cloud_provider_arg = task.args[-1]
        assert cloud_provider_arg == "aws"

    async def test_azure_monitor_payload_tags_cloud_provider_azure(self):
        body = {
            "data": {
                "essentials": {"monitorCondition": "Fired"},
            }
        }
        request = _make_request(_workspace_row(), body)
        bg = BackgroundTasks()

        result = await webhooks.aks_alert_webhook(request, bg, token="ws-token")

        assert result["status"] == "accepted"
        assert len(bg.tasks) == 1
        task = bg.tasks[0]
        cloud_provider_arg = task.args[-1]
        assert cloud_provider_arg == "azure"


# ──────────────────────────────────────────────────────────────────────────────
# github_webhook / azure_devops_webhook -- per-workspace signature
# validation, fail closed
# ──────────────────────────────────────────────────────────────────────────────
#
# Real bug this section guards against: both webhook handlers validated
# against a single global env var (GITHUB_WEBHOOK_SECRET/
# AZURE_DEVOPS_WEBHOOK_SECRET) and, worse, SKIPPED validation entirely if
# that env var was unset ("if webhook_secret and not _verify..."). GitHub
# was fixed first (migration 022 + PATCH /workspace/credentials/github mint
# and store a real per-workspace encrypted_github_webhook_secret); Azure
# DevOps was fixed the same way in item 5 (migration 024 + PATCH
# /workspace/credentials/azure-devops). Both paths now fail closed (403)
# when a workspace hasn't configured a secret yet, rather than accepting
# any payload.

import hashlib
import hmac as _hmac
from unittest.mock import patch as _patch

import pytest
from cryptography.fernet import Fernet as _Fernet
from fastapi import HTTPException as _HTTPException

_FERNET_KEY = _Fernet.generate_key().decode()


def _make_request_with_headers(workspace_row: dict, body: dict, headers: dict) -> SimpleNamespace:
    request = _make_request(workspace_row, body)
    request.headers = headers
    return request


def _sign_github(payload_bytes: bytes, secret: str) -> str:
    return "sha256=" + _hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


class TestGithubWebhookSignatureValidation:
    async def test_rejects_when_no_secret_configured_for_workspace(self):
        row = _workspace_row()
        row["encrypted_github_webhook_secret"] = None
        body = {"action": "completed", "workflow_run": {"conclusion": "failure", "id": 1}}
        request = _make_request_with_headers(row, body, {
            "X-GitHub-Event": "workflow_run",
            "X-Hub-Signature-256": "sha256=irrelevant",
        })
        bg = BackgroundTasks()

        with pytest.raises(_HTTPException) as exc:
            await webhooks.github_webhook(request, bg, token="ws-token")

        assert exc.value.status_code == 403

    async def test_accepts_valid_signature_from_workspace_secret(self):
        from security.encryption import encrypt

        raw_secret = "real-workspace-secret"
        row = _workspace_row()
        with _patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            row["encrypted_github_webhook_secret"] = encrypt(raw_secret)

            body = {"action": "completed", "workflow_run": {"conclusion": "failure", "id": 1}}
            body_bytes = json.dumps(body).encode()
            request = _make_request_with_headers(row, body, {
                "X-GitHub-Event": "workflow_run",
                "X-Hub-Signature-256": _sign_github(body_bytes, raw_secret),
            })
            bg = BackgroundTasks()

            result = await webhooks.github_webhook(request, bg, token="ws-token")

        assert result["status"] == "accepted"

    async def test_rejects_wrong_signature(self):
        from security.encryption import encrypt

        raw_secret = "real-workspace-secret"
        row = _workspace_row()
        with _patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            row["encrypted_github_webhook_secret"] = encrypt(raw_secret)

            body = {"action": "completed", "workflow_run": {"conclusion": "failure", "id": 1}}
            request = _make_request_with_headers(row, body, {
                "X-GitHub-Event": "workflow_run",
                "X-Hub-Signature-256": "sha256=" + "0" * 64,
            })
            bg = BackgroundTasks()

            with pytest.raises(_HTTPException) as exc:
                await webhooks.github_webhook(request, bg, token="ws-token")

        assert exc.value.status_code == 401


def _sign_azure_devops(secret: str) -> str:
    import base64 as _base64
    return "Basic " + _base64.b64encode(f"anything:{secret}".encode()).decode()


class TestAzureDevOpsWebhookSignatureValidation:
    async def test_rejects_when_no_secret_configured_for_workspace(self):
        row = _workspace_row()
        row["encrypted_azure_devops_webhook_secret"] = None
        body = {"eventType": "build.complete", "resource": {"result": "failed", "id": 1}}
        request = _make_request_with_headers(row, body, {"Authorization": "Basic irrelevant"})
        bg = BackgroundTasks()

        with pytest.raises(_HTTPException) as exc:
            await webhooks.azure_devops_webhook(request, bg, token="ws-token")

        assert exc.value.status_code == 403

    async def test_accepts_valid_signature_from_workspace_secret(self):
        from security.encryption import encrypt

        raw_secret = "real-workspace-secret"
        row = _workspace_row()
        with _patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            row["encrypted_azure_devops_webhook_secret"] = encrypt(raw_secret)

            body = {"eventType": "build.complete", "resource": {"result": "failed", "id": 1}}
            request = _make_request_with_headers(row, body, {"Authorization": _sign_azure_devops(raw_secret)})
            bg = BackgroundTasks()

            result = await webhooks.azure_devops_webhook(request, bg, token="ws-token")

        assert result["status"] == "accepted"

    async def test_rejects_wrong_signature(self):
        from security.encryption import encrypt

        raw_secret = "real-workspace-secret"
        row = _workspace_row()
        with _patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            row["encrypted_azure_devops_webhook_secret"] = encrypt(raw_secret)

            body = {"eventType": "build.complete", "resource": {"result": "failed", "id": 1}}
            request = _make_request_with_headers(row, body, {"Authorization": _sign_azure_devops("wrong-secret")})
            bg = BackgroundTasks()

            with pytest.raises(_HTTPException) as exc:
                await webhooks.azure_devops_webhook(request, bg, token="ws-token")

        assert exc.value.status_code == 401


# ──────────────────────────────────────────────────────────────────────────────
# POST /webhooks/github-app -- item 4 migration, installation-id-based lookup
# ──────────────────────────────────────────────────────────────────────────────

def _make_app_webhook_request(fetchrow_results: list, body: dict, headers: dict) -> SimpleNamespace:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=fetchrow_results)
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    app = SimpleNamespace(state=SimpleNamespace(db_pool=pool))
    payload_bytes = json.dumps(body).encode()
    request = SimpleNamespace(app=app, body=AsyncMock(return_value=payload_bytes), headers=headers)
    return request, conn


class TestGithubAppWebhook:
    async def test_raises_503_when_app_not_registered(self):
        body = {"installation": {"id": 123}}
        request, conn = _make_app_webhook_request([None], body, {
            "X-GitHub-Event": "workflow_run", "X-Hub-Signature-256": "sha256=x",
        })
        bg = BackgroundTasks()
        with pytest.raises(_HTTPException) as exc:
            await webhooks.github_app_webhook(request, bg)
        assert exc.value.status_code == 503

    async def test_rejects_invalid_signature(self):
        from security.encryption import encrypt

        body = {"installation": {"id": 123}}
        with _patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            app_row = {"webhook_secret_encrypted": encrypt("app-webhook-secret")}
            request, conn = _make_app_webhook_request([app_row], body, {
                "X-GitHub-Event": "workflow_run", "X-Hub-Signature-256": "sha256=" + "0" * 64,
            })
            bg = BackgroundTasks()
            with pytest.raises(_HTTPException) as exc:
                await webhooks.github_app_webhook(request, bg)
        assert exc.value.status_code == 401

    async def test_ignores_event_for_unknown_installation(self):
        from security.encryption import encrypt

        body = {"installation": {"id": 123}, "action": "completed",
                "workflow_run": {"conclusion": "failure"}}
        body_bytes = json.dumps(body).encode()
        with _patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            secret = "app-webhook-secret"
            app_row = {"webhook_secret_encrypted": encrypt(secret)}
            request, conn = _make_app_webhook_request([app_row, None], body, {
                "X-GitHub-Event": "workflow_run",
                "X-Hub-Signature-256": _sign_github(body_bytes, secret),
            })
            bg = BackgroundTasks()
            result = await webhooks.github_app_webhook(request, bg)
        assert result["status"] == "ignored"
        assert "installation" in result["reason"]

    async def test_accepts_and_dispatches_workflow_run_failure_for_known_installation(self):
        from security.encryption import encrypt

        body = {"installation": {"id": 123}, "action": "completed",
                "workflow_run": {"conclusion": "failure", "id": 1}}
        body_bytes = json.dumps(body).encode()
        with _patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            secret = "app-webhook-secret"
            app_row = {"webhook_secret_encrypted": encrypt(secret)}
            workspace_row = _workspace_row()
            request, conn = _make_app_webhook_request([app_row, workspace_row], body, {
                "X-GitHub-Event": "workflow_run",
                "X-Hub-Signature-256": _sign_github(body_bytes, secret),
            })
            bg = BackgroundTasks()
            result = await webhooks.github_app_webhook(request, bg)
        assert result["status"] == "accepted"

    async def test_ignores_successful_workflow_run(self):
        from security.encryption import encrypt

        body = {"installation": {"id": 123}, "action": "completed",
                "workflow_run": {"conclusion": "success", "id": 1}}
        body_bytes = json.dumps(body).encode()
        with _patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            secret = "app-webhook-secret"
            app_row = {"webhook_secret_encrypted": encrypt(secret)}
            workspace_row = _workspace_row()
            request, conn = _make_app_webhook_request([app_row, workspace_row], body, {
                "X-GitHub-Event": "workflow_run",
                "X-Hub-Signature-256": _sign_github(body_bytes, secret),
            })
            bg = BackgroundTasks()
            result = await webhooks.github_app_webhook(request, bg)
        assert result["status"] == "ignored"


# ──────────────────────────────────────────────────────────────────────────────
# _run_migration / _run_dependency_patch -- credential wiring (Phase 1,
# connectivity gaps)
# ──────────────────────────────────────────────────────────────────────────────
#
# Real bug this section guards against: both background tasks used to
# instantiate their workflow with NO credentials at all
# (MigrationWorkflow(conn, workspace_id, checkpointer) / same for
# DependencyPatchWorkflow) -- unlike every other credentialed agent's
# dispatcher (_run_cicd_triage, _run_iam_minimize, _run_finops,
# _run_drift_detection), which all call build_agent_credentials() first.

def _make_run_request(workspace_row: dict) -> SimpleNamespace:
    conn = AsyncMock()
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    app = SimpleNamespace(state=SimpleNamespace(db_pool=pool, checkpointer=MagicMock()))
    return SimpleNamespace(app=app), conn


class TestRunMigrationCredentialWiring:
    async def test_calls_build_agent_credentials_and_spreads_into_workflow(self):
        workspace = _workspace_row()
        request, conn = _make_run_request(workspace)

        fake_creds = {"github_token": "ghp_real", "aws_session": None, "azure_access_token": None, "azure_devops_token": None}
        MockWorkflow = MagicMock()
        MockWorkflow.return_value.run = AsyncMock(return_value="incident-1")

        with (
            _patch("core.workspace_credentials.build_agent_credentials", new=AsyncMock(return_value=fake_creds)) as mock_creds,
            _patch("agents.agent_04_migration.workflow.MigrationWorkflow", MockWorkflow),
            _patch("api.routes.webhooks.WorkspaceComplianceGuard") as MockGuard,
        ):
            MockGuard.return_value.assert_workspace_active = AsyncMock(return_value=None)
            MockGuard.return_value.assert_agent_permitted = AsyncMock(return_value=None)
            await webhooks._run_migration(request.app, workspace, {"file_path": "x"}, "github")

        mock_creds.assert_awaited_once_with(conn, str(workspace["id"]))
        _, kwargs = MockWorkflow.call_args
        assert kwargs["github_token"] == "ghp_real"

    async def test_passes_workspace_llm_provider_and_byok_key(self):
        # Phase 5 (connectivity gaps): workspaces.llm_provider/encrypted_llm_key
        # were never passed into any agent's workflow constructor at all.
        workspace = {**_workspace_row(), "llm_provider": "openai", "encrypted_llm_key": "cipher-key"}
        request, conn = _make_run_request(workspace)

        fake_creds = {"github_token": None, "aws_session": None, "azure_access_token": None, "azure_devops_token": None}
        MockWorkflow = MagicMock()
        MockWorkflow.return_value.run = AsyncMock(return_value="incident-1")

        with (
            _patch("core.workspace_credentials.build_agent_credentials", new=AsyncMock(return_value=fake_creds)),
            _patch("agents.agent_04_migration.workflow.MigrationWorkflow", MockWorkflow),
            _patch("api.routes.webhooks.WorkspaceComplianceGuard") as MockGuard,
        ):
            MockGuard.return_value.assert_workspace_active = AsyncMock(return_value=None)
            MockGuard.return_value.assert_agent_permitted = AsyncMock(return_value=None)
            await webhooks._run_migration(request.app, workspace, {"file_path": "x"}, "github")

        _, kwargs = MockWorkflow.call_args
        assert kwargs["llm_provider"] == "openai"
        assert kwargs["byok_encrypted_key"] == "cipher-key"


class TestRunK8sAlertTriageCredentialWiring:
    # Phase 4 (connectivity gaps): _run_k8s_alert_triage used to instantiate
    # K8sAlertWorkflow with zero credentials -- neither build_agent_credentials()
    # (github_token, for create_gitops_pr) nor build_k8s_credentials()
    # (k8s_api_url/k8s_token, for the actual cluster calls) were ever called.

    async def test_calls_both_credential_builders_and_spreads_into_workflow(self):
        workspace = _workspace_row()
        request, conn = _make_run_request(workspace)

        fake_creds = {"github_token": "ghp_real", "aws_session": None, "azure_access_token": None,
                      "azure_devops_token": None, "azure_devops_org": None}
        fake_k8s_creds = {"k8s_api_url": "https://prod-cluster.example.com", "k8s_token": "real_k8s_token", "k8s_ca_cert": None}
        MockWorkflow = MagicMock()
        MockWorkflow.return_value.run = AsyncMock(return_value="incident-1")

        with (
            _patch("core.workspace_credentials.build_agent_credentials", new=AsyncMock(return_value=fake_creds)) as mock_creds,
            _patch("core.workspace_credentials.build_k8s_credentials", new=AsyncMock(return_value=fake_k8s_creds)) as mock_k8s_creds,
            _patch("agents.agent_02_k8s_alert.workflow.K8sAlertWorkflow", MockWorkflow),
            _patch("api.routes.webhooks.WorkspaceComplianceGuard") as MockGuard,
        ):
            MockGuard.return_value.assert_workspace_active = AsyncMock(return_value=None)
            MockGuard.return_value.assert_agent_permitted = AsyncMock(return_value=None)
            await webhooks._run_k8s_alert_triage(request.app, workspace, {"alerts": []}, "aws")

        mock_creds.assert_awaited_once_with(conn, str(workspace["id"]))
        mock_k8s_creds.assert_awaited_once_with(conn, str(workspace["id"]))
        _, kwargs = MockWorkflow.call_args
        assert kwargs["github_token"] == "ghp_real"
        assert kwargs["k8s_api_url"] == "https://prod-cluster.example.com"
        assert kwargs["k8s_token"] == "real_k8s_token"


class TestRunDriftDetectionK8sCredentialWiring:
    async def test_calls_build_k8s_credentials_alongside_existing_creds(self):
        workspace = _workspace_row()
        request, conn = _make_run_request(workspace)

        fake_creds = {"github_token": "ghp_real", "aws_session": None, "azure_access_token": None,
                      "azure_devops_token": None, "azure_devops_org": None}
        fake_k8s_creds = {"k8s_api_url": "https://prod-cluster.example.com", "k8s_token": "real_k8s_token", "k8s_ca_cert": None}
        MockWorkflow = MagicMock()
        MockWorkflow.return_value.run = AsyncMock(return_value="incident-1")

        with (
            _patch("core.workspace_credentials.build_agent_credentials", new=AsyncMock(return_value=fake_creds)),
            _patch("core.workspace_credentials.build_k8s_credentials", new=AsyncMock(return_value=fake_k8s_creds)) as mock_k8s_creds,
            _patch("core.workspace_credentials.resolve_k8s_context", return_value=None),
            _patch("agents.agent_08_drift_detection.workflow.DriftWorkflow", MockWorkflow),
            _patch("api.routes.webhooks.WorkspaceComplianceGuard") as MockGuard,
        ):
            MockGuard.return_value.assert_workspace_active = AsyncMock(return_value=None)
            MockGuard.return_value.assert_agent_permitted = AsyncMock(return_value=None)
            await webhooks._run_drift_detection(request.app, workspace, {"drift_source": "terraform"}, "aws")

        mock_k8s_creds.assert_awaited_once_with(conn, str(workspace["id"]))
        _, kwargs = MockWorkflow.call_args
        assert kwargs["k8s_api_url"] == "https://prod-cluster.example.com"
        assert kwargs["k8s_token"] == "real_k8s_token"


class TestRunDependencyPatchCredentialWiring:
    async def test_calls_build_agent_credentials_and_spreads_into_workflow(self):
        workspace = _workspace_row()
        request, conn = _make_run_request(workspace)

        fake_creds = {"github_token": "ghp_real", "aws_session": None, "azure_access_token": None, "azure_devops_token": None}
        MockWorkflow = MagicMock()
        MockWorkflow.return_value.run = AsyncMock(return_value="incident-1")

        with (
            _patch("core.workspace_credentials.build_agent_credentials", new=AsyncMock(return_value=fake_creds)) as mock_creds,
            _patch("agents.agent_10_dependency_patch.workflow.DependencyPatchWorkflow", MockWorkflow),
            _patch("api.routes.webhooks.WorkspaceComplianceGuard") as MockGuard,
        ):
            MockGuard.return_value.assert_workspace_active = AsyncMock(return_value=None)
            MockGuard.return_value.assert_agent_permitted = AsyncMock(return_value=None)
            await webhooks._run_dependency_patch(request.app, workspace, {"repository": "x"}, "github")

        mock_creds.assert_awaited_once_with(conn, str(workspace["id"]))
        _, kwargs = MockWorkflow.call_args
        assert kwargs["github_token"] == "ghp_real"
