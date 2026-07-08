"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

"""
chat_router_agent — routes dashboard AgentChat input to the correct
handler by keyword match, per CLAUDE.md's routing logic:
  metrics/product name keywords  -> portfolio_monitor
  content/post/write keywords    -> content_agent
  research/niche/icp keywords    -> research_agent
  build/agent/new product kws    -> gap_detector_agent (creates a card)
  anything else                  -> Claude think tank

Handlers are injected as callables, not imported directly — content_agent
and research_agent don't exist in this repo yet (only gap_detector_agent
and portfolio_monitor were built this session), so routing to them
returns a clear "handler_not_available" result instead of raising an
ImportError or silently doing nothing. This is the same deferred-wiring
pattern used across agents/internal/*.

When nothing matches, the query routes to the Claude think tank: the
caller-supplied claude_fn receives the query plus a PlatformContext
snapshot (current products, MRR, active agents — CLAUDE.md: "passes full
platform context"), and the response comes back labeled "Claude" with an
appended "Create agent recommendation from this response" option so the
dashboard can hand it straight to gap_detector_agent.
"""

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

KEYWORDS_METRICS = {"metrics", "mrr", "revenue", "churn", "signups", "conversion", "portfolio", "product"}
KEYWORDS_CONTENT = {"content", "post", "write", "draft", "linkedin", "headline", "copy"}
KEYWORDS_RESEARCH = {"research", "niche", "icp", "market", "competitor", "validate"}
KEYWORDS_BUILD = {"build", "agent", "gap", "missing", "recommend"}
# Multi-word phrase — checked separately from the single-token sets above,
# since "new product" as a token-set entry would never match a tokenized
# single word (CLAUDE.md: "build/agent/new product keywords").
BUILD_PHRASES = ["new product"]

# Order matters — first matching bucket wins, mirroring CLAUDE.md's listed
# priority order (metrics, content, research, build, else-Claude).
ROUTE_TABLE: list[tuple[str, set[str]]] = [
    ("portfolio_monitor", KEYWORDS_METRICS),
    ("content_agent", KEYWORDS_CONTENT),
    ("research_agent", KEYWORDS_RESEARCH),
    ("gap_detector_agent", KEYWORDS_BUILD),
]

CLAUDE_FALLBACK_OPTION = "Create agent recommendation from this response"


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


@dataclass(frozen=True)
class RoutingDecision:
    target: str
    matched_keywords: list[str]
    confidence: float


@dataclass(frozen=True)
class PlatformContext:
    products: list[str]
    portfolio_mrr: float
    active_agents: list[str]


def route(query: str) -> RoutingDecision:
    lowered = query.lower()
    tokens = _tokenize(query)

    matched_phrases = [p for p in BUILD_PHRASES if p in lowered]
    if matched_phrases:
        confidence = min(0.95, 0.5 + 0.15 * len(matched_phrases))
        return RoutingDecision(target="gap_detector_agent", matched_keywords=matched_phrases, confidence=confidence)

    for target, keywords in ROUTE_TABLE:
        matched = sorted(tokens & keywords)
        if matched:
            confidence = min(0.95, 0.5 + 0.15 * len(matched))
            return RoutingDecision(target=target, matched_keywords=matched, confidence=confidence)
    return RoutingDecision(target="claude_think_tank", matched_keywords=[], confidence=0.3)


class ChatRouterAgent:
    def __init__(
        self,
        handlers: Optional[dict[str, Callable[[str], dict]]] = None,
        claude_fn: Optional[Callable[[str, PlatformContext], str]] = None,
    ):
        """handlers: {target_name: callable(query) -> dict}. Only targets
        with a registered handler actually execute; anything else routes
        but returns a handler_not_available result instead of erroring."""
        self._handlers = handlers or {}
        self._claude_fn = claude_fn

    def handle(self, query: str, context: Optional[PlatformContext] = None) -> dict:
        decision = route(query)

        if decision.target == "claude_think_tank":
            return self._handle_claude_fallback(query, context)

        handler = self._handlers.get(decision.target)
        if handler is None:
            return {
                "routed_to": decision.target,
                "matched_keywords": decision.matched_keywords,
                "status": "handler_not_available",
                "message": f"'{decision.target}' is not wired into ChatRouterAgent yet.",
            }

        result = handler(query)
        return {
            "routed_to": decision.target,
            "matched_keywords": decision.matched_keywords,
            "status": "handled",
            "result": result,
        }

    def _handle_claude_fallback(self, query: str, context: Optional[PlatformContext]) -> dict:
        if self._claude_fn is None:
            return {
                "routed_to": "claude_think_tank",
                "status": "handler_not_available",
                "message": "No claude_fn registered — nothing routes to the think tank yet.",
            }

        response_text = self._claude_fn(query, context)
        return {
            "routed_to": "claude_think_tank",
            "label": "Claude",
            "status": "handled",
            "response": response_text,
            "context_used": context is not None,
            "options": [CLAUDE_FALLBACK_OPTION],
        }
