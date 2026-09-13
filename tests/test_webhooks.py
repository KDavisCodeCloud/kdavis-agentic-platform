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
# github_webhook -- per-workspace signature validation, fail closed
# ──────────────────────────────────────────────────────────────────────────────
#
# Real bug this section guards against: the GitHub/Azure DevOps webhook
# handlers validated against a single global env var
# (GITHUB_WEBHOOK_SECRET/AZURE_DEVOPS_WEBHOOK_SECRET) and, worse, SKIPPED
# validation entirely if that env var was unset ("if webhook_secret and not
# _verify..."). Since migration 022 + PATCH /workspace/credentials/github
# already mint and store a real per-workspace encrypted_github_webhook_secret,
# the GitHub path now uses that instead and fails closed (403) when a
# workspace hasn't configured one yet, rather than accepting any payload.

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
