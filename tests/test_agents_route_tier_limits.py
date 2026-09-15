"""
tests/test_agents_route_tier_limits.py
Tests for api/routes/agents.py's list_agents() (GET /agents) after
consolidating its tier-limit lookup onto core/compliance.py's
WorkspaceComplianceGuard.TIER_LIMITS -- previously a second, hand-
maintained dict here had drifted from compliance.py (enterprise was a
hardcoded fixed count instead of compliance.py's -1/unlimited semantics),
the same class of bug that made Agent 11 briefly Enterprise-only by
numbering accident (GAPS.md #14, #16).

Calls list_agents.__wrapped__ directly to bypass slowapi's @limiter.limit()
decorator, which needs a real ASGI request context to enforce -- same
direct-call pattern already used for webhook handlers in test_webhooks.py.
The route doesn't read anything off `request` itself (only the decorator
does), so a bare placeholder is enough.
"""

from types import SimpleNamespace

from api.routes.agents import list_agents


async def _list(tier: str) -> dict:
    workspace = {"id": "ws-1", "product_tier": tier}
    return await list_agents.__wrapped__(request=SimpleNamespace(), workspace=workspace)


class TestListAgentsTierLimits:
    async def test_starter_gets_exactly_three(self):
        result = await _list("starter")
        assert len(result["available_agents"]) == 3
        assert len(result["locked_agents"]) == 8
        assert [a["id"] for a in result["available_agents"]] == [
            "agent_01_cicd_triage", "agent_02_k8s_alert", "agent_03_pr_review",
        ]

    async def test_growth_gets_all_eleven(self):
        result = await _list("growth")
        assert len(result["available_agents"]) == 11
        assert len(result["locked_agents"]) == 0

    async def test_enterprise_unlimited_gets_all_eleven_not_ten(self):
        """Regression guard: max_agents=-1 sliced naively (all_agents[:-1])
        would silently drop the last agent (agent_11) instead of returning
        everything. Enterprise must see all 11, agent_11 included."""
        result = await _list("enterprise")
        assert len(result["available_agents"]) == 11
        assert len(result["locked_agents"]) == 0
        assert result["available_agents"][-1]["id"] == "agent_11_resource_health"

    async def test_agent_11_present_and_available_at_growth(self):
        result = await _list("growth")
        ids = [a["id"] for a in result["available_agents"]]
        assert "agent_11_resource_health" in ids

    async def test_agent_11_locked_at_starter(self):
        result = await _list("starter")
        locked_ids = [a["id"] for a in result["locked_agents"]]
        assert "agent_11_resource_health" in locked_ids

    async def test_unknown_tier_defaults_to_starter_limits(self):
        result = await _list("nonexistent_tier")
        assert len(result["available_agents"]) == 3
