"""
tests/test_audit.py
Tests for api/routes/audit.py — Phase 2C: submit a findings.json, run the
analysis agent synchronously, retrieve the report, approve/dismiss items.

Mirrors tests/test_workspaces.py's SimpleNamespace + AsyncMock pattern (no
TestClient needed — this router's rate limit is a flat string like
save_llm_key's, which works fine called directly, unlike the callable
_tier_limit form fixed in gap #5).

What this file validates:
  - submit_audit: creates the submission row, invokes the analysis agent
    with the right payload, returns the persisted report
  - get_audit_report: found (scoped to the caller's workspace) and
    not-found (wrong workspace or unknown id) -> 404, never another
    workspace's data
  - approve_item / dismiss_item: status + actioned_at set on success,
    404 when the item doesn't belong to the caller's workspace
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.middleware.rate_limiter import limiter
from api.routes import audit


@pytest.fixture(autouse=True)
def _no_rate_limit():
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


def _make_request(conn) -> SimpleNamespace:
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))


def _submit_body() -> audit.AuditSubmitRequest:
    return audit.AuditSubmitRequest(
        generated_at="2026-09-11T00:00:00Z",
        provider="aws",
        scan_duration_seconds=1.2,
        summary=audit.SummaryModel(
            total_findings=1,
            high_severity=1,
            medium_severity=0,
            low_severity=0,
            total_estimated_monthly_waste_usd=50.0,
            total_estimated_annual_waste_usd=600.0,
        ),
        findings=[
            audit.FindingModel(
                finding_id="f1",
                provider="aws",
                category="WASTE",
                severity="HIGH",
                service="EC2",
                resource_type="instance",
                resource_id="i-REDACTED",
                title="Stopped instance",
                description="d",
                remediation="r",
                estimated_monthly_waste_usd=50.0,
                detected_at="2026-09-11T00:00:00Z",
            )
        ],
    )


class TestSubmitAudit:
    async def test_creates_submission_and_returns_report(self):
        submission_id = uuid4()
        item_row = {
            "id": uuid4(),
            "severity": "HIGH",
            "category": "WASTE",
            "title": "Stopped instance",
            "description": "d",
            "remediation": "r",
            "estimated_monthly_waste_usd": 50.0,
            "priority_rank": 1,
            "status": "pending_approval",
        }
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            side_effect=[
                {"id": submission_id},  # INSERT ... RETURNING id
                {  # _load_report's submission SELECT
                    "id": submission_id,
                    "provider": "aws",
                    "total_findings": 1,
                    "total_estimated_monthly_waste_usd": 50.0,
                    "status": "ready",
                    "analysis_error": None,
                },
            ]
        )
        conn.fetch = AsyncMock(return_value=[item_row])
        request = _make_request(conn)
        fake_workspace = {"id": uuid4()}

        with patch("api.routes.audit.AuditAnalysisAgent") as MockAgent:
            MockAgent.return_value.run = AsyncMock(return_value=str(submission_id))
            result = await audit.submit_audit(_submit_body(), request, workspace=fake_workspace)

        assert result.audit_id == str(submission_id)
        assert result.status == "ready"
        assert len(result.items) == 1
        assert result.items[0].title == "Stopped instance"

        MockAgent.assert_called_once_with(conn, str(fake_workspace["id"]))
        run_payload = MockAgent.return_value.run.await_args.kwargs["payload"]
        assert run_payload["submission_id"] == str(submission_id)
        assert len(run_payload["findings"]) == 1


class TestGetAuditReport:
    async def test_found_scoped_to_workspace(self):
        submission_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": submission_id,
                "provider": "aws",
                "total_findings": 0,
                "total_estimated_monthly_waste_usd": 0.0,
                "status": "ready",
                "analysis_error": None,
            }
        )
        conn.fetch = AsyncMock(return_value=[])
        request = _make_request(conn)
        fake_workspace = {"id": uuid4()}

        result = await audit.get_audit_report(str(submission_id), request, workspace=fake_workspace)

        assert result.audit_id == str(submission_id)
        sql, bound_id, bound_workspace = conn.fetchrow.await_args.args
        assert bound_workspace == fake_workspace["id"]

    async def test_not_found_raises_404(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await audit.get_audit_report(str(uuid4()), request, workspace={"id": uuid4()})

        assert exc.value.status_code == 404


class TestApproveDismissItem:
    async def test_approve_success(self):
        item_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": item_id, "status": "approved"})
        request = _make_request(conn)

        result = await audit.approve_item(str(item_id), request, workspace={"id": uuid4()})

        assert result.status == "approved"
        sql = conn.fetchrow.await_args.args[0]
        assert "SET status = 'approved'" in sql

    async def test_dismiss_success(self):
        item_id = uuid4()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": item_id, "status": "dismissed"})
        request = _make_request(conn)

        result = await audit.dismiss_item(str(item_id), request, workspace={"id": uuid4()})

        assert result.status == "dismissed"

    async def test_approve_wrong_workspace_404(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        request = _make_request(conn)

        with pytest.raises(HTTPException) as exc:
            await audit.approve_item(str(uuid4()), request, workspace={"id": uuid4()})

        assert exc.value.status_code == 404
