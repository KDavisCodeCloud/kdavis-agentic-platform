"""
tests/test_hitl_failed_incident.py
Tests for core/hitl.py's create_failed_incident() -- Phase 10,
scale-readiness build.

Previously, when an agent's diagnose node hit an error (LLM parse
failure, provider exhaustion, etc.), _hitl_gate_node's upstream-error
branch just logged and returned {} -- no incident row, no queryable
trace beyond a log line + Sentry capture. create_failed_incident() is
what all 11 agents now call instead, so "all failed runs for workspace
X in the last 24 hours" is a single query against incidents
(WHERE execution_status = 'failed'), not a cross-system stitch.
"""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

from core.hitl import STATUS_FAILED, HITLGate


def _mock_db():
    db = AsyncMock()
    db.fetchrow = AsyncMock()
    db.execute = AsyncMock(return_value=None)
    return db


class TestCreateFailedIncident:
    async def test_inserts_with_failed_status(self):
        db = _mock_db()
        row_id = uuid4()
        db.fetchrow.return_value = {"id": row_id}
        gate = HITLGate(db)

        incident_id = await gate.create_failed_incident(
            workspace_id=str(uuid4()),
            agent_id="agent_01_cicd_triage",
            error_message="LLM diagnosis unavailable — retry manually",
        )

        assert incident_id == str(row_id)
        db.fetchrow.assert_awaited_once()
        sql, *params = db.fetchrow.await_args.args
        assert "INSERT INTO incidents" in sql
        assert "execution_status" in sql
        # execution_status is the last positional param in the INSERT
        assert params[-1] == STATUS_FAILED

    async def test_parsed_error_is_the_error_message(self):
        db = _mock_db()
        db.fetchrow.return_value = {"id": uuid4()}
        gate = HITLGate(db)

        await gate.create_failed_incident(
            workspace_id=str(uuid4()),
            agent_id="agent_08_drift_detection",
            error_message="Manifest fetch failed: 404",
        )

        params = db.fetchrow.await_args.args[1:]
        # workspace_id, agent_id, cloud_provider, raw_log_hash, parsed_error, ...
        assert params[4] == "Manifest fetch failed: 404"

    async def test_remediation_options_is_empty_list(self):
        db = _mock_db()
        db.fetchrow.return_value = {"id": uuid4()}
        gate = HITLGate(db)

        await gate.create_failed_incident(
            workspace_id=str(uuid4()), agent_id="agent_01_cicd_triage", error_message="x",
        )

        params = db.fetchrow.await_args.args[1:]
        remediation_options_json = params[5]
        assert json.loads(remediation_options_json) == []

    async def test_no_interrupt_no_approval_needed(self):
        """Unlike create_incident (pending_approval, awaits an operator),
        create_failed_incident is a direct, one-shot INSERT -- no
        interrupt(), nothing left pending."""
        db = _mock_db()
        db.fetchrow.return_value = {"id": uuid4()}
        gate = HITLGate(db)

        # Completing without raising/hanging is the proof -- create_incident's
        # interrupt() path would need a running LangGraph context to even call;
        # this doesn't.
        incident_id = await gate.create_failed_incident(
            workspace_id=str(uuid4()), agent_id="agent_11_resource_health", error_message="x",
        )
        assert incident_id is not None

    async def test_cloud_provider_defaults_to_none(self):
        db = _mock_db()
        db.fetchrow.return_value = {"id": uuid4()}
        gate = HITLGate(db)

        await gate.create_failed_incident(
            workspace_id=str(uuid4()), agent_id="agent_01_cicd_triage", error_message="x",
        )

        params = db.fetchrow.await_args.args[1:]
        cloud_provider = params[2]
        assert cloud_provider is None

    async def test_cloud_provider_passed_through_when_given(self):
        db = _mock_db()
        db.fetchrow.return_value = {"id": uuid4()}
        gate = HITLGate(db)

        await gate.create_failed_incident(
            workspace_id=str(uuid4()), agent_id="agent_01_cicd_triage",
            error_message="x", cloud_provider="azure",
        )

        params = db.fetchrow.await_args.args[1:]
        assert params[2] == "azure"
