"""
tests/test_incident_evidence_and_audit.py
Gap-table #6-#10: evidence on incidents, a simulated outcome that matches the
approved option's own log, a reject that reaches audit_events, and the
per-incident audit trail.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from api.routes import incidents as R
from db.models import IncidentApproveRequest


def _pool(fetchrow=None, fetch=None, fetchval=None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow)
    conn.fetch = AsyncMock(return_value=fetch or [])
    conn.fetchval = AsyncMock(return_value=fetchval)
    conn.execute = AsyncMock(return_value=None)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool, conn


def _req(pool):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))


def _demo():
    return {"id": uuid4(), "member_id": None, "member_role": "approver", "is_demo_session": True, "demo_session_id": uuid4()}


def _row(log):
    return {"id": uuid4(), "workspace_id": uuid4(), "agent_id": "agent_01_cicd_triage",
            "execution_status": "pending_approval",
            "remediation_options": [{"id": "opt_1", "title": "t", "description": "d", "impact": "low", "docs_url": "",
                                     "execution_log": log}],
            "estimated_duration_seconds": 30, "cloud_provider": None, "is_test": True}


class TestSimulatedOutcomeMatchesTheLog:
    async def _approve(self, log):
        pool, conn = _pool(fetchrow=_row(log))
        with patch.object(R, "write_audit_event", new=AsyncMock()) as audit, \
             patch.object(R, "record_demo_server_event", new=AsyncMock()):
            result = await R.approve_incident(str(uuid4()), IncidentApproveRequest(selected_option_id="opt_1"),
                                              _req(pool), workspace=_demo())
        updates = [c.args[0] for c in conn.execute.await_args_list if "UPDATE incidents" in c.args[0]]
        return result, updates, audit

    async def test_success_log_simulates_executed(self):
        result, updates, audit = await self._approve(["▶  doing", "✓  Incident resolved"])
        assert result.status == "executed"
        assert "'executed'" in updates[-1]
        assert audit.await_args.kwargs["status"] == "success"

    async def test_failure_log_simulates_failed_with_reason(self):
        result, updates, audit = await self._approve(["▶  Re-running", "✗  Not resolved: the role policy still needs the renamed bucket"])
        assert result.status == "failed"
        assert "'failed'" in updates[-1] and "failure_reason" in updates[-1]
        assert audit.await_args.kwargs["status"] == "failed"

    async def test_option_without_log_simulates_executed(self):
        result, _, _ = await self._approve(None)
        assert result.status == "executed"


class TestRejectIsAudited:
    async def test_reject_writes_audit_event_and_demo_funnel_event(self):
        pool, conn = _pool(fetchrow={"id": uuid4(), "execution_status": "pending_approval"})
        ws = _demo()
        with patch.object(R, "write_audit_event", new=AsyncMock()) as audit, \
             patch.object(R, "record_demo_server_event", new=AsyncMock()) as funnel:
            await R.reject_incident(str(uuid4()), R.IncidentRejectRequest(reason="release freeze"), _req(pool), workspace=ws)
        assert audit.await_args.kwargs["action"] == "remediation_rejected"
        assert audit.await_args.kwargs["metadata"] == {"reason": "release freeze"}
        funnel.assert_awaited_once_with(pool, "fix_rejected", ws["demo_session_id"])

    def test_reason_is_required_and_capped(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            R.IncidentRejectRequest(reason="")
        with pytest.raises(ValidationError):
            R.IncidentRejectRequest(reason="x" * 2001)


class TestAuditTrailRoute:
    async def test_returns_labelled_rows_with_only_allowed_detail(self):
        now = datetime.now(timezone.utc)
        rows = [
            {"action": "test_incident_approved_simulated", "status": "failed",
             "metadata": {"selected_option_id": "opt_2", "secret_internal": "x"}, "created_at": now},
            {"action": "remediation_rejected", "status": "rejected", "metadata": '{"reason": "freeze"}', "created_at": now},
        ]
        pool, conn = _pool(fetch=rows, fetchval=1)
        out = await R.list_incident_audit(str(uuid4()), _req(pool), workspace=_demo())
        assert out[0]["label"] == "Fix approved; simulated run failed (demo)"
        assert out[0]["detail"] == {"selected_option_id": "opt_2"}   # unknown keys never returned
        assert out[1]["label"] == "Fix rejected" and out[1]["detail"] == {"reason": "freeze"}

    async def test_404_for_another_sessions_incident(self):
        from fastapi import HTTPException
        pool, conn = _pool(fetchval=None)
        with pytest.raises(HTTPException) as exc:
            await R.list_incident_audit(str(uuid4()), _req(pool), workspace=_demo())
        assert exc.value.status_code == 404
        assert "demo_session_id = $3" in conn.fetchval.await_args.args[0]


class TestEvidenceDecoding:
    def test_decodes_string_and_list_and_none(self):
        assert R._evidence(None) is None
        assert R._evidence([]) is None
        assert R._evidence('[{"kind": "log", "title": "t", "lines": ["a"]}]')[0]["kind"] == "log"
        assert R._evidence([{"kind": "cli", "title": "t", "lines": []}])[0]["kind"] == "cli"
