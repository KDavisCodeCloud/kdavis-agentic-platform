"""
tests/test_ticketing.py
Tests for core/ticketing.py -- ticketing-system integration fired on
incident RESOLUTION (Jira, Phase 1 of the ticketing build; more providers
land in later phases and get their own test classes here).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core import ticketing


def _mock_httpx_client(status_code: int = 200, json_body: dict | None = None):
    response = MagicMock()
    response.status_code = status_code
    response.json = MagicMock(return_value=json_body or {})
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = Exception(f"HTTP {status_code}")

    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client, response


class TestCreateJiraTicket:
    async def test_posts_correct_url_and_payload_shape(self):
        client, _ = _mock_httpx_client(json_body={"key": "OPS-42", "id": "10042"})
        config = {
            "instance_url": "https://acme.atlassian.net",
            "api_token": "jira-token-123",
            "project_key": "OPS",
            "issue_type": "Task",
        }
        incident_summary = {
            "incident_id": "abc-123",
            "resource_name": "vm-1",
            "parsed_error": "CPU high",
            "cloud_provider": "aws",
            "selected_option_id": "opt_1",
            "resolved_at": "2026-09-15T00:00:00+00:00",
        }
        with patch("core.ticketing.httpx.AsyncClient", return_value=client):
            result = await ticketing.create_jira_ticket(config, incident_summary, resolved_by=None)

        client.post.assert_awaited_once()
        url = client.post.await_args.args[0]
        assert url == "https://acme.atlassian.net/rest/api/3/issue"

        headers = client.post.await_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer jira-token-123"

        payload = client.post.await_args.kwargs["json"]
        fields = payload["fields"]
        assert fields["project"] == {"key": "OPS"}
        assert fields["issuetype"] == {"name": "Task"}
        assert "cloud-decoded" in fields["labels"]
        assert fields["priority"] == {"name": "P3"}
        assert "CPU high" in json.dumps(fields["description"])

        assert result == {"external_id": "OPS-42", "ticket_url": "https://acme.atlassian.net/browse/OPS-42"}

    async def test_manual_resolution_note_appended_to_description(self):
        client, _ = _mock_httpx_client(json_body={"key": "OPS-1"})
        config = {"instance_url": "https://acme.atlassian.net", "api_token": "t", "project_key": "OPS"}
        incident_summary = {"incident_id": "x", "resolution_note": "Rotated the key manually."}
        with patch("core.ticketing.httpx.AsyncClient", return_value=client):
            await ticketing.create_jira_ticket(config, incident_summary, resolved_by="member-1")

        payload = client.post.await_args.kwargs["json"]
        assert "resolved manually" in payload["fields"]["summary"].lower()
        assert "Rotated the key manually." in json.dumps(payload["fields"]["description"])

    async def test_raises_on_http_error(self):
        client, _ = _mock_httpx_client(status_code=400)
        config = {"instance_url": "https://acme.atlassian.net", "api_token": "t", "project_key": "OPS"}
        with patch("core.ticketing.httpx.AsyncClient", return_value=client):
            with pytest.raises(Exception):
                await ticketing.create_jira_ticket(config, {"incident_id": "x"}, resolved_by=None)


class TestNotifyResolution:
    async def test_no_database_url_skips_without_raising(self):
        with patch("core.ticketing.os.environ.get", return_value=""):
            await ticketing.notify_resolution("ws-1", {"incident_id": "i-1"})

    async def test_no_ticketing_channel_configured_is_a_noop(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        conn.close = AsyncMock()
        with (
            patch("core.ticketing.os.environ.get", return_value="postgresql://x"),
            patch("core.ticketing.asyncpg.connect", new=AsyncMock(return_value=conn)),
        ):
            await ticketing.notify_resolution("ws-1", {"incident_id": "i-1"})
        conn.close.assert_awaited_once()

    async def test_dispatches_to_jira_and_schedules_success_audit_event(self):
        """Ticketing build (2026-09-15), post-rebase: success/failure logging
        goes through core/audit.py's schedule_audit_event() -- the real,
        proven audit_events writer (GAPS.md #28) -- not a second, parallel
        ad-hoc INSERT."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"channel_type": "jira", "config_encrypted": "enc-jira"})
        conn.close = AsyncMock()

        with (
            patch("core.ticketing.os.environ.get", return_value="postgresql://x"),
            patch("core.ticketing.asyncpg.connect", new=AsyncMock(return_value=conn)),
            patch("core.ticketing.decrypt", return_value=json.dumps({"instance_url": "https://x", "api_token": "t", "project_key": "OPS"})),
            patch("core.ticketing.create_jira_ticket", new=AsyncMock(return_value={"external_id": "OPS-1", "ticket_url": "https://x/browse/OPS-1"})) as mock_jira,
            patch("core.ticketing.schedule_audit_event") as mock_audit,
        ):
            await ticketing.notify_resolution("ws-1", {"incident_id": "i-1", "agent_id": "agent_01_cicd_triage"})

        mock_jira.assert_awaited_once()
        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["workspace_id"] == "ws-1"
        assert kwargs["action"] == "ticket_created"
        assert kwargs["status"] == "success"
        assert kwargs["incident_id"] == "i-1"
        assert kwargs["agent_id"] == "agent_01_cicd_triage"
        assert kwargs["metadata"]["provider"] == "jira"
        assert kwargs["metadata"]["external_id"] == "OPS-1"

    async def test_ticket_creation_failure_schedules_failure_audit_event_and_does_not_raise(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"channel_type": "jira", "config_encrypted": "enc-jira"})
        conn.close = AsyncMock()

        with (
            patch("core.ticketing.os.environ.get", return_value="postgresql://x"),
            patch("core.ticketing.asyncpg.connect", new=AsyncMock(return_value=conn)),
            patch("core.ticketing.decrypt", return_value=json.dumps({"instance_url": "https://x", "api_token": "t", "project_key": "OPS"})),
            patch("core.ticketing.create_jira_ticket", new=AsyncMock(side_effect=Exception("jira down"))),
            patch("core.ticketing.schedule_audit_event") as mock_audit,
        ):
            # Must complete without raising.
            await ticketing.notify_resolution("ws-1", {"incident_id": "i-1", "agent_id": "agent_01_cicd_triage"})

        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["action"] == "ticket_creation_failed"
        assert kwargs["status"] == "failed"
        assert kwargs["metadata"]["provider"] == "jira"
        assert "jira down" in kwargs["metadata"]["error"]

    async def test_db_connect_failure_never_raises(self):
        with (
            patch("core.ticketing.os.environ.get", return_value="postgresql://x"),
            patch("core.ticketing.asyncpg.connect", side_effect=Exception("connection refused")),
        ):
            await ticketing.notify_resolution("ws-1", {"incident_id": "i-1"})

    async def test_resolved_by_merged_into_incident_summary(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"channel_type": "jira", "config_encrypted": "enc-jira"})
        conn.execute = AsyncMock(return_value=None)
        conn.close = AsyncMock()

        with (
            patch("core.ticketing.os.environ.get", return_value="postgresql://x"),
            patch("core.ticketing.asyncpg.connect", new=AsyncMock(return_value=conn)),
            patch("core.ticketing.decrypt", return_value=json.dumps({"instance_url": "https://x", "api_token": "t", "project_key": "OPS"})),
            patch("core.ticketing.create_jira_ticket", new=AsyncMock(return_value={})) as mock_jira,
        ):
            await ticketing.notify_resolution("ws-1", {"incident_id": "i-1"}, resolved_by="member-42")

        _, passed_summary, passed_resolved_by = mock_jira.await_args.args
        assert passed_resolved_by == "member-42"
        assert passed_summary["resolved_by"] == "member-42"


class TestScheduleResolutionNotification:
    async def test_schedules_notify_resolution_as_a_task(self):
        async def _drain():
            import asyncio
            current = asyncio.current_task()
            pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        with patch("core.ticketing.notify_resolution", new=AsyncMock()) as mock_notify:
            ticketing.schedule_resolution_notification("ws-1", {"incident_id": "i-1"}, resolved_by="m-1")
            await _drain()

        mock_notify.assert_awaited_once_with("ws-1", {"incident_id": "i-1"}, "m-1")

    def test_scheduling_failure_never_raises(self):
        with patch("core.ticketing.asyncio.create_task", side_effect=RuntimeError("no event loop")):
            # Must complete without raising.
            ticketing.schedule_resolution_notification("ws-1", {"incident_id": "i-1"})
