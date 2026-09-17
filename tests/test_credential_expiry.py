"""
tests/test_credential_expiry.py
24-gap-closure build, Phase 5 -- core/credential_expiry.py (daily
Azure SP secret / Azure DevOps PAT expiry check, migration 045).
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from core import credential_expiry


def _mock_pool(conn):
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool


def _workspace_row(**overrides):
    base = {
        "id": uuid4(), "company_name": "Acme", "contact_email": "ops@acme.com",
        "expires_at": None, "warned_at": None,
    }
    base.update(overrides)
    return base


class TestRunCredentialExpiryCheck:
    async def test_advisory_lock_not_acquired_skips_this_pass(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=False)
        pool = _mock_pool(conn)

        summary = await credential_expiry.run_credential_expiry_check(pool)

        conn.fetch.assert_not_called()
        assert summary == {"warned": 0, "critical_incidents": 0}

    async def test_expiring_within_window_sends_warning_email_once(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        soon = datetime.now(timezone.utc) + timedelta(days=5)
        row = _workspace_row(expires_at=soon, warned_at=None)
        # Two credential types checked -- Azure SP first (matches), Azure DevOps second (none).
        conn.fetch = AsyncMock(side_effect=[[row], []])
        pool = _mock_pool(conn)

        with patch("core.email.send_email", new=AsyncMock()) as mock_send:
            summary = await credential_expiry.run_credential_expiry_check(pool)

        mock_send.assert_awaited_once()
        assert mock_send.await_args.args[0] == "ops@acme.com"
        update_calls = [c for c in conn.execute.await_args_list if "azure_client_secret_expiry_warned_at" in c.args[0]]
        assert len(update_calls) == 1
        assert summary == {"warned": 1, "critical_incidents": 0}

    async def test_already_warned_is_not_re_emailed(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        soon = datetime.now(timezone.utc) + timedelta(days=5)
        row = _workspace_row(expires_at=soon, warned_at=datetime.now(timezone.utc))
        conn.fetch = AsyncMock(side_effect=[[row], []])
        pool = _mock_pool(conn)

        with patch("core.email.send_email", new=AsyncMock()) as mock_send:
            summary = await credential_expiry.run_credential_expiry_check(pool)

        mock_send.assert_not_awaited()
        assert summary == {"warned": 0, "critical_incidents": 0}

    async def test_no_contact_email_skips_send_but_still_marks_warned(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        soon = datetime.now(timezone.utc) + timedelta(days=5)
        row = _workspace_row(expires_at=soon, warned_at=None, contact_email=None)
        conn.fetch = AsyncMock(side_effect=[[row], []])
        pool = _mock_pool(conn)

        with patch("core.email.send_email", new=AsyncMock()) as mock_send:
            summary = await credential_expiry.run_credential_expiry_check(pool)

        mock_send.assert_not_awaited()
        assert summary["warned"] == 1

    async def test_already_expired_creates_critical_incident(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        past = datetime.now(timezone.utc) - timedelta(days=1)
        row = _workspace_row(expires_at=past, warned_at=None)
        conn.fetch = AsyncMock(side_effect=[[row], []])
        pool = _mock_pool(conn)

        with patch("core.hitl.HITLGate.create_incident", new=AsyncMock(return_value="inc-1")) as mock_create:
            summary = await credential_expiry.run_credential_expiry_check(pool)

        mock_create.assert_awaited_once()
        assert mock_create.await_args.kwargs["severity"] == "critical"
        assert mock_create.await_args.kwargs["workspace_id"] == str(row["id"])
        assert summary == {"warned": 0, "critical_incidents": 1}

    async def test_expired_incident_id_is_deterministic_for_dedup(self):
        """Re-running the check for an already-expired, already-flagged
        credential must compute the SAME incident_id every time so
        HITLGate.create_incident's own ON CONFLICT DO NOTHING dedups it,
        rather than this module tracking a separate 'already flagged' flag."""
        workspace_id = uuid4()
        id_1 = credential_expiry._incident_id_for(workspace_id, "azure_sp_secret")
        id_2 = credential_expiry._incident_id_for(workspace_id, "azure_sp_secret")
        id_3 = credential_expiry._incident_id_for(workspace_id, "azure_devops_pat")
        assert id_1 == id_2
        assert id_1 != id_3

    async def test_no_matching_workspaces_is_a_clean_noop(self):
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=True)
        conn.fetch = AsyncMock(side_effect=[[], []])
        pool = _mock_pool(conn)

        summary = await credential_expiry.run_credential_expiry_check(pool)

        assert summary == {"warned": 0, "critical_incidents": 0}
