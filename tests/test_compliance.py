"""
tests/test_compliance.py
Tests for core/compliance.py's WorkspaceComplianceGuard -- previously had
zero test coverage. Added while fixing a real gap: TIER_LIMITS gates
purely on the numeric position extracted from agent_id
(_extract_agent_number), so adding Agent 11 without bumping growth's
max_agents from 10 to 11 would have silently made it Enterprise-only by
numbering coincidence, not by deliberate pricing decision.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from core.compliance import SubscriptionError, WorkspaceComplianceGuard


def _mock_conn(tier: str, cloud_providers: list | None = None):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"product_tier": tier, "cloud_providers": cloud_providers or []})
    return conn


class TestAssertAgentPermitted:
    async def test_agent_11_permitted_at_growth_tier(self):
        guard = WorkspaceComplianceGuard(_mock_conn("growth"))
        await guard.assert_agent_permitted(str(uuid4()), "agent_11_resource_health")  # must not raise

    async def test_agent_11_permitted_at_enterprise_tier(self):
        guard = WorkspaceComplianceGuard(_mock_conn("enterprise"))
        await guard.assert_agent_permitted(str(uuid4()), "agent_11_resource_health")  # must not raise

    async def test_agent_11_blocked_at_starter_tier(self):
        guard = WorkspaceComplianceGuard(_mock_conn("starter"))
        with pytest.raises(SubscriptionError):
            await guard.assert_agent_permitted(str(uuid4()), "agent_11_resource_health")

    async def test_agent_04_still_permitted_at_growth_tier(self):
        """Regression check: bumping growth's cap to 11 must not change
        anything for the original 10-agent roster."""
        guard = WorkspaceComplianceGuard(_mock_conn("growth"))
        await guard.assert_agent_permitted(str(uuid4()), "agent_04_migration")  # must not raise

    async def test_agent_01_permitted_at_starter_tier(self):
        guard = WorkspaceComplianceGuard(_mock_conn("starter"))
        await guard.assert_agent_permitted(str(uuid4()), "agent_01_cicd_triage")  # must not raise

    async def test_agent_04_blocked_at_starter_tier(self):
        guard = WorkspaceComplianceGuard(_mock_conn("starter"))
        with pytest.raises(SubscriptionError):
            await guard.assert_agent_permitted(str(uuid4()), "agent_04_migration")

    async def test_cloud_provider_not_configured_blocked(self):
        guard = WorkspaceComplianceGuard(_mock_conn("growth", cloud_providers=["aws"]))
        with pytest.raises(SubscriptionError):
            await guard.assert_agent_permitted(str(uuid4()), "agent_02_k8s_alert", cloud_provider="azure")

    async def test_cloud_provider_configured_permitted(self):
        guard = WorkspaceComplianceGuard(_mock_conn("growth", cloud_providers=["aws", "azure"]))
        await guard.assert_agent_permitted(str(uuid4()), "agent_02_k8s_alert", cloud_provider="azure")

    async def test_unlimited_cloud_providers_at_enterprise(self):
        guard = WorkspaceComplianceGuard(_mock_conn("enterprise", cloud_providers=[]))
        await guard.assert_agent_permitted(str(uuid4()), "agent_02_k8s_alert", cloud_provider="gcp")

    async def test_unknown_workspace_raises(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        guard = WorkspaceComplianceGuard(conn)
        with pytest.raises(SubscriptionError):
            await guard.assert_agent_permitted(str(uuid4()), "agent_01_cicd_triage")


class TestTierLimitsRetentionDays:
    """
    Phase 12, scale-readiness build. core/retention.py reads
    retention_days directly off TIER_LIMITS -- this pins the single-
    source-of-truth values so a future edit here can't silently change
    what gets deleted without a test noticing (same GAPS.md #16 drift
    class this dict already exists to prevent for agent/repo/cloud caps).
    """

    def test_starter_retention_is_90_days(self):
        assert WorkspaceComplianceGuard.TIER_LIMITS["starter"]["retention_days"] == 90

    def test_growth_retention_is_365_days(self):
        assert WorkspaceComplianceGuard.TIER_LIMITS["growth"]["retention_days"] == 365

    def test_enterprise_retention_is_unlimited(self):
        assert WorkspaceComplianceGuard.TIER_LIMITS["enterprise"]["retention_days"] == -1


class TestTierLimitsMaxSeats:
    """Membership plan, Phase B. Same single-source-of-truth pinning as
    TestTierLimitsRetentionDays above, for max_seats."""

    def test_starter_max_seats_is_3(self):
        assert WorkspaceComplianceGuard.TIER_LIMITS["starter"]["max_seats"] == 3

    def test_growth_max_seats_is_15(self):
        assert WorkspaceComplianceGuard.TIER_LIMITS["growth"]["max_seats"] == 15

    def test_enterprise_max_seats_is_unlimited(self):
        assert WorkspaceComplianceGuard.TIER_LIMITS["enterprise"]["max_seats"] == -1


class TestAssertSeatAvailable:
    def _mock_conn(self, tier, seats_used):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"product_tier": tier},
            {"n": seats_used},
        ])
        return conn

    async def test_under_cap_permitted(self):
        guard = WorkspaceComplianceGuard(self._mock_conn("starter", 2))
        await guard.assert_seat_available(str(uuid4()))  # must not raise

    async def test_at_cap_blocked(self):
        guard = WorkspaceComplianceGuard(self._mock_conn("starter", 3))
        with pytest.raises(SubscriptionError):
            await guard.assert_seat_available(str(uuid4()))

    async def test_over_cap_blocked(self):
        guard = WorkspaceComplianceGuard(self._mock_conn("starter", 4))
        with pytest.raises(SubscriptionError):
            await guard.assert_seat_available(str(uuid4()))

    async def test_enterprise_always_permitted(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"product_tier": "enterprise"})
        guard = WorkspaceComplianceGuard(conn)
        await guard.assert_seat_available(str(uuid4()))  # must not raise
        # unlimited tier short-circuits before the seat-count query
        assert conn.fetchrow.await_count == 1

    async def test_unknown_workspace_raises(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        guard = WorkspaceComplianceGuard(conn)
        with pytest.raises(SubscriptionError):
            await guard.assert_seat_available(str(uuid4()))
