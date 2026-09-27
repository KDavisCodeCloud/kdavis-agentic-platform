"""
tests/test_setup_checklist_core.py
24-gap-closure build, Phase 6 -- core/setup_checklist.py's
compute_setup_checklist, shared by api/routes/setup_checklist.py and
core/onboarding_sequence.py.

Admin visibility build (2026-09-27) -- compute_setup_checklist_detail /
_bulk, the per-item-timestamp companion used by api/routes/
internal_workspaces.py and core/setup_checklist_stall_alert.py.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from core.setup_checklist import (
    compute_setup_checklist,
    compute_setup_checklist_detail,
    compute_setup_checklist_detail_bulk,
)


class TestComputeSetupChecklist:
    async def test_zero_of_five_when_nothing_set(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, None])
        result = await compute_setup_checklist(conn, {"id": uuid4()})
        assert result["completed_count"] == 0

    async def test_five_of_five_when_everything_set(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"?column?": 1}, {"?column?": 1}])
        workspace = {
            "id": uuid4(), "azure_verified_at": "2026-01-01",
            "github_pat_verified_at": "2026-01-01", "setup_test_passed_at": "2026-01-01",
        }
        result = await compute_setup_checklist(conn, workspace)
        assert result["completed_count"] == 5

    async def test_k8s_alone_counts_as_cloud_connected(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, None])
        result = await compute_setup_checklist(conn, {"id": uuid4(), "k8s_verified_at": "2026-01-01"})
        assert result["cloud_connected"] is True
        assert result["repo_connected"] is False

    async def test_azure_devops_alone_counts_as_repo_connected(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, None])
        result = await compute_setup_checklist(conn, {"id": uuid4(), "azure_devops_pat_verified_at": "2026-01-01"})
        assert result["repo_connected"] is True
        assert result["cloud_connected"] is False


def _dt(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=timezone.utc)


class TestComputeSetupChecklistDetail:
    async def test_nothing_done_has_no_last_activity(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"first_at": None}, {"first_at": None}])
        result = await compute_setup_checklist_detail(conn, {"id": uuid4()})
        assert result["completed_count"] == 0
        assert result["last_activity_at"] is None
        assert result["cloud_connected"]["done"] is False
        assert result["cloud_connected"]["completed_at"] is None

    async def test_item_completed_at_is_the_earliest_of_its_sources(self):
        """cloud_connected is an OR of 3 columns -- it "flipped" true at
        whichever came first, not the latest."""
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"first_at": None}, {"first_at": None}])
        workspace = {
            "id": uuid4(),
            "aws_role_verified_at": _dt(10),
            "azure_verified_at": _dt(5),  # earliest -- this is the real flip date
            "k8s_verified_at": None,
        }
        result = await compute_setup_checklist_detail(conn, workspace)
        assert result["cloud_connected"]["done"] is True
        assert result["cloud_connected"]["completed_at"] == _dt(5)

    async def test_last_activity_at_is_the_most_recent_completed_item(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"first_at": _dt(2)}, {"first_at": None}])
        workspace = {
            "id": uuid4(),
            "azure_verified_at": _dt(1),
            "github_pat_verified_at": _dt(20),  # most recent flip
            "setup_test_passed_at": None,
        }
        result = await compute_setup_checklist_detail(conn, workspace)
        assert result["completed_count"] == 3  # cloud, repo, alert_source
        assert result["last_activity_at"] == _dt(20)

    async def test_alert_and_channel_use_their_own_queries(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"first_at": _dt(3)}, {"first_at": _dt(4)}])
        result = await compute_setup_checklist_detail(conn, {"id": uuid4()})
        assert result["alert_source_verified"]["completed_at"] == _dt(3)
        assert result["notification_channel_set"]["completed_at"] == _dt(4)
        alert_sql = conn.fetchrow.await_args_list[0].args[0]
        channel_sql = conn.fetchrow.await_args_list[1].args[0]
        assert "alert_ingestion_log" in alert_sql
        assert "workspace_notification_channels" in channel_sql


class TestComputeSetupChecklistDetailBulk:
    async def test_empty_workspace_list_returns_empty_dict_no_queries(self):
        conn = AsyncMock()
        result = await compute_setup_checklist_detail_bulk(conn, [])
        assert result == {}
        conn.fetch.assert_not_awaited()

    async def test_bulk_matches_per_workspace_computation(self):
        ws_a, ws_b = uuid4(), uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(side_effect=[
            [{"workspace_id": ws_a, "first_at": _dt(5)}],       # alert rows -- only A has one
            [{"workspace_id": ws_b, "first_at": _dt(7)}],       # channel rows -- only B has one
        ])
        workspaces = [
            {"id": ws_a, "azure_verified_at": _dt(1)},
            {"id": ws_b, "github_pat_verified_at": _dt(2)},
        ]
        result = await compute_setup_checklist_detail_bulk(conn, workspaces)

        assert result[ws_a]["cloud_connected"]["done"] is True
        assert result[ws_a]["alert_source_verified"]["completed_at"] == _dt(5)
        assert result[ws_a]["notification_channel_set"]["done"] is False

        assert result[ws_b]["repo_connected"]["done"] is True
        assert result[ws_b]["notification_channel_set"]["completed_at"] == _dt(7)
        assert result[ws_b]["alert_source_verified"]["done"] is False

    async def test_bulk_queries_use_any_uuid_array(self):
        ws_a = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(side_effect=[[], []])
        await compute_setup_checklist_detail_bulk(conn, [{"id": ws_a}])
        first_call_args = conn.fetch.await_args_list[0].args
        assert first_call_args[1] == [ws_a]
        assert "ANY($1::uuid[])" in first_call_args[0]
