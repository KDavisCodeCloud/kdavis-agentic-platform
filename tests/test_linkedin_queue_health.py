"""
tests/test_linkedin_queue_health.py
2026-09-22 incident fix -- core/linkedin_queue_health.py (hourly check for
approved-but-stuck LinkedIn posts, migration 055). Alerts on the symptom
(a post stuck past its scheduled_for with no published_at) rather than
any one specific cause, so every future failure mode surfaces within
hours instead of days. See that module's docstring for the full incident
this closes the loop on.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from core import linkedin_queue_health


def _mock_pool(conn):
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool


def _stale_row(**overrides):
    base = {"id": uuid4(), "scheduled_for": datetime.now(timezone.utc) - timedelta(hours=5)}
    base.update(overrides)
    return base


class TestRunLinkedinQueueHealthCheck:
    async def test_advisory_lock_not_acquired_skips_this_pass(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=False)
        pool = _mock_pool(conn)

        summary = await linkedin_queue_health.run_linkedin_queue_health_check(pool)

        conn.fetch.assert_not_called()
        assert summary == {"stale_count": 0, "alerted": False}

    async def test_no_stale_rows_is_a_clean_noop(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetch = AsyncMock(return_value=[])
        pool = _mock_pool(conn)

        summary = await linkedin_queue_health.run_linkedin_queue_health_check(pool)

        conn.fetchrow.assert_not_called()  # never even checks alert dedup state
        assert summary == {"stale_count": 0, "alerted": False}

    async def test_stale_rows_trigger_an_alert_when_none_sent_recently(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetch = AsyncMock(return_value=[_stale_row(), _stale_row()])
        conn.fetchrow = AsyncMock(return_value=None)  # never alerted before
        pool = _mock_pool(conn)

        with patch("core.email.send_email", new=AsyncMock()) as mock_send:
            summary = await linkedin_queue_health.run_linkedin_queue_health_check(pool)

        mock_send.assert_awaited_once()
        assert "2 LinkedIn posts stuck" in mock_send.await_args.args[1]
        assert summary == {"stale_count": 2, "alerted": True}

    async def test_recently_alerted_is_not_re_emailed(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetch = AsyncMock(return_value=[_stale_row()])
        conn.fetchrow = AsyncMock(return_value={"last_alerted_at": datetime.now(timezone.utc) - timedelta(hours=2)})
        pool = _mock_pool(conn)

        with patch("core.email.send_email", new=AsyncMock()) as mock_send:
            summary = await linkedin_queue_health.run_linkedin_queue_health_check(pool)

        mock_send.assert_not_awaited()
        assert summary == {"stale_count": 1, "alerted": False}

    async def test_re_alerts_once_the_dedup_window_has_passed(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetch = AsyncMock(return_value=[_stale_row()])
        conn.fetchrow = AsyncMock(return_value={"last_alerted_at": datetime.now(timezone.utc) - timedelta(hours=25)})
        pool = _mock_pool(conn)

        with patch("core.email.send_email", new=AsyncMock()) as mock_send:
            summary = await linkedin_queue_health.run_linkedin_queue_health_check(pool)

        mock_send.assert_awaited_once()
        assert summary == {"stale_count": 1, "alerted": True}

    async def test_query_uses_the_stale_threshold_not_just_any_past_schedule(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetch = AsyncMock(return_value=[])
        pool = _mock_pool(conn)

        await linkedin_queue_health.run_linkedin_queue_health_check(pool)

        sql, threshold = conn.fetch.call_args.args
        assert "status = 'approved'" in sql
        assert "published_at IS NULL" in sql
        assert threshold == "2"
