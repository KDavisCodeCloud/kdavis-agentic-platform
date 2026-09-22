"""
tests/test_social_token_expiry.py
2026-09-22 incident fix -- core/social_token_expiry.py (hourly LinkedIn
token expiry check, migration 052). See that module's docstring for the
root cause: linkedin_callback never captured expires_in, so an expired
token failed every scheduled post silently for 3 days with no alerting.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from core import social_token_expiry


def _mock_pool(conn):
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool


def _connection_row(**overrides):
    base = {"expires_at": None, "expiry_warned_at": None, "platform_display_name": "Kelvin Davis"}
    base.update(overrides)
    return base


class TestRunSocialTokenExpiryCheck:
    async def test_advisory_lock_not_acquired_skips_this_pass(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=False)
        pool = _mock_pool(conn)

        summary = await social_token_expiry.run_social_token_expiry_check(pool)

        conn.fetchrow.assert_not_called()
        assert summary == {"warned": False, "expired_alerted": False}

    async def test_no_connection_row_is_a_clean_noop(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetchrow = AsyncMock(return_value=None)
        pool = _mock_pool(conn)

        summary = await social_token_expiry.run_social_token_expiry_check(pool)

        assert summary == {"warned": False, "expired_alerted": False}

    async def test_no_expires_at_captured_yet_is_a_clean_noop(self):
        """A row that predates migration 052's backfill (or a token
        exchange that returned no expires_in) has NULL expires_at --
        blind, not broken. Never crash or false-positive-alert on this."""
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetchrow = AsyncMock(return_value=_connection_row(expires_at=None))
        pool = _mock_pool(conn)

        summary = await social_token_expiry.run_social_token_expiry_check(pool)

        assert summary == {"warned": False, "expired_alerted": False}

    async def test_expiring_within_window_sends_warning_once(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        soon = datetime.now(timezone.utc) + timedelta(days=5)
        conn.fetchrow = AsyncMock(return_value=_connection_row(expires_at=soon, expiry_warned_at=None))
        pool = _mock_pool(conn)

        with patch("core.email.send_email", new=AsyncMock()) as mock_send:
            summary = await social_token_expiry.run_social_token_expiry_check(pool)

        mock_send.assert_awaited_once()
        assert "expires in" in mock_send.await_args.args[1]
        conn.execute.assert_awaited_once()
        assert summary == {"warned": True, "expired_alerted": False}

    async def test_already_warned_within_window_is_not_re_emailed(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        soon = datetime.now(timezone.utc) + timedelta(days=5)
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(expires_at=soon, expiry_warned_at=datetime.now(timezone.utc))
        )
        pool = _mock_pool(conn)

        with patch("core.email.send_email", new=AsyncMock()) as mock_send:
            summary = await social_token_expiry.run_social_token_expiry_check(pool)

        mock_send.assert_not_awaited()
        assert summary == {"warned": False, "expired_alerted": False}

    async def test_already_expired_sends_urgent_alert(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        past = datetime.now(timezone.utc) - timedelta(days=3)
        conn.fetchrow = AsyncMock(return_value=_connection_row(expires_at=past, expiry_warned_at=None))
        pool = _mock_pool(conn)

        with patch("core.email.send_email", new=AsyncMock()) as mock_send:
            summary = await social_token_expiry.run_social_token_expiry_check(pool)

        mock_send.assert_awaited_once()
        assert "URGENT" in mock_send.await_args.args[1]
        assert "expired 3 days ago" in mock_send.await_args.args[1]
        assert summary == {"warned": False, "expired_alerted": True}

    async def test_already_expired_re_alerts_after_a_day_not_every_hourly_pass(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        past = datetime.now(timezone.utc) - timedelta(days=3)
        alerted_recently = datetime.now(timezone.utc) - timedelta(hours=2)
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(expires_at=past, expiry_warned_at=alerted_recently)
        )
        pool = _mock_pool(conn)

        with patch("core.email.send_email", new=AsyncMock()) as mock_send:
            summary = await social_token_expiry.run_social_token_expiry_check(pool)

        mock_send.assert_not_awaited()
        assert summary == {"warned": False, "expired_alerted": False}

    async def test_already_expired_re_alerts_once_a_day_has_passed(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        past = datetime.now(timezone.utc) - timedelta(days=3)
        alerted_yesterday = datetime.now(timezone.utc) - timedelta(days=1, hours=1)
        conn.fetchrow = AsyncMock(
            return_value=_connection_row(expires_at=past, expiry_warned_at=alerted_yesterday)
        )
        pool = _mock_pool(conn)

        with patch("core.email.send_email", new=AsyncMock()) as mock_send:
            summary = await social_token_expiry.run_social_token_expiry_check(pool)

        mock_send.assert_awaited_once()
        assert summary == {"warned": False, "expired_alerted": True}
