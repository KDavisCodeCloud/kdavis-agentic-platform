"""
Tests for agents/internal/email_sequence_agent.py.

Same injected-callable approach as test_content_agent.py — no router,
no Supabase, no GitHub Actions call. approve_sequence() is checked
against the exact workflow_dispatch input shape defined in
.github/workflows/email-sequence-deploy.yml. The research fixture
matches the dict shape agents/internal/research_agent.py actually
produces.
"""

import copy

from agents.internal.email_sequence_agent import (
    DEFAULT_WORD_LIMIT,
    EMAIL_ONLY_NURTURE_PLAN,
    POST_CHURN_WINBACK_PLAN,
    REENGAGEMENT_WORD_LIMIT,
    TRIAL_NURTURE_PLAN,
    EmailSequenceAgent,
)

BASE_RESEARCH = {
    "niche": "manual Kubernetes cost audits",
    "icp": {
        "job_title": "Head of Platform",
        "company_size": "50-200 engineers",
        "tools_daily": ["Datadog", "Terraform"],
        "visual_environment": "Datadog meets Linear",
        "emotional_register": "ANALYTICAL",
        "trust_blockers": ["another dashboard nobody opens"],
        "proof_format": "METRICS",
    },
    "pain_language": ["I spend every Friday afternoon reconciling the AWS bill by hand"],
    "top_llm_queries": ["kubernetes cost audit tool"],
    "competitor_gaps": ["no one shows cost per namespace in real time"],
    "estimated_build_days": 12,
    "estimated_mrr_range": {"low": 2000, "high": 6000},
    "viability_score": 0.82,
    "design_brief_vars": {
        "pain_headline_options": ["Stop reconciling the AWS bill by hand"],
        "roi_number": "Save 6 hours a week",
        "proof_stat_1": "6 hours saved per week",
        "proof_stat_2": "94% anomalies caught",
        "proof_stat_3": "3 minute setup",
        "faq_questions": ["Does this replace Datadog?"],
    },
}


def make_research(**overrides) -> dict:
    research = copy.deepcopy(BASE_RESEARCH)
    research.update(overrides)
    return research


def make_llm_stub(subject="Quick question", body=None, cta="Start your free trial"):
    default_body = "Short plain-text email body with no banned phrases in it at all."

    def llm_call(prompt: str) -> str:
        if "Write only the subject line" in prompt:
            return subject
        if "Write only the single call-to-action" in prompt:
            return cta
        if "Write the email body" in prompt:
            return body if body is not None else default_body
        return "generic completion"
    return llm_call


def test_draft_all_sequences_validates_schema_and_raises_on_missing_field():
    research = make_research()
    del research["estimated_build_days"]
    agent = EmailSequenceAgent(llm_call=make_llm_stub())
    try:
        agent.draft_all_sequences(research, product_id="k8s-cost-audit")
        assert False, "expected ValueError for missing estimated_build_days"
    except ValueError as exc:
        assert "estimated_build_days" in str(exc)


def test_trial_nurture_sequence_has_fourteen_emails_in_spec_order():
    research = make_research()
    agent = EmailSequenceAgent(llm_call=make_llm_stub())
    package = agent.draft_all_sequences(research, product_id="k8s-cost-audit")

    trial = package["sequences"]["trial_nurture"]
    assert len(trial["emails"]) == len(TRIAL_NURTURE_PLAN) == 14
    assert [e["day"] for e in trial["emails"]] == [day for day, _ in TRIAL_NURTURE_PLAN]
    assert trial["max_words"] == DEFAULT_WORD_LIMIT


def test_email_only_and_winback_sequence_lengths():
    research = make_research()
    agent = EmailSequenceAgent(llm_call=make_llm_stub())
    package = agent.draft_all_sequences(research, product_id="k8s-cost-audit")

    assert len(package["sequences"]["email_only_nurture"]["emails"]) == len(EMAIL_ONLY_NURTURE_PLAN) == 5
    assert len(package["sequences"]["post_churn_winback"]["emails"]) == len(POST_CHURN_WINBACK_PLAN) == 4


def test_post_churn_winback_uses_reengagement_word_limit():
    research = make_research()
    agent = EmailSequenceAgent(llm_call=make_llm_stub())
    package = agent.draft_all_sequences(research, product_id="k8s-cost-audit")

    winback = package["sequences"]["post_churn_winback"]
    assert winback["max_words"] == REENGAGEMENT_WORD_LIMIT
    assert all(email["word_count"] <= REENGAGEMENT_WORD_LIMIT for email in winback["emails"])


def test_email_flags_buzzwords_and_over_word_limit():
    research = make_research()
    long_buzzy_body = "This is a revolutionary game-changing tool. " + "word " * 200
    agent = EmailSequenceAgent(llm_call=make_llm_stub(body=long_buzzy_body))
    package = agent.draft_all_sequences(research, product_id="k8s-cost-audit")

    email = package["sequences"]["trial_nurture"]["emails"][0]
    assert email["meets_word_limit"] is False
    assert "revolutionary" in email["buzzword_flags"]
    assert "game-changing" in email["buzzword_flags"]


def test_email_clean_and_within_limit():
    research = make_research()
    agent = EmailSequenceAgent(llm_call=make_llm_stub())
    package = agent.draft_all_sequences(research, product_id="k8s-cost-audit")

    email = package["sequences"]["trial_nurture"]["emails"][0]
    assert email["meets_word_limit"] is True
    assert email["buzzword_flags"] == []
    assert email["status"] == "pending"
    assert email["subject"] == "Quick question"
    assert email["cta"] == "Start your free trial"


def test_hitl_card_lists_all_action_options_and_total_email_count():
    research = make_research()
    agent = EmailSequenceAgent(llm_call=make_llm_stub())
    package = agent.draft_all_sequences(research, product_id="k8s-cost-audit")

    card = package["hitl_card"]
    assert card["agent"] == "email_sequence_agent"
    assert card["product_id"] == "k8s-cost-audit"
    assert "23 emails" in card["what_happened"]
    assert {"approve_email", "modify_email", "hold_email", "reject_email", "approve_sequence"} == {
        opt["action"] for opt in card["options"]
    }


def test_approve_sequence_returns_deploy_dispatch_payload_matching_workflow_inputs():
    agent = EmailSequenceAgent(llm_call=make_llm_stub())
    payload = agent.approve_sequence(
        sequence_name="trial_nurture", product_id="k8s-cost-audit", sequence_id="seq_123"
    )

    assert payload["workflow"] == "email-sequence-deploy.yml"
    assert payload["inputs"] == {"product_id": "k8s-cost-audit", "sequence_id": "seq_123"}
    assert payload["sequence_name"] == "trial_nurture"
