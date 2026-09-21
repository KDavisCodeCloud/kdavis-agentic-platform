"""
tests/test_internal_email_campaigns.py
api/routes/internal_email_campaigns.py -- the approval API the CEO
Decoded dashboard's Email Campaign queue consumes. Covers the two
compliance-critical behaviors: a sequence can't activate while any step
lacks an approved template, and editing a template resets it to
pending_approval (never stays approved after an edit).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.routes import internal_email_campaigns as iec


def _mock_request(conn):
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    request = MagicMock()
    request.app.state.db_pool = pool
    return request


_ADMIN = {"id": "u1", "email": "kelvin@theclouddecoded.com", "role": "admin"}


class TestActivateSequence:
    async def test_refuses_when_a_step_has_no_approved_template(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"key": "onboarding"})
        conn.fetch = AsyncMock(return_value=[
            {"step_number": 1, "has_approved": True},
            {"step_number": 2, "has_approved": False},
        ])
        request = _mock_request(conn)

        with pytest.raises(HTTPException) as exc:
            await iec.activate_sequence("onboarding", request, admin=_ADMIN)
        assert exc.value.status_code == 400
        assert "[2]" in exc.value.detail

        activate_calls = [c for c in conn.execute.await_args_list if "SET active = true" in c.args[0]]
        assert len(activate_calls) == 0

    async def test_activates_when_every_step_has_an_approved_template(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"key": "onboarding"})
        conn.fetch = AsyncMock(return_value=[
            {"step_number": 1, "has_approved": True},
            {"step_number": 2, "has_approved": True},
        ])
        request = _mock_request(conn)

        result = await iec.activate_sequence("onboarding", request, admin=_ADMIN)

        assert result.active is True
        activate_calls = [c for c in conn.execute.await_args_list if "SET active = true" in c.args[0]]
        assert len(activate_calls) == 1

    async def test_unknown_sequence_404s(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        request = _mock_request(conn)

        with pytest.raises(HTTPException) as exc:
            await iec.activate_sequence("nope", request, admin=_ADMIN)
        assert exc.value.status_code == 404


class TestEditTemplate:
    async def test_edit_resets_status_to_pending_approval(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={
            "key": "t1", "sequence_key": "onboarding", "step_number": 1, "delay_days": 0,
            "subject": "new subject", "preheader": None, "status": "pending_approval",
            "origin": "generated", "source_script": None, "cta_url": None, "skip_if": None,
            "approved_at": None, "approved_by": None,
        })
        request = _mock_request(conn)

        result = await iec.edit_template(
            "t1", iec.TemplateEditRequest(subject="new subject"), request, admin=_ADMIN,
        )

        sql = conn.fetchrow.await_args.args[0]
        assert "status = 'pending_approval'" in sql
        assert "approved_at = NULL" in sql
        assert result.status == "pending_approval"

    async def test_no_fields_rejected(self):
        request = _mock_request(AsyncMock())
        with pytest.raises(HTTPException) as exc:
            await iec.edit_template("t1", iec.TemplateEditRequest(), request, admin=_ADMIN)
        assert exc.value.status_code == 400


class TestApproveTemplate:
    async def test_approve_stamps_approver_and_timestamp(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={
            "key": "t1", "sequence_key": "onboarding", "step_number": 1, "delay_days": 0,
            "subject": "s", "preheader": None, "status": "approved",
            "origin": "generated", "source_script": None, "cta_url": None, "skip_if": None,
            "approved_at": None, "approved_by": "kelvin@theclouddecoded.com",
        })
        request = _mock_request(conn)

        result = await iec.approve_template("t1", request, admin=_ADMIN)

        assert result.status == "approved"
        assert conn.fetchrow.await_args.args[2] == "kelvin@theclouddecoded.com"

    async def test_missing_template_404s(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        request = _mock_request(conn)
        with pytest.raises(HTTPException) as exc:
            await iec.approve_template("nope", request, admin=_ADMIN)
        assert exc.value.status_code == 404
