"""
Item 5: verification_failed is "your fix didn't work" -- the most important
alert this product sends. It fans out to Slack / PagerDuty / email as
critical and reopens the resolution ticket if one was filed.
"""

import json
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from core import notifications, ticketing
from core import verification as v

INCIDENT_ID = "6f1c2d3e-0000-4000-8000-000000000001"
FAILED = {"incident_id": INCIDENT_ID, "agent_id": "agent_05_iam_minimizer", "execution_status": "verification_failed",
          "summary": "The fix ran but the problem is still there: policy is still *:*", "detail": "policy is still *:*",
          "severity": "critical", "resource_name": "cdlab-a3"}


def _client(*responses):
    """httpx.AsyncClient mock; get/post/patch return the given JSON bodies in order (shared queue)."""
    queue = list(responses)

    def _resp(*_a, **_k):
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json = MagicMock(return_value=queue.pop(0) if queue else {})
        return r

    client = AsyncMock()
    for verb in ("get", "post", "patch"):
        setattr(client, verb, AsyncMock(side_effect=_resp))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# ── channel wording and paging ───────────────────────────────────────────────

def test_every_channel_says_the_fix_didnt_work():
    assert notifications._headline("verification_failed") == "Cloud Decoded — your fix didn't work"
    assert "your fix didn't work" in notifications._format_slack_text(FAILED)


async def test_email_subject():
    with patch("core.email.send_email", new=AsyncMock()) as send:
        await notifications.send_email_notification("ops@example.com", FAILED)
    assert send.await_args.args[1] == "Cloud Decoded — your fix didn't work"


async def test_pagerduty_pages_critical_on_its_own_dedup_key():
    client = _client()
    with patch("core.notifications.httpx.AsyncClient", return_value=client):
        await notifications.send_pagerduty_notification("rk", FAILED)
    body = client.post.await_args.kwargs["json"]
    assert body["payload"]["severity"] == "critical"
    # Its own key: the incident's original alert may still be open, and PagerDuty
    # would fold a repeat trigger on that key into it without paging.
    assert body["dedup_key"] == f"{INCIDENT_ID}:fix-failed"


async def test_a_normal_incident_keeps_its_key_and_warning_severity():
    client = _client()
    with patch("core.notifications.httpx.AsyncClient", return_value=client):
        await notifications.send_pagerduty_notification("rk", {"incident_id": "i", "execution_status": "pending_approval"})
    body = client.post.await_args.kwargs["json"]
    assert (body["dedup_key"], body["payload"]["severity"]) == ("i", "warning")


