"""
tests/test_workspace_ticketing_routes.py
Tests for api/routes/workspace_ticketing.py -- self-serve ticketing-channel
config (Jira in Phase 1; more providers land in later phases).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import HTTPException
import pytest

from api.routes import workspace_ticketing as wt_routes

_FERNET_KEY = Fernet.generate_key().decode()


def _make_request(fetch_return=None) -> tuple:
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=fetch_return or [])
    conn.fetchrow = AsyncMock(return_value=None)
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))
    return request, conn


class TestConnectJira:
    async def test_upserts_encrypted_config_and_never_returns_raw_secret(self):
        request, conn = _make_request()
        workspace_id = uuid4()

        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            result = await wt_routes.connect_jira(
                wt_routes.ConnectJiraRequest(
                    instance_url="https://acme.atlassian.net",
                    api_token="jira-secret-token",
                    project_key="OPS",
                ),
                request,
                workspace={"id": workspace_id},
            )

        assert result.channel_type == "jira"
        assert result.enabled is True
        assert "api_token" not in result.model_dump()

        conn.execute.assert_awaited_once()
        sql, *params = conn.execute.await_args.args
        assert "workspace_notification_channels" in sql
        assert workspace_id in params
        assert "jira" in params
        assert "jira-secret-token" not in params

    async def test_rejects_when_a_different_ticketing_channel_already_configured(self):
        request, conn = _make_request(fetch_return=[{"channel_type": "linear"}])
        workspace_id = uuid4()

        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            with pytest.raises(HTTPException) as exc:
                await wt_routes.connect_jira(
                    wt_routes.ConnectJiraRequest(
                        instance_url="https://acme.atlassian.net",
                        api_token="t",
                        project_key="OPS",
                    ),
                    request,
                    workspace={"id": workspace_id},
                )
        assert exc.value.status_code == 409
        conn.execute.assert_not_awaited()

    async def test_reconfiguring_same_provider_is_allowed(self):
        # The conflict query excludes the channel_type being written, so an
        # existing 'jira' row must not itself trigger the 409 -- confirmed
        # by fetch() returning no rows (mirrors the real "!= $3" SQL).
        request, conn = _make_request(fetch_return=[])
        workspace_id = uuid4()

        with patch.dict("os.environ", {"ENCRYPTION_KEY": _FERNET_KEY}):
            result = await wt_routes.connect_jira(
                wt_routes.ConnectJiraRequest(
                    instance_url="https://acme.atlassian.net",
                    api_token="t",
                    project_key="OPS-2",
                ),
                request,
                workspace={"id": workspace_id},
            )
        assert result.channel_type == "jira"
        conn.execute.assert_awaited_once()


class TestGetTicketingStatus:
    async def test_no_channel_configured_returns_none(self):
        request, conn = _make_request()
        result = await wt_routes.get_ticketing_status(request, workspace={"id": uuid4()})
        assert result.channel is None

    async def test_configured_channel_returned_without_secret(self):
        request, conn = _make_request()
        conn.fetchrow = AsyncMock(return_value={"channel_type": "jira", "enabled": True})
        result = await wt_routes.get_ticketing_status(request, workspace={"id": uuid4()})
        assert result.channel.channel_type == "jira"
        assert result.channel.enabled is True
        assert "api_token" not in result.model_dump_json()
