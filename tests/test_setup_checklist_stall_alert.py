"""
tests/test_setup_checklist_stall_alert.py
Admin visibility build (2026-09-27) -- core/setup_checklist_stall_alert.py.
item 3: paying workspace stalled below 5/5 for 72h+ -> email Kelvin,
with re-alert only after new activity + another 72h of silence.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from core import setup_checklist_stall_alert as stall_alert
from core.email import EmailError


def _mock_pool(conn):
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool


def _dt(hours_ago: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours_ago)


def _workspace_row(**overrides) -> dict:
    base = {
        "id": uuid4(), "company_name": "Acme", "contact_email": "ops@acme.com",
        "created_at": _dt(200),
        "aws_role_verified_at": None, "azure_verified_at": None, "k8s_verified_at": None,
        "github_app_installed_at": None, "github_pat_verified_at": None, "azure_devops_pat_verified_at": None,
        "setup_test_passed_at": None, "setup_stall_alert_sent_at": None,
    }
    base.update(overrides)
    return base


def _mock_conn(workspace_rows, alert_rows=None, channel_rows=None):
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[workspace_rows, alert_rows or [], channel_rows or []])
    conn.execute = AsyncMock(return_value=None)
    return conn


class TestRunStalledSetupCheck:
    async def test_workspace_at_5_of_5_is_never_alerted(self):
        row = _workspace_row(
            aws_role_verified_at=_dt(200), github_pat_verified_at=_dt(200),
            setup_test_passed_at=_dt(200),
        )
        conn = _mock_conn([row], alert_rows=[{"workspace_id": row["id"], "first_at": _dt(200)}],
                           channel_rows=[{"workspace_id": row["id"], "first_at": _dt(200)}])
        pool = _mock_pool(conn)

        with patch.object(stall_alert, "send_email", new=AsyncMock()) as mock_send:
            summary = await stall_alert.run_stalled_setup_check(pool)

        mock_send.assert_not_awaited()
        assert summary == {"checked": 1, "alerted": []}

    async def test_recently_active_workspace_is_not_yet_stalled(self):
        row = _workspace_row(aws_role_verified_at=_dt(10))  # 1/5, but active 10h ago
        conn = _mock_conn([row])
        pool = _mock_pool(conn)

        with patch.object(stall_alert, "send_email", new=AsyncMock()) as mock_send:
            summary = await stall_alert.run_stalled_setup_check(pool)

        mock_send.assert_not_awaited()
        assert summary["alerted"] == []

    async def test_stalled_never_alerted_workspace_gets_emailed_and_recorded(self):
        row = _workspace_row(aws_role_verified_at=_dt(200))  # 1/5, stalled since 200h ago
        conn = _mock_conn([row])
        pool = _mock_pool(conn)

        with patch.object(stall_alert, "send_email", new=AsyncMock()) as mock_send:
            summary = await stall_alert.run_stalled_setup_check(pool)

        mock_send.assert_awaited_once()
        # Owner alert, not the customer's own contact -- same pattern as
        # _send_enterprise_alert (defaults to Kelvin's address).
        assert mock_send.await_args.kwargs["to"] == "kdav2k5@gmail.com"
        assert "Acme" in mock_send.await_args.kwargs["subject"]
        assert summary["alerted"] == [str(row["id"])]
        update_calls = [c for c in conn.execute.await_args_list if "setup_stall_alert_sent_at" in c.args[0]]
        assert len(update_calls) == 1
        assert update_calls[0].args[2] == row["id"]

    async def test_zero_of_five_workspace_uses_created_at_as_baseline(self):
        row = _workspace_row(created_at=_dt(200))  # 0/5, never touched, created 200h ago
        conn = _mock_conn([row])
        pool = _mock_pool(conn)

        with patch.object(stall_alert, "send_email", new=AsyncMock()) as mock_send:
            summary = await stall_alert.run_stalled_setup_check(pool)

        mock_send.assert_awaited_once()
        html = mock_send.await_args.kwargs["html"]
        assert "never" in html.lower() or "No checklist item" in html

    async def test_already_alerted_for_this_stall_episode_is_not_re_emailed(self):
        row = _workspace_row(
            aws_role_verified_at=_dt(200),  # last activity 200h ago
            setup_stall_alert_sent_at=_dt(100),  # alerted AFTER that activity, no new activity since
        )
        conn = _mock_conn([row])
        pool = _mock_pool(conn)

        with patch.object(stall_alert, "send_email", new=AsyncMock()) as mock_send:
            summary = await stall_alert.run_stalled_setup_check(pool)

        mock_send.assert_not_awaited()
        assert summary["alerted"] == []

    async def test_new_activity_after_a_prior_alert_permits_a_fresh_alert(self):
        row = _workspace_row(
            aws_role_verified_at=_dt(300),          # first alert would have covered this
            github_pat_verified_at=_dt(200),        # NEW activity after that alert
            setup_stall_alert_sent_at=_dt(250),     # alert sent between the two activities
        )
        conn = _mock_conn([row])
        pool = _mock_pool(conn)

        with patch.object(stall_alert, "send_email", new=AsyncMock()) as mock_send:
            summary = await stall_alert.run_stalled_setup_check(pool)

        # last_activity_at (200h ago) is well past 72h, and the alert (250h ago)
        # predates that later activity -- a fresh alert must fire.
        mock_send.assert_awaited_once()
        assert summary["alerted"] == [str(row["id"])]

    async def test_email_failure_is_logged_not_raised_and_not_recorded(self):
        row = _workspace_row(aws_role_verified_at=_dt(200))
        conn = _mock_conn([row])
        pool = _mock_pool(conn)

        with patch.object(stall_alert, "send_email", new=AsyncMock(side_effect=EmailError("boom"))) as mock_send:
            summary = await stall_alert.run_stalled_setup_check(pool)

        mock_send.assert_awaited_once()
        assert summary["alerted"] == []
        update_calls = [c for c in conn.execute.await_args_list if "setup_stall_alert_sent_at" in c.args[0]]
        assert update_calls == []

    async def test_missing_items_listed_in_email_match_incomplete_checklist_items(self):
        row = _workspace_row(aws_role_verified_at=_dt(200))  # only cloud_connected is done
        conn = _mock_conn([row])
        pool = _mock_pool(conn)

        with patch.object(stall_alert, "send_email", new=AsyncMock()) as mock_send:
            await stall_alert.run_stalled_setup_check(pool)

        html = mock_send.await_args.kwargs["html"]
        assert "Cloud connected" not in html.split("Still missing")[1] if "Still missing" in html else True
        assert "Repo connected" in html
        assert "Alert source verified" in html
        assert "Notification channel set" in html
        assert "End-to-end test passed" in html

    async def test_no_active_workspaces_is_a_clean_no_op(self):
        conn = _mock_conn([])
        pool = _mock_pool(conn)

        with patch.object(stall_alert, "send_email", new=AsyncMock()) as mock_send:
            summary = await stall_alert.run_stalled_setup_check(pool)

        mock_send.assert_not_awaited()
        assert summary == {"checked": 0, "alerted": []}
