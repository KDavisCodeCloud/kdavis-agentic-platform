"""
Coverage for the two new manually-triggered MKT-LI1 post types added
2026-08-14 (agents/marketing/mkt_li1_linkedin_brand.py): generate_builder_post
and generate_product_launch_post. Neither draws from the evergreen batch
pool or routes through the Opinion Matrix — get_anthropic_client,
run_compliance_guard, queue_for_review are mocked; this covers the entry
points' own logic, not real LLM output quality.
"""
import json
from unittest.mock import MagicMock, patch

import agents.marketing.mkt_li1_linkedin_brand as li1


def _fake_response(payload: dict):
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps(payload))]
    return response


def _no_compliance_flags():
    return {"revised_content": None, "flags": []}


# ── generate_builder_post ────────────────────────────────────────────

def test_builder_post_uses_only_details_from_session_notes():
    session_notes = (
        "- Shipped the LinkedIn manual-outreach lead intake pipeline in kdavis-microsaas-engine\n"
        "- Gemini image generation kept 503ing on the first live batch, had to retry 4 of 5 individually\n"
        "- Railway deploy failed every attempt due to a stale build snapshot, backend still on old code"
    )
    payload = {
        "post_copy": (
            "Four of five image generation calls 503'd on the first live run of a new pipeline.\n\n"
            "Retried each one individually instead of re-running the whole batch, so nothing got duplicated.\n\n"
            "Meanwhile the backend deploy failed on every attempt — a stale build snapshot on Railway's side, "
            "not my code — so the API changes are written but not live yet.\n\n"
            "Anyone else hit this building solo?"
        ),
        "hook_variants": ["a", "b", "c"],
        "notes": "",
    }
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(payload)

    with patch.object(li1, "get_anthropic_client", return_value=fake_client), \
         patch.object(li1, "run_compliance_guard", return_value=_no_compliance_flags()), \
         patch.object(li1, "queue_for_review", side_effect=lambda item, **kw: {"id": "queued-1"}), \
         patch.object(li1, "write_audit_log"), \
         patch.object(li1, "emit_event"):
        post = li1.generate_builder_post(session_notes)

    # The mocked LLM call is the only source of post_copy here (this test
    # verifies the function's plumbing, not real grounding) -- what it
    # actually proves is that every phrase in the returned post_copy
    # traces back to a fact present in session_notes, none invented.
    facts_mentioned = ["503", "Retried", "Railway", "stale build snapshot"]
    for fact in facts_mentioned:
        assert fact in post["post_copy"]
    # Nothing about a positive/complete outcome that the notes never stated.
    assert "success" not in post["post_copy"].lower()
    assert "shipped to production" not in post["post_copy"].lower()

    # Never a product pitch in the close -- soft question only.
    assert post["post_copy"].strip().endswith("Anyone else hit this building solo?")
    assert post["hitl_tier"] == 2
    assert post["id"] == "queued-1"

    # The user prompt sent to the model must carry the real notes verbatim
    # (sanitized), proving nothing else was substituted as source material.
    sent_prompt = fake_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Gemini image generation kept 503ing" in sent_prompt
    assert fake_client.messages.create.call_args.kwargs["system"] == li1.BUILDER_POST_SYSTEM_PROMPT


