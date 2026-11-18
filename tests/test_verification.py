"""
G4 (Break-It Lab, item 4): post-fix verification.

A3 said "executed" while the policy was still `*:*`; A1/Z1 while CPU stayed
pegged; A2/Z2 never learned whether the fix landed. Now the live resource is
re-read and the incident closes as verified or verification_failed --
and "couldn't check" is never reported as either.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from core import verification as v
from core.live_state import LiveStateError
from core.ticketing import RESOLVED_STATUSES

STAR = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}
MINIMIZED = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject"],
                                                    "Resource": "arn:aws:s3:::cdlab/*"}]}
POLICY_ARN = "arn:aws:iam::402916653765:policy/cdlab-app"
SG_FINDING = "port 22 (SSH) open to 0.0.0.0/0"


# ── checks ──────────────────────────────────────────────────────────────────

async def test_lab_a3_policy_still_star_is_not_fixed():
    with patch("core.verification.aws_policy_default_document", new=AsyncMock(return_value=STAR)):
        out = await v.run_check({"check": "aws_policy", "policy_arn": POLICY_ARN, "expected": MINIMIZED},
                                {"aws_session": object()})
    assert out.result == v.NOT_FIXED


async def test_policy_matching_the_minimized_document_is_fixed():
    live = {"Version": "2012-10-17", "Statement": {"Effect": "Allow", "Action": "s3:GetObject",
                                                   "Resource": ["arn:aws:s3:::cdlab/*"]}}
    with patch("core.verification.aws_policy_default_document", new=AsyncMock(return_value=live)):
        out = await v.run_check({"check": "aws_policy", "policy_arn": POLICY_ARN, "expected": MINIMIZED},
                                {"aws_session": object()})
    assert out.result == v.FIXED


async def test_lab_a4_stopped_instance_is_fixed_and_running_one_is_not():
    spec = {"check": "compute_stopped", "cloud": "aws", "instance_ids": ["i-1", "i-2"]}
    with patch("core.verification.aws_instance_states",
               new=AsyncMock(return_value={"i-1": "stopped", "i-2": "stopped"})):
        assert (await v.run_check(spec, {"aws_session": object()})).result == v.FIXED
    with patch("core.verification.aws_instance_states",
               new=AsyncMock(return_value={"i-1": "stopped", "i-2": "running"})):
        out = await v.run_check(spec, {"aws_session": object()})
    assert out.result == v.NOT_FIXED and "i-2" in out.detail


async def test_lab_z5_deallocated_vm_is_fixed():
    spec = {"check": "compute_stopped", "cloud": "azure", "vm_names": ["vm-cdlab-idle"],
            "subscription_id": "s", "resource_group": "rg-cdlab"}
    with patch("core.verification.azure_vm_power_states",
               new=AsyncMock(return_value={"vm-cdlab-idle": "PowerState/deallocated"})):
        assert (await v.run_check(spec, {"azure_access_token": "t"})).result == v.FIXED


@pytest.mark.parametrize("live_findings,expected", [([SG_FINDING], v.NOT_FIXED), ([], v.FIXED),
                                                    (["port 3389 (RDP) open to 0.0.0.0/0"], v.FIXED)])
async def test_lab_a2_drift_findings(live_findings, expected):
    spec = {"check": "drift_findings", "live_fetch": {"security_group_id": "sg-1"}, "baseline_findings": [SG_FINDING]}
    with patch("agents.agent_08_drift_detection.tools.DriftTools.fetch_live",
               new=AsyncMock(return_value={"status": "ok", "findings": live_findings})):
        assert (await v.run_check(spec, {"aws_session": object()})).result == expected


async def test_drift_reader_error_is_unknown():
    spec = {"check": "drift_findings", "live_fetch": {"security_group_id": "sg-1"}, "baseline_findings": [SG_FINDING]}
    with patch("agents.agent_08_drift_detection.tools.DriftTools.fetch_live",
               new=AsyncMock(return_value={"error": "AccessDenied"})):
        out = await v.run_check(spec, {"aws_session": object()})
    assert out.result == v.UNKNOWN and "AccessDenied" in out.detail


@pytest.mark.parametrize("state,expected", [("OK", v.FIXED), ("ALARM", v.NOT_FIXED), ("INSUFFICIENT_DATA", v.UNKNOWN)])
async def test_lab_a1_cloudwatch_alarm(state, expected):
    spec = {"check": "alarm", "cloud": "aws", "alarm_arn": "arn:aws:cloudwatch:us-east-1:1:alarm:cdlab-cpu"}
    with patch("core.verification.aws_alarm_state", new=AsyncMock(return_value=state)):
        assert (await v.run_check(spec, {"aws_session": object()})).result == expected


@pytest.mark.parametrize("condition,expected", [("Resolved", v.FIXED), ("Fired", v.NOT_FIXED)])
async def test_lab_z1_azure_alert(condition, expected):
    spec = {"check": "alarm", "cloud": "azure", "alert_id": "/subscriptions/s/providers/x/alerts/a"}
    with patch("core.verification.azure_alert_condition", new=AsyncMock(return_value=condition)):
        assert (await v.run_check(spec, {"azure_access_token": "t"})).result == expected


async def test_azure_assignments_removed():
    spec = {"check": "azure_assignments_removed", "subscription_id": "s", "principal_id": "p",
            "removed_ids": ["/a/owner-1"]}
    with patch("agents.agent_05_iam_minimizer.tools.IAMMinimizeTools.get_azure_role_assignments",
               new=AsyncMock(return_value=[{"id": "/a/reader-1"}])):
        assert (await v.run_check(spec, {"azure_access_token": "t"})).result == v.FIXED
    with patch("agents.agent_05_iam_minimizer.tools.IAMMinimizeTools.get_azure_role_assignments",
               new=AsyncMock(return_value=[{"id": "/a/owner-1"}])):
        assert (await v.run_check(spec, {"azure_access_token": "t"})).result == v.NOT_FIXED


@pytest.mark.parametrize("spec", [{"check": "nope"}, None, {"check": "aws_policy"}])
async def test_unknown_or_incomplete_spec_is_unknown(spec):
    assert (await v.run_check(spec, {})).result == v.UNKNOWN


async def test_live_state_error_is_never_fixed_or_not_fixed():
    with patch("core.verification.aws_instance_states", new=AsyncMock(side_effect=LiveStateError("throttled"))):
        out = await v.run_check({"check": "compute_stopped", "cloud": "aws", "instance_ids": ["i-1"]}, {})
    assert out.result == v.UNKNOWN


# ── state transitions ───────────────────────────────────────────────────────

def _row(status="executed", deadline_in=timedelta(minutes=10), attempts=0):
    return {"id": uuid4(), "workspace_id": uuid4(), "agent_id": "agent_06_finops", "execution_status": status,
            "verification_spec": json.dumps({"check": "compute_stopped", "cloud": "aws", "instance_ids": ["i-1"]}),
            "verification_deadline": datetime.now(timezone.utc) + deadline_in, "verification_attempts": attempts}


def _conn():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"resource_name": "cdlab-app", "resolved_at": None})
    return conn


async def _verify(row, outcome, creds=None):
    conn = _conn()
    with patch("core.verification.run_check", new=AsyncMock(return_value=outcome)), \
         patch("core.ticketing.schedule_resolution_notification") as notify:
        await v._verify_one(conn, row, AsyncMock(return_value=creds if creds is not None else {"aws_session": 1}))
    return conn, notify


def _updates(conn):
    return [c for c in conn.execute.await_args_list if c.args[0].startswith("UPDATE incidents")]


async def test_fixed_closes_as_verified_guarded_on_the_prior_status():
    row = _row()
    conn, notify = await _verify(row, v.Outcome(v.FIXED, "stopped"))
    (update,) = _updates(conn)
    assert update.args[1] == "verified" and "verified_at = NOW()" in update.args[0]
    assert "resolved_at = COALESCE(resolved_at, NOW())" in update.args[0]
    assert "AND execution_status = $4" in update.args[0] and update.args[4] == "executed"
    notify.assert_not_called()  # an executed action already notified when it ran


async def test_merged_fix_verified_closes_tickets_now():
    conn, notify = await _verify(_row("fix_merged"), v.Outcome(v.FIXED, "gone"))
    assert notify.call_args.args[1]["execution_status"] == "verified"
    assert "verified" in RESOLVED_STATUSES


async def test_not_fixed_before_deadline_retries():
    conn, _ = await _verify(_row(), v.Outcome(v.NOT_FIXED, "running"))
    (update,) = _updates(conn)
    assert "verification_next_at = NOW() + $1" in update.args[0] and update.args[1] == v.LIVE_RETRY
    assert "execution_status" not in update.args[0]


async def test_not_fixed_at_deadline_is_verification_failed():
    conn, notify = await _verify(_row(deadline_in=timedelta(seconds=-1)), v.Outcome(v.NOT_FIXED, "still *:*"))
    (update,) = _updates(conn)
    assert update.args[1] == "verification_failed"
    assert json.loads(update.args[2])["detail"] == "still *:*"
    notify.assert_not_called()
    assert "verification_failed" not in RESOLVED_STATUSES


async def test_unknown_at_deadline_stops_without_changing_status():
    conn, _ = await _verify(_row(deadline_in=timedelta(seconds=-1)), v.Outcome(v.UNKNOWN, "AccessDenied"))
    (update,) = _updates(conn)
    assert "execution_status" not in update.args[0] and "verification_next_at = NULL" in update.args[0]
    assert json.loads(update.args[1])["outcome"] == "unverifiable"


async def test_merged_fix_retries_on_the_slower_cadence():
    conn, _ = await _verify(_row("fix_merged"), v.Outcome(v.NOT_FIXED, "pipeline hasn't applied"))
    assert _updates(conn)[0].args[1] == v.MERGED_RETRY


async def test_missing_credentials_is_unknown_never_not_fixed():
    conn = _conn()
    failing = AsyncMock(side_effect=RuntimeError("role assumption failed"))
    await v._verify_one(conn, _row(deadline_in=timedelta(seconds=-1)), failing)
    (update,) = _updates(conn)
    assert "execution_status" not in update.args[0]
    assert json.loads(update.args[1])["outcome"] == "unverifiable"


async def test_incident_resolved_by_hand_meanwhile_is_just_unscheduled():
    conn, _ = await _verify(_row("resolved_manually"), v.Outcome(v.FIXED, "x"))
    (update,) = _updates(conn)
    assert update.args[0] == "UPDATE incidents SET verification_next_at = NULL WHERE id = $1"


async def test_pass_claims_due_rows_with_skip_locked():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    tx = MagicMock(); tx.__aenter__ = AsyncMock(); tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    ctx = MagicMock(); ctx.__aenter__ = AsyncMock(return_value=conn); ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock(); pool.acquire = MagicMock(return_value=ctx)
    assert await v.run_verification_pass(pool, AsyncMock()) == 0
    sql = conn.fetch.await_args.args[0]
    assert "FOR UPDATE SKIP LOCKED" in sql and "verification_next_at <= NOW()" in sql


# ── recording specs from the real complete node ─────────────────────────────

INC = "aaaaaaaa-0000-4000-8000-000000000003"


async def _complete(agent, state, result, option, mock_db, workspace_id, mock_router):
    from tests.test_execution_outcome import _make
    wf = _make(agent, mock_db, workspace_id, mock_router)
    wf.db = MagicMock(); wf.db.execute = AsyncMock()
    with patch.object(wf.hitl, "mark_executed", new=AsyncMock()), patch.object(wf.hitl, "mark_failed", new=AsyncMock()):
        await wf._complete_node({"incident_id": INC, "selected_option": option, "execution_result": result, **state})
    return [c for c in wf.db.execute.await_args_list if "verification_spec" in c.args[0]]


async def test_lab_a3_agent05_records_policy_check_and_schedules_it(mock_db, workspace_id, mock_router):
    calls = await _complete("agent_05", {"cloud_provider": "aws", "resource_scope": POLICY_ARN,
                                         "minimized_policy": MINIMIZED},
                            {"status": "policy_updated"}, {"id": "opt_1", "proposal": False},
                            mock_db, workspace_id, mock_router)
    (call,) = calls
    spec = json.loads(call.args[1])
    assert spec == {"check": "aws_policy", "policy_arn": POLICY_ARN, "expected": MINIMIZED}
    assert "verification_next_at = NOW() + $2" in call.args[0]  # executed -> checked now


async def test_proposal_records_spec_but_waits_for_the_merge(mock_db, workspace_id, mock_router):
    calls = await _complete("agent_05", {"cloud_provider": "aws", "resource_scope": POLICY_ARN,
                                         "minimized_policy": MINIMIZED},
                            {"status": "pr_opened"}, {"id": "opt_2", "proposal": True},
                            mock_db, workspace_id, mock_router)
    (call,) = calls
    assert "verification_next_at" not in call.args[0]


async def test_lab_a1_agent11_records_the_alarm(mock_db, workspace_id, mock_router):
    arn = "arn:aws:cloudwatch:us-east-1:402916653765:alarm:cdlab-cpu"
    calls = await _complete("agent_11", {"webhook_payload": {"cloudwatch_alarm": {"AlarmArn": arn}}},
                            {"status": "pr_created"}, {"id": "opt_1", "proposal": True},
                            mock_db, workspace_id, mock_router)
    assert json.loads(calls[0].args[1]) == {"check": "alarm", "cloud": "aws", "alarm_arn": arn}


async def test_lab_a2_agent08_records_live_findings(mock_db, workspace_id, mock_router):
    calls = await _complete("agent_08", {"live_fetch": {"security_group_id": "sg-1"},
                                         "baseline_findings": [SG_FINDING]},
                            {"status": "pr_created"}, {"id": "opt_1", "proposal": True},
                            mock_db, workspace_id, mock_router)
    assert json.loads(calls[0].args[1])["check"] == "drift_findings"


async def test_failed_execution_records_no_spec(mock_db, workspace_id, mock_router):
    calls = await _complete("agent_06", {"cloud_provider": "aws", "quick_win_resources": {"instance_ids": ["i-1"]}},
                            {"status": "failed", "error": "AccessDenied"}, {"id": "opt_2", "proposal": False},
                            mock_db, workspace_id, mock_router)
    assert calls == []


async def test_agents_without_a_live_check_record_nothing(mock_db, workspace_id, mock_router):
    calls = await _complete("agent_03", {}, {"status": "review_posted"}, {"id": "opt_2", "proposal": False},
                            mock_db, workspace_id, mock_router)
    assert calls == []
