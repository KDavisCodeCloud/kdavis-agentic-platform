"""
tests/test_setup_checklist_core.py
24-gap-closure build, Phase 6 -- core/setup_checklist.py's
compute_setup_checklist, shared by api/routes/setup_checklist.py and
core/onboarding_sequence.py.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

from core.setup_checklist import compute_setup_checklist


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
