"""
tests/test_workspace_notifications_routes.py
Tests for api/routes/workspace_notifications.py -- self-serve Slack/
PagerDuty notification-channel config (Tier 1 webhook build).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from cryptography.fernet import Fernet

from api.routes import workspace_notifications as wn_routes

_FERNET_KEY = Fernet.generate_key().decode()


def _make_request(fetch_return=None) -> tuple:
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=fetch_return or [])
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))
    return request, conn


class TestConnectSlack:
    async def test_upserts_encrypted_config_and_never_returns_raw_url(self):
        request, conn = _make_request()
        workspace_id = uuid4()

        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            result = await wn_routes.connect_slack(
                wn_routes.ConnectSlackRequest(webhook_url="https://hooks.slack.com/services/x"),
                request,
                workspace={"id": workspace_id},
            )

        assert result.channel_type == "slack"
        assert result.enabled is True
        assert not hasattr(result, "webhook_url")
        assert "webhook_url" not in result.model_dump()

        conn.execute.assert_awaited_once()
        sql, *params = conn.execute.await_args.args
        assert "workspace_notification_channels" in sql
        assert workspace_id in params
        assert "slack" in params
        # The raw webhook URL must never be passed to the DB in plaintext --
        # only the Fernet-encrypted blob (which never equals the plaintext).
        assert "https://hooks.slack.com/services/x" not in params

    async def test_defaults_enabled_true(self):
        request, conn = _make_request()
        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            result = await wn_routes.connect_slack(
                wn_routes.ConnectSlackRequest(webhook_url="https://hooks.slack.com/services/x"),
                request,
                workspace={"id": uuid4()},
            )
        assert result.enabled is True


class TestConnectPagerDuty:
    async def test_upserts_encrypted_config_and_never_returns_raw_key(self):
        request, conn = _make_request()
        workspace_id = uuid4()

        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            result = await wn_routes.connect_pagerduty(
                wn_routes.ConnectPagerDutyRequest(routing_key="pd-routing-key-123", enabled=False),
                request,
                workspace={"id": workspace_id},
            )

        assert result.channel_type == "pagerduty"
        assert result.enabled is False
        assert "routing_key" not in result.model_dump()

        conn.execute.assert_awaited_once()
        sql, *params = conn.execute.await_args.args
        assert "pagerduty" in params
        assert "pd-routing-key-123" not in params


class TestListNotificationChannels:
    async def test_never_returns_config_encrypted_column(self):
        request, conn = _make_request(
            fetch_return=[
                {"channel_type": "slack", "enabled": True},
                {"channel_type": "pagerduty", "enabled": False},
            ]
        )

        result = await wn_routes.list_notification_channels(request, workspace={"id": uuid4()})

        assert len(result.channels) == 2
        dumped = [c.model_dump() for c in result.channels]
        assert all("config_encrypted" not in c and "webhook_url" not in c and "routing_key" not in c for c in dumped)
        assert {"channel_type": "slack", "enabled": True} in dumped
        assert {"channel_type": "pagerduty", "enabled": False} in dumped

    async def test_empty_when_no_channels_configured(self):
        request, conn = _make_request(fetch_return=[])
        result = await wn_routes.list_notification_channels(request, workspace={"id": uuid4()})
        assert result.channels == []
