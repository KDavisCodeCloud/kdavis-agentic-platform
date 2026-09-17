"""
tests/test_notification_retry.py
24-gap-closure build, Phase 3 -- core/notification_retry.py (durable
outbound retry queue + quiet-hours digest, migration 043).
"""

import json
from datetime import datetime, time, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from core import notification_retry


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


class TestIsChannelInQuietHours:
    async def test_within_normal_window(self):
        row = {"quiet_hours_start": time(22, 0), "quiet_hours_end": time(23, 0), "quiet_hours_timezone": "UTC"}
        now = datetime(2026, 1, 1, 22, 30, tzinfo=timezone.utc)
        assert await notification_retry.is_channel_in_quiet_hours(row, now) is True

    async def test_outside_normal_window(self):
        row = {"quiet_hours_start": time(22, 0), "quiet_hours_end": time(23, 0), "quiet_hours_timezone": "UTC"}
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        assert await notification_retry.is_channel_in_quiet_hours(row, now) is False

    async def test_window_wraps_midnight_inside(self):
        row = {"quiet_hours_start": time(22, 0), "quiet_hours_end": time(7, 0), "quiet_hours_timezone": "UTC"}
        now = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)  # 2am -- inside 22:00-07:00
        assert await notification_retry.is_channel_in_quiet_hours(row, now) is True

    async def test_window_wraps_midnight_outside(self):
        row = {"quiet_hours_start": time(22, 0), "quiet_hours_end": time(7, 0), "quiet_hours_timezone": "UTC"}
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)  # noon -- outside
        assert await notification_retry.is_channel_in_quiet_hours(row, now) is False

    async def test_no_quiet_hours_configured_is_never_in_them(self):
        row = {"quiet_hours_start": None, "quiet_hours_end": None, "quiet_hours_timezone": None}
        assert await notification_retry.is_channel_in_quiet_hours(row) is False

    async def test_invalid_timezone_fails_open_not_suppressing(self):
        """A config error must never silently swallow every notification
        for a channel -- fails OPEN (never suppress), not closed."""
        row = {"quiet_hours_start": time(22, 0), "quiet_hours_end": time(7, 0), "quiet_hours_timezone": "Not/ARealZone"}
        assert await notification_retry.is_channel_in_quiet_hours(row) is False

    async def test_respects_a_real_non_utc_timezone(self):
        # 2026-01-01 06:00 UTC == 2025-12-31 22:00 America/Los_Angeles (PST, UTC-8)
        row = {"quiet_hours_start": time(22, 0), "quiet_hours_end": time(7, 0), "quiet_hours_timezone": "America/Los_Angeles"}
        now = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
        assert await notification_retry.is_channel_in_quiet_hours(row, now) is True


class TestEnqueueRetry:
    async def test_inserts_a_pending_row_with_first_backoff_step(self):
        conn = AsyncMock()
        with (
            patch("core.notification_retry.os.environ.get", return_value="postgresql://x"),
            patch("core.notification_retry.asyncpg.connect", new=AsyncMock(return_value=conn)),
        ):
            await notification_retry.enqueue_retry("ws-1", "slack", "create", {"summary": "x"}, "boom")

        conn.execute.assert_awaited_once()
        sql, *params = conn.execute.await_args.args
        assert "INSERT INTO notification_retry_queue" in sql
        assert params[0] == "ws-1"
        assert params[1] == "slack"
        assert params[2] == "create"
        assert params[3] is None  # resolved_by
        assert json.loads(params[4]) == {"summary": "x"}
        conn.close.assert_awaited_once()

    async def test_no_database_url_is_a_silent_noop(self):
        with patch("core.notification_retry.os.environ.get", return_value=""):
            await notification_retry.enqueue_retry("ws-1", "slack", "create", {}, "boom")  # must not raise

    async def test_connect_failure_never_raises(self):
        with (
            patch("core.notification_retry.os.environ.get", return_value="postgresql://x"),
            patch("core.notification_retry.asyncpg.connect", side_effect=Exception("refused")),
        ):
            await notification_retry.enqueue_retry("ws-1", "slack", "create", {}, "boom")  # must not raise


