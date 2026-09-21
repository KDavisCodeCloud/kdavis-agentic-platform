"""
Coverage for MKT-LI1's image handling after the 2026-09-21 revert (v2.7
of agents/marketing/mkt_li1_linkedin_brand.py): this agent generates and
attaches a real image to every text_post draft BEFORE it queues for
review, via _attach_generated_image -> assets_library/scene_image_gen.
generate_relevant_image. Kelvin's correction of the 2026-09-15 change:
"I need to be able to approve the images and I was able to do so in
previous deployments. that needs to continue to take place before
approval, not after." He reviews and approves the image together with
the caption; a row never reaches pending_review without one, barring a
generation failure (image_brief stays null, a note is appended, and the
post still queues rather than blocking on an image-pipeline problem).

This file replaces the pre-2026-09-21 version, which asserted the
opposite (image_brief always null at draft time) — that assertion no
longer reflects a valid state for this module except in explicit
failure-path tests.

The pre-2026-09-15 asset-vault-wiring tests (asset_selector.select_asset
matching) still don't apply here — that module is never called, this
generates a bespoke image via scene_image_gen.py instead. See
test_internal_marketing_approval_image_gen.py for the now-fallback-only
post-approval path.

get_anthropic_client, run_compliance_guard, queue_for_review, and
generate_relevant_image are mocked; this covers the wiring logic, not
real LLM draft quality, real image generation, or a real DB write.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import agents.marketing.mkt_li1_linkedin_brand as li1

RESEARCH_REPORT = {"content_angles": [{"angle": "Why most HITL gates are theater"}]}

FAKE_ASSETS_ROOT = Path("/fake/assets_library")
FAKE_IMAGE_RESULT = {
    "image_path": FAKE_ASSETS_ROOT / "my_originals" / "llm-guardrails" / "llm-guardrails_20260921.png",
    "scene_description": "A developer reviewing a guardrail dashboard.",
    "scene_type": "TECHNICAL",
    "attempts": 1,
    "relevant": True,
    "reason": "subject matches, text legible",
    "flagged_for_review": False,
}


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


def _run(format_="text_post", image_result=None, image_side_effect=None):
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_draft_response(format_=format_)

    with patch("agents.marketing.mkt_li1_linkedin_brand.get_anthropic_client", return_value=fake_client), \
         patch("agents.marketing.mkt_li1_linkedin_brand.run_compliance_guard", return_value={"revised_content": None, "flags": []}), \
         patch("agents.marketing.mkt_li1_linkedin_brand.queue_for_review", side_effect=lambda item, **kw: {"id": "queued-1", **item}) as mock_queue, \
         patch("agents.marketing.mkt_li1_linkedin_brand.write_audit_log"), \
         patch("agents.marketing.mkt_li1_linkedin_brand.emit_event"), \
         patch("assets_library.gemini_image_gen.ASSETS_ROOT", FAKE_ASSETS_ROOT), \
         patch(
             "assets_library.scene_image_gen.generate_relevant_image",
             return_value=image_result or FAKE_IMAGE_RESULT,
             side_effect=image_side_effect,
         ) as mock_generate:
        posts = li1.run_li1_brand_agent(
            research_report=RESEARCH_REPORT,
            idea_reservoir=[],
            kelvin_voice_profile={},
            build_updates=[],
        )
    return posts, mock_queue, mock_generate


def test_module_no_longer_imports_asset_selector_at_all():
    """The direct cause of the 2026-09-15 image-mismatch incident --
    asset_selector's loose topic-word matching converging multiple
    posts onto one shared image -- can't recur if this module never
    calls it. The 2026-09-21 revert restored draft-time generation but
    still never re-introduces asset_selector; the real fix (bespoke
    scene-gated generation) stands independently of when it fires."""
    assert not hasattr(li1, "select_asset")
    assert not hasattr(li1, "_select_image_for_post")


def test_text_post_queues_with_a_real_generated_image_brief():
    posts, _, mock_generate = _run(format_="text_post")

    assert len(posts) == 1
    mock_generate.assert_called_once()
    brief = posts[0]["image_brief"]
    assert brief is not None
    assert brief["image_path"] == "assets_library/my_originals/llm-guardrails/llm-guardrails_20260921.png"
    assert brief["is_original"] is True
    assert "pre-review" in brief["selected_because"]
    assert posts[0]["image_description"] == FAKE_IMAGE_RESULT["scene_description"]


def test_carousel_format_never_calls_image_generation():
    posts, _, mock_generate = _run(format_="document_carousel")

    assert posts[0]["format"] == "document_carousel"
    assert posts[0]["image_brief"] is None
    mock_generate.assert_not_called()


def test_image_generation_failure_leaves_brief_null_and_notes_it_but_still_queues():
    posts, mock_queue, mock_generate = _run(format_="text_post", image_side_effect=RuntimeError("Gemini API down"))

    assert len(posts) == 1
    assert posts[0]["image_brief"] is None
    assert "IMAGE GENERATION FAILED" in posts[0]["notes"]
    assert "Gemini API down" in posts[0]["notes"]
    mock_queue.assert_called_once()  # a failed image must never block queuing the post itself


def test_flagged_for_review_image_still_attaches_but_adds_a_hitl_note():
    flagged_result = {**FAKE_IMAGE_RESULT, "flagged_for_review": True, "reason": "subject mismatch"}
    posts, _, _ = _run(format_="text_post", image_result=flagged_result)

    assert posts[0]["image_brief"] is not None  # still attached -- Kelvin reviews it himself now
    assert "IMAGE RELEVANCE GATE FAILED" in posts[0]["hitl_notes"]
    assert "subject mismatch" in posts[0]["hitl_notes"]


def test_queued_content_item_carries_the_final_formatted_copy_not_the_raw_draft():
    _, mock_queue, _ = _run(format_="text_post")

    queued_item = mock_queue.call_args.args[0]
    assert "\n\n" in queued_item["post_copy"]
