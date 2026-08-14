"""
Coverage for the Opinion Matrix stance-rotation mechanism added to
MKT-LI1 (agents/marketing/mkt_li1_linkedin_brand.py, 2026-08-14): each
post is drafted via its own independent LLM call with no memory of the
rest of the batch, so "never use the same stance twice in a row" only
holds if the code itself threads the previous post's chosen stance into
the next draft call. This covers that threading, not real LLM stance
selection quality.
"""
import json
from unittest.mock import MagicMock, patch

import agents.marketing.mkt_li1_linkedin_brand as li1

# _build_slots pops from the pillar_1 pool for its own quota AND as the
# fallback for pillar_2/3 (both empty here, see _build_slots' own
# fallback rule) -- once the pool runs dry it drops the remaining slots
# rather than fabricating source material. Exactly 3 content_angles
# yields exactly 3 built slots/posts, matching the 3 canned LLM responses
# below one-to-one.
RESEARCH_REPORT = {"content_angles": [{"angle": f"angle {i}"} for i in range(3)]}


def _response_with_stance(stance: str):
    payload = {
        "pillar": 1, "stance": stance, "topic": "t", "hitl_tier": 2, "estimated_length": "medium",
        "post_copy": "post body", "hook_variants": [], "format": "text_post",
        "image_brief": None, "image_description": None,
        "carousel_slides": None, "carousel_pdf_brief": None, "notes": "",
    }
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps(payload))]
    return response


def test_last_stance_is_threaded_into_the_next_drafts_user_prompt():
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _response_with_stance("HIRING"),
        _response_with_stance("AI_AGENTIC"),
        _response_with_stance("PRODUCT"),
    ]
    no_match = {
        "image_id": None, "image_path": None, "credit_line": None, "is_original": None,
        "selected_because": "no match found", "generation_available": False,
    }

    with patch("agents.marketing.mkt_li1_linkedin_brand.get_anthropic_client", return_value=fake_client), \
         patch("agents.marketing.mkt_li1_linkedin_brand.run_compliance_guard", return_value={"revised_content": None, "flags": []}), \
         patch("agents.marketing.mkt_li1_linkedin_brand.queue_for_review", side_effect=lambda item, **kw: {"id": "queued-1", **item}), \
         patch("agents.marketing.mkt_li1_linkedin_brand.select_asset", return_value=no_match), \
         patch("agents.marketing.mkt_li1_linkedin_brand.write_audit_log"), \
         patch("agents.marketing.mkt_li1_linkedin_brand.emit_event"):
        posts = li1.run_li1_brand_agent(
            research_report=RESEARCH_REPORT, idea_reservoir=[], kelvin_voice_profile={}, build_updates=[],
        )

    assert len(posts) == 3
    assert posts[0]["stance"] == "HIRING"
    assert posts[1]["stance"] == "AI_AGENTIC"
    assert posts[2]["stance"] == "PRODUCT"

    calls = fake_client.messages.create.call_args_list
    first_prompt = calls[0].kwargs["messages"][0]["content"]
    second_prompt = calls[1].kwargs["messages"][0]["content"]
    third_prompt = calls[2].kwargs["messages"][0]["content"]

    # First call has no prior post yet -- nothing to avoid.
    assert "last_stance_used" not in first_prompt
    # Second call must be told to avoid the first post's stance.
    assert "last_stance_used (do not pick this one again): HIRING" in second_prompt
    # Third call must be told to avoid the second post's stance, not the first's.
    assert "last_stance_used (do not pick this one again): AI_AGENTIC" in third_prompt


def test_draft_post_omits_last_stance_line_when_none_given():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _response_with_stance("BUILD_IN_PUBLIC")

    li1._draft_post(fake_client, "pillar_1", "source text", {})

    prompt = fake_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "last_stance_used" not in prompt


def test_draft_post_includes_last_stance_line_when_given():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _response_with_stance("BUILD_IN_PUBLIC")

    li1._draft_post(fake_client, "pillar_1", "source text", {}, last_stance="ENTERPRISE_INERTIA")

    prompt = fake_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "last_stance_used (do not pick this one again): ENTERPRISE_INERTIA" in prompt
