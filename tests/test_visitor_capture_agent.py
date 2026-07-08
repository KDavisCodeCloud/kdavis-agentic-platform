"""
tests/test_visitor_capture_agent.py
Stub coverage for agents/internal/visitor_capture_agent.py.

What this file validates:
  - score_lead() scores a trial + direct-source lead higher than an
    email-only + paid-source lead
  - company size and pages_viewed both add to the score when present
  - process_incoming_lead() produces a decision card only for
    high_intent leads, with the exact "New high-intent trial: ..."
    message format CLAUDE.md specifies
  - process_incoming_lead() calls tag_fn with the score bucket included
    in the applied tags
  - low-intent leads get nurture="automatic" and no decision card
"""

from agents.internal.visitor_capture_agent import (
    CompanySizeEstimate,
    IncomingLead,
    VisitorCaptureAgent,
    score_lead,
)


def test_trial_direct_scores_higher_than_email_only_paid():
    trial_direct = score_lead(IncomingLead("p1", "a@b.com", "trial", "direct"))
    email_paid = score_lead(IncomingLead("p1", "c@d.com", "email_only", "paid"))
    assert trial_direct.score > email_paid.score


def test_company_size_and_pages_viewed_add_to_score():
    base = score_lead(IncomingLead("p1", "a@b.com", "trial", "direct"))
    enriched = score_lead(
        IncomingLead("p1", "a@b.com", "trial", "direct", pages_viewed=5),
        company_size=CompanySizeEstimate("acme.com", "201-1000", 0.8),
    )
    assert enriched.score > base.score


def test_high_intent_lead_gets_decision_card_with_exact_message_format():
    lead = IncomingLead("p1", "a@b.com", "trial", "direct", company="Acme", pages_viewed=5)
    result = VisitorCaptureAgent().process_incoming_lead(lead)
    assert result["bucket"] == "high_intent"
    assert result["decision_card"]["message"] == "New high-intent trial: a@b.com, Acme, direct"
    assert result["decision_card"]["options"] == ["reach_out_personally", "let_nurture_run", "flag_for_follow_up"]


def test_tag_fn_receives_bucket_in_applied_tags():
    captured = {}

    def fake_tag_fn(product_id, email, tags):
        captured["tags"] = tags

    lead = IncomingLead("p1", "a@b.com", "trial", "direct", pages_viewed=5)
    VisitorCaptureAgent().process_incoming_lead(lead, tag_fn=fake_tag_fn)
    assert "high_intent" in captured["tags"]


def test_low_intent_lead_has_no_decision_card_and_automatic_nurture():
    lead = IncomingLead("p1", "a@b.com", "email_only", "paid")
    result = VisitorCaptureAgent().process_incoming_lead(lead)
    assert result["decision_card"] is None
    assert result["nurture"] == "automatic"


def test_enrich_fn_not_called_when_email_has_no_domain():
    calls = []

    def enrich_fn(domain):
        calls.append(domain)
        return None

    lead = IncomingLead("p1", "not-an-email", "trial", "direct")
    VisitorCaptureAgent().process_incoming_lead(lead, enrich_fn=enrich_fn)
    assert calls == []
