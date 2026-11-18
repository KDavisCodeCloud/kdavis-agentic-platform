"""
Item 5 (Break-It Lab G2 + G3): regression linking and source-resolved ingest.

G2: lab step 6 re-injected every fixed problem; each came back as a fresh,
unlinked incident (agents 05/06/08 stored no resource identity).
G3: CloudWatch OK / Azure Monitor 'Resolved' were dropped at the webhook.
"""

import copy
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from core import regression as r
from core.hitl import SOURCE_RESOLVABLE_STATUSES, HITLGate


# ── keys: deterministic, never on blanks ─────────────────────────────────────

def test_keys_are_deterministic_and_order_insensitive_for_compute():
    assert r.compute_key("aws", ["i-2", "i-1"]) == r.compute_key("aws", ["i-1", "i-2", "i-1"]) == "aws:compute:i-1,i-2"


@pytest.mark.parametrize("key", [
    r.compute_key("aws", []),
    r.drift_key(""),
    r.alert_key("unknown", "High CPU"),
    r.alert_key("vm-1", ""),
    r.iam_key("aws", ""),
    r.iam_key("azure", "/subscriptions/s", ""),
])
def test_missing_identity_gives_no_key(key):
    assert key is None


def test_azure_iam_key_includes_the_principal():
    assert r.iam_key("azure", "/subscriptions/s", "p-1") != r.iam_key("azure", "/subscriptions/s", "p-2")
    assert r.iam_key("aws", "arn:aws:iam::1:policy/x", "ignored") == "aws:iam:arn:aws:iam::1:policy/x"


# ── link_previous ────────────────────────────────────────────────────────────

def _db(prev):
    db = AsyncMock()
    db.fetchrow = AsyncMock(return_value=prev)
    db.execute = AsyncMock()
    return db


@pytest.mark.parametrize("status", sorted(r.FIXED_STATUSES))
async def test_a_problem_back_after_a_fix_is_a_regression(status):
    prev_id, new_id = uuid4(), str(uuid4())
    db = _db({"id": prev_id, "execution_status": status})
    link = await r.link_previous(db, "ws", "agent_05_iam_minimizer", "aws:iam:arn", new_id)
    assert link == {"id": str(prev_id), "execution_status": status, "is_regression": True}
    lookup = db.fetchrow.await_args.args
    assert "regression_key = $3" in lookup[0] and "id <> $4" in lookup[0]
    assert lookup[1:4] == ("ws", "agent_05_iam_minimizer", "aws:iam:arn")
    update = db.execute.await_args_list[0].args
    assert "previous_incident_id = $1, is_regression = $2" in update[0] and update[1:3] == (prev_id, True)


@pytest.mark.parametrize("status", ["pending_approval", "proposed", "failed", "verification_failed", "rejected"])
async def test_recurrence_of_something_never_fixed_is_linked_not_a_regression(status):
    db = _db({"id": uuid4(), "execution_status": status})
    link = await r.link_previous(db, "ws", "a", "k", str(uuid4()))
    assert link["is_regression"] is False
    assert db.execute.await_args_list[0].args[2] is False


async def test_first_occurrence_links_nothing():
    db = _db(None)
    assert await r.link_previous(db, "ws", "a", "k", str(uuid4())) is None
    db.execute.assert_not_called()


async def test_no_key_never_queries():
    db = _db({"id": uuid4(), "execution_status": "executed"})
    assert await r.link_previous(db, "ws", "a", None, str(uuid4())) is None
    db.fetchrow.assert_not_called()


async def test_regression_pulls_the_earlier_incidents_verification_forward():
    prev_id = uuid4()
    db = _db({"id": prev_id, "execution_status": "executed"})
    await r.link_previous(db, "ws", "a", "k", str(uuid4()))
    pull = db.execute.await_args_list[1].args
    assert "verification_next_at = NOW()" in pull[0] and "verification_next_at IS NOT NULL" in pull[0]
    assert pull[1] == prev_id


def test_regression_summary_says_so_in_the_notification():
    assert r.regression_summary("port 22 open", None) == "port 22 open"
    assert r.regression_summary("x", {"id": "p", "execution_status": "proposed", "is_regression": False}) == "x"
    text = r.regression_summary("port 22 open", {"id": "p-1", "execution_status": "verified", "is_regression": True})
    assert text.startswith("REGRESSION") and "p-1" in text and "port 22 open" in text


# ── create_incident stores the key and links ─────────────────────────────────

