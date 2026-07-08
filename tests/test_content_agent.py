"""
Tests for agents/internal/content_agent.py.

llm_call is a plain injected callable (see content_agent.py docstring),
so these tests use a small keyword-routed stub instead of a real router
or network call — no LangGraph/asyncpg/stripe stubs from conftest.py are
needed since this module has no import-time dependency on any of that.

The research fixture below matches the exact dict shape
agents/internal/research_agent.py's ResearchAgent.run()["research"]
produces (and validate_research_schema checks) — not an invented shape.
"""

import copy
import json

from agents.internal.content_agent import ContentAgent

BASE_RESEARCH = {
    "niche": "manual Kubernetes cost audits",
    "icp": {
        "job_title": "Head of Platform",
        "company_size": "50-200 engineers",
        "tools_daily": ["Datadog", "Terraform", "kubectl"],
        "visual_environment": "Datadog meets Linear",
        "emotional_register": "ANALYTICAL",
        "trust_blockers": ["another dashboard nobody opens", "vendor lock-in"],
        "proof_format": "METRICS",
    },
    "pain_language": [
        "I spend every Friday afternoon reconciling the AWS bill by hand",
        "nobody trusts the cost numbers because they're always stale",
    ],
    "top_llm_queries": ["kubernetes cost audit tool", "fargate cost optimization"],
    "competitor_gaps": ["no one shows cost per namespace in real time"],
    "estimated_build_days": 12,
    "estimated_mrr_range": {"low": 2000, "high": 6000},
    "viability_score": 0.82,
    "design_brief_vars": {
        "pain_headline_options": [
            "Stop reconciling the AWS bill by hand every Friday",
            "Another dashboard nobody opens? Not this one.",
            "Kubernetes cost visibility, finally",
        ],
        "roi_number": "Save 6 hours a week on cost reconciliation",
        "proof_stat_1": "6 hours saved per engineer per week",
        "proof_stat_2": "94% cost anomalies caught before month-end",
        "proof_stat_3": "3 minute setup, no agent installs",
        "faq_questions": [
            "Does this replace our existing Datadog setup?",
            "How is this different from the AWS Cost Explorer?",
        ],
    },
}


def make_research(**overrides) -> dict:
    research = copy.deepcopy(BASE_RESEARCH)
    research.update(overrides)
    return research


def make_llm_stub(linkedin_body=None, faq_answer="Yes — it reads your existing Datadog tags directly.",
                   demo_narration="Narration beat."):
    def llm_call(prompt: str) -> str:
        if "LinkedIn post" in prompt:
            return linkedin_body if linkedin_body is not None else "Clean short before/after post with no banned phrases."
        if "Answer this FAQ question" in prompt:
            return faq_answer
        if "demo script narration" in prompt:
            return demo_narration
        return "generic completion"
    return llm_call


def test_rank_headlines_orders_by_pain_directness():
    research = make_research()
    agent = ContentAgent(llm_call=make_llm_stub())
    ranked = agent._rank_headlines(research)

    # "Stop reconciling the AWS bill by hand every Friday" shares >=3
    # significant words with a pain_language quote -> +2
    # "Another dashboard nobody opens? Not this one." shares >=3
    # significant words with a trust blocker -> +1
    # "Kubernetes cost visibility, finally" matches neither -> 0
    assert [item["headline"] for item in ranked] == [
        "Stop reconciling the AWS bill by hand every Friday",
        "Another dashboard nobody opens? Not this one.",
        "Kubernetes cost visibility, finally",
    ]
    assert ranked[0]["pain_directness_score"] == 2
    assert ranked[1]["pain_directness_score"] == 1
    assert ranked[2]["pain_directness_score"] == 0


def test_rank_headlines_ties_preserve_original_order():
    research = make_research(
        design_brief_vars={
            "pain_headline_options": ["Neutral headline A", "Neutral headline B", "Neutral headline C"],
            "roi_number": "x", "proof_stat_1": "a", "proof_stat_2": "b", "proof_stat_3": "c",
            "faq_questions": ["Q1?"],
        }
    )
    agent = ContentAgent(llm_call=make_llm_stub())
    ranked = agent._rank_headlines(research)
    assert [item["headline"] for item in ranked] == ["Neutral headline A", "Neutral headline B", "Neutral headline C"]


