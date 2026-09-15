"""
tests/test_hitl_notifications.py
Tests for core/hitl.py's Tier 1 webhook-build wiring: create_incident()
and create_failed_incident() fire a best-effort, fire-and-forget
notification dispatch (core/notifications.py's notify_incident_channels)
via asyncio.create_task() after a successful insert.
"""

import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from core.hitl import STATUS_FAILED, STATUS_PENDING, HITLGate


def _mock_db():
    db = AsyncMock()
    db.fetchrow = AsyncMock()
    db.execute = AsyncMock(return_value=None)
    return db


async def _drain_scheduled_tasks() -> None:
    """Let any asyncio.create_task() scheduled during the test body actually
    run to completion, without depending on a fragile fixed sleep duration.
    return_exceptions=True: a task raising is exactly what
    test_notification_failure_does_not_raise_from_create_incident exercises
    -- draining must never itself propagate that, only create_incident()
    failing to raise is under test."""
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


class TestCreateIncidentFiresNotification:
    async def test_fires_notify_incident_channels_with_pending_status(self):
        db = _mock_db()
        db.fetchrow.return_value = {"id": uuid4()}
        gate = HITLGate(db)

        with patch("core.notifications.notify_incident_channels", new=AsyncMock()) as mock_notify:
            await gate.create_incident(
                workspace_id="ws-1",
                agent_id="agent_11_resource_health",
                raw_log="log",
                parsed_error="CPU high",
                remediation_options=[],
                alert_name="HighCPU",
                resource_name="vm-1",
            )
            await _drain_scheduled_tasks()

        mock_notify.assert_awaited_once()
        workspace_id, incident_summary = mock_notify.await_args.args
        assert workspace_id == "ws-1"
        assert incident_summary["execution_status"] == STATUS_PENDING
        assert incident_summary["summary"] == "CPU high"
        assert incident_summary["alert_name"] == "HighCPU"
        assert incident_summary["resource_name"] == "vm-1"

    async def test_notification_failure_does_not_raise_from_create_incident(self):
        db = _mock_db()
        db.fetchrow.return_value = {"id": uuid4()}
        gate = HITLGate(db)

        with patch("core.notifications.notify_incident_channels", new=AsyncMock(side_effect=Exception("boom"))):
            incident_id = await gate.create_incident(
                workspace_id="ws-1", agent_id="agent_01_cicd_triage", raw_log="log",
                parsed_error="x", remediation_options=[],
            )
            await _drain_scheduled_tasks()

        assert incident_id is not None

    async def test_resumed_incident_does_not_fire_duplicate_notification(self):
        """ON CONFLICT DO NOTHING path (row is None, a resumed hitl_gate_node
        re-running its pre-interrupt code) must not notify a second time."""
        db = _mock_db()
        db.fetchrow.return_value = None
        gate = HITLGate(db)

        with patch("core.notifications.notify_incident_channels", new=AsyncMock()) as mock_notify:
            await gate.create_incident(
                workspace_id="ws-1", agent_id="agent_01_cicd_triage", raw_log="log",
                parsed_error="x", remediation_options=[], incident_id=str(uuid4()),
            )
            await _drain_scheduled_tasks()

        mock_notify.assert_not_awaited()


class TestCreateFailedIncidentFiresNotification:
    async def test_fires_notify_incident_channels_with_failed_status(self):
        db = _mock_db()
        db.fetchrow.return_value = {"id": uuid4()}
        gate = HITLGate(db)

        with patch("core.notifications.notify_incident_channels", new=AsyncMock()) as mock_notify:
            await gate.create_failed_incident(
                workspace_id="ws-1", agent_id="agent_08_drift_detection", error_message="boom",
            )
            await _drain_scheduled_tasks()

        mock_notify.assert_awaited_once()
        workspace_id, incident_summary = mock_notify.await_args.args
        assert workspace_id == "ws-1"
        assert incident_summary["execution_status"] == STATUS_FAILED
        assert incident_summary["summary"] == "boom"

    async def test_notification_failure_does_not_raise_from_create_failed_incident(self):
        db = _mock_db()
        db.fetchrow.return_value = {"id": uuid4()}
        gate = HITLGate(db)

        with patch("core.notifications.notify_incident_channels", new=AsyncMock(side_effect=Exception("boom"))):
            incident_id = await gate.create_failed_incident(
                workspace_id="ws-1", agent_id="agent_01_cicd_triage", error_message="x",
            )
            await _drain_scheduled_tasks()

        assert incident_id is not None


class TestMarkExecutedFiresTicketingNotification:
    """
    Ticketing build (2026-09-15): mark_executed() fires a best-effort
    resolution-ticketing dispatch (core/ticketing.py's
    schedule_resolution_notification) after a successful UPDATE ...
    RETURNING -- the resolution-side mirror of create_incident's
    notify_incident_channels dispatch on creation.
    """

    async def test_fires_schedule_resolution_notification_with_incident_fields(self):
        db = _mock_db()
        workspace_id = uuid4()
        db.fetchrow.return_value = {
            "workspace_id": workspace_id,
            "agent_id": "agent_06_finops",
            "resource_name": "vm-1",
            "resource_group": "rg-1",
            "metric_name": "cpu",
            "parsed_error": "CPU high",
            "selected_option_id": "opt_1",
            "resolved_at": None,
            "cloud_provider": "azure",
        }
        gate = HITLGate(db)

        with patch("core.ticketing.schedule_resolution_notification") as mock_schedule:
            await gate.mark_executed(str(uuid4()), tokens_used=10)

        mock_schedule.assert_called_once()
        called_workspace_id, incident_summary = mock_schedule.call_args.args
        assert called_workspace_id == str(workspace_id)
        assert incident_summary["agent_id"] == "agent_06_finops"
        assert incident_summary["resource_name"] == "vm-1"
        assert incident_summary["parsed_error"] == "CPU high"
        assert mock_schedule.call_args.kwargs["resolved_by"] is None

    async def test_no_returning_row_skips_ticketing_dispatch(self):
        db = _mock_db()
        db.fetchrow.return_value = None
        gate = HITLGate(db)

        with patch("core.ticketing.schedule_resolution_notification") as mock_schedule:
            await gate.mark_executed(str(uuid4()), tokens_used=0)

        mock_schedule.assert_not_called()

    async def test_ticketing_scheduling_failure_does_not_raise(self):
        db = _mock_db()
        db.fetchrow.return_value = {
            "workspace_id": uuid4(), "agent_id": "agent_01_cicd_triage",
            "resource_name": None, "resource_group": None, "metric_name": None,
            "parsed_error": "x", "selected_option_id": "opt_1", "resolved_at": None,
            "cloud_provider": None,
        }
        gate = HITLGate(db)

        with patch("core.ticketing.schedule_resolution_notification", side_effect=Exception("boom")):
            # Must complete without raising.
            await gate.mark_executed(str(uuid4()), tokens_used=0)
