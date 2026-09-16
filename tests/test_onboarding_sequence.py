"""
tests/test_onboarding_sequence.py
Tests for core/onboarding_sequence.py -- the day-2/day-5 onboarding email
sequence (onboarding completeness build, item 5).
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from core import onboarding_sequence


def _mock_pool(conn):
    tx_ctx = AsyncMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=tx_ctx)
    tx_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx_ctx)

    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    return pool


def _workspace_row(**overrides) -> dict:
    row = {
        "id": uuid4(),
        "contact_email": "customer@example.com",
        "company_name": "Acme Co",
        "created_at": datetime.now(timezone.utc) - timedelta(days=3),
        "github_app_installation_id": None,
        "github_pat_verified_at": None,
        "aws_role_verified_at": None,
        "azure_verified_at": None,
        "azure_devops_pat_verified_at": None,
        "k8s_verified_at": None,
    }
    row.update(overrides)
    return row


class TestHasConnectedAnything:
    def test_false_when_nothing_set(self):
        assert onboarding_sequence._has_connected_anything(_workspace_row()) is False

    def test_true_when_github_app_installed(self):
        row = _workspace_row(github_app_installation_id="inst-123")
        assert onboarding_sequence._has_connected_anything(row) is True

    def test_true_when_aws_role_verified(self):
        row = _workspace_row(aws_role_verified_at=datetime.now(timezone.utc))
        assert onboarding_sequence._has_connected_anything(row) is True


class TestRunOnboardingSequenceCheck:
    async def test_skips_entire_cycle_when_lock_not_acquired(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=False)  # pg_try_advisory_xact_lock fails
        pool = _mock_pool(conn)

        result = await onboarding_sequence.run_onboarding_sequence_check(pool)

        assert result == {"day2_checklist": 0, "day5_setup_help": 0}
        conn.fetch.assert_not_called()

    async def test_sends_day2_checklist_for_unconnected_workspace_at_2_days(self):
        conn = AsyncMock()
        row = _workspace_row(created_at=datetime.now(timezone.utc) - timedelta(days=2, hours=1))
        conn.fetchval = AsyncMock(side_effect=[True, None])  # lock acquired, then "already_sent" check = None
        conn.fetch = AsyncMock(return_value=[row])
        pool = _mock_pool(conn)

        with patch("core.onboarding_sequence.send_email", new=AsyncMock()) as mock_send:
            result = await onboarding_sequence.run_onboarding_sequence_check(pool)

        assert result["day2_checklist"] == 1
        mock_send.assert_awaited_once()
        assert mock_send.await_args.kwargs["to"] == "customer@example.com"

    async def test_does_not_send_day2_when_workspace_already_connected_something(self):
        conn = AsyncMock()
        row = _workspace_row(
            created_at=datetime.now(timezone.utc) - timedelta(days=2, hours=1),
            github_app_installation_id="inst-123",
        )
        conn.fetchval = AsyncMock(return_value=True)  # lock acquired; alert-source check also True path unused here
        conn.fetch = AsyncMock(return_value=[row])
        pool = _mock_pool(conn)

        with patch("core.onboarding_sequence.send_email", new=AsyncMock()) as mock_send:
            await onboarding_sequence.run_onboarding_sequence_check(pool)

        mock_send.assert_not_awaited()

    async def test_does_not_send_day2_outside_the_eligibility_window(self):
        conn = AsyncMock()
        row = _workspace_row(created_at=datetime.now(timezone.utc) - timedelta(days=10))  # long past day2+slack
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetch = AsyncMock(return_value=[row])
        pool = _mock_pool(conn)

        with patch("core.onboarding_sequence.send_email", new=AsyncMock()) as mock_send, \
                patch("core.onboarding_sequence._has_verified_alert_source", new=AsyncMock(return_value=True)):
            await onboarding_sequence.run_onboarding_sequence_check(pool)

        mock_send.assert_not_awaited()

    async def test_sends_day5_setup_help_when_no_alert_source_verified(self):
        conn = AsyncMock()
        row = _workspace_row(
            created_at=datetime.now(timezone.utc) - timedelta(days=5, hours=1),
            github_app_installation_id="inst-123",  # connected -- day2 gate should NOT fire
        )
        conn.fetchval = AsyncMock(side_effect=[True, None])  # lock, then already_sent=None for day5
        conn.fetch = AsyncMock(return_value=[row])
        pool = _mock_pool(conn)

        with patch("core.onboarding_sequence.send_email", new=AsyncMock()) as mock_send, \
                patch("core.onboarding_sequence._has_verified_alert_source", new=AsyncMock(return_value=False)):
            result = await onboarding_sequence.run_onboarding_sequence_check(pool)

        assert result["day2_checklist"] == 0
        assert result["day5_setup_help"] == 1
        mock_send.assert_awaited_once()

    async def test_does_not_send_day5_when_alert_source_already_verified(self):
        conn = AsyncMock()
        row = _workspace_row(created_at=datetime.now(timezone.utc) - timedelta(days=5, hours=1))
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetch = AsyncMock(return_value=[row])
        pool = _mock_pool(conn)

        with patch("core.onboarding_sequence.send_email", new=AsyncMock()) as mock_send, \
                patch("core.onboarding_sequence._has_verified_alert_source", new=AsyncMock(return_value=True)):
            await onboarding_sequence.run_onboarding_sequence_check(pool)

        mock_send.assert_not_awaited()

    async def test_does_not_send_twice_for_the_same_workspace_and_stage(self):
        conn = AsyncMock()
        row = _workspace_row(created_at=datetime.now(timezone.utc) - timedelta(days=2, hours=1))
        conn.fetchval = AsyncMock(side_effect=[True, "already-sent-row"])  # lock, then already_sent truthy
        conn.fetch = AsyncMock(return_value=[row])
        pool = _mock_pool(conn)

        with patch("core.onboarding_sequence.send_email", new=AsyncMock()) as mock_send:
            result = await onboarding_sequence.run_onboarding_sequence_check(pool)

        assert result["day2_checklist"] == 0
        mock_send.assert_not_awaited()

    async def test_email_failure_does_not_record_a_tracking_row(self):
        from core.email import EmailError

        conn = AsyncMock()
        row = _workspace_row(created_at=datetime.now(timezone.utc) - timedelta(days=2, hours=1))
        conn.fetchval = AsyncMock(side_effect=[True, None])
        conn.fetch = AsyncMock(return_value=[row])
        pool = _mock_pool(conn)

        with patch("core.onboarding_sequence.send_email", new=AsyncMock(side_effect=EmailError("boom"))):
            result = await onboarding_sequence.run_onboarding_sequence_check(pool)

        assert result["day2_checklist"] == 0
        insert_calls = [c for c in conn.execute.await_args_list if "INSERT INTO workspace_onboarding_emails" in c.args[0]]
        assert len(insert_calls) == 0
