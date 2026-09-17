"""
tests/test_workspace_members.py
Tests for api/routes/workspace_members.py -- Membership/SSO/RBAC/SCIM
plan, Phase A. Generalizes the admin-only mcp-invite pattern (see
tests/test_internal_workspaces.py::TestInviteMcpUser) into a self-serve
customer feature: a workspace's own admin (or the bootstrap workspace
token, before any members exist) can invite teammates.

Same test convention as test_internal_workspaces.py: call each handler
directly with workspace=/request= injected, mock the DB pool and the
Supabase admin client.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.middleware.rate_limiter import limiter
from api.routes import workspace_members as wm


@pytest.fixture(autouse=True)
def _no_rate_limit():
    """24-gap-closure Phase 4 added @limiter.limit to invite_member/
    accept_invite -- slowapi's decorator needs a real starlette Request,
    which these SimpleNamespace fakes deliberately are not (same
    convention as tests/test_workspaces.py's own fixture of this name)."""
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


def _make_request(conn, headers: dict | None = None) -> SimpleNamespace:
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    return SimpleNamespace(headers=headers or {}, app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))


def _token_workspace(workspace_id):
    """A workspace dict shaped like get_workspace()'s return -- no
    member_role key at all, the bootstrap/integration path."""
    return {"id": workspace_id}


def _member_workspace(workspace_id, role):
    """A workspace dict shaped like get_workspace_member()'s return."""
    return {"id": workspace_id, "member_id": str(uuid4()), "member_role": role, "member_email": "admin@acme.com"}


def _seat_check_rows(tier="starter", seats_used=0):
    """The two fetchrow calls assert_seat_available() makes (Phase B),
    which now run before every fetchrow sequence below."""
    return [{"product_tier": tier}, {"n": seats_used}]


