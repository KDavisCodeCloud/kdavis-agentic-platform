"""
tests/test_email_triggers.py
core/email_triggers.py -- the two scheduled scans with no Stripe event to
hook: abandoned checkout (24h pending_payment) and stall nudges (72h
after first connection with no alert source verified). Both must never
re-enroll (and re-send step 1) on every hourly pass once a workspace has
already been enrolled once.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from core import email_triggers


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


class TestAbandonedCheckoutScan:
    async def test_enrolls_candidates_in_the_eligibility_window(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)  # lock acquired
        conn.fetch = AsyncMock(return_value=[
            {"id": uuid4(), "contact_email": "a@b.com", "created_at": datetime.now(timezone.utc) - timedelta(hours=25)},
        ])
        pool = _mock_pool(conn)

        with patch("core.email_triggers.enroll_by_email", new=AsyncMock()) as mock_enroll:
            summary = await email_triggers.run_abandoned_checkout_scan(pool)

        assert summary["enrolled"] == 1
        mock_enroll.assert_awaited_once()
        assert mock_enroll.await_args.args[2] == "abandoned_checkout"

    async def test_lock_not_acquired_skips_pass(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=False)
        pool = _mock_pool(conn)

        summary = await email_triggers.run_abandoned_checkout_scan(pool)

        assert summary["enrolled"] == 0
        conn.fetch.assert_not_called()

    async def test_a_failed_enroll_does_not_abort_the_batch(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetch = AsyncMock(return_value=[
            {"id": uuid4(), "contact_email": "a@b.com", "created_at": datetime.now(timezone.utc) - timedelta(hours=25)},
            {"id": uuid4(), "contact_email": "b@b.com", "created_at": datetime.now(timezone.utc) - timedelta(hours=25)},
        ])
        pool = _mock_pool(conn)

        with patch("core.email_triggers.enroll_by_email", new=AsyncMock(side_effect=[Exception("boom"), None])):
            summary = await email_triggers.run_abandoned_checkout_scan(pool)

        assert summary["enrolled"] == 1


class TestStallNudgeScan:
    def _workspace_row(self, **overrides):
        row = {
            "id": uuid4(), "contact_email": "a@b.com",
            "aws_role_verified_at": datetime.now(timezone.utc) - timedelta(hours=80),
            "azure_verified_at": None, "k8s_verified_at": None,
            "github_pat_verified_at": None, "azure_devops_pat_verified_at": None,
            "github_app_installation_id": None, "setup_test_passed_at": None,
        }
        row.update(overrides)
        return row

    async def test_enrolls_when_stalled_past_window_with_no_alert_source(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetch = AsyncMock(return_value=[self._workspace_row()])
        pool = _mock_pool(conn)

        with (
            patch("core.email_triggers.compute_setup_checklist", new=AsyncMock(return_value={"alert_source_verified": False})),
            patch("core.email_triggers.has_ever_enrolled_by_email", new=AsyncMock(return_value=False)),
            patch("core.email_triggers.enroll_by_email", new=AsyncMock()) as mock_enroll,
        ):
            summary = await email_triggers.run_stall_nudge_scan(pool)

        assert summary["enrolled"] == 1
        assert mock_enroll.await_args.args[2] == "stall_nudges"

    async def test_skips_when_alert_source_already_verified(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetch = AsyncMock(return_value=[self._workspace_row()])
        pool = _mock_pool(conn)

        with (
            patch("core.email_triggers.compute_setup_checklist", new=AsyncMock(return_value={"alert_source_verified": True})),
            patch("core.email_triggers.enroll_by_email", new=AsyncMock()) as mock_enroll,
        ):
            summary = await email_triggers.run_stall_nudge_scan(pool)

        assert summary["enrolled"] == 0
        mock_enroll.assert_not_awaited()

    async def test_never_reenrolls_once_already_enrolled(self):
        """The re-enrollment guard -- without this, an hourly scan would
        reset the sequence to step 0 and re-send step 1 forever."""
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetch = AsyncMock(return_value=[self._workspace_row()])
        pool = _mock_pool(conn)

        with (
            patch("core.email_triggers.compute_setup_checklist", new=AsyncMock(return_value={"alert_source_verified": False})),
            patch("core.email_triggers.has_ever_enrolled_by_email", new=AsyncMock(return_value=True)),
            patch("core.email_triggers.enroll_by_email", new=AsyncMock()) as mock_enroll,
        ):
            summary = await email_triggers.run_stall_nudge_scan(pool)

        assert summary["enrolled"] == 0
        mock_enroll.assert_not_awaited()

    async def test_workspace_with_no_connection_ever_is_skipped(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetch = AsyncMock(return_value=[self._workspace_row(aws_role_verified_at=None)])
        pool = _mock_pool(conn)

        with patch("core.email_triggers.enroll_by_email", new=AsyncMock()) as mock_enroll:
            summary = await email_triggers.run_stall_nudge_scan(pool)

        assert summary["enrolled"] == 0
        mock_enroll.assert_not_awaited()
