"""
tests/test_chat_router_agent.py
Stub coverage for agents/internal/chat_router_agent.py.

What this file validates:
  - route() matches each documented keyword bucket in priority order
    (metrics, content, research, build/new-product, else-Claude)
  - the "new product" multi-word phrase routes to gap_detector_agent
    even though it can't match as a single token
  - handle() returns handler_not_available for a routed target with no
    registered handler, instead of raising
  - handle() falls back to claude_fn with a PlatformContext and appends
    the "Create agent recommendation from this response" option
"""

from agents.internal.chat_router_agent import (
    CLAUDE_FALLBACK_OPTION,
    ChatRouterAgent,
    PlatformContext,
    route,
)


def test_route_metrics_keywords():
    assert route("what's our MRR this month?").target == "portfolio_monitor"


def test_route_content_keywords():
    assert route("write a LinkedIn post about the launch").target == "content_agent"


def test_route_research_keywords():
    assert route("research the ICP for this niche").target == "research_agent"


def test_route_new_product_phrase_routes_to_gap_detector():
    decision = route("thinking about a new product idea")
    assert decision.target == "gap_detector_agent"
    assert "new product" in decision.matched_keywords


def test_route_unmatched_query_falls_back_to_claude():
    assert route("what do you think about the meaning of life").target == "claude_think_tank"


def test_handle_returns_not_available_without_registered_handler():
    router = ChatRouterAgent(handlers={})
    result = router.handle("what's our MRR?")
    assert result["status"] == "handler_not_available"
    assert result["routed_to"] == "portfolio_monitor"


def test_handle_dispatches_to_registered_handler():
    router = ChatRouterAgent(handlers={"portfolio_monitor": lambda q: {"mrr": 1000}})
    result = router.handle("show me MRR")
    assert result["status"] == "handled"
    assert result["result"] == {"mrr": 1000}


def test_handle_claude_fallback_includes_recommendation_option():
    captured = {}

    def fake_claude(query, context):
        captured["query"] = query
        captured["context"] = context
        return "here's my analysis"

    router = ChatRouterAgent(claude_fn=fake_claude)
    context = PlatformContext(products=["p1"], portfolio_mrr=1000.0, active_agents=["research_agent"])
    result = router.handle("what's the meaning of scaling a micro-SaaS?", context=context)

    assert result["label"] == "Claude"
    assert CLAUDE_FALLBACK_OPTION in result["options"]
    assert captured["context"] is context
