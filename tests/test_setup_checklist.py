"""
tests/test_setup_checklist.py
24-gap-closure build, Phase 6 -- api/routes/setup_checklist.py (5-item
setup completeness checklist, migration 046).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.routes import setup_checklist as sc_routes


def _make_request(fetchrow_side_effect=None) -> tuple:
    conn = AsyncMock()
    if fetchrow_side_effect is not None:
        conn.fetchrow = AsyncMock(side_effect=fetchrow_side_effect)
    conn.execute = AsyncMock(return_value=None)
    pool_ctx = AsyncMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=conn)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=pool_ctx)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=pool)))
    return request, conn


class TestGetSetupChecklist:
    async def test_nothing_connected_is_zero_of_five(self):
        request, conn = _make_request(fetchrow_side_effect=[None, None])
        workspace = {"id": uuid4()}

        result = await sc_routes.get_setup_checklist(request, workspace=workspace)

        assert result.completed_count == 0
        assert result.cloud_connected is False
        assert result.repo_connected is False
        assert result.alert_source_verified is False
        assert result.notification_channel_set is False
        assert result.end_to_end_test_passed is False

    async def test_all_five_signals_present_is_five_of_five(self):
        request, conn = _make_request(fetchrow_side_effect=[{"?column?": 1}, {"?column?": 1}])
        workspace = {
            "id": uuid4(),
            "aws_role_verified_at": "2026-01-01",
            "github_app_installation_id": "12345",
            "setup_test_passed_at": "2026-01-01",
        }

        result = await sc_routes.get_setup_checklist(request, workspace=workspace)

        assert result.completed_count == 5
        assert result.cloud_connected is True
        assert result.repo_connected is True
        assert result.alert_source_verified is True
        assert result.notification_channel_set is True
        assert result.end_to_end_test_passed is True

    async def test_alert_source_verified_requires_a_real_ingestion_log_row(self):
        """The one item Kelvin's spec called out explicitly: must never
        self-report, only flip on a real received webhook delivery."""
        request, conn = _make_request(fetchrow_side_effect=[None, {"?column?": 1}])
        workspace = {"id": uuid4()}

        result = await sc_routes.get_setup_checklist(request, workspace=workspace)

        assert result.alert_source_verified is False
        query_sql = conn.fetchrow.await_args_list[0].args[0]
        assert "alert_ingestion_log" in query_sql

    async def test_notification_channel_set_requires_enabled_true(self):
        request, conn = _make_request(fetchrow_side_effect=[None, None])
        workspace = {"id": uuid4()}

        await sc_routes.get_setup_checklist(request, workspace=workspace)

        query_sql = conn.fetchrow.await_args_list[1].args[0]
        assert "workspace_notification_channels" in query_sql
        assert "enabled = true" in query_sql


class TestRunConnectionTest:
    async def test_creates_a_test_incident_via_hitl_gate(self):
        request, conn = _make_request()
        workspace_id = uuid4()
        fake_incident_id = str(uuid4())

        with patch("api.routes.setup_checklist.HITLGate.create_incident", new=AsyncMock(return_value=fake_incident_id)) as mock_create:
            result = await sc_routes.run_connection_test(request, workspace={"id": workspace_id})

        assert result.incident_id == fake_incident_id
        mock_create.assert_awaited_once()
        assert mock_create.await_args.kwargs["agent_id"] == "system_connection_test"
        assert mock_create.await_args.kwargs["workspace_id"] == str(workspace_id)
        # Marked is_test=true after creation
        update_calls = [c for c in conn.execute.await_args_list if "is_test = true" in c.args[0]]
        assert len(update_calls) == 1


class TestCleanupConnectionTest:
    async def test_deletes_test_incident_and_flips_checklist_item(self):
        request, conn = _make_request(fetchrow_side_effect=[{"id": uuid4()}])
        workspace_id = uuid4()

        with patch("api.routes.setup_checklist.write_audit_event", new=AsyncMock()) as mock_audit:
            await sc_routes.cleanup_connection_test("11111111-1111-1111-1111-111111111111", request, workspace={"id": workspace_id})

        delete_calls = [c for c in conn.execute.await_args_list if "DELETE FROM incidents" in c.args[0]]
        assert len(delete_calls) == 1
        flip_calls = [c for c in conn.execute.await_args_list if "setup_test_passed_at = NOW()" in c.args[0]]
        assert len(flip_calls) == 1
        mock_audit.assert_awaited_once()

    async def test_nonexistent_or_non_test_incident_404s(self):
        request, conn = _make_request(fetchrow_side_effect=[None])
        with pytest.raises(HTTPException) as exc:
            await sc_routes.cleanup_connection_test("11111111-1111-1111-1111-111111111111", request, workspace={"id": uuid4()})
        assert exc.value.status_code == 404

    async def test_invalid_uuid_400(self):
        request, conn = _make_request()
        with pytest.raises(HTTPException) as exc:
            await sc_routes.cleanup_connection_test("not-a-uuid", request, workspace={"id": uuid4()})
        assert exc.value.status_code == 400
