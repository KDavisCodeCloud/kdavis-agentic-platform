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

from unittest.mock import patch

from api.middleware.auth import (
    _hash_token,
    get_workspace,
    get_workspace_allow_pending_payment,
    get_workspace_any_status,
    get_workspace_by_scim_token,
    get_workspace_member,
    get_workspace_or_member,
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

    async def test_select_includes_migration_022_credential_columns(self):
        """Pins the real SQL shape -- migration 022 added github/aws/azure
        credential columns to workspaces, and core/workspace_credentials.py's
        build_agent_credentials() + api/routes/workspace_credentials.py both
        need get_workspace's dict to actually carry them. Existing tests here
        all bypass the real query with a hand-built fake dict (_workspace_row),
        so a dropped column here would pass every other test in this file and
        only surface as a live KeyError -- same bug class as the one found in
        kdavis-finops-agent/kdavis-compliance-agent's get_tenant() earlier."""
        row = _workspace_row("active")
        request = _make_request("cd_ws_real", row)
        await get_workspace(request)
        conn = request.app.state.db_pool.acquire.return_value.__aenter__.return_value
        sql = conn.fetchrow.await_args.args[0]
        for column in (
            "github_pat_encrypted", "github_pat_verified_at", "github_app_installation_id",
            "encrypted_github_webhook_secret", "aws_role_arn", "aws_external_id",
            "aws_role_verified_at", "azure_tenant_id", "azure_client_id",
            "azure_client_secret_encrypted", "azure_subscription_id", "azure_verified_at",
            "azure_devops_pat_verified_at", "k8s_verified_at",
            "llm_provider",  # Phase 5 -- workspaces.llm_provider, routed into call_llm()'s defaults
        ):
            assert column in sql, f"{column} missing from get_workspace's SELECT"


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


# ── get_workspace_member / get_workspace_or_member (Phase A, membership plan) ──

def _make_bearer_request(token: str | None, member_row: dict | None, workspace_row: dict | None) -> SimpleNamespace:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[member_row, workspace_row])
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return SimpleNamespace(headers=headers, app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))


def _member_row(member_id, workspace_id, role="member"):
    return {"id": member_id, "workspace_id": workspace_id, "role": role, "email": "member@acme.com"}


def _mock_supabase_user(user_id, email="member@acme.com"):
    mock_client = MagicMock()
    mock_client.auth.get_user.return_value = MagicMock(user=MagicMock(id=user_id, email=email))
    return mock_client


class TestGetWorkspaceMember:
    async def test_missing_bearer_header_401(self):
        request = _make_bearer_request(None, None, None)
        with pytest.raises(HTTPException) as exc:
            await get_workspace_member(request)
        assert exc.value.status_code == 401

    async def test_invalid_session_token_401(self):
        request = _make_bearer_request("bogus", None, None)
        mock_client = MagicMock()
        mock_client.auth.get_user.side_effect = Exception("invalid")
        with (
            patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"}),
            patch("supabase.create_client", return_value=mock_client),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_workspace_member(request)
        assert exc.value.status_code == 401

    async def test_no_active_membership_403(self):
        user_id = uuid4()
        request = _make_bearer_request("tok", None, None)  # member lookup returns None
        mock_client = _mock_supabase_user(user_id)
        with (
            patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"}),
            patch("supabase.create_client", return_value=mock_client),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_workspace_member(request)
        assert exc.value.status_code == 403

    async def test_active_member_resolves_workspace(self):
        user_id = uuid4()
        workspace_id = uuid4()
        member_id = uuid4()
        request = _make_bearer_request(
            "tok",
            _member_row(member_id, workspace_id, role="admin"),
            _workspace_row("active"),
        )
        mock_client = _mock_supabase_user(user_id)
        with (
            patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"}),
            patch("supabase.create_client", return_value=mock_client),
        ):
            result = await get_workspace_member(request)

        assert result["member_id"] == str(member_id)
        assert result["member_role"] == "admin"
        assert result["member_email"] == "member@acme.com"
        assert result["stripe_subscription_status"] == "active"

    async def test_blocked_workspace_subscription_402(self):
        user_id = uuid4()
        workspace_id = uuid4()
        member_id = uuid4()
        request = _make_bearer_request(
            "tok",
            _member_row(member_id, workspace_id),
            _workspace_row("suspended"),
        )
        mock_client = _mock_supabase_user(user_id)
        with (
            patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"}),
            patch("supabase.create_client", return_value=mock_client),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_workspace_member(request)
        assert exc.value.status_code == 402


class TestGetWorkspaceOrMember:
    async def test_prefers_token_path_when_token_header_present(self):
        request = _make_request("cd_ws_real", _workspace_row("active"))
        result = await get_workspace_or_member(request)
        assert "member_id" not in result

    async def test_falls_back_to_member_path_when_only_bearer_present(self):
        user_id = uuid4()
        workspace_id = uuid4()
        member_id = uuid4()
        request = _make_bearer_request(
            "tok",
            _member_row(member_id, workspace_id),
            _workspace_row("active"),
        )
        mock_client = _mock_supabase_user(user_id)
        with (
            patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"}),
            patch("supabase.create_client", return_value=mock_client),
        ):
            result = await get_workspace_or_member(request)
        assert result["member_id"] == str(member_id)

    async def test_no_credential_at_all_401(self):
        request = SimpleNamespace(headers={}, app=SimpleNamespace(state=SimpleNamespace(db_pool=MagicMock())))
        with pytest.raises(HTTPException) as exc:
            await get_workspace_or_member(request)
        assert exc.value.status_code == 401


# ── get_workspace_by_scim_token (Phase E, membership plan) ──────────────────

def _make_scim_request(token: str | None, row: dict | None) -> SimpleNamespace:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=row)
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return SimpleNamespace(headers=headers, app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))


class TestGetWorkspaceByScimToken:
    async def test_missing_bearer_401(self):
        request = _make_scim_request(None, None)
        with pytest.raises(HTTPException) as exc:
            await get_workspace_by_scim_token(request)
        assert exc.value.status_code == 401

    async def test_invalid_token_403(self):
        request = _make_scim_request("cd_scim_bogus", None)
        with pytest.raises(HTTPException) as exc:
            await get_workspace_by_scim_token(request)
        assert exc.value.status_code == 403

    async def test_valid_token_resolves_workspace(self):
        workspace_id = uuid4()
        request = _make_scim_request("cd_scim_real", {"workspace_id": workspace_id, "sso_status": "pending"})
        result = await get_workspace_by_scim_token(request)
        assert result["workspace_id"] == str(workspace_id)

    async def test_token_is_hashed_before_lookup(self):
        workspace_id = uuid4()
        request = _make_scim_request("cd_scim_plaintext", {"workspace_id": workspace_id, "sso_status": "pending"})
        await get_workspace_by_scim_token(request)
        conn = request.app.state.db_pool.acquire.return_value.__aenter__.return_value
        sql, bound_hash = conn.fetchrow.await_args.args
        assert bound_hash == _hash_token("cd_scim_plaintext")
        assert bound_hash != "cd_scim_plaintext"
