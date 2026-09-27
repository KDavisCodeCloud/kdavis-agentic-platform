"""
tests/test_demo_sandbox.py
24-gap-closure build, Phase 6 -- core/demo_sandbox.py, api/routes/demo.py,
and the structural guarantee that a demo session cannot authenticate
against any Settings/Members/Billing/Connections route.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from api.middleware.rate_limiter import limiter
from core.demo_sandbox import (
    DEMO_INCIDENTS,
    DEMO_SESSION_TOKEN_PREFIX,
    create_demo_session,
    get_or_create_demo_workspace,
    hash_demo_token,
    insert_demo_incidents,
    resolve_demo_session,
    run_demo_reset,
)


@pytest.fixture(autouse=True)
def _no_rate_limit():
    """Same convention as tests/test_email_public_routes.py's fixture of
    this name -- slowapi's @limiter.limit decorator on start_demo_session
    requires a real starlette Request, which the SimpleNamespace fakes
    used throughout this file deliberately are not."""
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


def _make_pool(fetchrow_side_effect=None, fetchval_return=None, execute_return=None):
    conn = AsyncMock()
    if fetchrow_side_effect is not None:
        conn.fetchrow = AsyncMock(side_effect=fetchrow_side_effect)
    conn.fetchval = AsyncMock(return_value=fetchval_return)
    conn.execute = AsyncMock(return_value=execute_return)

    # asyncpg's conn.transaction() is a sync call returning an async
    # context manager -- run_demo_reset's advisory-lock guard needs this
    # to actually work under `async with`, same setup as
    # tests/conftest.py's mock_db fixture.
    tx_ctx = AsyncMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=tx_ctx)
    tx_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx_ctx)
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    return pool, conn


class TestGetOrCreateDemoWorkspace:
    async def test_returns_existing_singleton_when_present(self):
        existing_id = uuid4()
        pool, conn = _make_pool(fetchrow_side_effect=[{"id": existing_id}])
        result = await get_or_create_demo_workspace(conn)
        assert result == existing_id
        # Only the SELECT ran -- never an INSERT when one already exists.
        assert conn.fetchrow.await_count == 1

    async def test_creates_one_when_none_exists(self):
        new_id = uuid4()
        pool, conn = _make_pool(fetchrow_side_effect=[None, {"id": new_id}])
        result = await get_or_create_demo_workspace(conn)
        assert result == new_id
        insert_sql = conn.fetchrow.await_args_list[1].args[0]
        assert "INSERT INTO workspaces" in insert_sql
        assert "is_demo_workspace" in insert_sql

    async def test_created_workspace_has_no_credentials_and_is_read_only(self):
        pool, conn = _make_pool(fetchrow_side_effect=[None, {"id": uuid4()}])
        await get_or_create_demo_workspace(conn)
        insert_call = conn.fetchrow.await_args_list[1]
        insert_sql = insert_call.args[0]
        # No credential column appears anywhere in the INSERT -- nothing
        # to leak even if execution somehow ran.
        for forbidden in ("aws_role_arn", "azure_client_secret", "github_pat", "encrypted_llm_key"):
            assert forbidden not in insert_sql
        assert "'read_only', 'read_only'" in insert_sql


class TestDemoIncidentDataShape:
    """Regression test for a real bug found live (2026-09-27): the
    original seed data (scripts/seed_demo_incidents.py, before it moved
    here) never carried impact/docs_url on any remediation option, so
    every GET /incidents and GET /incidents/{id} call against a seeded
    workspace 500'd inside db.models.RemediationOption's validation --
    never caught before because nothing had exercised that exact
    Pydantic-validating path against seeded data until GET /demo's live
    verification."""

    def test_every_remediation_option_satisfies_the_real_response_model(self):
        from db.models import RemediationOption

        for incident in DEMO_INCIDENTS:
            for option in incident["remediation_options"]:
                RemediationOption(**option)  # raises on any missing field


class TestInsertDemoIncidents:
    async def test_inserts_exactly_the_baseline_count(self):
        pool, conn = _make_pool()
        workspace_id = uuid4()
        count = await insert_demo_incidents(conn, workspace_id, wipe_first=False)
        assert count == len(DEMO_INCIDENTS) == 8
        insert_calls = [c for c in conn.execute.await_args_list if "INSERT INTO incidents" in c.args[0]]
        assert len(insert_calls) == 8

    async def test_every_seeded_row_is_marked_is_test(self):
        pool, conn = _make_pool()
        await insert_demo_incidents(conn, uuid4(), wipe_first=False)
        insert_calls = [c for c in conn.execute.await_args_list if "INSERT INTO incidents" in c.args[0]]
        for call in insert_calls:
            assert "is_test" in call.args[0]

    async def test_wipe_first_deletes_only_is_test_rows_for_this_workspace(self):
        pool, conn = _make_pool()
        workspace_id = uuid4()
        await insert_demo_incidents(conn, workspace_id, wipe_first=True)
        delete_calls = [c for c in conn.execute.await_args_list if "DELETE FROM incidents" in c.args[0]]
        assert len(delete_calls) == 1
        assert "is_test = true" in delete_calls[0].args[0]
        assert delete_calls[0].args[1] == workspace_id


class TestCreateDemoSession:
    async def test_mints_a_token_with_the_correct_prefix(self):
        pool, conn = _make_pool(fetchrow_side_effect=[{"id": uuid4()}], fetchval_return=8)
        token, expires_at = await create_demo_session(pool)
        assert token.startswith(DEMO_SESSION_TOKEN_PREFIX)
        assert expires_at > datetime.now(timezone.utc)

    async def test_seeds_baseline_when_workspace_has_zero_incidents(self):
        pool, conn = _make_pool(fetchrow_side_effect=[{"id": uuid4()}], fetchval_return=0)
        await create_demo_session(pool)
        insert_calls = [c for c in conn.execute.await_args_list if "INSERT INTO incidents" in c.args[0]]
        assert len(insert_calls) == 8

    async def test_does_not_reseed_when_incidents_already_exist(self):
        pool, conn = _make_pool(fetchrow_side_effect=[{"id": uuid4()}], fetchval_return=3)
        await create_demo_session(pool)
        insert_calls = [c for c in conn.execute.await_args_list if "INSERT INTO incidents" in c.args[0]]
        assert len(insert_calls) == 0

    async def test_writes_a_demo_sessions_row(self):
        pool, conn = _make_pool(fetchrow_side_effect=[{"id": uuid4()}], fetchval_return=8)
        await create_demo_session(pool)
        session_inserts = [c for c in conn.execute.await_args_list if "INSERT INTO demo_sessions" in c.args[0]]
        assert len(session_inserts) == 1


class TestResolveDemoSession:
    async def test_wrong_prefix_returns_none_without_touching_db(self):
        pool, conn = _make_pool()
        result = await resolve_demo_session(pool, "cd_ws_not_a_demo_token")
        assert result is None
        conn.fetchrow.assert_not_awaited()

    async def test_empty_token_returns_none(self):
        pool, conn = _make_pool()
        assert await resolve_demo_session(pool, "") is None

    async def test_unknown_token_returns_none(self):
        pool, conn = _make_pool(fetchrow_side_effect=[None])
        result = await resolve_demo_session(pool, "cd_demo_bogus")
        assert result is None

    async def test_expired_session_returns_none(self):
        session_row = {"workspace_id": uuid4(), "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)}
        pool, conn = _make_pool(fetchrow_side_effect=[session_row])
        result = await resolve_demo_session(pool, "cd_demo_expired")
        assert result is None

    async def test_valid_session_returns_approver_shaped_dict(self):
        workspace_id = uuid4()
        session_row = {"workspace_id": workspace_id, "expires_at": datetime.now(timezone.utc) + timedelta(hours=1)}
        workspace_row = {"id": workspace_id, "stripe_subscription_status": "active"}
        pool, conn = _make_pool(fetchrow_side_effect=[session_row, workspace_row])

        result = await resolve_demo_session(pool, "cd_demo_valid")

        assert result["id"] == workspace_id
        assert result["member_id"] is None
        assert result["member_role"] == "approver"
        assert result["is_demo_session"] is True

    async def test_token_is_hashed_before_lookup(self):
        pool, conn = _make_pool(fetchrow_side_effect=[None])
        raw = "cd_demo_plaintext_secret"
        await resolve_demo_session(pool, raw)
        looked_up_hash = conn.fetchrow.await_args_list[0].args[1]
        assert looked_up_hash == hash_demo_token(raw)
        assert looked_up_hash != raw


class TestRunDemoReset:
    async def test_wipes_and_reseeds_to_exactly_the_baseline_count(self):
        workspace_id = uuid4()
        pool, conn = _make_pool(fetchrow_side_effect=[{"id": workspace_id}], fetchval_return=True)
        await run_demo_reset(pool)
        insert_calls = [c for c in conn.execute.await_args_list if "INSERT INTO incidents" in c.args[0]]
        delete_calls = [c for c in conn.execute.await_args_list if "DELETE FROM incidents" in c.args[0]]
        assert len(insert_calls) == len(DEMO_INCIDENTS) == 8
        assert len(delete_calls) == 1

    async def test_prunes_expired_demo_sessions(self):
        pool, conn = _make_pool(fetchrow_side_effect=[{"id": uuid4()}], fetchval_return=True)
        await run_demo_reset(pool)
        prune_calls = [c for c in conn.execute.await_args_list if "DELETE FROM demo_sessions" in c.args[0]]
        assert len(prune_calls) == 1
        assert "expires_at < NOW()" in prune_calls[0].args[0]

    async def test_skips_entirely_when_another_worker_holds_the_lock(self):
        """4 --workers processes each run their own reset loop -- only one
        should ever actually wipe/reseed per tick."""
        pool, conn = _make_pool(fetchval_return=False)
        await run_demo_reset(pool)
        conn.fetchrow.assert_not_awaited()
        insert_calls = [c for c in conn.execute.await_args_list if "INSERT INTO incidents" in c.args[0]]
        assert len(insert_calls) == 0


class TestDemoIdentityCanApproveASyntheticIncident:
    """
    The actual end-to-end contract the task asked for: a demo-shaped
    workspace dict (exactly what get_workspace_or_member_or_demo hands
    approve_incident) must be able to approve one of the seeded is_test
    incidents, and the result must be the simulated-success path, never a
    real workflow resume.
    """

    async def test_demo_identity_approves_a_synthetic_incident(self):
        from api.routes import incidents
        from db.models import IncidentApproveRequest

        workspace_id = uuid4()
        incident_id = uuid4()
        incident_row = {
            "id": incident_id,
            "workspace_id": workspace_id,
            "agent_id": "agent_02_k8s_alert",
            "execution_status": "pending_approval",
            "remediation_options": [{"id": "opt_1", "title": "Increase memory limit", "description": "d"}],
            "estimated_duration_seconds": 30,
            "cloud_provider": "aws",
            "is_test": True,
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=incident_row)
        conn.execute = AsyncMock(return_value=None)
        pool_ctx = AsyncMock()
        pool_ctx.__aenter__ = AsyncMock(return_value=conn)
        pool_ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire = MagicMock(return_value=pool_ctx)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))

        demo_workspace = {
            "id": workspace_id,
            "member_id": None,
            "member_role": "approver",
            "member_email": "Demo Visitor",
            "is_demo_session": True,
        }

        from unittest.mock import patch
        with patch("api.routes.incidents.write_audit_event", new=AsyncMock()):
            result = await incidents.approve_incident(
                str(incident_id),
                IncidentApproveRequest(selected_option_id="opt_1"),
                request,
                workspace=demo_workspace,
            )

        assert result.status == "executed"
        assert "simulated" in result.message.lower()


class TestStartDemoSessionRoute:
    async def test_route_returns_a_demo_token_and_expiry(self):
        from api.routes.demo import start_demo_session

        pool, conn = _make_pool(fetchrow_side_effect=[{"id": uuid4()}], fetchval_return=8)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))

        result = await start_demo_session(request)

        assert result.demo_token.startswith(DEMO_SESSION_TOKEN_PREFIX)
        assert result.expires_at


# ── Structural guarantee: a demo session cannot authenticate against ───────
# ── Settings/Members/Billing/Connections routes ────────────────────────────

class TestDemoCredentialCannotReachProtectedRoutes:
    """
    Not a role check that could later be loosened by mistake -- these
    routers simply never import get_workspace_or_member_or_demo (or the
    private _get_workspace_by_demo_session it wraps), so an
    X-Demo-Session-Token header is never even parsed there. Verified
    directly against each router's actual registered FastAPI
    dependencies, not by re-implementing the auth logic in the test.
    """

    @pytest.mark.parametrize("module_name, router_attr", [
        ("api.routes.workspace_members", "router"),
        ("api.routes.stripe_billing", "router"),
        ("api.routes.workspace_credentials", "router"),
        ("api.routes.workspace_notifications", "router"),
        ("api.routes.workspace_ticketing", "router"),
        ("api.routes.workspaces", "router"),
    ])
    def test_router_never_depends_on_demo_credential(self, module_name, router_attr):
        import importlib

        from api.middleware.auth import get_workspace_or_member_or_demo

        module = importlib.import_module(module_name)
        router = getattr(module, router_attr)

        offending = []
        for route in router.routes:
            dependant = getattr(route, "dependant", None)
            if dependant is None:
                continue
            for dep in dependant.dependencies:
                if dep.call is get_workspace_or_member_or_demo:
                    offending.append(route.path)

        assert offending == [], (
            f"{module_name} has routes depending on get_workspace_or_member_or_demo: {offending} "
            "-- a demo session must never be able to authenticate against Settings/Members/Billing/Connections"
        )

    def test_incidents_router_has_at_least_one_route_using_the_demo_credential(self):
        """Sanity check the opposite direction -- confirms the parametrized
        check above is actually discriminating (would catch a router that
        simply has no protected routes at all) by proving the pattern DOES
        detect a real usage where one is deliberately wired."""
        from api.middleware.auth import get_workspace_or_member_or_demo
        from api.routes import incidents

        found = False
        for route in incidents.router.routes:
            dependant = getattr(route, "dependant", None)
            if dependant is None:
                continue
            for dep in dependant.dependencies:
                if dep.call is get_workspace_or_member_or_demo:
                    found = True
        assert found, "expected api/routes/incidents.py to have at least one route wired for the demo credential"
