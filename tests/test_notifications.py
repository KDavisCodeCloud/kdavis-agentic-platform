"""
tests/test_notifications.py
Tests for core/notifications.py -- Tier 1 webhook build (Slack + PagerDuty
outbound notifications on incident creation).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core import notifications


def _mock_httpx_client(status_code: int = 200):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = Exception(f"HTTP {status_code}")

    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client, response


class TestSendSlackNotification:
    async def test_posts_text_body_to_webhook_url(self):
        client, response = _mock_httpx_client()
        with patch("core.notifications.httpx.AsyncClient", return_value=client):
            await notifications.send_slack_notification(
                "https://hooks.slack.com/services/x", {"agent_id": "agent_11_resource_health", "summary": "CPU high"}
            )

        client.post.assert_awaited_once()
        url, kwargs = client.post.await_args.args[0], client.post.await_args.kwargs
        assert url == "https://hooks.slack.com/services/x"
        assert "CPU high" in kwargs["json"]["text"]
        response.raise_for_status.assert_called_once()

    async def test_raises_on_http_error(self):
        client, _ = _mock_httpx_client(status_code=500)
        with patch("core.notifications.httpx.AsyncClient", return_value=client):
            with pytest.raises(Exception):
                await notifications.send_slack_notification("https://hooks.slack.com/services/x", {})


class TestSendPagerDutyNotification:
    async def test_pending_incident_maps_to_warning_severity(self):
        client, _ = _mock_httpx_client()
        with patch("core.notifications.httpx.AsyncClient", return_value=client):
            await notifications.send_pagerduty_notification(
                "routing-key-123",
                {"incident_id": "abc", "execution_status": "pending_approval", "summary": "x", "agent_id": "agent_01"},
            )

        body = client.post.await_args.kwargs["json"]
        assert body["routing_key"] == "routing-key-123"
        assert body["event_action"] == "trigger"
        assert body["dedup_key"] == "abc"
        assert body["payload"]["severity"] == "warning"

    async def test_failed_incident_maps_to_critical_severity(self):
        client, _ = _mock_httpx_client()
        with patch("core.notifications.httpx.AsyncClient", return_value=client):
            await notifications.send_pagerduty_notification(
                "routing-key-123",
                {"incident_id": "abc", "execution_status": "failed", "summary": "x", "agent_id": "agent_01"},
            )

        body = client.post.await_args.kwargs["json"]
        assert body["payload"]["severity"] == "critical"

    async def test_posts_to_pagerduty_events_endpoint(self):
        client, _ = _mock_httpx_client()
        with patch("core.notifications.httpx.AsyncClient", return_value=client):
            await notifications.send_pagerduty_notification("routing-key-123", {})

        url = client.post.await_args.args[0]
        assert url == "https://events.pagerduty.com/v2/enqueue"


class TestNotifyIncidentChannels:
    async def test_no_database_url_skips_without_raising(self):
        with patch("core.notifications.os.environ.get", return_value=""):
            # Must complete without raising.
            await notifications.notify_incident_channels("ws-1", {})

    async def test_dispatches_to_enabled_slack_and_pagerduty_channels(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {"channel_type": "slack", "config_encrypted": "enc-slack"},
                {"channel_type": "pagerduty", "config_encrypted": "enc-pd"},
            ]
        )
        conn.close = AsyncMock()

        def _fake_decrypt(value):
            if value == "enc-slack":
                return json.dumps({"webhook_url": "https://hooks.slack.com/x"})
            return json.dumps({"routing_key": "pd-key"})

        with (
            patch("core.notifications.os.environ.get", return_value="postgresql://x"),
            patch("core.notifications.asyncpg.connect", new=AsyncMock(return_value=conn)),
            patch("core.notifications.decrypt", side_effect=_fake_decrypt),
            patch("core.notifications.send_slack_notification", new=AsyncMock()) as mock_slack,
            patch("core.notifications.send_pagerduty_notification", new=AsyncMock()) as mock_pd,
        ):
            await notifications.notify_incident_channels("ws-1", {"summary": "x"})

        mock_slack.assert_awaited_once_with("https://hooks.slack.com/x", {"summary": "x"})
        mock_pd.assert_awaited_once_with("pd-key", {"summary": "x"})
        conn.close.assert_awaited_once()

    async def test_disabled_or_unconfigured_channel_lookup_failure_never_raises(self):
        with (
            patch("core.notifications.os.environ.get", return_value="postgresql://x"),
            patch("core.notifications.asyncpg.connect", side_effect=Exception("connection refused")),
        ):
            # Must complete without raising even when the DB is unreachable.
            await notifications.notify_incident_channels("ws-1", {})

    async def test_one_channel_failure_does_not_stop_the_other(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {"channel_type": "slack", "config_encrypted": "enc-slack"},
                {"channel_type": "pagerduty", "config_encrypted": "enc-pd"},
            ]
        )
        conn.close = AsyncMock()

        def _fake_decrypt(value):
            if value == "enc-slack":
                return json.dumps({"webhook_url": "https://hooks.slack.com/x"})
            return json.dumps({"routing_key": "pd-key"})

        with (
            patch("core.notifications.os.environ.get", return_value="postgresql://x"),
            patch("core.notifications.asyncpg.connect", new=AsyncMock(return_value=conn)),
            patch("core.notifications.decrypt", side_effect=_fake_decrypt),
            patch("core.notifications.send_slack_notification", new=AsyncMock(side_effect=Exception("boom"))),
            patch("core.notifications.send_pagerduty_notification", new=AsyncMock()) as mock_pd,
        ):
            await notifications.notify_incident_channels("ws-1", {})

        mock_pd.assert_awaited_once()
