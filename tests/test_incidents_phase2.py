"""
tests/test_incidents_phase2.py
24-gap-closure build, Phase 2 ("Incident workflow UX"):
- PATCH /incidents/{id}/assign
- GET/POST /incidents/{id}/comments
- POST /incidents/bulk (dismiss / resolve_manually)

Runs with pytest-asyncio (asyncio_mode = auto) + unittest.mock -- no live DB,
same convention as tests/test_incidents.py / test_incidents_workspace_scope.py.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.routes import incidents
from db.models import (
    IncidentAssignRequest,
    IncidentCommentCreateRequest,
    BulkIncidentActionRequest,
)


def _make_request(fetchrow_side_effect=None, fetchrow_return=None, fetch_return=None):
    """One shared conn/pool mock -- db.acquire() always returns the same
    conn, so fetchrow's side_effect list is consumed in call order across
    however many separate `async with db.acquire()` blocks a route uses."""
    conn = AsyncMock()
    if fetchrow_side_effect is not None:
        conn.fetchrow = AsyncMock(side_effect=fetchrow_side_effect)
    else:
        conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.fetch = AsyncMock(return_value=fetch_return or [])
    conn.execute = AsyncMock(return_value=None)

    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    app = SimpleNamespace(state=SimpleNamespace(db_pool=pool))
    return SimpleNamespace(app=app), conn


class TestAssignIncident:
    async def test_assigns_to_a_real_member(self):
        workspace_id = uuid4()
        incident_id = uuid4()
        member_id = uuid4()

        request, conn = _make_request(fetchrow_side_effect=[
            {"id": member_id},  # member validation
            {  # UPDATE ... RETURNING
                "id": incident_id, "parsed_error": "boom", "remediation_options": json.dumps([]),
                "execution_status": "pending_approval", "estimated_duration_seconds": 30,
                "severity": "medium", "agent_id": "agent_01_cicd_triage",
                "resource_id": None, "resource_name": None, "created_at": None,
                "assigned_to": member_id,
            },
            {"email": "ops@acme.com"},  # email lookup
        ])

        result = await incidents.assign_incident(
            str(incident_id), IncidentAssignRequest(member_id=str(member_id)),
            request, workspace={"id": workspace_id},
        )

        assert result.assigned_to == str(member_id)
        assert result.assigned_to_email == "ops@acme.com"
        # An audit_events row must be written
        insert_calls = [c for c in conn.execute.await_args_list if "INSERT INTO audit_events" in c.args[0]]
        assert len(insert_calls) == 1
        assert insert_calls[0].args[2] == "agent_01_cicd_triage"

    async def test_unassign_with_none_member_id(self):
        workspace_id = uuid4()
        incident_id = uuid4()

        request, conn = _make_request(fetchrow_side_effect=[
            {  # no member validation call -- member_id is None
                "id": incident_id, "parsed_error": "boom", "remediation_options": json.dumps([]),
                "execution_status": "pending_approval", "estimated_duration_seconds": 30,
                "severity": "medium", "agent_id": "agent_01_cicd_triage",
                "resource_id": None, "resource_name": None, "created_at": None,
                "assigned_to": None,
            },
        ])

        result = await incidents.assign_incident(
            str(incident_id), IncidentAssignRequest(member_id=None),
            request, workspace={"id": workspace_id},
        )

        assert result.assigned_to is None
        assert result.assigned_to_email is None

    async def test_member_not_in_workspace_raises_404(self):
        workspace_id = uuid4()
        incident_id = uuid4()
        request, conn = _make_request(fetchrow_return=None)  # member validation finds nothing

        with pytest.raises(HTTPException) as exc_info:
            await incidents.assign_incident(
                str(incident_id), IncidentAssignRequest(member_id=str(uuid4())),
                request, workspace={"id": workspace_id},
            )
        assert exc_info.value.status_code == 404

    async def test_incident_not_found_raises_404(self):
        workspace_id = uuid4()
        incident_id = uuid4()
        member_id = uuid4()
        request, conn = _make_request(fetchrow_side_effect=[
            {"id": member_id},  # member exists
            None,               # UPDATE...RETURNING finds no matching incident
        ])

        with pytest.raises(HTTPException) as exc_info:
            await incidents.assign_incident(
                str(incident_id), IncidentAssignRequest(member_id=str(member_id)),
                request, workspace={"id": workspace_id},
            )
        assert exc_info.value.status_code == 404

    async def test_viewer_cannot_assign(self):
        workspace_id = uuid4()
        request, _ = _make_request()

        with pytest.raises(HTTPException) as exc_info:
            await incidents.assign_incident(
                str(uuid4()), IncidentAssignRequest(member_id=str(uuid4())),
                request, workspace={"id": workspace_id, "member_role": "viewer"},
            )
        assert exc_info.value.status_code == 403

    async def test_approver_can_assign(self):
        workspace_id = uuid4()
        incident_id = uuid4()
        request, conn = _make_request(fetchrow_side_effect=[
            {
                "id": incident_id, "parsed_error": "boom", "remediation_options": json.dumps([]),
                "execution_status": "pending_approval", "estimated_duration_seconds": 30,
                "severity": "medium", "agent_id": "agent_01_cicd_triage",
                "resource_id": None, "resource_name": None, "created_at": None,
                "assigned_to": None,
            },
        ])

        result = await incidents.assign_incident(
            str(incident_id), IncidentAssignRequest(member_id=None),
            request, workspace={"id": workspace_id, "member_role": "approver"},
        )
        assert result.incident_id == str(incident_id)


class TestIncidentComments:
    async def test_list_comments_returns_them_in_order(self):
        workspace_id = uuid4()
        incident_id = uuid4()
        comment_id = uuid4()
        member_id = uuid4()
        request, conn = _make_request(
            fetchrow_return={"id": incident_id},
            fetch_return=[{
                "id": comment_id, "incident_id": incident_id, "member_id": member_id,
                "body": "Investigating now", "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                "member_email": "ops@acme.com",
            }],
        )

        results = await incidents.list_incident_comments(
            str(incident_id), request, workspace={"id": workspace_id},
        )

        assert len(results) == 1
        assert results[0].body == "Investigating now"
        assert results[0].member_email == "ops@acme.com"

    async def test_list_comments_incident_not_found_raises_404(self):
        workspace_id = uuid4()
        request, _ = _make_request(fetchrow_return=None)

        with pytest.raises(HTTPException) as exc_info:
            await incidents.list_incident_comments(
                str(uuid4()), request, workspace={"id": workspace_id},
            )
        assert exc_info.value.status_code == 404

    async def test_create_comment_persists_body_and_member_id(self):
        workspace_id = uuid4()
        incident_id = uuid4()
        member_id = uuid4()
        comment_id = uuid4()
        created = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

        request, conn = _make_request(fetchrow_side_effect=[
            {"id": incident_id},  # incident existence check
            {"id": comment_id, "incident_id": incident_id, "member_id": member_id,
             "body": "Rotated the credential", "created_at": created},  # INSERT ... RETURNING
        ])

        result = await incidents.create_incident_comment(
            str(incident_id), IncidentCommentCreateRequest(body="Rotated the credential"),
            request, workspace={"id": workspace_id, "member_id": str(member_id), "member_email": "ops@acme.com"},
        )

        assert result.body == "Rotated the credential"
        assert result.member_id == str(member_id)
        assert result.member_email == "ops@acme.com"

    async def test_create_comment_empty_body_raises_400(self):
        workspace_id = uuid4()
        request, _ = _make_request()

        with pytest.raises(HTTPException) as exc_info:
            await incidents.create_incident_comment(
                str(uuid4()), IncidentCommentCreateRequest(body="   "),
                request, workspace={"id": workspace_id},
            )
        assert exc_info.value.status_code == 400

    async def test_create_comment_token_auth_has_no_member_id(self):
        """A token-authenticated caller (no member session) can still
        comment -- member_id/member_email are NULL, not rejected."""
        workspace_id = uuid4()
        incident_id = uuid4()
        comment_id = uuid4()
        created = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

        request, conn = _make_request(fetchrow_side_effect=[
            {"id": incident_id},
            {"id": comment_id, "incident_id": incident_id, "member_id": None,
             "body": "Automated note", "created_at": created},
        ])

        result = await incidents.create_incident_comment(
            str(incident_id), IncidentCommentCreateRequest(body="Automated note"),
            request, workspace={"id": workspace_id},
        )

        assert result.member_id is None
        assert result.member_email is None


class TestBulkIncidentAction:
    async def test_dismiss_applies_to_pending_incident_and_writes_audit_row(self):
        workspace_id = uuid4()
        incident_id = uuid4()
        request, conn = _make_request(fetchrow_side_effect=[
            {"id": incident_id, "agent_id": "agent_01_cicd_triage", "execution_status": "pending_approval"},
        ])

        result = await incidents.bulk_incident_action(
            BulkIncidentActionRequest(incident_ids=[str(incident_id)], action="dismiss", reason="stale alert"),
            request, workspace={"id": workspace_id},
        )

        assert result.results[0].outcome == "applied"
        update_calls = [c for c in conn.execute.await_args_list if "UPDATE incidents" in c.args[0]]
        assert len(update_calls) == 1
        assert "rejected" in update_calls[0].args[0]
        audit_calls = [c for c in conn.execute.await_args_list if "bulk_rejected" in c.args[0]]
        assert len(audit_calls) == 1

    async def test_resolve_manually_applies_and_writes_audit_row(self):
        workspace_id = uuid4()
        incident_id = uuid4()
        request, conn = _make_request(fetchrow_side_effect=[
            {"id": incident_id, "agent_id": "agent_06_finops", "execution_status": "pending_approval"},
        ])

        result = await incidents.bulk_incident_action(
            BulkIncidentActionRequest(
                incident_ids=[str(incident_id)], action="resolve_manually",
                resolution_note="Fixed via console",
            ),
            request, workspace={"id": workspace_id},
        )

        assert result.results[0].outcome == "applied"
        audit_calls = [c for c in conn.execute.await_args_list if "bulk_manual_resolution" in c.args]
        assert len(audit_calls) == 1

    async def test_writes_one_audit_row_per_incident_not_one_for_the_batch(self):
        workspace_id = uuid4()
        ids = [uuid4(), uuid4(), uuid4()]
        request, conn = _make_request(fetchrow_side_effect=[
            {"id": i, "agent_id": "agent_01_cicd_triage", "execution_status": "pending_approval"}
            for i in ids
        ])

        result = await incidents.bulk_incident_action(
            BulkIncidentActionRequest(incident_ids=[str(i) for i in ids], action="dismiss"),
            request, workspace={"id": workspace_id},
        )

        assert all(r.outcome == "applied" for r in result.results)
        audit_calls = [c for c in conn.execute.await_args_list if "bulk_rejected" in c.args[0]]
        assert len(audit_calls) == 3

    async def test_not_found_incident_is_skipped_not_a_hard_failure(self):
        workspace_id = uuid4()
        request, conn = _make_request(fetchrow_side_effect=[None])

        result = await incidents.bulk_incident_action(
            BulkIncidentActionRequest(incident_ids=[str(uuid4())], action="dismiss"),
            request, workspace={"id": workspace_id},
        )

        assert result.results[0].outcome == "not_found"

    async def test_non_pending_incident_is_skipped(self):
        workspace_id = uuid4()
        incident_id = uuid4()
        request, conn = _make_request(fetchrow_side_effect=[
            {"id": incident_id, "agent_id": "agent_01_cicd_triage", "execution_status": "executed"},
        ])

        result = await incidents.bulk_incident_action(
            BulkIncidentActionRequest(incident_ids=[str(incident_id)], action="dismiss"),
            request, workspace={"id": workspace_id},
        )

        assert result.results[0].outcome == "not_pending"

    async def test_partial_batch_mixed_outcomes(self):
        workspace_id = uuid4()
        found_pending = uuid4()
        found_executed = uuid4()
        missing = uuid4()
        request, conn = _make_request(fetchrow_side_effect=[
            {"id": found_pending, "agent_id": "agent_01_cicd_triage", "execution_status": "pending_approval"},
            {"id": found_executed, "agent_id": "agent_01_cicd_triage", "execution_status": "executed"},
            None,
        ])

        result = await incidents.bulk_incident_action(
            BulkIncidentActionRequest(
                incident_ids=[str(found_pending), str(found_executed), str(missing)],
                action="dismiss",
            ),
            request, workspace={"id": workspace_id},
        )

        outcomes = {r.incident_id: r.outcome for r in result.results}
        assert outcomes[str(found_pending)] == "applied"
        assert outcomes[str(found_executed)] == "not_pending"
        assert outcomes[str(missing)] == "not_found"

    async def test_viewer_cannot_bulk_act(self):
        request, _ = _make_request()

        with pytest.raises(HTTPException) as exc_info:
            await incidents.bulk_incident_action(
                BulkIncidentActionRequest(incident_ids=[str(uuid4())], action="dismiss"),
                request, workspace={"id": uuid4(), "member_role": "viewer"},
            )
        assert exc_info.value.status_code == 403

    async def test_empty_incident_ids_raises_400(self):
        request, _ = _make_request()

        with pytest.raises(HTTPException) as exc_info:
            await incidents.bulk_incident_action(
                BulkIncidentActionRequest(incident_ids=[], action="dismiss"),
                request, workspace={"id": uuid4()},
            )
        assert exc_info.value.status_code == 400

    async def test_invalid_action_raises_400(self):
        request, _ = _make_request()

        with pytest.raises(HTTPException) as exc_info:
            await incidents.bulk_incident_action(
                BulkIncidentActionRequest(incident_ids=[str(uuid4())], action="delete_everything"),
                request, workspace={"id": uuid4()},
            )
        assert exc_info.value.status_code == 400

    async def test_malformed_incident_id_is_not_found_not_a_500(self):
        request, _ = _make_request()

        result = await incidents.bulk_incident_action(
            BulkIncidentActionRequest(incident_ids=["not-a-uuid"], action="dismiss"),
            request, workspace={"id": uuid4()},
        )

        assert result.results[0].outcome == "not_found"


# ── Bulk and single-incident actions accept exactly the same statuses ─────────

import re
from pathlib import Path
from unittest.mock import patch

from api.routes.incidents import IncidentRejectRequest
from core.hitl import MANUALLY_RESOLVABLE_STATUSES, REJECTABLE_STATUSES
from db.models import IncidentResolveManuallyRequest

_TYPES_TS = Path(__file__).resolve().parents[1] / "frontend/src/lib/types.ts"


def _all_statuses() -> list[str]:
    block = re.search(r"export type IncidentStatus =(.*?)\n\n", _TYPES_TS.read_text(), re.S).group(1)
    return re.findall(r"\|\s*'(\w+)'", block)


async def _single_accepts(action: str, status: str) -> bool:
    incident_id = uuid4()
    request, _conn = _make_request(fetchrow_return={
        "id": incident_id, "agent_id": "agent_08_drift_detection", "execution_status": status,
        "resource_name": None, "resource_group": None, "metric_name": None, "parsed_error": "x",
        "cloud_provider": None, "severity": None,
    })
    try:
        with patch("core.ticketing.schedule_resolution_notification"):
            if action == "dismiss":
                await incidents.reject_incident(str(incident_id), IncidentRejectRequest(reason="r"),
                                                request, workspace={"id": uuid4()})
            else:
                await incidents.resolve_incident_manually(str(incident_id), IncidentResolveManuallyRequest(),
                                                          request, workspace={"id": uuid4()})
    except HTTPException as exc:
        assert exc.status_code == 409, exc.detail
        return False
    return True


async def _bulk_accepts(action: str, status: str) -> bool:
    incident_id = uuid4()
    request, _conn = _make_request(fetchrow_side_effect=[
        {"id": incident_id, "agent_id": "agent_08_drift_detection", "execution_status": status},
    ])
    result = await incidents.bulk_incident_action(
        BulkIncidentActionRequest(incident_ids=[str(incident_id)], action=action),
        request, workspace={"id": uuid4()},
    )
    return result.results[0].outcome == "applied"


@pytest.mark.parametrize("action", ["dismiss", "resolve_manually"])
async def test_bulk_and_single_accept_exactly_the_same_statuses(action):
    statuses = _all_statuses()
    assert "proposed" in statuses and "pending_approval" in statuses
    single = {s for s in statuses if await _single_accepts(action, s)}
    bulk = {s for s in statuses if await _bulk_accepts(action, s)}
    assert single == bulk
    expected = REJECTABLE_STATUSES if action == "dismiss" else MANUALLY_RESOLVABLE_STATUSES
    assert bulk == set(expected)


async def test_bulk_resolve_accepts_fix_proposed():
    assert await _bulk_accepts("resolve_manually", "proposed")
    assert not await _bulk_accepts("dismiss", "proposed")  # a PR was already opened; nothing to reject


def test_frontend_status_rules_match_the_backend():
    ts = _TYPES_TS.read_text()

    def ts_list(name: str) -> set[str]:
        return set(re.findall(r"'(\w+)'", re.search(rf"export const {name}[^=]*=\s*\[(.*?)\]", ts, re.S).group(1)))

    assert ts_list("REJECTABLE_STATUSES") == set(REJECTABLE_STATUSES)
    assert ts_list("MANUALLY_RESOLVABLE_STATUSES") == set(MANUALLY_RESOLVABLE_STATUSES)


# ── Item 5: bulk resolve fires ticketing through the single endpoint's path ──

def _resolvable_row(incident_id):
    return {"id": incident_id, "agent_id": "agent_08_drift_detection", "execution_status": "proposed",
            "resource_name": "sg-123", "resource_group": "rg", "metric_name": None, "parsed_error": "port 22 open",
            "cloud_provider": "aws", "severity": "high"}


async def test_bulk_and_single_resolve_send_the_same_ticketing_payload():
    single_id, bulk_id = uuid4(), uuid4()
    with patch("core.ticketing.schedule_resolution_notification") as ticketing:
        request, _ = _make_request(fetchrow_return=_resolvable_row(single_id))
        await incidents.resolve_incident_manually(
            str(single_id), IncidentResolveManuallyRequest(resolution_note="merged"), request,
            workspace={"id": uuid4(), "member_id": "m-1"})
        request, _ = _make_request(fetchrow_side_effect=[_resolvable_row(bulk_id)])
        await incidents.bulk_incident_action(
            BulkIncidentActionRequest(incident_ids=[str(bulk_id)], action="resolve_manually", resolution_note="merged"),
            request, workspace={"id": uuid4(), "member_id": "m-1"})

    assert ticketing.call_count == 2
    (single_ws, single_summary), single_kw = ticketing.call_args_list[0]
    (bulk_ws, bulk_summary), bulk_kw = ticketing.call_args_list[1]
    assert single_summary["incident_id"] == str(single_id) and bulk_summary["incident_id"] == str(bulk_id)
    strip = lambda d: {k: v for k, v in d.items() if k not in ("incident_id", "resolved_at")}  # noqa: E731
    assert strip(single_summary) == strip(bulk_summary)
    assert bulk_summary["execution_status"] == "resolved_manually"
    assert single_kw == bulk_kw == {"resolved_by": "m-1"}


async def test_bulk_resolve_skipped_incident_fires_no_ticketing():
    incident_id = uuid4()
    row = {**_resolvable_row(incident_id), "execution_status": "executed"}  # not manually resolvable
    with patch("core.ticketing.schedule_resolution_notification") as ticketing:
        request, _ = _make_request(fetchrow_side_effect=[row])
        result = await incidents.bulk_incident_action(
            BulkIncidentActionRequest(incident_ids=[str(incident_id)], action="resolve_manually"),
            request, workspace={"id": uuid4()})
    assert result.results[0].outcome == "not_pending"
    ticketing.assert_not_called()


async def test_bulk_dismiss_fires_no_ticketing():
    incident_id = uuid4()
    row = {**_resolvable_row(incident_id), "execution_status": "pending_approval"}
    with patch("core.ticketing.schedule_resolution_notification") as ticketing:
        request, _ = _make_request(fetchrow_side_effect=[row])
        await incidents.bulk_incident_action(
            BulkIncidentActionRequest(incident_ids=[str(incident_id)], action="dismiss"),
            request, workspace={"id": uuid4()})
    ticketing.assert_not_called()
