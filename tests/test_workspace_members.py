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

from api.routes import workspace_members as wm


def _make_request(conn) -> SimpleNamespace:
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    return SimpleNamespace(headers={}, app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))


def _token_workspace(workspace_id):
    """A workspace dict shaped like get_workspace()'s return -- no
    member_role key at all, the bootstrap/integration path."""
    return {"id": workspace_id}


def _member_workspace(workspace_id, role):
    """A workspace dict shaped like get_workspace_member()'s return."""
    return {"id": workspace_id, "member_id": str(uuid4()), "member_role": role, "member_email": "admin@acme.com"}


class TestInviteMember:
    async def test_bootstrap_via_token_permitted(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            None,  # no existing member with this email
            {"id": uuid4(), "email": "new@acme.com", "role": "member", "status": "invited",
             "invited_at": None, "joined_at": None},
        ])
        request = _make_request(conn)
        mock_client = MagicMock()

        with (
            patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "svc"}),
            patch("supabase.create_client", return_value=mock_client),
        ):
            result = await wm.invite_member(
                wm.InviteMemberRequest(email="new@acme.com", role="member"),
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
            None,
            {"id": uuid4(), "email": "new@acme.com", "role": "member", "status": "invited",
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
                workspace=_member_workspace(workspace_id, "member"),
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

    async def test_duplicate_email_409(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": uuid4()})  # existing row found
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
            None,
            {"id": uuid4(), "email": "new@acme.com", "role": "member", "status": "invited",
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
            {"id": uuid4(), "email": "b@acme.com", "role": "member", "status": "invited",
             "invited_at": None, "joined_at": None},
        ])
        request = _make_request(conn)

        result = await wm.list_members(request, workspace=_token_workspace(workspace_id))

        assert len(result) == 2
        assert result[0].email == "a@acme.com"
        assert result[1].status == "invited"


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