class TestInviteMember:
    async def test_bootstrap_via_token_permitted(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            *_seat_check_rows(),
            None,  # no existing member with this email
            {"id": uuid4(), "email": "new@acme.com", "role": "viewer", "status": "invited",
             "invited_at": None, "joined_at": None},
        ])
        request = _make_request(conn)
        mock_client = MagicMock()

        with (
            patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"}),
            patch("supabase.create_client", return_value=mock_client),
        ):
            result = await wm.invite_member(
                wm.InviteMemberRequest(email="new@acme.com", role="viewer"),
                request,
                workspace=_token_workspace(workspace_id),
            )

        assert result.email == "new@acme.com"
        assert result.status == "invited"
        mock_client.auth.admin.invite_user_by_email.assert_called_once()

    async def test_admin_member_permitted(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            *_seat_check_rows(),
            None,
            {"id": uuid4(), "email": "new@acme.com", "role": "viewer", "status": "invited",
             "invited_at": None, "joined_at": None},
        ])
        request = _make_request(conn)
        mock_client = MagicMock()

        with (
            patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"}),
            patch("supabase.create_client", return_value=mock_client),
        ):
            result = await wm.invite_member(
                wm.InviteMemberRequest(email="new@acme.com"),
                request,
                workspace=_member_workspace(workspace_id, "admin"),
            )

        assert result.email == "new@acme.com"

    async def test_non_admin_member_rejected(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await wm.invite_member(
                wm.InviteMemberRequest(email="new@acme.com"),
                request,
                workspace=_member_workspace(workspace_id, "viewer"),
            )
        assert exc.value.status_code == 403

    async def test_invalid_role_rejected(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await wm.invite_member(
                wm.InviteMemberRequest(email="new@acme.com", role="owner"),
                request,
                workspace=_token_workspace(workspace_id),
            )
        assert exc.value.status_code == 400

    async def test_seat_limit_reached_403(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=_seat_check_rows(tier="starter", seats_used=3))
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await wm.invite_member(
                wm.InviteMemberRequest(email="new@acme.com"),
                request,
                workspace=_token_workspace(workspace_id),
            )
        assert exc.value.status_code == 403
        assert "Seat limit" in exc.value.detail

    async def test_duplicate_email_409(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[*_seat_check_rows(), {"id": uuid4()}])  # existing row found
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await wm.invite_member(
                wm.InviteMemberRequest(email="existing@acme.com"),
                request,
                workspace=_token_workspace(workspace_id),
            )
        assert exc.value.status_code == 409

    async def test_supabase_invite_failure_502(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            *_seat_check_rows(),
            None,
            {"id": uuid4(), "email": "new@acme.com", "role": "viewer", "status": "invited",
             "invited_at": None, "joined_at": None},
        ])
        request = _make_request(conn)
        mock_client = MagicMock()
        mock_client.auth.admin.invite_user_by_email.side_effect = Exception("smtp down")

        with (
            patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"}),
            patch("supabase.create_client", return_value=mock_client),
        ):
            with pytest.raises(HTTPException) as exc:
                await wm.invite_member(
                    wm.InviteMemberRequest(email="new@acme.com"),
                    request,
                    workspace=_token_workspace(workspace_id),
                )
        assert exc.value.status_code == 502

    def test_invalid_email_shape_rejected_at_model_level(self):
        with pytest.raises(ValueError):
            wm.InviteMemberRequest(email="not-an-email")


class TestListMembers:
    async def test_lists_workspace_members(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[
            {"id": uuid4(), "email": "a@acme.com", "role": "admin", "status": "active",
             "invited_at": None, "joined_at": None},
            {"id": uuid4(), "email": "b@acme.com", "role": "viewer", "status": "invited",
             "invited_at": None, "joined_at": None},
        ])
        request = _make_request(conn)

        result = await wm.list_members(request, workspace=_token_workspace(workspace_id))

        assert len(result.members) == 2
        assert result.members[0].email == "a@acme.com"
        assert result.members[1].status == "invited"

    async def test_reports_seats_used_and_max_seats(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[
            {"id": uuid4(), "email": "a@acme.com", "role": "admin", "status": "active",
             "invited_at": None, "joined_at": None},
            {"id": uuid4(), "email": "b@acme.com", "role": "viewer", "status": "invited",
             "invited_at": None, "joined_at": None},
            {"id": uuid4(), "email": "c@acme.com", "role": "viewer", "status": "deactivated",
             "invited_at": None, "joined_at": None},
        ])
        request = _make_request(conn)

        workspace = _token_workspace(workspace_id)
        workspace["product_tier"] = "starter"
        result = await wm.list_members(request, workspace=workspace)

        # deactivated doesn't count toward seats_used
        assert result.seats_used == 2
        assert result.max_seats == 3

    async def test_enterprise_reports_unlimited_max_seats(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        request = _make_request(conn)

        workspace = _token_workspace(workspace_id)
        workspace["product_tier"] = "enterprise"
        result = await wm.list_members(request, workspace=workspace)

        assert result.max_seats == -1


class TestAcceptInvite:
    def _bearer_request(self, token, conn):
        pool_ctx = AsyncMock()
        pool_ctx.__aenter__ = AsyncMock(return_value=conn)
        pool_ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=pool_ctx)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return SimpleNamespace(headers=headers, app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))

    async def test_missing_bearer_401(self):
        request = self._bearer_request(None, AsyncMock())
        with pytest.raises(HTTPException) as exc:
            await wm.accept_invite(request)
        assert exc.value.status_code == 401

    async def test_invalid_session_401(self):
        request = self._bearer_request("bogus", AsyncMock())
        mock_client = MagicMock()
        mock_client.auth.get_user.side_effect = Exception("invalid")
        with (
            patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"}),
            patch("supabase.create_client", return_value=mock_client),
        ):
            with pytest.raises(HTTPException) as exc:
                await wm.accept_invite(request)
        assert exc.value.status_code == 401

    async def test_no_pending_invite_404(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        request = self._bearer_request("tok", conn)
        mock_client = MagicMock()
        mock_client.auth.get_user.return_value = MagicMock(
            user=MagicMock(id="u1", email="ghost@acme.com")
        )
        with (
            patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"}),
            patch("supabase.create_client", return_value=mock_client),
        ):
            with pytest.raises(HTTPException) as exc:
                await wm.accept_invite(request)
        assert exc.value.status_code == 404

    async def test_accepts_and_activates(self):
        workspace_id = uuid4()
        member_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"id": member_id, "workspace_id": workspace_id, "email": "new@acme.com",
             "role": "member", "status": "invited"},
            {"id": member_id, "workspace_id": workspace_id, "email": "new@acme.com",
             "role": "member", "status": "active"},
        ])
        request = self._bearer_request("tok", conn)
        mock_client = MagicMock()
        mock_client.auth.get_user.return_value = MagicMock(
            user=MagicMock(id="supabase-user-1", email="new@acme.com")
        )
        with (
            patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"}),
            patch("supabase.create_client", return_value=mock_client),
        ):
            result = await wm.accept_invite(request)

        assert result.status == "active"
        assert result.email == "new@acme.com"
        assert result.workspace_id == str(workspace_id)

        update_sql = conn.fetchrow.await_args_list[1].args[0]
        assert "UPDATE workspace_members" in update_sql
        assert "supabase_user_id" in update_sql


