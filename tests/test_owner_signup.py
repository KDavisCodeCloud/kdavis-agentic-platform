"""
tests/test_owner_signup.py
Owner account at signup (2026-11-18): core/owner_signup.py's verification of
the founder's new Supabase account, the status-aware member auth variants in
api/middleware/auth.py, and the admin-only billing actions.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.middleware import auth
from api.routes import stripe_billing
from core import owner_signup
from core.owner_signup import OwnerVerificationError, verify_new_owner

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def _admin_returning(user):
    client = MagicMock()
    client.auth.admin.get_user_by_id = MagicMock(return_value=SimpleNamespace(user=user))
    return patch.object(owner_signup, "_supabase_admin", return_value=client)


def _user(email="ops@acme.com", age=timedelta(minutes=1)):
    return SimpleNamespace(email=email, created_at=(NOW - age).isoformat().replace("+00:00", "Z"))


class TestVerifyNewOwner:
    async def test_fresh_account_with_matching_email_passes(self):
        with _admin_returning(_user(email="OPS@acme.com")):
            await verify_new_owner(str(uuid4()), "ops@acme.com", now=NOW)

    async def test_unknown_account(self):
        with _admin_returning(None), pytest.raises(OwnerVerificationError, match="couldn't find"):
            await verify_new_owner(str(uuid4()), "ops@acme.com", now=NOW)

    async def test_lookup_error_is_treated_as_unknown(self):
        client = MagicMock()
        client.auth.admin.get_user_by_id = MagicMock(side_effect=Exception("404"))
        with patch.object(owner_signup, "_supabase_admin", return_value=client), \
             pytest.raises(OwnerVerificationError):
            await verify_new_owner(str(uuid4()), "ops@acme.com", now=NOW)

    async def test_someone_elses_account_is_refused(self):
        with _admin_returning(_user(email="victim@other.com")), pytest.raises(OwnerVerificationError, match="match"):
            await verify_new_owner(str(uuid4()), "ops@acme.com", now=NOW)

    async def test_existing_account_is_refused(self):
        with _admin_returning(_user(age=timedelta(days=3))), pytest.raises(OwnerVerificationError, match="Log in"):
            await verify_new_owner(str(uuid4()), "ops@acme.com", now=NOW)


def _request(headers):
    return SimpleNamespace(headers=headers)


class TestMemberAuthVariants:
    @pytest.mark.parametrize("dep,token_dep,blocked", [
        (auth.get_workspace_or_member_allow_pending_payment, "get_workspace_allow_pending_payment", ("canceled", "suspended")),
        (auth.get_workspace_or_member_any_status, "get_workspace_any_status", ()),
    ])
    async def test_member_session_uses_the_matching_status_rule(self, dep, token_dep, blocked):
        with patch.object(auth, "_get_workspace_member", new=AsyncMock(return_value={"id": 1})) as member:
            await dep(_request({"Authorization": "Bearer jwt"}))
        member.assert_awaited_once()
        assert member.await_args.args[1] == blocked

    @pytest.mark.parametrize("dep,token_dep", [
        (auth.get_workspace_or_member_allow_pending_payment, "get_workspace_allow_pending_payment"),
        (auth.get_workspace_or_member_any_status, "get_workspace_any_status"),
    ])
    async def test_token_header_keeps_the_token_path(self, dep, token_dep):
        with patch.object(auth, token_dep, new=AsyncMock(return_value={"id": 1})) as tok, \
             patch.object(auth, "_get_workspace_member", new=AsyncMock()) as member:
            await dep(_request({"X-Workspace-Token": "cd_ws_x"}))
        tok.assert_awaited_once()
        member.assert_not_awaited()

    async def test_plain_member_dependency_still_blocks_unpaid(self):
        with patch.object(auth, "_get_workspace_member", new=AsyncMock(return_value={})) as member:
            await auth.get_workspace_member(_request({}))
        assert "pending_payment" in member.await_args.args[1]


class TestBillingAdminOnly:
    async def test_non_admin_member_cannot_start_checkout(self):
        with pytest.raises(HTTPException) as exc:
            await stripe_billing.create_checkout_session(
                stripe_billing.CheckoutRequest(tier="growth"), MagicMock(),
                workspace={"id": uuid4(), "member_role": "approver"},
            )
        assert exc.value.status_code == 403

    async def test_non_admin_member_cannot_open_the_portal(self):
        with pytest.raises(HTTPException) as exc:
            await stripe_billing.create_customer_portal(MagicMock(), workspace={"id": uuid4(), "member_role": "viewer"})
        assert exc.value.status_code == 403

    async def test_billing_status_reachable_by_member_on_an_unpaid_workspace(self):
        out = await stripe_billing.billing_status(workspace={"product_tier": "starter",
                                                             "stripe_subscription_status": "pending_payment",
                                                             "member_role": "admin"})
        assert out.subscription_status == "pending_payment"
