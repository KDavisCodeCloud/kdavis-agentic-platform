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
content_agent — turns an approved research_agent brief into one content
package: an AEO page draft, ranked landing headlines, a LinkedIn post, a
demo script outline, and a populated Claude Design brief. CLAUDE.md
Phase 2, step 20. Routes the whole package to HITL as one approval card
with preview — this module never publishes anything itself.

Input is the plain `research` dict research_agent.ResearchAgent.run()
produces (research_agent.py, built earlier this session) — same shape
validate_research_schema checks, reused here rather than re-declaring a
parallel schema.

llm_call is injected, not imported: this module has zero import-time
dependency on .llm/router.py, core/, or agents/base_agent.py, matching
the pure-module convention already established by finance/__init__.py
and research_agent.py itself. Wire the real router in the integration
session, e.g.:

    from agents.base_agent import _load_router
    router = _load_router()
    agent = ContentAgent(llm_call=lambda prompt: router.complete(prompt))

Tests inject a deterministic stub instead, so this agent is fully
testable without a live LLM call.
"""

import json
import re
from typing import Callable

from agents.internal._copy_rules import scan_buzzwords, word_count
from agents.internal.research_agent import validate_research_schema

LLMCallFn = Callable[[str], str]

LINKEDIN_WORD_LIMIT = 150
_WORD_RE = re.compile(r"[a-z']+")
# Minimum shared significant (>3 char) words for a headline to count as
# "naming" a pain quote or trust blocker — full-sentence substring
# matching never fires since headlines are short paraphrases, not quotes.
_MIN_SHARED_WORDS = 3
DEMO_SCRIPT_PLAN = (
    # (section, seconds, prompt_brief_template)
    ("pain", 15, "Show the exact broken workflow a {job_title} lives in today for {niche}."),
    ("workflow", 30, "Show the agent doing the work end-to-end, using real search language: {queries}."),
    ("outcome", 15, "Show the measurable outcome: {roi_number}."),
)


class ContentAgent:
    def __init__(self, llm_call: LLMCallFn):
        self._llm_call = llm_call

    def build_package(self, research: dict, product_id: str) -> dict:
        validate_research_schema(research)

        headlines = self._rank_headlines(research)
        top_headline = headlines[0]["headline"] if headlines else research["niche"]

        aeo_page = self._build_aeo_page(research, top_headline)
        linkedin_post = self._build_linkedin_post(research)
        demo_script = self._build_demo_script(research)
        design_brief = self._build_design_brief(research)

        buzzword_flags = (
            [f"aeo_page: {phrase}" for phrase in scan_buzzwords(aeo_page)]
            + [f"linkedin_post: {phrase}" for phrase in linkedin_post["buzzword_flags"]]
        )

        return {
            "product_id": product_id,
            "niche": research["niche"],
            "landing_headlines": headlines,
            "aeo_page_markdown": aeo_page,
            "linkedin_post": linkedin_post,
            "demo_script": demo_script,
            "design_brief": design_brief,
            "buzzword_flags": buzzword_flags,
            "hitl_card": self._build_hitl_card(research, product_id, buzzword_flags),
        }

    def _significant_words(self, text: str) -> set[str]:
        return {word for word in _WORD_RE.findall(text.lower()) if len(word) > 3}

    def _shares_significant_words(self, headline_words: set[str], phrase: str) -> bool:
        return len(headline_words & self._significant_words(phrase)) >= _MIN_SHARED_WORDS

    def _pain_directness_score(self, headline: str, research: dict) -> int:
        headline_words = self._significant_words(headline)
        score = 0
        for quote in research["pain_language"]:
            if self._shares_significant_words(headline_words, quote):
                score += 2
        for blocker in research["icp"]["trust_blockers"]:
            if self._shares_significant_words(headline_words, blocker):
                score += 1
        return score

    def _rank_headlines(self, research: dict) -> list[dict]:
        scored = [
            {"headline": headline, "pain_directness_score": self._pain_directness_score(headline, research)}
            for headline in research["design_brief_vars"]["pain_headline_options"]
        ]
        # sorted() is stable — ties keep their original relative order.
        ranked = sorted(scored, key=lambda item: item["pain_directness_score"], reverse=True)
        return ranked[:5]

    def _build_aeo_page(self, research: dict, top_headline: str) -> str:
        icp = research["icp"]
        design_brief_vars = research["design_brief_vars"]

        faq_items = [
            (question, self._llm_call(
                f"Answer this FAQ question in one direct sentence first, for a "
                f"{icp['job_title']} considering a tool that replaces "
                f"'{research['niche']}'. Question: {question}"
            ))
            for question in design_brief_vars["faq_questions"]
        ]

        faq_schema = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": question,
                    "acceptedAnswer": {"@type": "Answer", "text": answer},
                }
                for question, answer in faq_items
            ],
        }

        proof_strip = "\n".join(
            f"- {stat}"
            for stat in (
                design_brief_vars["proof_stat_1"],
                design_brief_vars["proof_stat_2"],
                design_brief_vars["proof_stat_3"],
            )
        )
        problem_section = "\n\n".join(f"> {quote}" for quote in research["pain_language"])
        faq_markdown = "\n\n".join(f"### {question}\n{answer}" for question, answer in faq_items)

        return (
            f"# {top_headline}\n\n"
            f"{design_brief_vars['roi_number']}\n\n"
            f"## Proof\n{proof_strip}\n\n"
            f"## The problem\n{problem_section}\n\n"
            f"## FAQ\n{faq_markdown}\n\n"
            f'<script type="application/ld+json">\n{json.dumps(faq_schema, indent=2)}\n</script>\n'
        )

    def _build_linkedin_post(self, research: dict) -> dict:
        prompt = (
            f"Write a LinkedIn post in before/after format for {research['icp']['job_title']}s dealing "
            f"with: {research['niche']}. Before: the painful workflow today. After: the outcome once "
            f"solved. Under {LINKEDIN_WORD_LIMIT} words. No buzzwords "
            f"('AI-powered', 'revolutionary', 'game-changing')."
        )
        body = self._llm_call(prompt)
        return {
            "body": body,
            "word_count": word_count(body),
            "meets_word_limit": word_count(body) <= LINKEDIN_WORD_LIMIT,
            "buzzword_flags": scan_buzzwords(body),
        }

    def _build_demo_script(self, research: dict) -> dict:
        icp = research["icp"]
        sections = []
        for name, seconds, brief_template in DEMO_SCRIPT_PLAN:
            brief = brief_template.format(
                job_title=icp["job_title"],
                niche=research["niche"],
                queries=", ".join(research["top_llm_queries"]),
                roi_number=research["design_brief_vars"]["roi_number"],
            )
            narration = self._llm_call(f"Write demo script narration (~{seconds}s) for the '{name}' beat: {brief}")
            sections.append({"section": name, "seconds": seconds, "narration": narration})
        return {"total_seconds": sum(s["seconds"] for s in sections), "sections": sections}

    def _build_design_brief(self, research: dict) -> dict:
        icp = research["icp"]
        design_brief_vars = research["design_brief_vars"]
        return {
            "product_name": research["niche"],
            "job_title": icp["job_title"],
            "company_size": icp["company_size"],
            "tools_daily": list(icp["tools_daily"]),
            "visual_reference": icp["visual_environment"],
            "emotional_register": icp["emotional_register"],
            "trust_blockers": list(icp["trust_blockers"]),
            "proof_format": icp["proof_format"],
            "roi_number": design_brief_vars["roi_number"],
            "proof_stats": [
                design_brief_vars["proof_stat_1"],
                design_brief_vars["proof_stat_2"],
                design_brief_vars["proof_stat_3"],
            ],
            "faq_questions": list(design_brief_vars["faq_questions"]),
        }

    def _confidence_score(self, research: dict, buzzword_flags: list[str]) -> float:
        score = max(0.0, min(1.0, research["viability_score"])) - (0.05 * len(buzzword_flags))
        return round(max(0.0, min(1.0, score)), 2)

    def _build_hitl_card(self, research: dict, product_id: str, buzzword_flags: list[str]) -> dict:
        return {
            "agent": "content_agent",
            "type": "RECOMMENDATION",
            "product_id": product_id,
            "what_happened": f"Content package drafted for '{research['niche']}' from the approved research brief.",
            "why_it_matters": (
                "Feeds the landing page, AEO page, launch LinkedIn post, and demo script for this product."
            ),
            "options": [
                {"label": "Approve package", "action": "approve_package"},
                {"label": "Modify", "action": "modify"},
                {"label": "Hold", "action": "hold"},
                {"label": "Reject", "action": "reject"},
            ],
            "confidence_score": self._confidence_score(research, buzzword_flags),
        }
