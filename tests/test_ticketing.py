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


class TestCreateLinearTicket:
    def _client_with_responses(self, bodies: list[dict]):
        """Returns a mock httpx.AsyncClient whose .post() yields each body
        in `bodies` in sequence -- create_linear_ticket makes 2-3 calls
        (label lookup, [label create], done-state lookup, issue create)."""
        responses = []
        for body in bodies:
            resp = MagicMock()
            resp.status_code = 200
            resp.json = MagicMock(return_value=body)
            resp.raise_for_status = MagicMock()
            responses.append(resp)
        client = AsyncMock()
        client.post = AsyncMock(side_effect=responses)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    async def test_existing_label_and_done_state_used_directly(self):
        client = self._client_with_responses([
            {"data": {"team": {"labels": {"nodes": [{"id": "label-1"}]}}}},
            {"data": {"team": {"states": {"nodes": [{"id": "state-done"}]}}}},
            {"data": {"issueCreate": {"success": True, "issue": {"id": "i1", "identifier": "ENG-42", "url": "https://linear.app/x/issue/ENG-42"}}}},
        ])
        config = {"api_key": "lin_api_key", "team_id": "team-1"}
        incident_summary = {"incident_id": "abc", "parsed_error": "Disk full", "cloud_provider": "aws"}

        with patch("core.ticketing.httpx.AsyncClient", return_value=client):
            result = await ticketing.create_linear_ticket(config, incident_summary, resolved_by=None)

        assert client.post.await_count == 3
        headers = client.post.await_args_list[0].kwargs["headers"]
        assert headers["Authorization"] == "lin_api_key"
        assert "Bearer" not in headers["Authorization"]

        create_call = client.post.await_args_list[2]
        variables = create_call.kwargs["json"]["variables"]
        assert variables["input"]["teamId"] == "team-1"
        assert variables["input"]["labelIds"] == ["label-1"]
        assert variables["input"]["stateId"] == "state-done"
        assert "Disk full" in variables["input"]["description"]

        assert result == {"external_id": "ENG-42", "ticket_url": "https://linear.app/x/issue/ENG-42"}

    async def test_creates_cloud_decoded_label_when_missing(self):
        client = self._client_with_responses([
            {"data": {"team": {"labels": {"nodes": []}}}},
            {"data": {"issueLabelCreate": {"issueLabel": {"id": "label-new"}}}},
            {"data": {"team": {"states": {"nodes": [{"id": "state-done"}]}}}},
            {"data": {"issueCreate": {"success": True, "issue": {"id": "i2", "identifier": "ENG-43", "url": "https://linear.app/x/issue/ENG-43"}}}},
        ])
        config = {"api_key": "lin_api_key", "team_id": "team-1"}

        with patch("core.ticketing.httpx.AsyncClient", return_value=client):
            result = await ticketing.create_linear_ticket(config, {"incident_id": "x"}, resolved_by=None)

        assert client.post.await_count == 4
        create_label_call = client.post.await_args_list[1]
        assert create_label_call.kwargs["json"]["variables"]["name"] == "Cloud Decoded"
        assert result["external_id"] == "ENG-43"

    async def test_missing_completed_state_still_creates_issue_without_state_id(self):
        client = self._client_with_responses([
            {"data": {"team": {"labels": {"nodes": [{"id": "label-1"}]}}}},
            {"data": {"team": {"states": {"nodes": []}}}},
            {"data": {"issueCreate": {"success": True, "issue": {"id": "i3", "identifier": "ENG-44", "url": "https://linear.app/x/issue/ENG-44"}}}},
        ])
        config = {"api_key": "k", "team_id": "team-1"}

        with patch("core.ticketing.httpx.AsyncClient", return_value=client):
            await ticketing.create_linear_ticket(config, {"incident_id": "x"}, resolved_by=None)

        create_call = client.post.await_args_list[2]
        assert "stateId" not in create_call.kwargs["json"]["variables"]["input"]

    async def test_graphql_error_raises(self):
        client = self._client_with_responses([
            {"errors": [{"message": "invalid team id"}]},
        ])
        config = {"api_key": "k", "team_id": "bad-team"}

        with patch("core.ticketing.httpx.AsyncClient", return_value=client):
            with pytest.raises(RuntimeError, match="invalid team id"):
                await ticketing.create_linear_ticket(config, {"incident_id": "x"}, resolved_by=None)


