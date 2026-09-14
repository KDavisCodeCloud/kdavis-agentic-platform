"""
tests/test_internal_workspaces.py
Tests for api/routes/internal_workspaces.py -- the admin-only workspace
list/suspend/reactivate/rotate-token endpoints (Phase 1 of the paywall
fix: these are the real revocation mechanism a paid product needs).

get_internal_user itself is already covered by tests/test_internal_agents.py
-- these tests call each handler directly with admin= injected, same
convention as every other Depends()-based route test in this suite.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.middleware.auth import _hash_token
from api.routes import internal_workspaces as iw

_ADMIN = {"id": "admin-1", "email": "kelvin@thd.example", "role": "admin"}


def _make_request(conn) -> SimpleNamespace:
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))


class TestListWorkspaces:
    async def test_returns_summaries_never_the_token(self):
        from datetime import datetime, timezone

        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": uuid4(),
                    "company_name": "Acme", "contact_email": "ops@acme.com",
                    "product_tier": "growth",
                    "stripe_subscription_status": "active",
                    "created_at": datetime.now(timezone.utc),
                }
            ]
        )
        request = _make_request(conn)

        result = await iw.list_workspaces(request, admin=_ADMIN)

        assert len(result) == 1
        assert result[0].company_name == "Acme"
        assert not hasattr(result[0], "workspace_token")


class TestGetWorkspaceDetail:
    async def test_404_when_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await iw.get_workspace_detail(str(uuid4()), request, admin=_ADMIN)
        assert exc.value.status_code == 404


class TestSuspendReactivate:
    async def test_suspend_sets_status(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"id": workspace_id, "company_name": "Acme", "contact_email": "ops@acme.com", "product_tier": "growth",
                 "stripe_subscription_status": "active", "created_at": None},
                {"id": workspace_id, "stripe_subscription_status": "suspended"},
            ]
        )
        request = _make_request(conn)

        result = await iw.suspend_workspace(str(workspace_id), request, admin=_ADMIN)

        assert result.stripe_subscription_status == "suspended"
        update_sql, new_status, bound_id = conn.fetchrow.await_args_list[1].args
        assert new_status == "suspended"
        assert bound_id == str(workspace_id)

    async def test_reactivate_sets_active(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"id": workspace_id, "company_name": "Acme", "contact_email": "ops@acme.com", "product_tier": "growth",
                 "stripe_subscription_status": "suspended", "created_at": None},
                {"id": workspace_id, "stripe_subscription_status": "active"},
            ]
        )
        request = _make_request(conn)

        result = await iw.reactivate_workspace(str(workspace_id), request, admin=_ADMIN)

        assert result.stripe_subscription_status == "active"

    async def test_suspend_404_when_workspace_missing(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await iw.suspend_workspace(str(uuid4()), request, admin=_ADMIN)
        assert exc.value.status_code == 404


class TestRotateToken:
    async def test_rotate_returns_new_raw_token_and_stores_its_hash(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"id": workspace_id, "company_name": "Acme", "contact_email": "ops@acme.com", "product_tier": "growth",
                 "stripe_subscription_status": "active", "created_at": None},
                {"id": workspace_id},
            ]
        )
        request = _make_request(conn)

        result = await iw.rotate_workspace_token(str(workspace_id), request, admin=_ADMIN)

        assert result.workspace_token.startswith("cd_ws_")
        assert "not be shown again" in result.warning

        update_sql, stored_hash, bound_id = conn.fetchrow.await_args_list[1].args
        assert stored_hash == _hash_token(result.workspace_token)
        assert stored_hash != result.workspace_token

    async def test_rotate_404_when_workspace_missing(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await iw.rotate_workspace_token(str(uuid4()), request, admin=_ADMIN)
        assert exc.value.status_code == 404


class TestSetTier:
    async def test_sets_enterprise_tier(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"id": workspace_id, "company_name": "Acme", "contact_email": "ops@acme.com", "product_tier": "starter",
                 "stripe_subscription_status": "active", "created_at": None},
                {"id": workspace_id, "product_tier": "enterprise"},
            ]
        )
        request = _make_request(conn)

        result = await iw.set_workspace_tier(
            str(workspace_id), iw.SetTierRequest(tier="enterprise"), request, admin=_ADMIN
        )

        assert result.product_tier == "enterprise"
        update_sql, new_tier, bound_id = conn.fetchrow.await_args_list[1].args
        assert new_tier == "enterprise"
        assert bound_id == str(workspace_id)

    async def test_invalid_tier_raises_400(self):
        conn = AsyncMock()
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await iw.set_workspace_tier(
                str(uuid4()), iw.SetTierRequest(tier="platinum"), request, admin=_ADMIN
            )
        assert exc.value.status_code == 400
        conn.fetchrow.assert_not_awaited()

    async def test_404_when_workspace_missing(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await iw.set_workspace_tier(
                str(uuid4()), iw.SetTierRequest(tier="growth"), request, admin=_ADMIN
            )
        assert exc.value.status_code == 404


class TestPurgeData:
    # Real data-deletion path (migration 027, GDPR/CCPA gap found in the
    # 2026-09-14 operational-readiness assessment). Two safety rails:
    # never against a live customer, and the caller must type the exact
    # company_name as confirmation.

    def _workspace_row(self, workspace_id, status="canceled", company_name="Acme"):
        return {
            "id": workspace_id, "company_name": company_name, "contact_email": "ops@acme.com",
            "product_tier": "growth", "stripe_subscription_status": status, "created_at": None,
        }

    async def test_purges_when_canceled_and_confirmed(self):
        from datetime import datetime, timezone

        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            side_effect=[
                self._workspace_row(workspace_id, status="canceled"),
                {"id": workspace_id, "data_purged_at": datetime.now(timezone.utc)},
            ]
        )
        request = _make_request(conn)

        result = await iw.purge_workspace_data(
            str(workspace_id), iw.PurgeDataRequest(confirm_company_name="Acme"), request, admin=_ADMIN,
        )

        assert result.id == str(workspace_id)
        assert result.data_purged_at
        update_sql = conn.fetchrow.await_args_list[1].args[0]
        assert "contact_email = NULL" in update_sql
        assert "github_app_installation_id = NULL" in update_sql
        assert "aws_role_arn = NULL" in update_sql
        assert "k8s_token_encrypted = NULL" in update_sql
        assert "data_purged_at = NOW()" in update_sql
        # workspace_token itself must never be nulled -- a purged workspace
        # still needs to 404/401 cleanly, not match an empty-string token
        assert "workspace_token" not in update_sql

    async def test_suspended_also_purgeable(self):
        from datetime import datetime, timezone

        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            side_effect=[
                self._workspace_row(workspace_id, status="suspended"),
                {"id": workspace_id, "data_purged_at": datetime.now(timezone.utc)},
            ]
        )
        request = _make_request(conn)

        result = await iw.purge_workspace_data(
            str(workspace_id), iw.PurgeDataRequest(confirm_company_name="Acme"), request, admin=_ADMIN,
        )
        assert result.id == str(workspace_id)

    async def test_refuses_live_customer(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._workspace_row(workspace_id, status="active"))
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await iw.purge_workspace_data(
                str(workspace_id), iw.PurgeDataRequest(confirm_company_name="Acme"), request, admin=_ADMIN,
            )
        assert exc.value.status_code == 409
        assert conn.fetchrow.await_count == 1  # never reached the UPDATE

    async def test_refuses_pending_payment(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._workspace_row(workspace_id, status="pending_payment"))
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await iw.purge_workspace_data(
                str(workspace_id), iw.PurgeDataRequest(confirm_company_name="Acme"), request, admin=_ADMIN,
            )
        assert exc.value.status_code == 409

    async def test_wrong_confirmation_name_raises_400(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._workspace_row(workspace_id, status="canceled"))
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await iw.purge_workspace_data(
                str(workspace_id), iw.PurgeDataRequest(confirm_company_name="Wrong Name"), request, admin=_ADMIN,
            )
        assert exc.value.status_code == 400
        assert conn.fetchrow.await_count == 1  # never reached the UPDATE

    async def test_404_when_workspace_missing(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await iw.purge_workspace_data(
                str(uuid4()), iw.PurgeDataRequest(confirm_company_name="Acme"), request, admin=_ADMIN,
            )
        assert exc.value.status_code == 404


class TestInviteMcpUser:
    # Phase 6 (connectivity gaps): provisions a real Supabase Auth account
    # for MCP OAuth 2.1 access. Two Supabase Admin API calls, not one --
    # invite_user_by_email only sets user_metadata; workspace_id/
    # workspace_tier/mcp_scopes (what mcp/auth/oauth.py actually trusts)
    # must go through update_user_by_id's app_metadata instead.

    def _workspace_row(self, workspace_id):
        return {
            "id": workspace_id, "company_name": "Acme", "contact_email": "ops@acme.com", "product_tier": "enterprise",
            "stripe_subscription_status": "active", "created_at": None,
        }

    async def test_invites_and_sets_app_metadata(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._workspace_row(workspace_id))
        request = _make_request(conn)

        invited_user = MagicMock(id="supabase-user-1")
        mock_client = MagicMock()
        mock_client.auth.admin.invite_user_by_email.return_value = MagicMock(user=invited_user)
        mock_client.auth.admin.update_user_by_id.return_value = MagicMock()

        with (
            patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"}),
            patch("supabase.create_client", return_value=mock_client),
        ):
            result = await iw.invite_mcp_user(
                str(workspace_id),
                iw.McpInviteRequest(email="engineer@acme.com", name="Jane Doe"),
                request,
                admin=_ADMIN,
            )

        assert result.user_id == "supabase-user-1"
        assert result.email == "engineer@acme.com"
        assert result.workspace_id == str(workspace_id)
        assert result.scopes == ["mcp:read", "mcp:write"]

        mock_client.auth.admin.invite_user_by_email.assert_called_once()
        email_arg = mock_client.auth.admin.invite_user_by_email.call_args.args[0]
        assert email_arg == "engineer@acme.com"

        mock_client.auth.admin.update_user_by_id.assert_called_once()
        user_id_arg, attrs_arg = mock_client.auth.admin.update_user_by_id.call_args.args
        assert user_id_arg == "supabase-user-1"
        assert attrs_arg["app_metadata"] == {
            "workspace_id": str(workspace_id),
            "workspace_tier": "enterprise",
            "mcp_scopes": ["mcp:read", "mcp:write"],
        }

    async def test_read_only_scope_honored(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._workspace_row(workspace_id))
        request = _make_request(conn)

        mock_client = MagicMock()
        mock_client.auth.admin.invite_user_by_email.return_value = MagicMock(user=MagicMock(id="u1"))

        with (
            patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"}),
            patch("supabase.create_client", return_value=mock_client),
        ):
            result = await iw.invite_mcp_user(
                str(workspace_id),
                iw.McpInviteRequest(email="viewer@acme.com", scopes=["mcp:read"]),
                request,
                admin=_ADMIN,
            )

        assert result.scopes == ["mcp:read"]
        _, attrs_arg = mock_client.auth.admin.update_user_by_id.call_args.args
        assert attrs_arg["app_metadata"]["mcp_scopes"] == ["mcp:read"]

    async def test_unknown_scope_raises_400(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await iw.invite_mcp_user(
                str(workspace_id),
                iw.McpInviteRequest(email="x@acme.com", scopes=["mcp:admin"]),
                request,
                admin=_ADMIN,
            )
        assert exc.value.status_code == 400
        conn.fetchrow.assert_not_awaited()

    async def test_404_when_workspace_missing(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await iw.invite_mcp_user(
                str(uuid4()), iw.McpInviteRequest(email="x@acme.com"), request, admin=_ADMIN
            )
        assert exc.value.status_code == 404

    async def test_502_when_supabase_not_configured(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._workspace_row(workspace_id))
        request = _make_request(conn)

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(HTTPException) as exc:
                await iw.invite_mcp_user(
                    str(workspace_id), iw.McpInviteRequest(email="x@acme.com"), request, admin=_ADMIN
                )
        assert exc.value.status_code == 500

    async def test_502_when_invite_fails(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._workspace_row(workspace_id))
        request = _make_request(conn)

        mock_client = MagicMock()
        mock_client.auth.admin.invite_user_by_email.side_effect = RuntimeError("already registered")

        with (
            patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"}),
            patch("supabase.create_client", return_value=mock_client),
        ):
            with pytest.raises(HTTPException) as exc:
                await iw.invite_mcp_user(
                    str(workspace_id), iw.McpInviteRequest(email="x@acme.com"), request, admin=_ADMIN
                )
        assert exc.value.status_code == 502

    async def test_502_when_app_metadata_update_fails(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=self._workspace_row(workspace_id))
        request = _make_request(conn)

        mock_client = MagicMock()
        mock_client.auth.admin.invite_user_by_email.return_value = MagicMock(user=MagicMock(id="u1"))
        mock_client.auth.admin.update_user_by_id.side_effect = RuntimeError("boom")

        with (
            patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"}),
            patch("supabase.create_client", return_value=mock_client),
        ):
            with pytest.raises(HTTPException) as exc:
                await iw.invite_mcp_user(
                    str(workspace_id), iw.McpInviteRequest(email="x@acme.com"), request, admin=_ADMIN
                )
        assert exc.value.status_code == 502
        assert "u1" in exc.value.detail  # tells the operator how to find/fix the orphaned user
