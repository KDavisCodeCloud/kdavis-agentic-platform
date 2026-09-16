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


class TestGetIncidentUsesWorkspaceScope:
    async def test_sets_workspace_session_variable_before_query(self):
        workspace_id = uuid4()
        incident_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": incident_id,
                "workspace_id": workspace_id,
                "agent_id": "agent_01_cicd_triage",
                "parsed_error": "boom",
                "remediation_options": json.dumps([]),
                "selected_option_id": None,
                "execution_status": "pending_approval",
                "estimated_duration_seconds": 30,
                "tokens_used": 0,
                "severity": "medium",
            }
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
            return_value={
                "id": incident_id,
                "workspace_id": workspace_id,
                "agent_id": "agent_08_drift_detection",
                "parsed_error": "boom",
                "remediation_options": json.dumps([]),
                "selected_option_id": None,
                "execution_status": "pending_approval",
                "estimated_duration_seconds": 30,
                "tokens_used": 0,
                "severity": "critical",
            }
        )
        request = _make_request(conn)

        result = await incidents.get_incident(
            str(incident_id), request, workspace={"id": workspace_id},
        )

        assert result.severity == "critical"


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
        assert "CASE severity" in fetch_sql
        for severity, rank in SEVERITY_SORT_RANK.items():
            assert f"WHEN '{severity}' THEN {rank}" in fetch_sql
        assert "created_at DESC" in fetch_sql

    async def test_severity_included_in_each_result(self):
        workspace_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[
            {
                "id": uuid4(), "parsed_error": "boom",
                "remediation_options": json.dumps([]),
                "execution_status": "pending_approval",
                "estimated_duration_seconds": 30,
                "severity": "low",
            },
        ])
        request = _make_request(conn)

        results = await incidents.list_incidents(request, workspace={"id": workspace_id})

        assert results[0].severity == "low"