class TestDispatchTicketRoutesLinear:
    async def test_notify_resolution_dispatches_linear_channel(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, {"channel_type": "linear", "config_encrypted": "enc-linear"}])
        conn.close = AsyncMock()

        with (
            patch("core.ticketing.os.environ.get", return_value="postgresql://x"),
            patch("core.ticketing.asyncpg.connect", new=AsyncMock(return_value=conn)),
            patch("core.ticketing.decrypt", return_value=json.dumps({"api_key": "k", "team_id": "team-1"})),
            patch("core.ticketing.create_linear_ticket", new=AsyncMock(return_value={"external_id": "ENG-1", "ticket_url": "https://linear.app/x/issue/ENG-1"})) as mock_linear,
            patch("core.ticketing.schedule_audit_event") as mock_audit,
        ):
            await ticketing.notify_resolution("ws-1", {"incident_id": "i-1", "agent_id": "agent_06_finops"})

        mock_linear.assert_awaited_once()
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["metadata"]["provider"] == "linear"


class TestCreateGithubIssueTicket:
    def _client_with_responses(self, create_body: dict, create_status: int = 201, close_status: int = 200):
        create_resp = MagicMock()
        create_resp.status_code = create_status
        create_resp.json = MagicMock(return_value=create_body)
        create_resp.raise_for_status = MagicMock()
        if create_status >= 400:
            create_resp.raise_for_status.side_effect = Exception(f"HTTP {create_status}")

        close_resp = MagicMock()
        close_resp.status_code = close_status
        close_resp.raise_for_status = MagicMock()
        if close_status >= 400:
            close_resp.raise_for_status.side_effect = Exception(f"HTTP {close_status}")

        client = AsyncMock()
        client.post = AsyncMock(return_value=create_resp)
        client.patch = AsyncMock(return_value=close_resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client, create_resp, close_resp

    async def test_creates_then_closes_issue_using_github_app_token(self):
        client, _, _ = self._client_with_responses(
            {"number": 42, "html_url": "https://github.com/acme/infra/issues/42"}
        )
        config = {"repo": "acme/infra"}
        incident_summary = {"incident_id": "abc", "parsed_error": "Disk full", "cloud_provider": "aws"}

        with (
            patch("core.ticketing.httpx.AsyncClient", return_value=client),
            patch("core.ticketing.build_agent_credentials", new=AsyncMock(return_value={"github_token": "ghs_token123"})),
        ):
            result = await ticketing.create_github_issue_ticket(
                conn=AsyncMock(), workspace_id="ws-1", config=config, incident_summary=incident_summary, resolved_by=None,
            )

        create_url = client.post.await_args.args[0]
        assert create_url == "https://api.github.com/repos/acme/infra/issues"
        create_headers = client.post.await_args.kwargs["headers"]
        assert create_headers["Authorization"] == "Bearer ghs_token123"
        create_payload = client.post.await_args.kwargs["json"]
        assert create_payload["labels"] == ["cloud-decoded-incident"]
        assert "Disk full" in create_payload["body"]

        close_url = client.patch.await_args.args[0]
        assert close_url == "https://api.github.com/repos/acme/infra/issues/42"
        assert client.patch.await_args.kwargs["json"] == {"state": "closed"}

        assert result == {"external_id": "42", "ticket_url": "https://github.com/acme/infra/issues/42"}

    async def test_invalid_repo_format_raises(self):
        with pytest.raises(ValueError, match="owner/repo"):
            await ticketing.create_github_issue_ticket(
                conn=AsyncMock(), workspace_id="ws-1", config={"repo": "not-a-repo"},
                incident_summary={"incident_id": "x"}, resolved_by=None,
            )

    async def test_no_github_credentials_raises(self):
        with patch("core.ticketing.build_agent_credentials", new=AsyncMock(return_value={"github_token": None})):
            with pytest.raises(RuntimeError, match="GitHub"):
                await ticketing.create_github_issue_ticket(
                    conn=AsyncMock(), workspace_id="ws-1", config={"repo": "acme/infra"},
                    incident_summary={"incident_id": "x"}, resolved_by=None,
                )

    async def test_manual_resolution_note_and_gap_disclosure_in_body(self):
        client, _, _ = self._client_with_responses({"number": 1, "html_url": "https://github.com/acme/infra/issues/1"})
        with (
            patch("core.ticketing.httpx.AsyncClient", return_value=client),
            patch("core.ticketing.build_agent_credentials", new=AsyncMock(return_value={"github_token": "t"})),
        ):
            await ticketing.create_github_issue_ticket(
                conn=AsyncMock(), workspace_id="ws-1", config={"repo": "acme/infra"},
                incident_summary={"incident_id": "x", "resolution_note": "Rotated manually"}, resolved_by="member-1",
            )

        payload = client.post.await_args.kwargs["json"]
        assert "resolved manually" in payload["title"].lower()
        assert "Rotated manually" in payload["body"]
        assert "opened and closed automatically" in payload["body"]

    async def test_create_failure_raises_before_close_is_attempted(self):
        client, _, _ = self._client_with_responses({}, create_status=500)
        with (
            patch("core.ticketing.httpx.AsyncClient", return_value=client),
            patch("core.ticketing.build_agent_credentials", new=AsyncMock(return_value={"github_token": "t"})),
        ):
            with pytest.raises(Exception):
                await ticketing.create_github_issue_ticket(
                    conn=AsyncMock(), workspace_id="ws-1", config={"repo": "acme/infra"},
                    incident_summary={"incident_id": "x"}, resolved_by=None,
                )
        client.patch.assert_not_awaited()


class TestDispatchTicketRoutesGithubIssues:
    async def test_notify_resolution_dispatches_github_issues_channel(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, {"channel_type": "github_issues", "config_encrypted": "enc-gh"}])
        conn.close = AsyncMock()

        with (
            patch("core.ticketing.os.environ.get", return_value="postgresql://x"),
            patch("core.ticketing.asyncpg.connect", new=AsyncMock(return_value=conn)),
            patch("core.ticketing.decrypt", return_value=json.dumps({"repo": "acme/infra"})),
            patch("core.ticketing.create_github_issue_ticket", new=AsyncMock(return_value={"external_id": "42", "ticket_url": "https://github.com/acme/infra/issues/42"})) as mock_gh,
            patch("core.ticketing.schedule_audit_event") as mock_audit,
        ):
            await ticketing.notify_resolution("ws-1", {"incident_id": "i-1", "agent_id": "agent_04_migration"})

        mock_gh.assert_awaited_once()
        # conn and workspace_id are threaded through to the sender positionally.
        call_args = mock_gh.await_args
        assert call_args.args[0] is conn
        assert call_args.args[1] == "ws-1"
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["metadata"]["provider"] == "github_issues"


