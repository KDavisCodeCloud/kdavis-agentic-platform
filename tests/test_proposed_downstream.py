"""
'Fix Proposed' (G1) is not a resolution anywhere downstream (Kelvin, 2026-11-17):

  - no Jira / Linear / GitHub Issues / ServiceNow ticket is created or closed
  - no PagerDuty resolve event
  - no new-incident channel notification (Slack/Teams/PagerDuty trigger) fires
    on the transition either -- those only fire at incident creation
  - MTTR: the product has no MTTR computation today; the only resolution-time
    field is incidents.resolved_at (migration 038 documents MTTR as
    resolved_at - created_at). A proposed incident never gets resolved_at.
    It does once it's resolved (resolve-manually now; merge + verification
    from items 3/4), and that resolution does go to ticketing/PagerDuty.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core import ticketing
from core.hitl import HITLGate

INCIDENT = "11111111-1111-1111-1111-111111111111"
PROPOSAL = {"id": "opt_1", "proposal": True}
LIVE = {"id": "opt_1", "proposal": False}


@pytest.mark.parametrize("status", ["proposed", "failed", "pending_approval", "held", None])
def test_non_resolution_statuses_never_reach_ticketing_or_pagerduty(status):
    summary = {"incident_id": "i-1"} | ({"execution_status": status} if status else {})
    with patch("core.ticketing.notify_resolution", new=AsyncMock()) as notify, \
         patch("core.ticketing.asyncio.create_task") as create_task:
        ticketing.schedule_resolution_notification("ws-1", summary)
    notify.assert_not_called()
    create_task.assert_not_called()


@pytest.mark.parametrize("status", ["executed", "resolved_manually"])
def test_resolution_statuses_do_reach_ticketing(status):
    with patch("core.ticketing.asyncio.create_task") as create_task, \
         patch("core.ticketing.notify_resolution", new=lambda *a, **k: None):
        ticketing.schedule_resolution_notification("ws-1", {"incident_id": "i-1", "execution_status": status})
    create_task.assert_called_once()


async def test_proposed_fires_no_ticketing_pagerduty_or_channel_notification(mock_db):
    gate = HITLGate(mock_db)
    with patch("core.ticketing.schedule_resolution_notification") as resolution, \
         patch("core.ticketing.notify_resolution", new=AsyncMock()) as pd_and_tickets, \
         patch("core.notifications.notify_incident_channels", new=AsyncMock()) as channels, \
         patch.object(gate, "_fire_notification") as fire:
        status = await gate.record_execution(INCIDENT, {"status": "pr_created"}, PROPOSAL)
    assert status == "proposed"
    resolution.assert_not_called()
    pd_and_tickets.assert_not_called()
    channels.assert_not_called()
    fire.assert_not_called()


async def test_proposed_never_sets_resolved_at(mock_db):
    """resolved_at is the MTTR end time (migration 038); a proposed incident must not have one."""
    gate = HITLGate(mock_db)
    await gate.record_execution(INCIDENT, {"status": "pr_created"}, PROPOSAL)
    for call in mock_db.execute.await_args_list + mock_db.fetchrow.await_args_list:
        assert "resolved_at" not in call.args[0]


async def test_executed_still_resolves_downstream_with_status(mock_db):
    """Control: a real executed change does dispatch, tagged executed."""
    mock_db.fetchrow.return_value = {
        "workspace_id": "ws-1", "agent_id": "agent_02_k8s_alert", "resource_name": "api", "resource_group": None,
        "metric_name": None, "parsed_error": "OOM", "selected_option_id": "opt_1", "resolved_at": None,
        "cloud_provider": "aws", "severity": "high",
    }
    gate = HITLGate(mock_db)
    with patch("core.ticketing.schedule_resolution_notification") as resolution:
        await gate.record_execution(INCIDENT, {"status": "patched"}, LIVE)
    resolution.assert_called_once()
    assert resolution.call_args.args[1]["execution_status"] == "executed"