async def test_critical_passes_every_severity_floor():
    """A channel set to critical-only still gets "your fix didn't work"."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"channel_type": "slack", "config_encrypted": "x", "min_severity": "critical",
                                          "quiet_hours_start": None, "quiet_hours_end": None,
                                          "quiet_hours_timezone": None}])
    with patch.dict("os.environ", {"DATABASE_URL": "postgresql://x"}), \
         patch("core.notifications.asyncpg.connect", new=AsyncMock(return_value=conn)), \
         patch("core.notifications.decrypt", return_value=json.dumps({"webhook_url": "https://hooks"})), \
         patch("core.notification_retry.is_channel_in_quiet_hours", new=AsyncMock(return_value=False)), \
         patch("core.notifications.send_slack_notification", new=AsyncMock()) as slack:
        await notifications.notify_incident_channels("ws", FAILED)
    slack.assert_awaited_once()


# ── verification fires both on verification_failed only ─────────────────────

def _row(status="executed"):
    from datetime import datetime, timezone
    return {"id": uuid4(), "workspace_id": uuid4(), "agent_id": "agent_05_iam_minimizer", "execution_status": status,
            "verification_spec": json.dumps({"check": "aws_policy"}), "verification_attempts": 3,
            "verification_deadline": datetime.now(timezone.utc) - timedelta(seconds=1)}


async def _verify(row, outcome):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"parsed_error": "Policy grants *:*", "resource_name": "cdlab-a3",
                                            "alert_name": None, "severity": "high", "resolved_at": None})
    with patch("core.verification.run_check", new=AsyncMock(return_value=outcome)), \
         patch("core.notifications.notify_incident_channels", new=AsyncMock()) as notify, \
         patch("core.ticketing.reopen_resolution_ticket", new=AsyncMock()) as reopen, \
         patch("core.ticketing.schedule_resolution_notification"):
        await v._verify_one(conn, row, AsyncMock(return_value={"aws_session": 1}))
        import asyncio
        await asyncio.sleep(0)  # let the scheduled tasks run
    return notify, reopen


@pytest.mark.parametrize("status", ["executed", "fix_merged"])
async def test_verification_failed_alerts_and_reopens(status):
    row = _row(status)
    notify, reopen = await _verify(row, v.Outcome(v.NOT_FIXED, "policy is still *:*"))
    ws, summary = notify.await_args.args
    assert ws == str(row["workspace_id"])
    assert summary["execution_status"] == "verification_failed" and summary["severity"] == "critical"
    assert summary["incident_severity"] == "high"
    assert "policy is still *:*" in summary["summary"] and "Policy grants *:*" in summary["summary"]
    reopen.assert_awaited_once()
    assert reopen.await_args.args[1]["incident_id"] == str(row["id"])


@pytest.mark.parametrize("outcome", [v.Outcome(v.FIXED, "gone"), v.Outcome(v.UNKNOWN, "AccessDenied")])
async def test_fixed_or_unverifiable_sends_no_fix_failed_alert(outcome):
    notify, reopen = await _verify(_row(), outcome)
    notify.assert_not_called()
    reopen.assert_not_called()


# ── reopening the ticket ─────────────────────────────────────────────────────

def _db(ticket_meta, channel_row=True):
    conn = AsyncMock()
    rows = [{"metadata": json.dumps(ticket_meta)} if ticket_meta else None]
    if channel_row:
        rows.append({"config_encrypted": "enc"})
    conn.fetchrow = AsyncMock(side_effect=rows)
    conn.close = AsyncMock()
    return conn


async def _reopen(conn, dispatch=None):
    with patch.dict("os.environ", {"DATABASE_URL": "postgresql://x"}), \
         patch("core.ticketing.asyncpg.connect", new=AsyncMock(return_value=conn)), \
         patch("core.ticketing.decrypt", return_value=json.dumps({"repo": "o/r"})), \
         patch("core.ticketing._dispatch_reopen", new=dispatch or AsyncMock()) as d, \
         patch("core.ticketing.schedule_audit_event") as audit, \
         patch("core.notification_retry.enqueue_retry", new=AsyncMock()) as retry:
        await ticketing.reopen_resolution_ticket("ws", FAILED)
    return d, audit, retry


async def test_reopens_the_ticket_the_resolution_filed():
    conn = _db({"provider": "github_issues", "external_id": "42", "ticket_url": "u"})
    dispatch, audit, retry = await _reopen(conn)
    lookup = conn.fetchrow.await_args_list[0].args
    assert "action = 'ticket_created'" in lookup[0] and "status = 'success'" in lookup[0]
    assert set(lookup[2]) == set(ticketing.TICKETING_CHANNEL_TYPES)  # never the pagerduty_resolve row
    assert dispatch.await_args.args[:3] == ("github_issues", {"repo": "o/r"}, "42")
    assert audit.call_args.kwargs["action"] == "ticket_reopened"
    retry.assert_not_called()
    conn.close.assert_awaited()


async def test_no_ticket_filed_means_nothing_to_reopen():
    conn = _db(None, channel_row=False)
    dispatch, audit, retry = await _reopen(conn)
    dispatch.assert_not_called()
    audit.assert_not_called()


async def test_failed_reopen_is_audited_and_retried():
    conn = _db({"provider": "jira", "external_id": "OPS-7"})
    dispatch, audit, retry = await _reopen(conn, AsyncMock(side_effect=RuntimeError("401")))
    assert audit.call_args.kwargs["action"] == "ticket_reopen_failed"
    ws, channel, kind, payload, err = retry.await_args.args
    assert (channel, kind, payload["ticket"]["external_id"]) == ("jira", "reopen", "OPS-7")


async def test_channel_removed_since_is_a_failure_not_silence():
    conn = _db({"provider": "linear", "external_id": "ENG-1"}, channel_row=False)
    conn.fetchrow = AsyncMock(side_effect=[{"metadata": {"provider": "linear", "external_id": "ENG-1"}}, None])
    dispatch, audit, _ = await _reopen(conn)
    dispatch.assert_not_called()
    assert audit.call_args.kwargs["action"] == "ticket_reopen_failed"


async def test_github_issue_is_commented_and_reopened():
    client = _client()
    with patch("core.ticketing.httpx.AsyncClient", return_value=client), \
         patch("core.ticketing.build_agent_credentials", new=AsyncMock(return_value={"github_token": "t"})):
        await ticketing.reopen_github_issue(AsyncMock(), "ws", {"repo": "o/r"}, "42", FAILED)
    assert client.post.await_args.args[0].endswith("/repos/o/r/issues/42/comments")
    assert "fix did not work" in client.post.await_args.kwargs["json"]["body"]
    assert client.patch.await_args.kwargs["json"] == {"state": "open"}


async def test_jira_done_issue_transitions_back_out_of_done():
    client = _client(
        {},  # comment
        {"fields": {"status": {"statusCategory": {"key": "done"}}}},
        {"transitions": [{"id": "31", "to": {"statusCategory": {"key": "done"}}},
                         {"id": "11", "to": {"statusCategory": {"key": "indeterminate"}}}]},
        {},  # transition
    )
    with patch("core.ticketing.httpx.AsyncClient", return_value=client):
        await ticketing.reopen_jira_ticket({"instance_url": "https://j", "api_token": "t"}, "OPS-7", FAILED)
    assert client.post.await_args.kwargs["json"] == {"transition": {"id": "11"}}


async def test_jira_open_issue_only_gets_the_comment():
    client = _client({}, {"fields": {"status": {"statusCategory": {"key": "new"}}}})
    with patch("core.ticketing.httpx.AsyncClient", return_value=client):
        await ticketing.reopen_jira_ticket({"instance_url": "https://j", "api_token": "t"}, "OPS-7", FAILED)
    assert client.post.await_count == 1 and client.post.await_args.args[0].endswith("/comment")


async def test_linear_issue_is_commented_and_moved_to_unstarted():
    calls = []

    async def gql(_c, _h, query, variables):
        calls.append((query, variables))
        if "issue(id:" in query:
            return {"issue": {"id": "uuid-1", "team": {"id": "team-1"}}}
        if "states(" in query:
            return {"team": {"states": {"nodes": [{"id": f"state-{variables['type']}"}]}}}
        return {}

    with patch("core.ticketing._linear_graphql", new=gql), \
         patch("core.ticketing.httpx.AsyncClient", return_value=_client()):
        await ticketing.reopen_linear_ticket({"api_key": "k"}, "ENG-1", FAILED)
    assert any("commentCreate" in q for q, _ in calls)
    update = next(v for q, v in calls if "issueUpdate" in q)
    assert update == {"id": "uuid-1", "input": {"stateId": "state-unstarted"}}


async def test_servicenow_change_request_gets_a_work_note():
    client = _client({"result": [{"sys_id": "abc"}]}, {})
    with patch("core.ticketing.httpx.AsyncClient", return_value=client):
        await ticketing.reopen_servicenow_ticket(
            {"instance_url": "https://sn", "username": "u", "password": "p"}, "CHG001", FAILED)
    assert client.get.await_args.kwargs["params"]["sysparm_query"] == "number=CHG001"
    assert client.patch.await_args.args[0].endswith("/change_request/abc")
    assert "fix did not work" in client.patch.await_args.kwargs["json"]["work_notes"]


async def test_retry_queue_replays_a_reopen():
    from core import notification_retry
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value={"repo": "o/r"})
    cm.__aexit__ = AsyncMock(return_value=False)
    cm.conn = "conn"
    row = {"channel_type": "github_issues", "send_kind": "reopen", "workspace_id": "ws",
           "payload_json": json.dumps({**FAILED, "ticket": {"provider": "github_issues", "external_id": "42"}})}
    with patch("core.notification_retry._channel_config", return_value=cm), \
         patch("core.ticketing._dispatch_reopen", new=AsyncMock()) as dispatch:
        await notification_retry._attempt_send(row)
    assert dispatch.await_args.args[:3] == ("github_issues", {"repo": "o/r"}, "42")
    assert dispatch.await_args.kwargs == {"conn": "conn", "workspace_id": "ws"}