class TestCreateServiceNowTicket:
    def _client(self, status_code: int = 201, result: dict | None = None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json = MagicMock(return_value={"result": result or {"sys_id": "abc123", "number": "CHG0001234"}})
        resp.raise_for_status = MagicMock()
        if status_code >= 400:
            resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
        client = AsyncMock()
        client.post = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client, resp

    async def test_posts_change_request_with_basic_auth_and_closed_state(self):
        client, _ = self._client()
        config = {
            "instance_url": "https://acme.service-now.com",
            "username": "cd_integration",
            "password": "secret-pass",
            "assignment_group": "cloud-ops",
        }
        incident_summary = {"incident_id": "abc", "parsed_error": "CPU high", "cloud_provider": "azure"}

        with patch("core.ticketing.httpx.AsyncClient", return_value=client):
            result = await ticketing.create_servicenow_ticket(config, incident_summary, resolved_by=None)

        url = client.post.await_args.args[0]
        assert url == "https://acme.service-now.com/api/now/table/change_request"
        assert client.post.await_args.kwargs["auth"] == ("cd_integration", "secret-pass")

        payload = client.post.await_args.kwargs["json"]
        assert payload["state"] == "closed"
        assert payload["assignment_group"] == "cloud-ops"
        assert "CPU high" in payload["work_notes"]

        assert result["external_id"] == "CHG0001234"
        assert "abc123" in result["ticket_url"]

    async def test_manual_resolution_note_in_short_description_and_work_notes(self):
        client, _ = self._client()
        config = {
            "instance_url": "https://acme.service-now.com", "username": "u", "password": "p", "assignment_group": "g",
        }
        with patch("core.ticketing.httpx.AsyncClient", return_value=client):
            await ticketing.create_servicenow_ticket(
                config, {"incident_id": "x", "resolution_note": "Fixed by hand"}, resolved_by="member-1",
            )
        payload = client.post.await_args.kwargs["json"]
        assert "resolved manually" in payload["short_description"].lower()
        assert "Fixed by hand" in payload["work_notes"]

    async def test_raises_on_http_error(self):
        client, _ = self._client(status_code=401)
        config = {
            "instance_url": "https://acme.service-now.com", "username": "u", "password": "p", "assignment_group": "g",
        }
        with patch("core.ticketing.httpx.AsyncClient", return_value=client):
            with pytest.raises(Exception):
                await ticketing.create_servicenow_ticket(config, {"incident_id": "x"}, resolved_by=None)


class TestDispatchTicketRoutesServiceNow:
    async def test_notify_resolution_dispatches_servicenow_channel(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, {"channel_type": "servicenow", "config_encrypted": "enc-sn"}])
        conn.close = AsyncMock()

        with (
            patch("core.ticketing.os.environ.get", return_value="postgresql://x"),
            patch("core.ticketing.asyncpg.connect", new=AsyncMock(return_value=conn)),
            patch("core.ticketing.decrypt", return_value=json.dumps({
                "instance_url": "https://x.service-now.com", "username": "u", "password": "p", "assignment_group": "g",
            })),
            patch("core.ticketing.create_servicenow_ticket", new=AsyncMock(return_value={"external_id": "CHG1", "ticket_url": "https://x/CHG1"})) as mock_sn,
            patch("core.ticketing.schedule_audit_event") as mock_audit,
        ):
            await ticketing.notify_resolution("ws-1", {"incident_id": "i-1", "agent_id": "agent_06_finops"})

        mock_sn.assert_awaited_once()
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["metadata"]["provider"] == "servicenow"