class TestRunPendingRetries:
    def _row(self, **overrides):
        base = {
            "id": uuid4(), "workspace_id": "ws-1", "channel_type": "slack", "send_kind": "create",
            "resolved_by": None, "payload_json": json.dumps({"summary": "x"}),
            "attempt_count": 0, "max_attempts": 5,
        }
        base.update(overrides)
        return base

    async def test_successful_send_deletes_the_row(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetch = AsyncMock(return_value=[self._row()])
        pool = _mock_pool(conn)

        with patch("core.notification_retry._attempt_send", new=AsyncMock()) as mock_attempt:
            summary = await notification_retry.run_pending_retries(pool)

        mock_attempt.assert_awaited_once()
        delete_calls = [c for c in conn.execute.await_args_list if "DELETE FROM notification_retry_queue" in c.args[0]]
        assert len(delete_calls) == 1
        assert summary == {"attempted": 1, "succeeded": 1, "rescheduled": 0, "exhausted": 0}

    async def test_failure_below_max_attempts_reschedules_with_backoff(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetch = AsyncMock(return_value=[self._row(attempt_count=1)])
        pool = _mock_pool(conn)

        with patch("core.notification_retry._attempt_send", new=AsyncMock(side_effect=Exception("still down"))):
            summary = await notification_retry.run_pending_retries(pool)

        update_calls = [c for c in conn.execute.await_args_list if "status = 'exhausted'" not in c.args[0] and "UPDATE notification_retry_queue" in c.args[0]]
        assert len(update_calls) == 1
        assert update_calls[0].args[1] == 2  # new attempt_count
        assert summary["rescheduled"] == 1
        assert summary["exhausted"] == 0

    async def test_failure_at_max_attempts_marks_exhausted(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetch = AsyncMock(return_value=[self._row(attempt_count=4, max_attempts=5)])
        pool = _mock_pool(conn)

        with patch("core.notification_retry._attempt_send", new=AsyncMock(side_effect=Exception("still down"))):
            summary = await notification_retry.run_pending_retries(pool)

        exhausted_calls = [c for c in conn.execute.await_args_list if "status = 'exhausted'" in c.args[0]]
        assert len(exhausted_calls) == 1
        assert summary["exhausted"] == 1
        assert summary["rescheduled"] == 0

    async def test_advisory_lock_not_acquired_skips_this_pass(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=False)  # another worker holds the lock
        pool = _mock_pool(conn)

        summary = await notification_retry.run_pending_retries(pool)

        conn.fetch.assert_not_called()
        assert summary == {"attempted": 0, "succeeded": 0, "rescheduled": 0, "exhausted": 0}


class TestSuppressForQuietHours:
    async def test_inserts_suppressed_row(self):
        conn = AsyncMock()
        with (
            patch("core.notification_retry.os.environ.get", return_value="postgresql://x"),
            patch("core.notification_retry.asyncpg.connect", new=AsyncMock(return_value=conn)),
        ):
            await notification_retry.suppress_for_quiet_hours("ws-1", "slack", {"incident_id": "abc", "summary": "x"})

        sql, *params = conn.execute.await_args.args
        assert "INSERT INTO notification_suppressed" in sql
        assert params == ["ws-1", "slack", "abc", json.dumps({"incident_id": "abc", "summary": "x"})]


class TestRunQuietHoursDigests:
    async def test_sends_digest_and_marks_rows_digested_when_outside_window(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        channel_row = {
            "workspace_id": "ws-1", "channel_type": "slack", "config_encrypted": "enc",
            "quiet_hours_start": time(22, 0), "quiet_hours_end": time(7, 0), "quiet_hours_timezone": "UTC",
        }
        suppressed_id = uuid4()
        conn.fetch = AsyncMock(side_effect=[
            [channel_row],  # channels query
            [{"id": suppressed_id, "incident_id": "abc", "payload_json": json.dumps({"summary": "boom"})}],  # pending suppressed
        ])
        pool = _mock_pool(conn)

        with (
            patch("core.notification_retry.is_channel_in_quiet_hours", new=AsyncMock(return_value=False)),
            patch("core.notification_retry.decrypt", return_value=json.dumps({"webhook_url": "https://x"})),
            patch("core.notifications.send_slack_notification", new=AsyncMock()) as mock_slack,
        ):
            summary = await notification_retry.run_quiet_hours_digests(pool)

        mock_slack.assert_awaited_once()
        update_calls = [c for c in conn.execute.await_args_list if "SET digested = true" in c.args[0]]
        assert len(update_calls) == 1
        assert summary == {"digests_sent": 1, "incidents_digested": 1}

    async def test_skips_channel_still_inside_quiet_hours(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        channel_row = {
            "workspace_id": "ws-1", "channel_type": "slack", "config_encrypted": "enc",
            "quiet_hours_start": time(22, 0), "quiet_hours_end": time(7, 0), "quiet_hours_timezone": "UTC",
        }
        conn.fetch = AsyncMock(return_value=[channel_row])
        pool = _mock_pool(conn)

        with patch("core.notification_retry.is_channel_in_quiet_hours", new=AsyncMock(return_value=True)):
            summary = await notification_retry.run_quiet_hours_digests(pool)

        assert summary == {"digests_sent": 0, "incidents_digested": 0}

    async def test_pagerduty_channel_digest_is_a_documented_noop(self):
        """PagerDuty has no digest event shape -- must mark digested
        without attempting a send, not raise or skip marking."""
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        channel_row = {
            "workspace_id": "ws-1", "channel_type": "pagerduty", "config_encrypted": "enc",
            "quiet_hours_start": time(22, 0), "quiet_hours_end": time(7, 0), "quiet_hours_timezone": "UTC",
        }
        suppressed_id = uuid4()
        conn.fetch = AsyncMock(side_effect=[
            [channel_row],
            [{"id": suppressed_id, "incident_id": "abc", "payload_json": json.dumps({"summary": "boom"})}],
        ])
        pool = _mock_pool(conn)

        with (
            patch("core.notification_retry.is_channel_in_quiet_hours", new=AsyncMock(return_value=False)),
            patch("core.notification_retry.decrypt", return_value=json.dumps({"routing_key": "k"})),
        ):
            summary = await notification_retry.run_quiet_hours_digests(pool)

        update_calls = [c for c in conn.execute.await_args_list if "SET digested = true" in c.args[0]]
        assert len(update_calls) == 1
        assert summary == {"digests_sent": 1, "incidents_digested": 1}