async def test_create_incident_stores_key_links_and_notifies_as_regression():
    new_id, prev_id = uuid4(), uuid4()
    db = AsyncMock()
    db.fetchrow = AsyncMock(side_effect=[{"id": new_id}, {"id": prev_id, "execution_status": "verified"}])
    db.execute = AsyncMock()
    gate = HITLGate(db)
    with patch.object(gate, "_fire_notification") as notify, patch.object(gate, "_write_audit_entry") as audit:
        await gate.create_incident(
            workspace_id="ws", agent_id="agent_08_drift_detection", raw_log="r", parsed_error="SG allows 22",
            remediation_options=[], incident_id=str(new_id), regression_key="drift:sg-1",
        )
    insert = db.fetchrow.await_args_list[0].args
    assert "regression_key" in insert[0] and insert[-1] == "drift:sg-1"
    assert notify.call_args.args[4].startswith("REGRESSION")
    assert any(c.args[3] == "regression_detected" for c in audit.call_args_list)


async def test_create_incident_without_key_does_one_query():
    db = AsyncMock()
    db.fetchrow = AsyncMock(return_value={"id": uuid4()})
    gate = HITLGate(db)
    with patch.object(gate, "_fire_notification"), patch.object(gate, "_write_audit_entry"):
        await gate.create_incident(workspace_id="ws", agent_id="a", raw_log="r", parsed_error="p",
                                   remediation_options=[])
    assert db.fetchrow.await_count == 1


# ── each lab agent now passes a key ──────────────────────────────────────────

def _workflow(cls, router):
    with patch("agents.base_agent._load_router", return_value=router), \
         patch.object(cls, "_build_graph", return_value=MagicMock()):
        wf = cls(AsyncMock(), "ws", MagicMock())
    wf.hitl.create_incident = AsyncMock(return_value="inc-1")
    wf.record_token_usage = AsyncMock()
    return wf


@pytest.fixture
def router():
    m = MagicMock()
    m.complete = AsyncMock(return_value=("{}", 0))
    return m


async def _run_gate(cls, module_path, state, router):
    """Run the agent's HITL gate with create_incident captured; return its kwargs."""
    wf = _workflow(cls, router)
    with patch(f"{module_path}.interrupt", return_value={"id": "hold"}):
        try:
            await wf._hitl_gate_node(state)
        except Exception:
            pass  # downstream of create_incident isn't under test here
    return wf.hitl.create_incident.await_args.kwargs


async def test_agent05_passes_an_iam_key(router):
    from agents.agent_05_iam_minimizer.workflow import IAMMinimizeWorkflow
    state = {"incident_id": "inc-1", "cloud_provider": "aws", "parsed_error": "p", "remediation_options": [],
             "resource_scope": "arn:aws:iam::1:policy/cdlab-a3", "principal_id": "arn:aws:iam::1:role/r",
             "principal_name": "r", "permission_list": [], "unused_permissions": [], "risk_score": "HIGH",
             "log_excerpt": "", "tokens_used": 0, "current_policy_summary": "", "recommendation_summary": "",
             "principal_type": "role"}
    kw = await _run_gate(IAMMinimizeWorkflow, "agents.agent_05_iam_minimizer.workflow", state, router)
    assert kw["regression_key"] == "aws:iam:arn:aws:iam::1:policy/cdlab-a3"


async def test_agent08_stores_resource_id_and_key(router):
    from agents.agent_08_drift_detection.workflow import DriftWorkflow
    state = {"incident_id": "inc-1", "cloud_provider": "aws", "parsed_error": "p", "remediation_options": [],
             "resource_id": "sg-0abc", "drift_source": "aws", "drift_items": [], "drift_severity": "high",
             "tokens_used": 0, "desired_state_text": "", "actual_state_text": "", "resource_type": "sg",
             "scope": "", "repository": "", "file_path": ""}
    kw = await _run_gate(DriftWorkflow, "agents.agent_08_drift_detection.workflow", state, router)
    assert kw["resource_id"] == "sg-0abc" and kw["regression_key"] == "drift:sg-0abc"


def test_agent06_key_is_the_set_of_stopped_resources():
    from agents.agent_06_finops.workflow import _quick_win_ids
    state = {"quick_win_resources": {"instance_ids": ["i-2", "i-1"], "vm_names": []}}
    assert r.compute_key("aws", _quick_win_ids(state)) == "aws:compute:i-1,i-2"
    assert r.compute_key("aws", _quick_win_ids({"quick_win_resources": None})) is None


# ── G3: source-resolved ingest ───────────────────────────────────────────────

