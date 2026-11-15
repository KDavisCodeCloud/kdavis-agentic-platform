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
    demo_scope_clause,
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

    async def test_seeds_the_new_session_its_own_baseline(self):
        """Migration 059: every session gets all 8 incidents, each tagged
        with that session's id, no matter what other visitors have done."""
        session_id = uuid4()
        pool, conn = _make_pool(fetchrow_side_effect=[{"id": uuid4()}], fetchval_return=session_id)
        await create_demo_session(pool)
        insert_calls = [c for c in conn.execute.await_args_list if "INSERT INTO incidents" in c.args[0]]
        assert len(insert_calls) == len(DEMO_INCIDENTS) == 8
        # demo_session_id is $10; evidence ($11, migration 061) comes after it.
        assert all(c.args[10] == session_id for c in insert_calls)

    async def test_never_wipes_other_visitors_incidents(self):
        pool, conn = _make_pool(fetchrow_side_effect=[{"id": uuid4()}], fetchval_return=uuid4())
        await create_demo_session(pool)
        deletes = [c for c in conn.execute.await_args_list if "DELETE" in c.args[0]]
        assert deletes == []

    async def test_writes_one_demo_sessions_row_in_the_same_transaction(self):
        pool, conn = _make_pool(fetchrow_side_effect=[{"id": uuid4()}], fetchval_return=uuid4())
        await create_demo_session(pool)
        session_inserts = [c for c in conn.fetchval.await_args_list if "INSERT INTO demo_sessions" in c.args[0]]
        assert len(session_inserts) == 1
        assert "RETURNING id" in session_inserts[0].args[0]
        conn.transaction.assert_called_once()


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
        session_id = uuid4()
        session_row = {"id": session_id, "workspace_id": workspace_id, "expires_at": datetime.now(timezone.utc) + timedelta(hours=1)}
        workspace_row = {"id": workspace_id, "stripe_subscription_status": "active"}
        pool, conn = _make_pool(fetchrow_side_effect=[session_row, workspace_row])

        result = await resolve_demo_session(pool, "cd_demo_valid")

        assert result["id"] == workspace_id
        assert result["member_id"] is None
        assert result["member_role"] == "approver"
        assert result["is_demo_session"] is True
        assert result["demo_session_id"] == session_id

    async def test_token_is_hashed_before_lookup(self):
        pool, conn = _make_pool(fetchrow_side_effect=[None])
        raw = "cd_demo_plaintext_secret"
        await resolve_demo_session(pool, raw)
        looked_up_hash = conn.fetchrow.await_args_list[0].args[1]
        assert looked_up_hash == hash_demo_token(raw)
        assert looked_up_hash != raw


class TestRunDemoReset:
    async def test_never_reseeds_and_only_deletes_session_less_test_rows(self):
        """Migration 059: no shared baseline any more. Live sessions'
        incidents must survive a reset pass untouched."""
        workspace_id = uuid4()
        pool, conn = _make_pool(fetchrow_side_effect=[{"id": workspace_id}], fetchval_return=True)
        await run_demo_reset(pool)
        insert_calls = [c for c in conn.execute.await_args_list if "INSERT INTO incidents" in c.args[0]]
        delete_calls = [c for c in conn.execute.await_args_list if "DELETE FROM incidents" in c.args[0]]
        assert insert_calls == []
        assert len(delete_calls) == 1
        assert "demo_session_id IS NULL" in delete_calls[0].args[0]
        assert "is_test = true" in delete_calls[0].args[0]

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
            "demo_session_id": uuid4(),
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
        lookup = conn.fetchrow.await_args_list[0]
        assert "demo_session_id = $3" in lookup.args[0]
        assert lookup.args[3] == demo_workspace["demo_session_id"]


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


class TestDemoScopeClause:
    """Migration 059 -- the one helper every demo-reachable incidents query
    goes through."""

    def test_real_workspace_gets_no_extra_filter(self):
        assert demo_scope_clause({"id": uuid4(), "member_id": "m1"}, 3) == ("", [])

    def test_demo_session_is_filtered_to_its_own_rows(self):
        session_id = uuid4()
        sql, params = demo_scope_clause({"is_demo_session": True, "demo_session_id": session_id}, 3, column="i.demo_session_id")
        assert sql == " AND i.demo_session_id = $3"
        assert params == [session_id]

    def test_demo_identity_without_session_id_fails_closed(self):
        with pytest.raises(RuntimeError):
            demo_scope_clause({"is_demo_session": True}, 3)