class TestDeactivateMember:
    def _conn_with_row(self, row, updated_row):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[row, updated_row])
        conn.execute = AsyncMock(return_value="UPDATE 2")
        txn_ctx = AsyncMock()
        txn_ctx.__aenter__ = AsyncMock(return_value=None)
        txn_ctx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=txn_ctx)
        return conn

    async def test_admin_deactivates_member_and_unassigns_incidents(self):
        workspace_id = uuid4()
        member_id = uuid4()
        conn = self._conn_with_row(
            row={"id": member_id, "workspace_id": workspace_id, "email": "gone@acme.com", "role": "viewer", "status": "active"},
            updated_row={"id": member_id, "email": "gone@acme.com", "role": "viewer", "status": "deactivated", "invited_at": None, "joined_at": None},
        )
        request = _make_request(conn)

        with patch("api.routes.workspace_members.write_audit_event", new=AsyncMock()) as mock_audit:
            result = await wm.deactivate_member(
                str(member_id), request, workspace=_member_workspace(workspace_id, "admin"),
            )

        assert result.status == "deactivated"
        unassign_sql = conn.execute.await_args.args[0]
        assert "UPDATE incidents SET assigned_to = NULL" in unassign_sql
        mock_audit.assert_awaited_once()
        assert mock_audit.await_args.kwargs["action"] == "member_deactivated"

    async def test_non_admin_rejected(self):
        workspace_id = uuid4()
        member_id = uuid4()
        conn = AsyncMock()
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await wm.deactivate_member(str(member_id), request, workspace=_member_workspace(workspace_id, "viewer"))
        assert exc.value.status_code == 403

    async def test_cannot_deactivate_self(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        request = _make_request(conn)
        workspace = _member_workspace(workspace_id, "admin")

        with pytest.raises(HTTPException) as exc:
            await wm.deactivate_member(workspace["member_id"], request, workspace=workspace)
        assert exc.value.status_code == 400

    async def test_member_not_found_404(self):
        workspace_id = uuid4()
        member_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await wm.deactivate_member(str(member_id), request, workspace=_member_workspace(workspace_id, "admin"))
        assert exc.value.status_code == 404

    async def test_already_deactivated_409(self):
        workspace_id = uuid4()
        member_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": member_id, "workspace_id": workspace_id, "email": "x@acme.com", "role": "viewer", "status": "deactivated"})
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await wm.deactivate_member(str(member_id), request, workspace=_member_workspace(workspace_id, "admin"))
        assert exc.value.status_code == 409

    async def test_invalid_uuid_400(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await wm.deactivate_member("not-a-uuid", request, workspace=_member_workspace(workspace_id, "admin"))
        assert exc.value.status_code == 400


def _bearer_headers_with_aal(aal: str) -> dict:
    import jose.jwt as jose_jwt
    token = jose_jwt.encode({"aal": aal}, "unused-secret", algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


class TestSetRequireMfa:
    async def test_admin_enterprise_with_aal2_can_enable(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        request = _make_request(conn, headers=_bearer_headers_with_aal("aal2"))
        workspace = _member_workspace(workspace_id, "admin")
        workspace["product_tier"] = "enterprise"

        with patch("api.routes.workspace_members.write_audit_event", new=AsyncMock()):
            result = await wm.set_require_mfa(wm.RequireMfaRequest(require_mfa=True), request, workspace=workspace)

        assert result.require_mfa is True
        conn.execute.assert_awaited_once()

    async def test_enabling_without_own_aal2_session_rejected(self):
        """Self-lockout guard: an admin who hasn't stepped up their own
        session to aal2 (no verified factor enrolled/used yet) must not
        be able to flip this on and lock themselves out on their next request."""
        workspace_id = uuid4()
        conn = AsyncMock()
        request = _make_request(conn, headers=_bearer_headers_with_aal("aal1"))
        workspace = _member_workspace(workspace_id, "admin")
        workspace["product_tier"] = "enterprise"

        with pytest.raises(HTTPException) as exc:
            await wm.set_require_mfa(wm.RequireMfaRequest(require_mfa=True), request, workspace=workspace)
        assert exc.value.status_code == 400
        conn.execute.assert_not_awaited()

    async def test_disabling_never_requires_aal2(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        request = _make_request(conn)  # no Authorization header at all
        workspace = _member_workspace(workspace_id, "admin")
        workspace["product_tier"] = "enterprise"

        with patch("api.routes.workspace_members.write_audit_event", new=AsyncMock()):
            result = await wm.set_require_mfa(wm.RequireMfaRequest(require_mfa=False), request, workspace=workspace)
        assert result.require_mfa is False

    async def test_non_enterprise_rejected(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        request = _make_request(conn, headers=_bearer_headers_with_aal("aal2"))
        workspace = _member_workspace(workspace_id, "admin")
        workspace["product_tier"] = "starter"

        with pytest.raises(HTTPException) as exc:
            await wm.set_require_mfa(wm.RequireMfaRequest(require_mfa=True), request, workspace=workspace)
        assert exc.value.status_code == 403

    async def test_non_admin_rejected(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        request = _make_request(conn, headers=_bearer_headers_with_aal("aal2"))
        workspace = _member_workspace(workspace_id, "viewer")
        workspace["product_tier"] = "enterprise"

        with pytest.raises(HTTPException) as exc:
            await wm.set_require_mfa(wm.RequireMfaRequest(require_mfa=True), request, workspace=workspace)
        assert exc.value.status_code == 403