class TestDispatchPagerdutyResolve:
    """Phase 3: PagerDuty resolution sync -- reuses the workspace's
    existing PagerDuty *notification* channel (a separate category from
    the one-ticketing-channel dispatch), independent of whatever ticketing
    provider (if any) is also configured."""

    async def test_no_pagerduty_channel_is_a_silent_noop(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        with patch("core.ticketing.send_pagerduty_resolve_event", new=AsyncMock()) as mock_pd:
            await ticketing._dispatch_pagerduty_resolve(conn, "ws-1", {"incident_id": "i-1"})
        mock_pd.assert_not_awaited()

    async def test_configured_channel_sends_resolve_event_with_matching_dedup_key(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"config_encrypted": "enc-pd"})

        with (
            patch("core.ticketing.decrypt", return_value=json.dumps({"routing_key": "pd-key-1"})),
            patch("core.ticketing.send_pagerduty_resolve_event", new=AsyncMock()) as mock_pd,
            patch("core.ticketing.schedule_audit_event") as mock_audit,
        ):
            await ticketing._dispatch_pagerduty_resolve(conn, "ws-1", {"incident_id": "abc-123", "agent_id": "agent_01"})

        mock_pd.assert_awaited_once_with("pd-key-1", {"incident_id": "abc-123", "agent_id": "agent_01"})
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["metadata"]["provider"] == "pagerduty_resolve"
        assert mock_audit.call_args.kwargs["status"] == "success"

    async def test_send_failure_schedules_failure_audit_and_does_not_raise(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"config_encrypted": "enc-pd"})

        with (
            patch("core.ticketing.decrypt", return_value=json.dumps({"routing_key": "pd-key-1"})),
            patch("core.ticketing.send_pagerduty_resolve_event", new=AsyncMock(side_effect=Exception("pd down"))),
            patch("core.ticketing.schedule_audit_event") as mock_audit,
        ):
            # Must complete without raising.
            await ticketing._dispatch_pagerduty_resolve(conn, "ws-1", {"incident_id": "i-1"})

        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["status"] == "failed"
        assert mock_audit.call_args.kwargs["metadata"]["provider"] == "pagerduty_resolve"


