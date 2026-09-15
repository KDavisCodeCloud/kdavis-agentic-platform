"""
tests/test_scim.py
Tests for api/routes/scim.py -- Membership/SSO/RBAC/SCIM plan, Phase E.

An IdP's SCIM connector provisions/deprovisions workspace_members rows
through these endpoints. Same mocked-pool convention as the rest of this
suite (no live DB, no live IdP) -- these pin the protocol shape (SCIM
User resource, ListResponse, PatchOp) and the workspace_members mapping,
not a real Okta/Azure AD round trip (that requires Phase D's Supabase
Management API registration to actually be completed first, see
GAPS.md #24/#25).
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.routes import scim


def _make_request(conn) -> SimpleNamespace:
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))


def _scim_auth(workspace_id):
    return {"workspace_id": str(workspace_id)}


def _member_row(**overrides):
    row = {
        "id": uuid4(), "email": "person@acme.com", "role": "viewer", "status": "active",
        "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
    }
    row.update(overrides)
    return row


class TestListUsers:
    async def test_lists_all_members(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[_member_row(), _member_row(email="b@acme.com")])
        request = _make_request(conn)

        result = await scim.list_users(request, scim_auth=_scim_auth(workspace_id))

        assert result["schemas"] == [scim._SCIM_LIST_SCHEMA]
        assert result["totalResults"] == 2
        assert result["Resources"][0]["userName"] == "person@acme.com"

    async def test_filter_by_username(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[_member_row(email="found@acme.com")])
        request = _make_request(conn)

        result = await scim.list_users(
            request, filter='userName eq "found@acme.com"', scim_auth=_scim_auth(workspace_id),
        )

        assert result["totalResults"] == 1
        sql, ws_id, email = conn.fetch.await_args.args
        assert email == "found@acme.com"

    async def test_inactive_member_reported_as_not_active(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[_member_row(status="deactivated")])
        request = _make_request(conn)

        result = await scim.list_users(request, scim_auth=_scim_auth(workspace_id))

        assert result["Resources"][0]["active"] is False


class TestCreateUser:
    async def test_creates_active_member(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, _member_row(email="new@acme.com")])
        request = _make_request(conn)

        result = await scim.create_user(
            scim.ScimCreateUserRequest(userName="new@acme.com", active=True),
            request, scim_auth=_scim_auth(workspace_id),
        )

        assert result["userName"] == "new@acme.com"
        assert result["active"] is True

    async def test_duplicate_username_409(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": uuid4()})  # existing found
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await scim.create_user(
                scim.ScimCreateUserRequest(userName="dup@acme.com"),
                request, scim_auth=_scim_auth(workspace_id),
            )
        assert exc.value.status_code == 409

    async def test_new_member_defaults_to_viewer_role(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, _member_row()])
        request = _make_request(conn)

        await scim.create_user(
            scim.ScimCreateUserRequest(userName="new@acme.com"),
            request, scim_auth=_scim_auth(workspace_id),
        )

        insert_sql = conn.fetchrow.await_args_list[1].args[0]
        assert "'viewer'" in insert_sql

    async def test_inactive_create_lands_deactivated(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, _member_row(status="deactivated")])
        request = _make_request(conn)

        result = await scim.create_user(
            scim.ScimCreateUserRequest(userName="new@acme.com", active=False),
            request, scim_auth=_scim_auth(workspace_id),
        )

        insert_status_param = conn.fetchrow.await_args_list[1].args[-1]
        assert insert_status_param == "deactivated"
        assert result["active"] is False


class TestGetUser:
    async def test_returns_scim_shape(self):
        workspace_id = uuid4()
        member = _member_row()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=member)
        request = _make_request(conn)

        result = await scim.get_user(str(member["id"]), request, scim_auth=_scim_auth(workspace_id))

        assert result["id"] == str(member["id"])
        assert result["schemas"] == [scim._SCIM_USER_SCHEMA]

    async def test_404_when_not_found(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await scim.get_user(str(uuid4()), request, scim_auth=_scim_auth(workspace_id))
        assert exc.value.status_code == 404

    async def test_400_on_malformed_id(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await scim.get_user("not-a-uuid", request, scim_auth=_scim_auth(workspace_id))
        assert exc.value.status_code == 400


class TestPatchUser:
    async def test_deactivates_via_path_style_patch(self):
        workspace_id = uuid4()
        member = _member_row()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[member, _member_row(id=member["id"], status="deactivated")])
        request = _make_request(conn)

        result = await scim.patch_user(
            str(member["id"]),
            scim.ScimPatchRequest(Operations=[scim.ScimPatchOperation(op="replace", path="active", value=False)]),
            request, scim_auth=_scim_auth(workspace_id),
        )

        assert result["active"] is False
        update_status_param = conn.fetchrow.await_args_list[1].args[1]
        assert update_status_param == "deactivated"

    async def test_deactivates_via_value_object_style_patch(self):
        """Some connectors send {"op":"replace","value":{"active":false}}
        instead of a top-level path -- both are valid per RFC 7644 §3.5.2."""
        workspace_id = uuid4()
        member = _member_row()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[member, _member_row(id=member["id"], status="deactivated")])
        request = _make_request(conn)

        result = await scim.patch_user(
            str(member["id"]),
            scim.ScimPatchRequest(Operations=[scim.ScimPatchOperation(op="replace", value={"active": False})]),
            request, scim_auth=_scim_auth(workspace_id),
        )

        assert result["active"] is False

    async def test_reactivates(self):
        workspace_id = uuid4()
        member = _member_row(status="deactivated")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[member, _member_row(id=member["id"], status="active")])
        request = _make_request(conn)

        result = await scim.patch_user(
            str(member["id"]),
            scim.ScimPatchRequest(Operations=[scim.ScimPatchOperation(op="replace", path="active", value=True)]),
            request, scim_auth=_scim_auth(workspace_id),
        )

        assert result["active"] is True

    async def test_unsupported_patch_attribute_400(self):
        workspace_id = uuid4()
        member = _member_row()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=member)
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await scim.patch_user(
                str(member["id"]),
                scim.ScimPatchRequest(Operations=[scim.ScimPatchOperation(op="replace", path="displayName", value="X")]),
                request, scim_auth=_scim_auth(workspace_id),
            )
        assert exc.value.status_code == 400


class TestDeleteUser:
    async def test_deactivates_not_hard_deletes(self):
        workspace_id = uuid4()
        member = _member_row()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=member)
        conn.execute = AsyncMock(return_value=None)
        request = _make_request(conn)

        await scim.delete_user(str(member["id"]), request, scim_auth=_scim_auth(workspace_id))

        update_sql = conn.execute.await_args.args[0]
        assert "UPDATE workspace_members" in update_sql
        assert "deactivated" in update_sql
        assert "DELETE FROM" not in update_sql

    async def test_404_when_not_found(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await scim.delete_user(str(uuid4()), request, scim_auth=_scim_auth(workspace_id))
        assert exc.value.status_code == 404


class TestScimErrorShape:
    def test_error_body_matches_scim_schema(self):
        exc = scim._scim_error("not found", 404)
        assert exc.status_code == 404
        assert exc.detail["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
        assert exc.detail["detail"] == "not found"