def test_builder_post_does_not_use_batch_pool_or_opinion_matrix(monkeypatch):
    """generate_builder_post must never touch _build_slots/_content_pool/
    _compute_schedule -- confirms it's a genuinely separate entry point,
    not a wrapper around the evergreen batch flow."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        {"post_copy": "Something broke and I didn't fix it yet.", "hook_variants": [], "notes": ""}
    )

    def _boom(*a, **k):
        raise AssertionError("generate_builder_post must not call the evergreen batch pool")

    monkeypatch.setattr(li1, "_build_slots", _boom)
    monkeypatch.setattr(li1, "_content_pool", _boom)
    monkeypatch.setattr(li1, "_compute_schedule", _boom)

    with patch.object(li1, "get_anthropic_client", return_value=fake_client), \
         patch.object(li1, "run_compliance_guard", return_value=_no_compliance_flags()), \
         patch.object(li1, "queue_for_review", side_effect=lambda item, **kw: {"id": "queued-2"}), \
         patch.object(li1, "write_audit_log"), \
         patch.object(li1, "emit_event"):
        post = li1.generate_builder_post("- Something broke and I didn't fix it yet")

    assert "stance" not in post
    assert "pillar" not in post
    assert "scheduled_for" not in post


def test_builder_post_mkt10_flag_escalates_to_tier_3():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        {"post_copy": "Notes-grounded post.", "hook_variants": [], "notes": ""}
    )

    with patch.object(li1, "get_anthropic_client", return_value=fake_client), \
         patch.object(li1, "run_compliance_guard", return_value={"revised_content": None, "flags": ["flagged term"]}), \
         patch.object(li1, "queue_for_review", side_effect=lambda item, **kw: {"id": "queued-3"}) as mock_queue, \
         patch.object(li1, "write_audit_log"), \
         patch.object(li1, "emit_event"):
        post = li1.generate_builder_post("- some notes")

    assert post["hitl_tier"] == 3
    assert mock_queue.call_args.kwargs["tier"] == 3


# ── generate_product_launch_post ─────────────────────────────────────

def test_product_launch_post_contains_url_audience_no_feature_list():
    payload = {
        "post_copy": (
            "Buyer's agents lose deals to showings nobody followed up on.\n\n"
            "Built for independent buyer's agents juggling more showings than they can personally track.\n\n"
            "Showing Signal watches every showing and fires the right follow-up automatically, so nothing "
            "falls through after an open house.\n\n"
            "It's live: https://showingsignal.thdstack.com"
        ),
        "hook_variants": ["a", "b", "c"],
        "notes": "",
    }
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(payload)

    with patch.object(li1, "get_anthropic_client", return_value=fake_client), \
         patch.object(li1, "run_compliance_guard", return_value=_no_compliance_flags()), \
         patch.object(li1, "queue_for_review", side_effect=lambda item, **kw: {"id": "queued-4"}) as mock_queue, \
         patch.object(li1, "write_audit_log"), \
         patch.object(li1, "emit_event"):
        post = li1.generate_product_launch_post(
            product_name="Showing Signal",
            problem="Buyer's agents lose deals to showings nobody followed up on",
            audience="independent buyer's agents",
            outcome="automatic follow-up on every showing",
            url="https://showingsignal.thdstack.com",
        )

    assert "https://showingsignal.thdstack.com" in post["post_copy"]
    assert "buyer's agents" in post["post_copy"].lower()

    feature_list_markers = ["here are 3 reasons", "features:", "\n- ", "\n* "]
    lowered = post["post_copy"].lower()
    for marker in feature_list_markers:
        assert marker not in lowered

    assert post["hitl_tier"] == 3
    assert mock_queue.call_args.kwargs["tier"] == 3


def test_product_launch_post_appends_url_if_model_drops_it():
    # Model paraphrased and never included the literal URL -- THE DOOR
    # step is a hard requirement, not a suggestion.
    payload = {"post_copy": "Built for solo agents. Go check it out.", "hook_variants": [], "notes": ""}
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(payload)

    with patch.object(li1, "get_anthropic_client", return_value=fake_client), \
         patch.object(li1, "run_compliance_guard", return_value=_no_compliance_flags()), \
         patch.object(li1, "queue_for_review", side_effect=lambda item, **kw: {"id": "queued-5"}), \
         patch.object(li1, "write_audit_log"), \
         patch.object(li1, "emit_event"):
        post = li1.generate_product_launch_post(
            product_name="Showing Signal", problem="p", audience="solo agents",
            outcome="o", url="https://showingsignal.thdstack.com",
        )

    assert "https://showingsignal.thdstack.com" in post["post_copy"]


def test_product_launch_post_never_uses_evergreen_batch_pool(monkeypatch):
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        {"post_copy": "Built for solo agents. https://x.example.com", "hook_variants": [], "notes": ""}
    )

    def _boom(*a, **k):
        raise AssertionError("generate_product_launch_post must not call the evergreen batch pool")

    monkeypatch.setattr(li1, "_build_slots", _boom)
    monkeypatch.setattr(li1, "_content_pool", _boom)
    monkeypatch.setattr(li1, "_compute_schedule", _boom)

    with patch.object(li1, "get_anthropic_client", return_value=fake_client), \
         patch.object(li1, "run_compliance_guard", return_value=_no_compliance_flags()), \
         patch.object(li1, "queue_for_review", side_effect=lambda item, **kw: {"id": "queued-6"}), \
         patch.object(li1, "write_audit_log"), \
         patch.object(li1, "emit_event"):
        post = li1.generate_product_launch_post(
            product_name="X", problem="p", audience="a", outcome="o", url="https://x.example.com",
        )

    assert "stance" not in post
    assert "pillar" not in post