def test_source_resolution_also_matches_incidents_awaiting_verification():
    """Lab Z1: the alert auto-resolved after its incident said 'executed'."""
    for status in ("pending_approval", "executing", "executed", "proposed", "fix_merged"):
        assert status in SOURCE_RESOLVABLE_STATUSES
    for status in ("verified", "verification_failed", "resolved_manually", "rejected"):
        assert status not in SOURCE_RESOLVABLE_STATUSES


async def test_find_open_incident_default_is_still_open_only():
    db = AsyncMock()
    db.fetchrow = AsyncMock(return_value=None)
    await HITLGate(db).find_open_incident("ws", "vm-1", "High CPU")
    assert db.fetchrow.await_args.args[-1] == ["pending_approval", "executing"]


async def test_note_source_resolution_pulls_pending_verification_forward():
    db = AsyncMock()
    gate = HITLGate(db)
    with patch.object(gate, "_write_audit_entry"):
        await gate.note_source_resolution(str(uuid4()))
    sql = db.execute.await_args.args[0]
    assert "source_resolved_at = $2" in sql
    assert "CASE WHEN verification_next_at IS NOT NULL THEN $2" in sql
    assert "execution_status" not in sql  # the source's word never closes anything by itself


_AZURE = {"data": {"essentials": {
    "alertRule": "cdlab-z1-cpu", "severity": "Sev2", "targetResourceType": "Microsoft.Compute/virtualMachines",
    "alertTargetIDs": ["/subscriptions/s/resourceGroups/rg-cdlab/providers/Microsoft.Compute/virtualMachines/z1"],
    "monitorCondition": "Fired", "alertId": "/subscriptions/s/providers/Microsoft.AlertsManagement/alerts/a1",
}}}
_CLOUDWATCH = {"cloudwatch_alarm": {
    "AlarmName": "cdlab-a1-cpu", "NewStateValue": "ALARM", "NewStateReason": "Threshold Crossed",
    "AlarmArn": "arn:aws:cloudwatch:us-east-1:1:alarm:cdlab-a1-cpu",
    "Trigger": {"Namespace": "AWS/EC2", "MetricName": "CPUUtilization",
                "Dimensions": [{"name": "InstanceId", "value": "i-0a1"}]},
}}


def _agent11(router):
    from agents.agent_11_resource_health.workflow import ResourceHealthWorkflow
    with patch("agents.base_agent._load_router", return_value=router), \
         patch.object(ResourceHealthWorkflow, "_build_graph", return_value=MagicMock()):
        return ResourceHealthWorkflow(AsyncMock(), "ws", MagicMock())


async def _ingest(router, payload):
    wf = _agent11(router)
    return await wf._ingest_node({"workspace_id": "ws", "cloud_provider": "aws", "webhook_payload": payload})


@pytest.mark.parametrize("payload,path,resolved_value", [
    (_AZURE, ("data", "essentials", "monitorCondition"), "Resolved"),
    (_CLOUDWATCH, ("cloudwatch_alarm", "NewStateValue"), "OK"),
])
async def test_resolved_and_firing_share_one_identity(router, payload, path, resolved_value):
    firing = await _ingest(router, payload)
    resolved_payload = copy.deepcopy(payload)
    node = resolved_payload
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = resolved_value
    resolved = await _ingest(router, resolved_payload)
    assert firing["alert_status"] == "firing" and resolved["alert_status"] == "resolved"
    assert (resolved["resource_id"], resolved["alert_name"]) == (firing["resource_id"], firing["alert_name"])


async def test_resolution_check_searches_awaiting_verification_statuses(router):
    wf = _agent11(router)
    existing = str(uuid4())
    wf.hitl.find_open_incident = AsyncMock(return_value={"id": existing})
    wf.hitl.note_source_resolution = AsyncMock()
    state = {"alert_status": "resolved", "resource_id": "i-0a1", "alert_name": "cdlab-a1-cpu"}
    result = await wf._resolution_check_node(state)
    assert wf.hitl.find_open_incident.await_args.kwargs["statuses"] == SOURCE_RESOLVABLE_STATUSES
    wf.hitl.note_source_resolution.assert_awaited_once_with(existing)
    assert result == {"incident_id": existing, "is_source_resolved_noop": True}


def test_incident_response_exposes_the_link():
    from api.routes.incidents import _regression_fields
    prev = uuid4()
    out = _regression_fields({"previous_incident_id": prev, "is_regression": True, "source_resolved_at": None})
    assert out == {"previous_incident_id": str(prev), "is_regression": True, "source_resolved_at": None}
    assert _regression_fields({})["is_regression"] is False
    assert json.dumps(_regression_fields({}))  # serializable
