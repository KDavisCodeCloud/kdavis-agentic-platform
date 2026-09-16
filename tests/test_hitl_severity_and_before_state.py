"""
tests/test_hitl_severity_and_before_state.py
Tests for core/hitl.py's create_incident()/mark_executed() severity and
before_state additions -- migration 042, GAPS.md 24-gap closure Phase 1.

No prior dedicated test file exercised create_incident() or
mark_executed() directly against a mocked db connection (only indirectly
through each agent's own _hitl_gate_node tests) -- this file closes that
gap for the two new params specifically, following the same plain
HITLGate(db) construction tests/test_hitl_failed_incident.py already
uses for create_failed_incident().
"""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

from core.hitl import HITLGate


def _mock_db():
    db = AsyncMock()
    db.fetchrow = AsyncMock()
    db.execute = AsyncMock(return_value=None)
    return db


class TestCreateIncidentSeverity:
    async def test_defaults_to_medium_when_not_passed(self):
        db = _mock_db()
        row_id = uuid4()
        db.fetchrow.return_value = {"id": row_id}
        gate = HITLGate(db)

        await gate.create_incident(
            workspace_id=str(uuid4()),
            agent_id="agent_01_cicd_triage",
            raw_log="log",
            parsed_error="error",
            remediation_options=[],
        )

        sql, *params = db.fetchrow.await_args.args
        assert "severity" in sql
        assert "medium" in params

    async def test_passes_through_explicit_severity(self):
        db = _mock_db()
        row_id = uuid4()
        db.fetchrow.return_value = {"id": row_id}
        gate = HITLGate(db)

        await gate.create_incident(
            workspace_id=str(uuid4()),
            agent_id="agent_02_k8s_alert",
            raw_log="log",
            parsed_error="error",
            remediation_options=[],
            severity="critical",
        )

        sql, *params = db.fetchrow.await_args.args
        assert "critical" in params

    async def test_severity_threaded_through_with_pre_generated_incident_id(self):
        """The ON CONFLICT DO NOTHING branch (pre-generated incident_id,
        used by every real agent to match the LangGraph thread_id) has
        its own separate INSERT statement -- must carry severity too."""
        db = _mock_db()
        db.fetchrow.return_value = {"id": uuid4()}
        gate = HITLGate(db)

        incident_id = str(uuid4())
        await gate.create_incident(
            incident_id=incident_id,
            workspace_id=str(uuid4()),
            agent_id="agent_08_drift_detection",
            raw_log="log",
            parsed_error="error",
            remediation_options=[],
            severity="high",
        )

        sql, *params = db.fetchrow.await_args.args
        assert "ON CONFLICT" in sql
        assert "high" in params


class TestMarkExecutedBeforeState:
    async def test_before_state_serialized_and_passed(self):
        db = _mock_db()
        db.fetchrow.return_value = {
            "workspace_id": "ws-1", "agent_id": "agent_02_k8s_alert",
            "resource_name": None, "resource_group": None, "metric_name": None,
            "parsed_error": None, "selected_option_id": None,
            "resolved_at": None, "cloud_provider": "azure", "severity": "high",
        }
        gate = HITLGate(db)

        await gate.mark_executed(
            str(uuid4()), tokens_used=100, before_state={"memory_limit": "512Mi"},
        )

        sql, *params = db.fetchrow.await_args.args
        assert "before_state" in sql
        assert json.dumps({"memory_limit": "512Mi"}) in params

    async def test_none_before_state_passes_none_not_json_null_string(self):
        """COALESCE($5, before_state) in the SQL relies on a real SQL
        NULL, not the string 'null' -- passing json.dumps(None) would
        overwrite an existing before_state with the JSON literal null."""
        db = _mock_db()
        db.fetchrow.return_value = {
            "workspace_id": "ws-1", "agent_id": "agent_01_cicd_triage",
            "resource_name": None, "resource_group": None, "metric_name": None,
            "parsed_error": None, "selected_option_id": None,
            "resolved_at": None, "cloud_provider": None, "severity": "medium",
        }
        gate = HITLGate(db)

        await gate.mark_executed(str(uuid4()), tokens_used=0)

        sql, *params = db.fetchrow.await_args.args
        assert None in params
        assert "null" not in [p for p in params if isinstance(p, str)]

    async def test_severity_from_row_reaches_ticketing_summary(self, monkeypatch):
        """_fire_ticketing_notification builds incident_summary from
        mark_executed's RETURNING row -- severity must flow through to
        core/ticketing.py's Jira priority mapping. Patches the real
        schedule_resolution_notification (core/ticketing.py's own
        function, imported locally inside _fire_ticketing_notification)
        rather than re-implementing that method, so this exercises the
        actual production code path."""
        db = _mock_db()
        db.fetchrow.return_value = {
            "workspace_id": "ws-1", "agent_id": "agent_08_drift_detection",
            "resource_name": "vm-1", "resource_group": "rg-1", "metric_name": None,
            "parsed_error": "drift detected", "selected_option_id": "opt_1",
            "resolved_at": None, "cloud_provider": "azure", "severity": "critical",
        }
        gate = HITLGate(db)

        captured = {}

        def _fake_schedule(workspace_id, incident_summary, resolved_by=None):
            captured["incident_summary"] = incident_summary

        import core.ticketing
        monkeypatch.setattr(core.ticketing, "schedule_resolution_notification", _fake_schedule)

        await gate.mark_executed(str(uuid4()), tokens_used=0)

        assert captured["incident_summary"]["severity"] == "critical"
