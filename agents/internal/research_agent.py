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
research_agent — scores niche viability by scraping pain signal sources and
synthesizing them into the structured research JSON that gates a build/kill/
hold decision.

Pure orchestration + one LLM synthesis call routed through .llm/router.py.
Like the finance agents in this package, it does not extend
agents/base_agent.py (that class is built for the 10 commercial DevOps
agents — per-workspace billing, HITLGate, TokenBudgetGuard) and holds no
Supabase connection of its own. It returns a hitl_card dict; persisting that
to the hitl_queue table is the caller's responsibility in the integration
session that wires this into the live dashboard.

Reddit search has a public, unauthenticated JSON endpoint and is scraped for
real when live scraping is enabled. G2, LinkedIn, and Quora have no such
public API — the corresponding _scrape_* methods are stubs (env-gated, same
interface) until a real integration is built.
"""

import importlib.util
import json
import logging
import os
from pathlib import Path
from typing import Optional

import httpx

from security.sanitizer import shield as pii_shield

log = logging.getLogger(__name__)

LIVE_SCRAPING_ENABLED = os.getenv("ENABLE_LIVE_SCRAPING", "false").lower() == "true"

REQUIRED_TOP_LEVEL_FIELDS = [
    "niche", "icp", "pain_language", "top_llm_queries", "competitor_gaps",
    "estimated_build_days", "estimated_mrr_range", "viability_score",
    "design_brief_vars",
]
REQUIRED_ICP_FIELDS = [
    "job_title", "company_size", "tools_daily", "visual_environment",
    "emotional_register", "trust_blockers", "proof_format",
]
REQUIRED_DESIGN_BRIEF_FIELDS = [
    "pain_headline_options", "roi_number", "proof_stat_1", "proof_stat_2",
    "proof_stat_3", "faq_questions",
]

_SYSTEM_PROMPT = """You are a market research analyst for a micro-SaaS studio.
Given raw pain-point signal scraped from Reddit, G2, LinkedIn, and Quora for a
niche, extract the ICP, verbatim pain language, competitor gaps, and score
build viability. Respond with ONLY a JSON object matching this exact schema,
no markdown fences, no commentary:

{
  "niche": "string",
  "icp": {
    "job_title": "string",
    "company_size": "string",
    "tools_daily": ["string"],
    "visual_environment": "string",
    "emotional_register": "URGENT|ANALYTICAL|OPERATIONAL|ASPIRATIONAL",
    "trust_blockers": ["string"],
    "proof_format": "METRICS|ARCHITECTURE|PEER|CASE_STUDY"
  },
  "pain_language": ["exact quotes"],
  "top_llm_queries": ["string"],
  "competitor_gaps": ["string"],
  "estimated_build_days": number,
  "estimated_mrr_range": {"low": number, "high": number},
  "viability_score": number,
  "design_brief_vars": {
    "pain_headline_options": ["string"],
    "roi_number": "string",
    "proof_stat_1": "string",
    "proof_stat_2": "string",
    "proof_stat_3": "string",
    "faq_questions": ["string"]
  }
}
"""


def _load_router():
    router_path = Path(__file__).resolve().parent.parent.parent / ".llm" / "router.py"
    spec = importlib.util.spec_from_file_location("llm_router", router_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_research_schema(research: dict) -> None:
    """Raises ValueError describing exactly which fields are missing."""
    missing = [f for f in REQUIRED_TOP_LEVEL_FIELDS if f not in research]
    if missing:
        raise ValueError(f"research output missing top-level fields: {missing}")

    icp_missing = [f for f in REQUIRED_ICP_FIELDS if f not in research["icp"]]
    if icp_missing:
        raise ValueError(f"research output missing icp fields: {icp_missing}")

    dbv_missing = [
        f for f in REQUIRED_DESIGN_BRIEF_FIELDS if f not in research["design_brief_vars"]
    ]
    if dbv_missing:
        raise ValueError(f"research output missing design_brief_vars fields: {dbv_missing}")


class ResearchAgent:
    AGENT_NAME = "research_agent"

    def __init__(
        self,
        llm_complete=None,
        http_client: Optional[httpx.Client] = None,
    ):
        self._llm_complete = llm_complete or _load_router().complete
        self._http = http_client or httpx.Client(timeout=10.0)

    # ──────────────────────────────────────────────
    # Scrapers
    # ──────────────────────────────────────────────

    def _scrape_reddit(self, niche: str) -> list[str]:
        if not LIVE_SCRAPING_ENABLED:
            log.info("[research_agent] Live scraping disabled — skipping Reddit for %r", niche)
            return []
        resp = self._http.get(
            "https://www.reddit.com/search.json",
            params={"q": niche, "sort": "relevance", "limit": 25},
            headers={"User-Agent": "kdavis-research-agent/1.0"},
        )
        resp.raise_for_status()
        children = resp.json().get("data", {}).get("children", [])
        return [
            (c["data"].get("selftext") or c["data"].get("title") or "")
            for c in children
        ]

    def _scrape_g2(self, niche: str) -> list[str]:
        log.info("[research_agent] G2 scraping not yet implemented — skipping %r", niche)
        return []

    def _scrape_linkedin(self, niche: str) -> list[str]:
        log.info("[research_agent] LinkedIn scraping not yet implemented — skipping %r", niche)
        return []

    def _scrape_quora(self, niche: str) -> list[str]:
        log.info("[research_agent] Quora scraping not yet implemented — skipping %r", niche)
        return []

    # ──────────────────────────────────────────────
    # Synthesis
    # ──────────────────────────────────────────────

    def _synthesize(self, niche: str, hypothesis: Optional[str], scraped: dict) -> dict:
        raw_signal = "\n\n".join(
            f"--- {source} ---\n" + "\n".join(texts)
            for source, texts in scraped.items()
            if texts
        )
        sanitized_signal, _ = pii_shield.sanitize(raw_signal)

        user_content = f"Niche: {niche}\n"
        if hypothesis:
            user_content += f"Hypothesis: {hypothesis}\n"
        user_content += f"\nScraped signal:\n{sanitized_signal or '(no live scraping data — reason from niche/hypothesis alone)'}"

        response = self._llm_complete(
            task_type="assessment_generation",
            messages=[{"role": "user", "content": user_content}],
            system_prompt=_SYSTEM_PROMPT,
        )

        clean = response.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            research = json.loads(clean)
        except json.JSONDecodeError as exc:
            raise ValueError(f"research_agent LLM response was not valid JSON: {exc} — raw: {response[:300]}") from exc

        validate_research_schema(research)
        return research

    # ──────────────────────────────────────────────
    # HITL
    # ──────────────────────────────────────────────

    def _build_hitl_card(self, niche: str, research: dict) -> dict:
        return {
            "status": "pending_approval",
            "options": ["approve_to_build", "kill", "hold"],
            "summary": f"Research complete for niche '{niche}' — viability_score={research['viability_score']}",
            "payload": research,
        }

    # ──────────────────────────────────────────────
    # Entry point
    # ──────────────────────────────────────────────

    def run(self, niche: str, hypothesis: Optional[str] = None) -> dict:
        if not niche or not niche.strip():
            raise ValueError("niche is required")

        scraped = {
            "reddit": self._scrape_reddit(niche),
            "g2": self._scrape_g2(niche),
            "linkedin": self._scrape_linkedin(niche),
            "quora": self._scrape_quora(niche),
        }

        research = self._synthesize(niche, hypothesis, scraped)

        return {
            "research": research,
            "hitl_card": self._build_hitl_card(niche, research),
        }