class TestNotifyResolutionDispatchesBothCategories:
    """notify_resolution fires the PagerDuty resolve-sync and the
    ticketing-channel dispatch independently -- both, either, or neither
    can fire depending on what's configured."""

    async def test_pagerduty_and_ticketing_channel_both_fire(self):
        conn = AsyncMock()
        # First fetchrow call is _dispatch_pagerduty_resolve's lookup,
        # second is the ticketing-channel lookup.
        conn.fetchrow = AsyncMock(side_effect=[
            {"config_encrypted": "enc-pd"},
            {"channel_type": "jira", "config_encrypted": "enc-jira"},
        ])
        conn.close = AsyncMock()

        def _fake_decrypt(value):
            if value == "enc-pd":
                return json.dumps({"routing_key": "pd-key"})
            return json.dumps({"instance_url": "https://x", "api_token": "t", "project_key": "OPS"})

        with (
            patch("core.ticketing.os.environ.get", return_value="postgresql://x"),
            patch("core.ticketing.asyncpg.connect", new=AsyncMock(return_value=conn)),
            patch("core.ticketing.decrypt", side_effect=_fake_decrypt),
            patch("core.ticketing.send_pagerduty_resolve_event", new=AsyncMock()) as mock_pd,
            patch("core.ticketing.create_jira_ticket", new=AsyncMock(return_value={"external_id": "OPS-1"})) as mock_jira,
            patch("core.ticketing.schedule_audit_event"),
        ):
            await ticketing.notify_resolution("ws-1", {"incident_id": "i-1", "agent_id": "agent_01_cicd_triage"})

        mock_pd.assert_awaited_once()
        mock_jira.assert_awaited_once()

    async def test_only_pagerduty_configured_ticketing_channel_lookup_finds_nothing(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"config_encrypted": "enc-pd"},
            None,
        ])
        conn.close = AsyncMock()

        with (
            patch("core.ticketing.os.environ.get", return_value="postgresql://x"),
            patch("core.ticketing.decrypt", return_value=json.dumps({"routing_key": "pd-key"})),
            patch("core.ticketing.asyncpg.connect", new=AsyncMock(return_value=conn)),
            patch("core.ticketing.send_pagerduty_resolve_event", new=AsyncMock()) as mock_pd,
            patch("core.ticketing.schedule_audit_event"),
        ):
            # Must complete without raising even though there's no ticketing channel.
            await ticketing.notify_resolution("ws-1", {"incident_id": "i-1"})

        mock_pd.assert_awaited_once()


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
        # First fetchrow is _dispatch_pagerduty_resolve's own lookup (None
        # -- no PagerDuty channel configured, so it's a silent no-op and
        # never touches schedule_audit_event); second is the ticketing-
        # channel lookup this test is actually about.
        conn.fetchrow = AsyncMock(side_effect=[None, {"channel_type": "jira", "config_encrypted": "enc-jira"}])
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
        conn.fetchrow = AsyncMock(side_effect=[None, {"channel_type": "jira", "config_encrypted": "enc-jira"}])
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
        conn.fetchrow = AsyncMock(side_effect=[None, {"channel_type": "jira", "config_encrypted": "enc-jira"}])
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
