"""
tests/test_member_deactivation.py
core/member_deactivation.py -- the shared deactivation mechanism, reused
by api/routes/workspace_members.py's admin-triggered single deactivation
and api/routes/stripe_billing.py's automatic downgrade-enforcement
deactivation (Kelvin's item 3, 2026-09-17).
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from core.member_deactivation import deactivate_member_row


def _conn():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "id": uuid4(), "email": "gone@acme.com", "role": "viewer",
        "status": "deactivated", "invited_at": None, "joined_at": None,
    })
    conn.execute = AsyncMock(return_value="UPDATE 1")
    txn_ctx = AsyncMock()
    txn_ctx.__aenter__ = AsyncMock(return_value=None)
    txn_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn_ctx)
    return conn


class TestDeactivateMemberRow:
    async def test_updates_status_and_unassigns_incidents(self):
        conn = _conn()
        member_id = uuid4()
        workspace_id = uuid4()

        with patch("core.member_deactivation.write_audit_event", new=AsyncMock()):
            result = await deactivate_member_row(conn, workspace_id, member_id, "gone@acme.com")

        assert result["status"] == "deactivated"
        update_sql = conn.fetchrow.await_args.args[0]
        assert "SET status = 'deactivated'" in update_sql
        unassign_sql = conn.execute.await_args.args[0]
        assert "UPDATE incidents SET assigned_to = NULL" in unassign_sql
        assert conn.execute.await_args.args[1] == member_id

    async def test_writes_one_audit_event_with_default_action(self):
        conn = _conn()
        member_id = uuid4()
        workspace_id = uuid4()

        with patch("core.member_deactivation.write_audit_event", new=AsyncMock()) as mock_audit:
            await deactivate_member_row(conn, workspace_id, member_id, "gone@acme.com")

        mock_audit.assert_awaited_once()
        assert mock_audit.await_args.kwargs["action"] == "member_deactivated"
        assert mock_audit.await_args.kwargs["metadata"]["member_email"] == "gone@acme.com"

    async def test_custom_action_is_passed_through(self):
        """stripe_billing.py's downgrade path tags these distinctly from
        an admin-triggered single deactivation for audit-trail clarity."""
        conn = _conn()
        member_id = uuid4()
        workspace_id = uuid4()

        with patch("core.member_deactivation.write_audit_event", new=AsyncMock()) as mock_audit:
            await deactivate_member_row(
                conn, workspace_id, member_id, "gone@acme.com",
                action="member_deactivated_downgrade",
            )

        assert mock_audit.await_args.kwargs["action"] == "member_deactivated_downgrade"
