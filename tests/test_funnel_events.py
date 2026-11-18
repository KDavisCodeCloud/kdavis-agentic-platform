"""
tests/test_funnel_events.py
Migration 060 -- first-party funnel events and outreach ref attribution
(core/funnel_events.py, api/routes/funnel_events.py, and the server-side
hooks in demo, incidents, workspaces and stripe_billing).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.middleware.rate_limiter import limiter
from core import funnel_events as fe


@pytest.fixture(autouse=True)
def _no_rate_limit():
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


def _pool(fetchrow=None, fetchval=None, execute="INSERT 0 1"):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow)
    conn.fetchval = AsyncMock(return_value=fetchval)
    conn.execute = AsyncMock(return_value=execute)
    conn.fetch = AsyncMock(return_value=[])
    tx = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool, conn


def _inserts(conn):
    return [c for c in conn.execute.await_args_list if "INSERT INTO cd_funnel_events" in c.args[0]]


class TestValidators:
    @pytest.mark.parametrize("ref,ok", [
        ("ab12", True), ("lead_9f3K-x", True), ("a" * 64, True),
        ("abc", False), ("a" * 65, False), ("bad ref", False), ("x<script>", False), ("", False), (None, False),
    ])
    def test_ref(self, ref, ok):
        result = fe.clean_ref(ref)
        assert (result is not None) is ok
        if ok:
            assert result == ref

    def test_non_string_inputs_are_dropped_not_crashed_on(self):
        sentinel = object()
        assert fe.clean_ref(sentinel) is None
        assert fe.clean_utm(sentinel) is None
        assert fe.clean_path(sentinel) is None
        assert fe.clean_visitor_id(sentinel) is None
        assert fe.clean_properties(sentinel) == {}

    def test_path_drops_query_and_fragment(self):
        assert fe.clean_path("/demo?ref=abcd&utm_source=x#top") == "/demo"
        assert fe.clean_path("https://evil.example/x") is None

    def test_properties_keep_only_allowed_short_scalars(self):
        out = fe.clean_properties({
            "agent_id": "agent_02_k8s_alert", "tier": "growth", "cta": "x" * 500,
            "email": "someone@example.com", "nested": {"a": 1}, "option_id": True,
        })
        assert out == {"agent_id": "agent_02_k8s_alert", "tier": "growth", "cta": "x" * 64}

    def test_utm_is_trimmed_and_capped(self):
        assert fe.clean_utm("  linkedin  ") == "linkedin"
        assert len(fe.clean_utm("x" * 300)) == 100


class TestRecordEvent:
    async def test_unknown_event_raises(self):
        pool, conn = _pool()
        with pytest.raises(ValueError):
            await fe.record_event(conn, "made_up_event")

    async def test_properties_passed_as_native_dict_for_the_jsonb_codec(self):
        pool, conn = _pool()
        await fe.record_event(conn, "demo_opened", properties={"cta": "/"})
        args = _inserts(conn)[0].args
        assert args[-1] == {"cta": "/"}
        assert "::jsonb" not in args[0]

    async def test_malformed_ref_is_stored_as_null(self):
        pool, conn = _pool()
        await fe.record_event(conn, "demo_opened", ref="not a ref!")
        assert _inserts(conn)[0].args[4] is None


class TestClientEventRoute:
    def _request(self, pool, headers=None):
        return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)), headers=headers or {})

    @pytest.mark.parametrize("event", sorted(fe.SERVER_EVENTS))
    async def test_browser_cannot_report_server_events(self, event):
        from api.routes.funnel_events import ClientEventRequest, record_client_event

        pool, conn = _pool()
        with pytest.raises(HTTPException) as exc:
            await record_client_event(ClientEventRequest(event=event), self._request(pool))
        assert exc.value.status_code == 422
        assert _inserts(conn) == []

    async def test_client_event_is_recorded_with_attribution(self):
        from api.routes.funnel_events import ClientEventRequest, record_client_event

        pool, conn = _pool()
        body = ClientEventRequest(event="signup_clicked", ref="lead_abc1", utm_campaign="li-nov",
                                  visitor_id="0f8e2c1a-1111-2222-3333-444455556666", path="/demo")
        resp = await record_client_event(body, self._request(pool))
        assert resp.status_code == 204
        args = _inserts(conn)[0].args
        assert args[2] == "signup_clicked" and args[4] == "lead_abc1" and args[7] == "li-nov"

    async def test_demo_token_is_resolved_server_side(self):
        from api.routes.funnel_events import ClientEventRequest, record_client_event

        session_id = uuid4()
        pool, conn = _pool()
        with patch("api.routes.funnel_events.resolve_demo_session",
                   new=AsyncMock(return_value={"demo_session_id": session_id})) as resolve:
            await record_client_event(ClientEventRequest(event="demo_opened"),
                                      self._request(pool, {"X-Demo-Session-Token": "cd_demo_x"}))
        resolve.assert_awaited_once()
        assert _inserts(conn)[0].args[9] == session_id

    async def test_invalid_demo_token_records_without_a_session(self):
        from api.routes.funnel_events import ClientEventRequest, record_client_event

        pool, conn = _pool()
        with patch("api.routes.funnel_events.resolve_demo_session", new=AsyncMock(return_value=None)):
            await record_client_event(ClientEventRequest(event="demo_opened"),
                                      self._request(pool, {"X-Demo-Session-Token": "cd_demo_forged"}))
        assert _inserts(conn)[0].args[9] is None


class TestInternalRoutesRequireAdmin:
    def test_every_internal_funnel_route_depends_on_get_internal_user(self):
        from api.middleware.internal_auth import get_internal_user
        from api.routes.funnel_events import router

        internal = [r for r in router.routes if r.path.startswith("/internal/")]
        assert len(internal) == 2
        for route in internal:
            assert get_internal_user in [d.call for d in route.dependant.dependencies], route.path

    def test_internal_routes_never_read_workspaces_or_incidents(self):
        """api/middleware/internal_auth.py: an internal route must never read
        the customer workspaces / incidents tables."""
        import inspect
        from api.routes import funnel_events as mod

        for fn in (mod.funnel_summary, mod.funnel_for_ref):
            src = inspect.getsource(fn)
            assert "FROM workspaces" not in src and "FROM incidents" not in src, fn.__name__

    def test_public_event_route_has_no_internal_dependency(self):
        from api.middleware.internal_auth import get_internal_user
        from api.routes.funnel_events import router

        public = [r for r in router.routes if r.path == "/events"][0]
        assert get_internal_user not in [d.call for d in public.dependant.dependencies]


class TestServerEventHelpers:
    async def test_demo_event_inherits_session_attribution(self):
        session_id = uuid4()
        pool, conn = _pool(fetchrow={"ref": "lead_abc1", "utm_source": "linkedin", "utm_medium": None, "utm_campaign": "nov"})
        await fe.record_demo_server_event(pool, "fix_approved", session_id, {"agent_id": "agent_01_cicd_triage"})
        args = _inserts(conn)[0].args
        assert args[2] == "fix_approved" and args[4] == "lead_abc1" and args[9] == session_id

    async def test_workspace_event_once_skips_when_already_recorded(self):
        pool, conn = _pool(fetchval=1)
        await fe.record_workspace_server_event(pool, "subscribed", uuid4(), once=True)
        assert _inserts(conn) == []

    async def test_workspace_event_inherits_signup_attribution(self):
        ws_id = uuid4()
        pool, conn = _pool(fetchval=None, fetchrow={
            "signup_ref": "lead_abc1", "signup_utm_source": None, "signup_utm_medium": None,
            "signup_utm_campaign": "nov", "signup_visitor_id": "0f8e2c1a-1111-2222-3333-444455556666",
        })
        await fe.record_workspace_server_event(pool, "subscribed", ws_id, {"tier": "growth"}, once=True)
        args = _inserts(conn)[0].args
        assert args[2] == "subscribed" and args[4] == "lead_abc1" and str(args[10]) == str(ws_id)

    @pytest.mark.parametrize("helper,arg", [
        (fe.record_demo_server_event, "fix_approved"),
        (fe.record_workspace_server_event, "signup_completed"),
    ])
    async def test_db_failure_is_logged_never_raised(self, helper, arg, caplog):
        pool, conn = _pool()
        conn.fetchrow = AsyncMock(side_effect=RuntimeError("db down"))
        await helper(pool, arg, uuid4())
        assert "Failed to record" in caplog.text


class TestHooks:
    async def test_demo_approval_records_fix_approved(self):
        from api.routes import incidents
        from db.models import IncidentApproveRequest

        incident_id, session_id = uuid4(), uuid4()
        row = {"id": incident_id, "workspace_id": uuid4(), "agent_id": "agent_02_k8s_alert",
               "execution_status": "pending_approval",
               "remediation_options": [{"id": "opt_1", "title": "t", "description": "d"}],
               "estimated_duration_seconds": 30, "cloud_provider": "aws", "is_test": True}
        pool, conn = _pool(fetchrow=row)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))
        demo = {"id": row["workspace_id"], "member_id": None, "member_role": "approver",
                "is_demo_session": True, "demo_session_id": session_id}
        with patch("api.routes.incidents.write_audit_event", new=AsyncMock()), \
             patch("api.routes.incidents.record_demo_server_event", new=AsyncMock()) as rec:
            await incidents.approve_incident(str(incident_id), IncidentApproveRequest(selected_option_id="opt_1"),
                                             request, workspace=demo)
        rec.assert_awaited_once_with(pool, "fix_approved", session_id,
                                     {"agent_id": "agent_02_k8s_alert", "option_id": "opt_1"})

    async def test_real_workspace_test_incident_records_nothing(self):
        from api.routes import incidents
        from db.models import IncidentApproveRequest

        row = {"id": uuid4(), "workspace_id": uuid4(), "agent_id": "system_connection_test",
               "execution_status": "pending_approval",
               "remediation_options": [{"id": "opt_1", "title": "t", "description": "d"}],
               "estimated_duration_seconds": 30, "cloud_provider": None, "is_test": True}
        pool, conn = _pool(fetchrow=row)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))
        real = {"id": row["workspace_id"], "member_id": None, "member_role": None}
        with patch("api.routes.incidents.write_audit_event", new=AsyncMock()), \
             patch("api.routes.incidents.record_demo_server_event", new=AsyncMock()) as rec:
            await incidents.approve_incident(str(row["id"]), IncidentApproveRequest(selected_option_id="opt_1"),
                                             request, workspace=real)
        rec.assert_not_awaited()

    async def test_signup_stores_attribution_and_records_signup_completed(self):
        from api.routes.workspaces import CreateWorkspaceRequest, create_workspace

        ws_id = uuid4()
        pool, conn = _pool(fetchrow={"id": ws_id})
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))
        body = CreateWorkspaceRequest(company_name="Acme", contact_email="ops@acme.io", tos_accepted=True,
                                      owner_supabase_user_id=uuid4(),
                                      ref="lead_abc1", utm_campaign="nov", visitor_id="bad id!")
        with patch("api.routes.workspaces.record_workspace_server_event", new=AsyncMock()) as rec, \
             patch("api.routes.workspaces.verify_new_owner", new=AsyncMock()):
            await create_workspace(body, request)
        insert = conn.fetchrow.await_args_list[0].args
        assert "signup_ref" in insert[0]
        assert insert[4] == "lead_abc1" and insert[7] == "nov" and insert[8] is None  # malformed visitor id dropped
        rec.assert_awaited_once_with(pool, "signup_completed", ws_id)

    async def test_signup_without_attribution_still_works(self):
        from api.routes.workspaces import CreateWorkspaceRequest, create_workspace

        pool, conn = _pool(fetchrow={"id": uuid4()})
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))
        body = CreateWorkspaceRequest(company_name="Acme", contact_email="ops@acme.io", tos_accepted=True,
                                      owner_supabase_user_id=uuid4())
        with patch("api.routes.workspaces.record_workspace_server_event", new=AsyncMock()), \
             patch("api.routes.workspaces.verify_new_owner", new=AsyncMock()):
            await create_workspace(body, request)
        assert conn.fetchrow.await_args_list[0].args[4:] == (None, None, None, None, None)

    async def test_demo_session_stores_validated_attribution(self):
        from core.demo_sandbox import create_demo_session

        pool, conn = _pool(fetchrow={"id": uuid4()}, fetchval=uuid4())
        await create_demo_session(pool, {"ref": "lead_abc1", "utm_source": "linkedin", "utm_campaign": "x" * 300})
        insert = [c for c in conn.fetchval.await_args_list if "INSERT INTO demo_sessions" in c.args[0]][0].args
        assert insert[4] == "lead_abc1" and insert[5] == "linkedin" and insert[7] == "x" * 100


class TestPrune:
    async def test_skips_when_another_worker_holds_the_lock(self):
        pool, conn = _pool(fetchval=False)
        assert await fe.prune_funnel_events(pool) == 0
        assert not [c for c in conn.execute.await_args_list if "DELETE" in c.args[0]]

    async def test_deletes_past_retention(self):
        pool, conn = _pool(fetchval=True, execute="DELETE 7")
        assert await fe.prune_funnel_events(pool) == 7
        delete = [c for c in conn.execute.await_args_list if "DELETE FROM cd_funnel_events" in c.args[0]][0]
        assert delete.args[1] == str(fe.FUNNEL_RETENTION_DAYS) == "395"
