"""
tests/test_email_scheduler.py
core/email_scheduler.py -- the enrollment-advancing pass: quiet hours,
exit rules, skip_if branching, pending_approval-never-sends (via
_next_template's own status='approved' filter), and sequence completion.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from core import email_scheduler


def _mock_pool(conn):
    txn_ctx = AsyncMock()
    txn_ctx.__aenter__ = AsyncMock(return_value=None)
    txn_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn_ctx)

    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool


def _enrollment_row(**overrides):
    row = {
        "id": uuid4(), "subscriber_id": uuid4(), "sequence_key": "onboarding",
        "current_step": 0, "email": "a@b.com", "workspace_id": None,
    }
    row.update(overrides)
    return row


class TestWithinSendWindow:
    def test_within_window(self):
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        assert email_scheduler._within_send_window(now, "UTC") is True

    def test_outside_window(self):
        now = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
        assert email_scheduler._within_send_window(now, "UTC") is False

    def test_invalid_timezone_fails_open(self):
        now = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
        assert email_scheduler._within_send_window(now, "Not/AZone") is True


class TestEvaluateExitRules:
    def test_no_workspace_never_exits(self):
        assert email_scheduler._evaluate_exit_rules({"exit_on": ["workspace_active"]}, None) is None

    def test_workspace_active_exit_condition_met(self):
        ws = {"stripe_subscription_status": "active"}
        assert email_scheduler._evaluate_exit_rules({"exit_on": ["workspace_active"]}, ws) == "workspace_active"

    def test_workspace_canceled_exit_condition_met(self):
        ws = {"stripe_subscription_status": "canceled"}
        assert email_scheduler._evaluate_exit_rules({"exit_on": ["workspace_canceled"]}, ws) == "workspace_canceled"

    def test_condition_not_in_exit_on_never_fires(self):
        ws = {"stripe_subscription_status": "active"}
        assert email_scheduler._evaluate_exit_rules({"exit_on": ["workspace_canceled"]}, ws) is None


class TestRunPendingSendsQuietHours:
    async def test_outside_window_skips_entire_pass(self):
        pool = _mock_pool(AsyncMock())
        with patch.dict("os.environ", {"CD_EMAIL_QUIET_HOURS_TZ": "UTC"}):
            fixed_now = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)  # 2am UTC -- outside 06-18
            with patch("core.email_scheduler.datetime") as mock_dt:
                mock_dt.now.return_value = fixed_now
                summary = await email_scheduler.run_pending_sends(pool)
        assert summary["quiet_hours"] is True
        pool.acquire.assert_not_called()


class TestProcessOne:
    async def test_exits_when_exit_rule_met(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"active": True, "exit_rules": {"exit_on": ["workspace_active"]}},  # sequence row
            {"id": "ws-1", "stripe_subscription_status": "active"},  # workspace row
        ])
        with patch("core.email_scheduler.exit_enrollment", new=AsyncMock()) as mock_exit:
            outcome = await email_scheduler._process_one(conn, _enrollment_row(workspace_id="ws-1"))
        assert outcome == "exited"
        mock_exit.assert_awaited_once()

    async def test_inactive_sequence_does_not_process(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"active": False, "exit_rules": {}})
        outcome = await email_scheduler._process_one(conn, _enrollment_row())
        assert outcome == "sequence_inactive"

    async def test_no_approved_template_completes_sequence(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"active": True, "exit_rules": {}},  # sequence
            None,  # _next_template -- no approved template at step 1
        ])
        outcome = await email_scheduler._process_one(conn, _enrollment_row(current_step=0))
        assert outcome == "completed"
        update_calls = [c for c in conn.execute.await_args_list if "status = 'completed'" in c.args[0]]
        assert len(update_calls) == 1

    async def test_skip_if_true_advances_without_sending(self):
        conn = AsyncMock()
        template = {
            "key": "t1", "sequence_key": "onboarding", "subject": "s", "body_html": "h",
            "body_text": "t", "status": "approved", "cta_url": None, "utm_campaign": "t1",
            "skip_if": "alert_source_verified", "delay_days": 0,
        }
        conn.fetchrow = AsyncMock(side_effect=[
            {"active": True, "exit_rules": {}},  # sequence
            template,  # _next_template
        ])
        with (
            patch("core.email_scheduler._workspace_row", new=AsyncMock(return_value={"id": "ws-1"})),
            patch("core.email_scheduler._evaluate_skip_if", new=AsyncMock(return_value=True)),
            patch("core.email_scheduler.send_marketing_email", new=AsyncMock()) as mock_send,
        ):
            outcome = await email_scheduler._process_one(conn, _enrollment_row(workspace_id="ws-1"))
        assert outcome == "skipped"
        mock_send.assert_not_awaited()

    async def test_sends_and_advances_step_with_next_delay(self):
        conn = AsyncMock()
        template = {
            "key": "t1", "sequence_key": "onboarding", "subject": "s", "body_html": "h",
            "body_text": "t", "status": "approved", "cta_url": None, "utm_campaign": "t1",
            "skip_if": None, "delay_days": 0,
        }
        next_template = dict(template, key="t2", delay_days=3)
        conn.fetchrow = AsyncMock(side_effect=[
            {"active": True, "exit_rules": {}},  # sequence
            template,  # _next_template for step 1
            next_template,  # _next_template for step 2 (to compute next_send_at)
        ])
        with (
            patch("core.email_scheduler._workspace_row", new=AsyncMock(return_value=None)),
            patch("core.email_scheduler.send_marketing_email", new=AsyncMock(return_value="sent")) as mock_send,
        ):
            outcome = await email_scheduler._process_one(conn, _enrollment_row(current_step=0))
        assert outcome == "sent"
        mock_send.assert_awaited_once()
        update_call = [c for c in conn.execute.await_args_list if "current_step = $2, next_send_at" in c.args[0]][0]
        assert update_call.args[2] == 1  # advanced to step 1


class TestRunPendingSendsAbortsOnMissingSecret:
    async def test_missing_secret_stops_the_whole_pass(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)  # lock acquired
        conn.fetch = AsyncMock(return_value=[dict(_enrollment_row())])
        pool = _mock_pool(conn)

        from core.unsubscribe_token import UnsubscribeConfigError

        with (
            patch("core.email_scheduler._within_send_window", return_value=True),
            patch("core.email_scheduler._process_one", new=AsyncMock(side_effect=UnsubscribeConfigError("no secret"))),
        ):
            summary = await email_scheduler.run_pending_sends(pool)

        assert summary["attempted"] == 1
        assert summary["sent"] == 0
