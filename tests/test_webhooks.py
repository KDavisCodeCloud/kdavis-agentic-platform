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
