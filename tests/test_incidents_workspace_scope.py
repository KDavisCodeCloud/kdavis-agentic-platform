"""
tests/test_incidents_workspace_scope.py
Phase 11, scale-readiness build.

get_incident and list_incidents (api/routes/incidents.py) are the two
customer-facing read paths wrapped in workspace_scoped_connection() --
the DB-level workspace isolation from db/migrations/031_rls_core_tables.sql.
These tests confirm the routes actually go through that helper (i.e. set
app.current_workspace_id) rather than a bare db.acquire(), using the same
mocked-pool convention as tests/test_incidents.py (no live DB available).
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from api.routes import incidents


def _mock_pool(conn):
    txn_ctx = AsyncMock()
    txn_ctx.__aenter__ = AsyncMock(return_value=None)
    txn_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn_ctx)

    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool


def _make_request(conn):
    pool = _mock_pool(conn)
    app = SimpleNamespace(state=SimpleNamespace(db_pool=pool))
    return SimpleNamespace(app=app)


def _incident_row(**overrides) -> dict:
    """Shared base row shape for get_incident/list_incidents mocks --
    24-gap-closure Phase 2 added agent_id/resource_id/resource_name/
    created_at/assigned_to/assigned_to_email to both SELECTs; every mock
    row needs all of them present now, real KeyError otherwise (caught
    exactly this way when Phase 1 first added severity). Settings →
    Policies build (migration 050) added failure_reason/failure_kind the
    same way."""
    base = {
        "id": uuid4(),
        "workspace_id": uuid4(),
        "agent_id": "agent_01_cicd_triage",
        "parsed_error": "boom",
        "remediation_options": json.dumps([]),
        "selected_option_id": None,
        "execution_status": "pending_approval",
        "estimated_duration_seconds": 30,
        "tokens_used": 0,
        "severity": "medium",
        "resource_id": None,
        "resource_name": None,
        "cloud_provider": None,
        "created_at": None,
        "assigned_to": None,
        "assigned_to_email": None,
        "failure_reason": None,
        "failure_kind": None,
    }
    base.update(overrides)
    return base


class TestGetIncidentUsesWorkspaceScope:
    async def test_sets_workspace_session_variable_before_query(self):
        workspace_id = uuid4()
        incident_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_incident_row(id=incident_id, workspace_id=workspace_id)
        )
        request = _make_request(conn)

        result = await incidents.get_incident(
            str(incident_id), request, workspace={"id": workspace_id},
        )

        # First execute() call must be set_config -- before the SELECT fetchrow.
        set_config_calls = [
            c for c in conn.execute.await_args_list
            if c.args and "set_config" in c.args[0]
        ]
        assert len(set_config_calls) == 1
        assert set_config_calls[0].args[1] == str(workspace_id)
        assert result.incident_id == str(incident_id)

    async def test_severity_included_in_response(self):
        """Migration 042, GAPS.md 24-gap closure Phase 1."""
        workspace_id = uuid4()
        incident_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_incident_row(
                id=incident_id, workspace_id=workspace_id,
                agent_id="agent_08_drift_detection", severity="critical",
            )
        )
        request = _make_request(conn)

        result = await incidents.get_incident(
            str(incident_id), request, workspace={"id": workspace_id},
        )

        assert result.severity == "critical"

    async def test_new_phase2_fields_included_in_response(self):
        """24-gap-closure Phase 2: agent_id/resource_id/resource_name/
        created_at/assigned_to/assigned_to_email were referenced
        throughout the frontend but never actually returned before this."""
        import datetime as dt

        workspace_id = uuid4()
        incident_id = uuid4()
        member_id = uuid4()
        created = dt.datetime(2026, 9, 16, 12, 0, 0, tzinfo=dt.timezone.utc)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value=_incident_row(
                id=incident_id, workspace_id=workspace_id,
                agent_id="agent_11_resource_health",
                resource_id="vm-1", resource_name="acme-prod-vm",
                created_at=created, assigned_to=member_id,
                assigned_to_email="ops@acme.com",
            )
        )
        request = _make_request(conn)

        result = await incidents.get_incident(
            str(incident_id), request, workspace={"id": workspace_id},
        )

        assert result.agent_id == "agent_11_resource_health"
        assert result.resource_id == "vm-1"
        assert result.resource_name == "acme-prod-vm"
        assert result.created_at == created.isoformat()
        assert result.assigned_to == str(member_id)
        assert result.assigned_to_email == "ops@acme.com"


class TestListIncidentsUsesWorkspaceScope:
    async def test_sets_workspace_session_variable_before_query(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        request = _make_request(conn)

        await incidents.list_incidents(request, workspace={"id": workspace_id})

        set_config_calls = [
            c for c in conn.execute.await_args_list
            if c.args and "set_config" in c.args[0]
        ]
        assert len(set_config_calls) == 1
        assert set_config_calls[0].args[1] == str(workspace_id)

    async def test_orders_by_severity_rank_then_created_at_desc(self):
        """Migration 042, GAPS.md 24-gap closure Phase 1: critical/high
        incidents must sort ahead of medium/low regardless of creation
        order. The CASE expression's ranking must stay in sync with
        core/severity.py's SEVERITY_SORT_RANK -- pinned here explicitly."""
        from core.severity import SEVERITY_SORT_RANK

        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        request = _make_request(conn)

        await incidents.list_incidents(request, workspace={"id": workspace_id})

        fetch_sql = conn.fetch.await_args.args[0]
        assert "ORDER BY" in fetch_sql
        assert "CASE i.severity" in fetch_sql
        for severity, rank in SEVERITY_SORT_RANK.items():
            assert f"WHEN '{severity}' THEN {rank}" in fetch_sql
        assert "created_at DESC" in fetch_sql

    async def test_severity_included_in_each_result(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[_incident_row(severity="low")])
        request = _make_request(conn)

        results = await incidents.list_incidents(request, workspace={"id": workspace_id})

        assert results[0].severity == "low"

    async def test_filters_build_correct_where_clauses_and_params(self):
        """24-gap-closure Phase 2: resource_id/resource_name/severity/
        agent_id/date_from/date_to all reach the query as real filters,
        not just status_filter."""
        import datetime as dt

        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        request = _make_request(conn)
        d_from = dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)
        d_to = dt.datetime(2026, 9, 16, tzinfo=dt.timezone.utc)

        await incidents.list_incidents(
            request, workspace={"id": workspace_id},
            status_filter="pending_approval", severity="critical",
            agent_id="agent_02_k8s_alert", resource_id="vm-1",
            resource_name="prod", date_from=d_from, date_to=d_to,
        )

        sql, *params = conn.fetch.await_args.args
        assert "i.execution_status = $2" in sql
        assert "i.severity = $3" in sql
        assert "i.agent_id = $4" in sql
        assert "i.resource_id = $5" in sql
        assert "i.resource_name ILIKE $6" in sql
        assert "i.created_at >= $7" in sql
        assert "i.created_at <= $8" in sql
        assert params == [
            workspace_id, "pending_approval", "critical", "agent_02_k8s_alert",
            "vm-1", "%prod%", d_from, d_to,
        ]

    async def test_assigned_to_me_resolves_to_callers_own_member_id(self):
        workspace_id = uuid4()
        member_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        request = _make_request(conn)

        await incidents.list_incidents(
            request, workspace={"id": workspace_id, "member_id": str(member_id)},
            assigned_to="me",
        )

        sql, *params = conn.fetch.await_args.args
        assert "i.assigned_to = $2" in sql
        assert params == [workspace_id, member_id]

    async def test_assigned_to_me_without_member_session_raises_400(self):
        from fastapi import HTTPException

        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        request = _make_request(conn)

        try:
            await incidents.list_incidents(
                request, workspace={"id": workspace_id}, assigned_to="me",
            )
            assert False, "expected HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 400
