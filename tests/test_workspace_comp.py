"""
tests/test_workspace_comp.py
core/workspace_comp.py (migration 069) and POST /internal/workspaces/{id}/comp.
The real SQL was proved against Postgres (DECISIONS.md, 2026-11-18); these
pin the refusals, the audit row and the route's wiring.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.routes import internal_workspaces as iw
from api.routes import stripe_billing
from core.workspace_comp import CompError, comp_workspace


def _conn(ws_row):
    conn = MagicMock()
    txn = AsyncMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn)
    updated = {"product_tier": "growth", "stripe_subscription_status": "active",
               "comped_at": MagicMock(isoformat=lambda: "2026-11-18T00:00:00+00:00"),
               "comped_by": "admin@x", "comp_reason": "dogfood"}
    conn.fetchrow = AsyncMock(side_effect=[ws_row, updated])
    conn.execute = AsyncMock()
    return conn


def _ws(**kw):
    row = {"id": uuid4(), "company_name": "Dogfood", "product_tier": "starter",
           "stripe_subscription_status": "pending_payment", "stripe_customer_id": None}
    row.update(kw)
    return row


class TestCompWorkspace:
    async def test_comps_and_writes_an_audit_row(self):
        ws = _ws()
        conn = _conn(ws)
        out = await comp_workspace(conn, str(ws["id"]), "growth", "dogfood", "admin@x")
        assert out["product_tier"] == "growth"
        update_sql = conn.fetchrow.await_args_list[1].args[0]
        assert "stripe_subscription_status = 'active'" in update_sql and "comped_at = NOW()" in update_sql
        sql, wid, meta = conn.execute.await_args.args
        assert "workspace_comped" in sql and "$2::text::jsonb" in sql
        meta = json.loads(meta)
        assert meta == {"tier": "growth", "previous_tier": "starter",
                        "previous_subscription_status": "pending_payment",
                        "reason": "dogfood", "comped_by": "admin@x"}

    async def test_refuses_a_workspace_with_a_stripe_customer(self):
        conn = _conn(_ws(stripe_customer_id="cus_1"))
        with pytest.raises(CompError, match="Stripe customer"):
            await comp_workspace(conn, str(uuid4()), "growth", "dogfood", "admin@x")
        conn.execute.assert_not_awaited()

    @pytest.mark.parametrize("tier,reason,actor,msg", [
        ("platinum", "r", "a", "Unknown tier"),
        ("growth", "  ", "a", "reason"),
        ("growth", "r", "", "identity"),
    ])
    async def test_refuses_bad_input_before_touching_the_db(self, tier, reason, actor, msg):
        conn = _conn(_ws())
        with pytest.raises(CompError, match=msg):
            await comp_workspace(conn, str(uuid4()), tier, reason, actor)
        conn.fetchrow.assert_not_awaited()

    async def test_unknown_workspace(self):
        conn = _conn(None)
        with pytest.raises(CompError, match="not found"):
            await comp_workspace(conn, str(uuid4()), "growth", "r", "a")


class TestCompRoute:
    def _request(self, conn):
        acquire = AsyncMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock(acquire=MagicMock(return_value=acquire))
        return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))

    async def test_uses_the_admins_email_as_actor(self):
        conn = MagicMock()
        row = {"product_tier": "growth", "stripe_subscription_status": "active",
               "comped_at": MagicMock(isoformat=lambda: "t"), "comped_by": "kelvin@x", "comp_reason": "dogfood"}
        with patch.object(iw, "_get_workspace_or_404", new=AsyncMock()), \
             patch.object(iw, "comp_workspace", new=AsyncMock(return_value=row)) as comp:
            out = await iw.comp_workspace_route("ws-1", iw.CompRequest(tier="growth", reason="dogfood"),
                                                self._request(conn), admin={"email": "kelvin@x"})
        assert comp.await_args.args[1:] == ("ws-1", "growth", "dogfood", "kelvin@x")
        assert out.subscription_status == "active" and out.comped_by == "kelvin@x"

    async def test_refusal_is_a_400(self):
        with patch.object(iw, "_get_workspace_or_404", new=AsyncMock()), \
             patch.object(iw, "comp_workspace", new=AsyncMock(side_effect=CompError("nope"))):
            with pytest.raises(HTTPException) as exc:
                await iw.comp_workspace_route("ws-1", iw.CompRequest(tier="growth", reason="r"),
                                              self._request(MagicMock()), admin={"email": "a"})
        assert exc.value.status_code == 400

    def test_route_requires_a_platform_admin(self):
        import inspect
        dep = inspect.signature(iw.comp_workspace_route).parameters["admin"].default
        assert dep.dependency is iw.get_internal_user


class TestBillingStatusComped:
    async def test_comped_flag(self):
        out = await stripe_billing.billing_status(workspace={"product_tier": "growth",
                                                                 "stripe_subscription_status": "active",
                                                                 "comped_at": "2026-11-18"})
        assert out.comped is True and out.has_billing_account is False

    async def test_not_comped_by_default(self):
        out = await stripe_billing.billing_status(workspace={"product_tier": "growth",
                                                                 "stripe_subscription_status": "active"})
        assert out.comped is False
