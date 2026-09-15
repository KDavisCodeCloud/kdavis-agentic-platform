"""
Coverage for MKT-LI1's image handling after the 2026-09-15 sequencing
fix (agents/marketing/mkt_li1_linkedin_brand.py v2.5): this agent no
longer selects or generates any image at draft time. image_brief and
image_description are always null on the queued row regardless of
format, and post_copy is always formatted with credit_line=None/
is_original=False -- there is nothing to credit yet. The real image
comes later, from api/routes/internal_marketing.py's approval
endpoints calling assets_library/scene_image_gen.py against the
post text a human has since approved (see test_internal_marketing_
approval_image_gen.py for that half).

This file replaces the pre-2026-09-15 asset-vault-wiring tests, which
covered draft-time asset_selector.select_asset() calls that no longer
exist in this module at all.

get_anthropic_client, run_compliance_guard, and queue_for_review are
mocked; this covers the wiring logic, not real LLM draft quality or a
real DB write.
"""
import json
from unittest.mock import MagicMock, patch

import agents.marketing.mkt_li1_linkedin_brand as li1

RESEARCH_REPORT = {"content_angles": [{"angle": "Why most HITL gates are theater"}]}


def _fake_draft_response(format_="text_post", topic="LLM guardrails"):
    payload = {
        "pillar": 1, "topic": topic, "hitl_tier": 2, "estimated_length": "medium",
        "post_copy": "Most engineers think guardrails are optional. They are not.",
        "hook_variants": [], "format": format_,
        "image_brief": None,
        "image_description": None,
        "carousel_slides": ["a", "b"] if format_ == "document_carousel" else None,
        "carousel_pdf_brief": {"concept": "x", "slide_count": 2, "style": "y"} if format_ == "document_carousel" else None,
        "notes": "",
    }
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps(payload))]
    return response


def _run(format_="text_post"):
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_draft_response(format_=format_)

    with patch("agents.marketing.mkt_li1_linkedin_brand.get_anthropic_client", return_value=fake_client), \
         patch("agents.marketing.mkt_li1_linkedin_brand.run_compliance_guard", return_value={"revised_content": None, "flags": []}), \
         patch("agents.marketing.mkt_li1_linkedin_brand.queue_for_review", side_effect=lambda item, **kw: {"id": "queued-1", **item}) as mock_queue, \
         patch("agents.marketing.mkt_li1_linkedin_brand.write_audit_log"), \
         patch("agents.marketing.mkt_li1_linkedin_brand.emit_event"):
        posts = li1.run_li1_brand_agent(
            research_report=RESEARCH_REPORT,
            idea_reservoir=[],
            kelvin_voice_profile={},
            build_updates=[],
        )
    return posts, mock_queue


def test_module_no_longer_imports_asset_selector_at_all():
    """The direct cause of the 2026-09-15 image-mismatch incident --
    asset_selector's loose topic-word matching converging multiple
    posts onto one shared image -- can't recur if this module never
    calls it. Asserts the import itself is gone, not just unused."""
    assert not hasattr(li1, "select_asset")
    assert not hasattr(li1, "_select_image_for_post")


def test_text_post_queues_with_null_image_brief_and_description():
    posts, _ = _run(format_="text_post")

    assert len(posts) == 1
    assert posts[0]["image_brief"] is None
    assert posts[0]["image_description"] is None


def test_text_post_copy_is_formatted_with_no_credit_line():
    posts, _ = _run(format_="text_post")

    # post_formatter still ran (sentence-per-line formatting), but with no
    # image to credit yet -- no credit line appended to the post body.
    assert "\n\n" in posts[0]["post_copy"]
    assert "Visual credit" not in posts[0]["post_copy"]


def test_carousel_format_also_queues_with_null_image_brief():
    posts, _ = _run(format_="document_carousel")

    assert posts[0]["format"] == "document_carousel"
    assert posts[0]["image_brief"] is None
    assert "\n\n" not in posts[0]["post_copy"]  # never ran through post_formatter


def test_queued_content_item_carries_the_final_formatted_copy_not_the_raw_draft():
    _, mock_queue = _run(format_="text_post")

    queued_item = mock_queue.call_args.args[0]
    assert "\n\n" in queued_item["post_copy"]