class TestEveryDemoReachableIncidentRouteIsSessionScoped:
    """Structural guard: any incidents route that accepts a demo token must
    scope its incident lookup with demo_scope_clause. A future route that
    forgets would let one demo visitor read or act on another's incidents."""

    def _demo_routes(self):
        from api.middleware.auth import get_workspace_or_member_or_demo
        from api.routes.incidents import router

        routes = []
        for route in router.routes:
            deps = [d.call for d in route.dependant.dependencies]
            if get_workspace_or_member_or_demo in deps:
                routes.append(route)
        return routes

    def test_there_are_demo_reachable_routes(self):
        assert len(self._demo_routes()) >= 6

    def test_each_one_calls_demo_scope_clause(self):
        import inspect

        missing = [
            route.path
            for route in self._demo_routes()
            if "demo_scope_clause(" not in inspect.getsource(route.endpoint)
        ]
        assert missing == [], f"demo-reachable routes without session scoping: {missing}"


class TestCommentLengthCap:
    def test_comment_over_4000_chars_is_rejected(self):
        from pydantic import ValidationError

        from db.models import IncidentCommentCreateRequest

        IncidentCommentCreateRequest(body="x" * 4000)
        with pytest.raises(ValidationError):
            IncidentCommentCreateRequest(body="x" * 4001)


class TestDemoScenarioContent:
    """Gap-table #5-#9: what a buyer evaluating the demo actually sees."""

    def test_still_eight_incidents(self):
        assert len(DEMO_INCIDENTS) == 8

    def test_the_four_target_scenarios_are_present(self):
        text = " ".join(i["parsed_error"] for i in DEMO_INCIDENTS)
        assert "CrashLoopBackOff" in text and "OOMKilled" in text
        assert "0.0.0.0/0" in text and "Terraform" in text          # SG drift
        assert "AccessDenied" in text and "github-deploy-role" in text  # CI IAM mismatch
        assert "publicly readable" in text and "Block Public Access" in text  # S3 exposure

    def test_every_incident_has_valid_evidence(self):
        from db.models import EvidenceBlock

        for inc in DEMO_INCIDENTS:
            assert inc.get("evidence"), inc["resource_name"]
            for block in inc["evidence"]:
                EvidenceBlock(**block)
                assert block["lines"]

    def test_every_option_has_blast_radius_and_its_own_execution_log(self):
        from db.models import RemediationOption

        for inc in DEMO_INCIDENTS:
            for opt in inc["remediation_options"]:
                o = RemediationOption(**opt)
                assert o.blast_radius is not None, (inc["resource_name"], o.id)
                assert o.execution_log, (inc["resource_name"], o.id)

    def test_diffs_are_unified_diffs(self):
        for inc in DEMO_INCIDENTS:
            for opt in inc["remediation_options"]:
                if opt.get("diff"):
                    lines = opt["diff"].splitlines()
                    assert lines[0].startswith("--- ") and lines[1].startswith("+++ "), opt["title"]
                    assert any(l.startswith(("+", "-")) and not l.startswith(("+++", "---")) for l in lines)

    def test_execution_log_matches_its_incident(self):
        """No generic logs: each option's log names something from its own incident."""
        markers = {
            "agent_02_k8s_alert": "checkout-service",
            "agent_01_cicd_triage": "deploy-assets",
            "agent_10_dependency_patch": "lodash",
            "agent_06_finops": "i-0a1b2c3d4e5f67890",
        }
        for inc in DEMO_INCIDENTS:
            marker = markers.get(inc["agent_id"])
            if not marker:
                continue
            for opt in inc["remediation_options"]:
                assert any(marker in line for line in opt["execution_log"]), (inc["agent_id"], opt["id"])

    def test_rds_storage_growth_is_marked_irreversible(self):
        rds = [i for i in DEMO_INCIDENTS if i["agent_id"] == "agent_11_resource_health"][0]
        assert rds["remediation_options"][0]["blast_radius"]["reversible"] is False

    async def test_insert_passes_evidence_natively(self):
        pool, conn = _make_pool()
        await insert_demo_incidents(conn, uuid4(), wipe_first=False, demo_session_id=uuid4())
        inserts = [c for c in conn.execute.await_args_list if "INSERT INTO incidents" in c.args[0]]
        assert "evidence" in inserts[0].args[0]
        assert isinstance(inserts[0].args[-1], list)
