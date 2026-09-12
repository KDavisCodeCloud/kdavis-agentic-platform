"""
tests/test_auth.py
Tests for api/middleware/auth.py's get_workspace -- the actual paywall
enforcement point. Previously untested despite being the single choke
point every protected customer route depends on.

Covers the blocked-status set (canceled, suspended, and the new
pending_payment default every new signup now starts in -- see
db/migrations/021_workspace_pending_payment.sql), the happy path, missing
token, and invalid token.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.middleware.auth import (
    _hash_token,
    get_workspace,
    get_workspace_allow_pending_payment,
    get_workspace_any_status,
)


def _make_request(token: str | None, row: dict | None) -> SimpleNamespace:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    headers = {"X-Workspace-Token": token} if token else {}
    return SimpleNamespace(headers=headers, app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))


def _workspace_row(status_val: str) -> dict:
    return {
        "id": uuid4(),
        "company_name": "Acme",
        "stripe_subscription_status": status_val,
        "product_tier": "starter",
        "encrypted_llm_key": None,
        "monthly_token_budget_usd": 50.0,
        "current_month_spend_usd": 0.0,
    }


class TestGetWorkspace:
    async def test_missing_token_401(self):
        request = _make_request(None, None)
        with pytest.raises(HTTPException) as exc:
            await get_workspace(request)
        assert exc.value.status_code == 401

    async def test_invalid_token_403(self):
        request = _make_request("cd_ws_bogus", None)
        with pytest.raises(HTTPException) as exc:
            await get_workspace(request)
        assert exc.value.status_code == 403

    async def test_active_workspace_passes(self):
        request = _make_request("cd_ws_real", _workspace_row("active"))
        result = await get_workspace(request)
        assert result["stripe_subscription_status"] == "active"

    @pytest.mark.parametrize("blocked_status", ["pending_payment", "canceled", "suspended"])
    async def test_blocked_statuses_return_402(self, blocked_status):
        request = _make_request("cd_ws_real", _workspace_row(blocked_status))
        with pytest.raises(HTTPException) as exc:
            await get_workspace(request)
        assert exc.value.status_code == 402
        assert blocked_status in exc.value.detail

    async def test_never_paid_signup_is_blocked_by_default(self):
        """The actual paywall regression test: a workspace fresh off
        POST /workspaces (before completing Stripe checkout) must never
        reach a protected route. Confirmed live 2026-09-11 that this was
        NOT the case before migration 021 -- 'trialing' was the default
        and was never blocked."""
        request = _make_request("cd_ws_real", _workspace_row("pending_payment"))
        with pytest.raises(HTTPException) as exc:
            await get_workspace(request)
        assert exc.value.status_code == 402

    async def test_token_is_hashed_before_lookup(self):
        row = _workspace_row("active")
        request = _make_request("cd_ws_plaintext", row)
        await get_workspace(request)
        conn = request.app.state.db_pool.acquire.return_value.__aenter__.return_value
        sql, bound_hash = conn.fetchrow.await_args.args
        assert bound_hash == _hash_token("cd_ws_plaintext")
        assert bound_hash != "cd_ws_plaintext"


class TestGetWorkspaceAllowPendingPayment:
    async def test_pending_payment_passes_through(self):
        """The real regression: a brand-new signup must be able to reach
        POST /billing/checkout -- the one call that gets it OUT of
        pending_payment. Found live 2026-09-11 exercising the actual
        signup -> checkout flow: get_workspace's normal block made this
        endpoint permanently unreachable for every new workspace."""
        request = _make_request("cd_ws_real", _workspace_row("pending_payment"))
        result = await get_workspace_allow_pending_payment(request)
        assert result["stripe_subscription_status"] == "pending_payment"

    @pytest.mark.parametrize("blocked_status", ["canceled", "suspended"])
    async def test_canceled_and_suspended_still_blocked(self, blocked_status):
        request = _make_request("cd_ws_real", _workspace_row(blocked_status))
        with pytest.raises(HTTPException) as exc:
            await get_workspace_allow_pending_payment(request)
        assert exc.value.status_code == 402

    async def test_active_workspace_passes(self):
        request = _make_request("cd_ws_real", _workspace_row("active"))
        result = await get_workspace_allow_pending_payment(request)
        assert result["stripe_subscription_status"] == "active"


class TestGetWorkspaceAnyStatus:
    """GET /billing/status must be readable no matter how locked the
    workspace is -- a customer can't fix pending_payment/canceled/
    suspended without first being told that's their status."""

    @pytest.mark.parametrize(
        "blocked_status", ["pending_payment", "canceled", "suspended"]
    )
    async def test_all_blocked_statuses_pass_through(self, blocked_status):
        request = _make_request("cd_ws_real", _workspace_row(blocked_status))
        result = await get_workspace_any_status(request)
        assert result["stripe_subscription_status"] == blocked_status

    async def test_active_workspace_passes(self):
        request = _make_request("cd_ws_real", _workspace_row("active"))
        result = await get_workspace_any_status(request)
        assert result["stripe_subscription_status"] == "active"

    async def test_invalid_token_still_403s(self):
        request = _make_request("cd_ws_bogus", None)
        with pytest.raises(HTTPException) as exc:
            await get_workspace_any_status(request)
        assert exc.value.status_code == 403