def test_build_package_validates_schema_and_raises_on_missing_field():
    research = make_research()
    del research["viability_score"]
    agent = ContentAgent(llm_call=make_llm_stub())
    try:
        agent.build_package(research, product_id="k8s-cost-audit")
        assert False, "expected ValueError for missing viability_score"
    except ValueError as exc:
        assert "viability_score" in str(exc)


def test_build_package_aeo_page_has_valid_faqpage_jsonld():
    research = make_research()
    agent = ContentAgent(llm_call=make_llm_stub(faq_answer="Yes, directly."))
    package = agent.build_package(research, product_id="k8s-cost-audit")

    aeo_page = package["aeo_page_markdown"]
    assert '<script type="application/ld+json">' in aeo_page

    json_block = aeo_page.split('<script type="application/ld+json">')[1].split("</script>")[0]
    schema = json.loads(json_block)

    assert schema["@type"] == "FAQPage"
    assert len(schema["mainEntity"]) == len(research["design_brief_vars"]["faq_questions"])
    assert schema["mainEntity"][0]["name"] == research["design_brief_vars"]["faq_questions"][0]
    assert schema["mainEntity"][0]["acceptedAnswer"]["text"] == "Yes, directly."


def test_linkedin_post_flags_buzzwords_and_over_limit():
    research = make_research()
    long_buzzy_body = ("This is a revolutionary approach. " + "word " * 160).strip()
    agent = ContentAgent(llm_call=make_llm_stub(linkedin_body=long_buzzy_body))
    package = agent.build_package(research, product_id="k8s-cost-audit")

    linkedin = package["linkedin_post"]
    assert linkedin["meets_word_limit"] is False
    assert "revolutionary" in linkedin["buzzword_flags"]
    assert any("linkedin_post" in flag for flag in package["buzzword_flags"])


def test_linkedin_post_clean_and_within_limit():
    research = make_research()
    agent = ContentAgent(llm_call=make_llm_stub(linkedin_body="Short clean before/after post, no banned phrases."))
    package = agent.build_package(research, product_id="k8s-cost-audit")

    linkedin = package["linkedin_post"]
    assert linkedin["meets_word_limit"] is True
    assert linkedin["buzzword_flags"] == []


def test_demo_script_has_three_beats_summing_to_60_seconds():
    research = make_research()
    agent = ContentAgent(llm_call=make_llm_stub())
    package = agent.build_package(research, product_id="k8s-cost-audit")

    demo = package["demo_script"]
    assert [s["section"] for s in demo["sections"]] == ["pain", "workflow", "outcome"]
    assert demo["total_seconds"] == 60


def test_design_brief_maps_icp_and_design_vars():
    research = make_research()
    agent = ContentAgent(llm_call=make_llm_stub())
    package = agent.build_package(research, product_id="k8s-cost-audit")

    brief = package["design_brief"]
    assert brief["job_title"] == "Head of Platform"
    assert brief["emotional_register"] == "ANALYTICAL"
    assert brief["proof_stats"] == [
        "6 hours saved per engineer per week",
        "94% cost anomalies caught before month-end",
        "3 minute setup, no agent installs",
    ]
    assert brief["faq_questions"] == research["design_brief_vars"]["faq_questions"]


def test_hitl_card_confidence_score_drops_with_buzzword_flags():
    research = make_research(viability_score=0.9)
    clean_agent = ContentAgent(llm_call=make_llm_stub(linkedin_body="Clean copy, no banned phrases at all."))
    clean_package = clean_agent.build_package(research, product_id="k8s-cost-audit")

    buzzy_agent = ContentAgent(llm_call=make_llm_stub(linkedin_body="This revolutionary game-changing tool helps."))
    buzzy_package = buzzy_agent.build_package(research, product_id="k8s-cost-audit")

    assert clean_package["hitl_card"]["confidence_score"] > buzzy_package["hitl_card"]["confidence_score"]
    assert buzzy_package["hitl_card"]["agent"] == "content_agent"
    assert {"approve_package", "modify", "hold", "reject"} == {
        opt["action"] for opt in buzzy_package["hitl_card"]["options"]
    }
