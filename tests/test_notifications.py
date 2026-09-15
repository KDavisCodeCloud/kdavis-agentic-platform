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


class TestSendPagerDutyResolveEvent:
    """Ticketing build, Phase 3 (2026-09-15): the resolve event this
    module's TestSendPagerDutyNotification class notes wasn't built yet."""

    async def test_posts_resolve_event_action(self):
        client, _ = _mock_httpx_client()
        with patch("core.notifications.httpx.AsyncClient", return_value=client):
            await notifications.send_pagerduty_resolve_event(
                "routing-key-123", {"incident_id": "abc", "agent_id": "agent_01"},
            )

        body = client.post.await_args.kwargs["json"]
        assert body["event_action"] == "resolve"
        assert body["routing_key"] == "routing-key-123"

    async def test_dedup_key_matches_trigger_events_dedup_key_extraction(self):
        """Both the original trigger event (send_pagerduty_notification)
        and this resolve event must derive dedup_key from
        incident_summary['incident_id'] the identical way -- PagerDuty
        correlates them purely by an exact dedup_key string match."""
        client, _ = _mock_httpx_client()
        incident_summary = {"incident_id": "abc-123", "agent_id": "agent_06_finops"}

        with patch("core.notifications.httpx.AsyncClient", return_value=client):
            await notifications.send_pagerduty_resolve_event("routing-key-123", incident_summary)
        resolve_dedup_key = client.post.await_args.kwargs["json"]["dedup_key"]

        client2, _ = _mock_httpx_client()
        with patch("core.notifications.httpx.AsyncClient", return_value=client2):
            await notifications.send_pagerduty_notification("routing-key-123", incident_summary)
        trigger_dedup_key = client2.post.await_args.kwargs["json"]["dedup_key"]

        assert resolve_dedup_key == trigger_dedup_key == "abc-123"

    async def test_no_payload_block(self):
        """Unlike a trigger event, PagerDuty's resolve/acknowledge events
        take no `payload` -- confirms this doesn't carry one over from
        send_pagerduty_notification's shape by accident."""
        client, _ = _mock_httpx_client()
        with patch("core.notifications.httpx.AsyncClient", return_value=client):
            await notifications.send_pagerduty_resolve_event("routing-key-123", {"incident_id": "x"})

        assert "payload" not in client.post.await_args.kwargs["json"]

    async def test_posts_to_pagerduty_events_endpoint(self):
        client, _ = _mock_httpx_client()
        with patch("core.notifications.httpx.AsyncClient", return_value=client):
            await notifications.send_pagerduty_resolve_event("routing-key-123", {"incident_id": "x"})

        assert client.post.await_args.args[0] == "https://events.pagerduty.com/v2/enqueue"

    async def test_raises_on_http_error(self):
        client, _ = _mock_httpx_client(status_code=500)
        with patch("core.notifications.httpx.AsyncClient", return_value=client):
            with pytest.raises(Exception):
                await notifications.send_pagerduty_resolve_event("routing-key-123", {"incident_id": "x"})


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
