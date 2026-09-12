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
from unittest.mock import AsyncMock, MagicMock
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
                    "company_name": "Acme",
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
                {"id": workspace_id, "company_name": "Acme", "product_tier": "growth",
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
                {"id": workspace_id, "company_name": "Acme", "product_tier": "growth",
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
                {"id": workspace_id, "company_name": "Acme", "product_tier": "growth",
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
