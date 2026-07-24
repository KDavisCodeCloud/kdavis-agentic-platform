"""
Coverage for the asset-vault + post_formatter wiring added to MKT-LI1
(agents/marketing/mkt_li1_linkedin_brand.py, 2026-07-22): image
selection and text formatting happen at DRAFT time, before HITL
queuing, so a human reviewer sees the actual image/text that would
publish -- never re-selected later at publish time.

get_anthropic_client, run_compliance_guard, and queue_for_review are
mocked; this covers the wiring logic, not the real LLM draft quality
or the real DB write.
"""
from unittest.mock import MagicMock, patch

import agents.marketing.mkt_li1_linkedin_brand as li1

RESEARCH_REPORT = {"content_angles": [{"angle": "Why most HITL gates are theater"}]}


def _fake_draft_response(format_="text_post", topic="LLM guardrails"):
    payload = {
        "pillar": 1, "topic": topic, "hitl_tier": 2, "estimated_length": "medium",
        "post_copy": "Most engineers think guardrails are optional. They are not.",
        "hook_variants": [], "format": format_,
        "image_brief": {"concept": "old canva shape", "style": "x", "brand_colors": ["#000"]},
        "carousel_slides": ["a", "b"] if format_ == "document_carousel" else None,
        "carousel_pdf_brief": {"concept": "x", "slide_count": 2, "style": "y"} if format_ == "document_carousel" else None,
        "notes": "",
    }
    response = MagicMock()
    response.content = [MagicMock(text=__import__("json").dumps(payload))]
    return response


def _run(format_="text_post", asset_result=None):
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_draft_response(format_=format_)

    with patch("agents.marketing.mkt_li1_linkedin_brand.get_anthropic_client", return_value=fake_client), \
         patch("agents.marketing.mkt_li1_linkedin_brand.run_compliance_guard", return_value={"revised_content": None, "flags": []}), \
         patch("agents.marketing.mkt_li1_linkedin_brand.queue_for_review", side_effect=lambda item, **kw: {"id": "queued-1", **item}) as mock_queue, \
         patch("agents.marketing.mkt_li1_linkedin_brand.select_asset", return_value=asset_result) as mock_select, \
         patch("agents.marketing.mkt_li1_linkedin_brand.write_audit_log"), \
         patch("agents.marketing.mkt_li1_linkedin_brand.emit_event"):
        posts = li1.run_li1_brand_agent(
            research_report=RESEARCH_REPORT,
            idea_reservoir=[],
            kelvin_voice_profile={},
            build_updates=[],
        )
    return posts, mock_select, mock_queue


def test_text_post_selects_an_image_and_overwrites_image_brief_with_vault_payload():
    asset_result = {
        "image_id": "img_001", "image_path": "assets_library/ai_agents/foo.png",
        "credit_line": "Visual credit: @aloksharan", "is_original": False,
        "selected_because": "topic match on: guardrails", "generation_available": False,
    }
    posts, mock_select, _ = _run(asset_result=asset_result)

    assert len(posts) == 1
    mock_select.assert_called_once_with("LLM guardrails", image_description=None)
    assert posts[0]["image_brief"] == asset_result


def test_text_post_with_no_asset_match_and_no_generation_still_queues_with_null_image_brief():
    no_match = {
        "image_id": None, "image_path": None, "credit_line": None, "is_original": None,
        "selected_because": "no match found", "generation_available": False,
    }
    posts, mock_select, _ = _run(asset_result=no_match)

    assert posts[0]["image_brief"] is None


def test_text_post_with_no_vault_match_but_generation_available_keeps_the_signal():
    # image_description present (model drafted one) but no vault match yet —
    # image_brief still carries generation_available=True so the dashboard/
    # gemini_image_gen.py know a diagram can still be produced for this post.
    no_match_but_generatable = {
        "image_id": None, "image_path": None, "credit_line": None, "is_original": None,
        "selected_because": "no match found", "generation_available": True,
    }
    posts, mock_select, _ = _run(asset_result=no_match_but_generatable)

    assert posts[0]["image_brief"] == no_match_but_generatable


def test_post_copy_is_formatted_using_the_selected_assets_credit_line():
    asset_result = {
        "image_id": "img_001", "image_path": "assets_library/ai_agents/foo.png",
        "credit_line": "Visual credit: @aloksharan", "is_original": False,
        "selected_because": "topic match on: guardrails", "generation_available": False,
    }
    posts, _, _ = _run(asset_result=asset_result)

    assert posts[0]["post_copy"].endswith("Visual credit: @aloksharan")
    # sentence-per-line formatting actually ran, not just credit appended
    assert "\n\n" in posts[0]["post_copy"]


def test_carousel_format_never_calls_select_asset_or_reformats_post_copy():
    posts, mock_select, _ = _run(format_="document_carousel")

    mock_select.assert_not_called()
    assert posts[0]["format"] == "document_carousel"
    # image_brief for a carousel post stays whatever the model drafted -- untouched
    assert posts[0]["image_brief"] == {"concept": "old canva shape", "style": "x", "brand_colors": ["#000"]}
    assert "\n\n" not in posts[0]["post_copy"]  # never ran through post_formatter


def test_queued_content_item_carries_the_final_formatted_copy_not_the_raw_draft():
    asset_result = {
        "image_id": "img_001", "image_path": "assets_library/ai_agents/foo.png",
        "credit_line": "Visual credit: @aloksharan", "is_original": False,
        "selected_because": "topic match on: guardrails", "generation_available": False,
    }
    _, _, mock_queue = _run(asset_result=asset_result)

    queued_item = mock_queue.call_args.args[0]
    assert queued_item["post_copy"].endswith("Visual credit: @aloksharan")
