"""
Coverage for generate_on_demand_posts (agents/marketing/mkt_li1_linkedin_brand.py,
2026-08-17) -- the CEO dashboard's "fire posts now" button. Unlike
generate_builder_post/generate_product_launch_post, this DOES reuse the
evergreen pillar/Opinion Matrix machinery (_draft_post, CONTENT_MIX_RATIO,
apportion), it just sources each slot from PILLAR_TOPIC_SEEDS instead of a
curated research_report/idea_reservoir pool -- so these tests confirm it
never touches the monthly-batch-specific pool builders (_content_pool/
_build_slots/_compute_schedule), that count/pillar_focus drive the right
pillar sequence, and that every row is tagged source="on_demand".
"""
import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

import agents.marketing.mkt_li1_linkedin_brand as li1


def _response_for_pillar(pillar_num: int, stance: str = "BUILD_IN_PUBLIC"):
    payload = {
        "pillar": pillar_num, "stance": stance, "topic": f"topic for pillar {pillar_num}",
        "hitl_tier": 3 if pillar_num == 4 else 2, "estimated_length": "medium",
        "post_copy": f"post body for pillar {pillar_num}", "hook_variants": [], "format": "text_post",
        "image_brief": None, "image_description": None,
        "carousel_slides": None, "carousel_pdf_brief": None, "notes": "",
    }
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps(payload))]
    return response


_NO_MATCH_ASSET = {
    "image_id": None, "image_path": None, "credit_line": None, "is_original": None,
    "selected_because": "no match found", "generation_available": False,
}


def _patched(fake_client, queue_side_effect=None):
    return (
        patch.object(li1, "get_anthropic_client", return_value=fake_client),
        patch.object(li1, "run_compliance_guard", return_value={"revised_content": None, "flags": []}),
        patch.object(li1, "queue_for_review", side_effect=queue_side_effect or (lambda item, **kw: {"id": "queued"})),
        patch.object(li1, "select_asset", return_value=_NO_MATCH_ASSET),
        patch.object(li1, "write_audit_log"),
        patch.object(li1, "emit_event"),
    )


def test_balanced_mix_apportions_across_all_four_pillars():
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _response_for_pillar(1), _response_for_pillar(1), _response_for_pillar(1), _response_for_pillar(1),
        _response_for_pillar(2), _response_for_pillar(2), _response_for_pillar(2),
        _response_for_pillar(3), _response_for_pillar(3),
        _response_for_pillar(4),
    ]
    patches = _patched(fake_client)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        posts = li1.generate_on_demand_posts(10, pillar_focus=None)

    assert len(posts) == 10
    pillar_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for post in posts:
        pillar_counts[post["pillar"]] += 1
    # apportion({0.4,0.3,0.2,0.1}, 10) -> exactly 4/3/2/1
    assert pillar_counts == {1: 4, 2: 3, 3: 2, 4: 1}
    for post in posts:
        assert post["source"] == "on_demand"


def test_single_pillar_override_routes_every_post_into_that_pillar():
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [_response_for_pillar(2) for _ in range(5)]
    patches = _patched(fake_client)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        posts = li1.generate_on_demand_posts(5, pillar_focus="pillar_2")

    assert len(posts) == 5
    assert all(post["pillar"] == 2 for post in posts)
    assert all(post["pillar_name"] == "The Builder's Journey" for post in posts)


def test_pillar_4_always_tier_3_even_if_model_says_otherwise():
    # Model claims hitl_tier=2 for a pillar_4 post -- code must override it,
    # same rule as the evergreen monthly batch.
    payload = {
        "pillar": 4, "stance": "PRODUCT", "topic": "t", "hitl_tier": 2, "estimated_length": "short",
        "post_copy": "pillar 4 post", "hook_variants": [], "format": "text_post",
        "image_brief": None, "image_description": None,
        "carousel_slides": None, "carousel_pdf_brief": None, "notes": "",
    }
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps(payload))]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = response

    mock_queue = MagicMock(side_effect=lambda item, **kw: {"id": "queued"})
    patches = _patched(fake_client, queue_side_effect=mock_queue.side_effect)
    with patches[0], patches[1], patch.object(li1, "queue_for_review", mock_queue), patches[3], patches[4], patches[5]:
        posts = li1.generate_on_demand_posts(1, pillar_focus="pillar_4")

    assert posts[0]["hitl_tier"] == 3
    assert mock_queue.call_args.kwargs["tier"] == 3


def test_mkt10_flag_escalates_to_tier_3():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _response_for_pillar(1)
    mock_queue = MagicMock(side_effect=lambda item, **kw: {"id": "queued"})

    with patch.object(li1, "get_anthropic_client", return_value=fake_client), \
         patch.object(li1, "run_compliance_guard", return_value={"revised_content": None, "flags": ["flagged term"]}), \
         patch.object(li1, "queue_for_review", mock_queue), \
         patch.object(li1, "select_asset", return_value=_NO_MATCH_ASSET), \
         patch.object(li1, "write_audit_log"), patch.object(li1, "emit_event"):
        posts = li1.generate_on_demand_posts(1, pillar_focus="pillar_1")

    assert posts[0]["hitl_tier"] == 3
    assert mock_queue.call_args.kwargs["tier"] == 3


def test_invalid_pillar_focus_raises_value_error():
    with pytest.raises(ValueError):
        li1.generate_on_demand_posts(3, pillar_focus="not_a_real_pillar")


def test_count_below_one_raises_value_error():
    with pytest.raises(ValueError):
        li1.generate_on_demand_posts(0, pillar_focus="balanced")


def test_never_touches_monthly_batch_pool_builders(monkeypatch):
    """Confirms this is genuinely sourced from PILLAR_TOPIC_SEEDS, not a
    wrapper around the evergreen batch's own pool/scheduling -- same
    guardrail pattern as test_mkt_li1_new_post_types.py's equivalent
    checks for the other two manual entry points."""
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [_response_for_pillar(1) for _ in range(3)]

    def _boom(*a, **k):
        raise AssertionError("generate_on_demand_posts must not call the monthly-batch pool builders")

    monkeypatch.setattr(li1, "_content_pool", _boom)
    monkeypatch.setattr(li1, "_build_slots", _boom)
    monkeypatch.setattr(li1, "_compute_schedule", _boom)

    patches = _patched(fake_client)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        posts = li1.generate_on_demand_posts(3, pillar_focus="pillar_1")

    assert len(posts) == 3


def test_ondemand_schedule_starts_tomorrow_not_month_start():
    # 2026-08-17 is a Monday; POST_WEEKDAYS are Tue/Wed/Thu -- the very next
    # candidate is Tue 2026-08-18, not the 1st of the month like
    # _compute_schedule (the monthly batch) would use.
    schedule = li1._compute_ondemand_schedule(3, start_from=date(2026, 8, 17))
    assert [d.date().isoformat() for d in schedule] == ["2026-08-18", "2026-08-19", "2026-08-20"]
    assert all(d.hour == li1.POST_HOUR_ET for d in schedule)


def test_ondemand_schedule_rolls_into_next_month_without_dropping_posts():
    # Starting late in a month with a large count must roll forward rather
    # than truncate, same "never drop a post" rule as _compute_schedule.
    schedule = li1._compute_ondemand_schedule(2, start_from=date(2026, 8, 28))
    assert len(schedule) == 2
    assert schedule[-1].date() > date(2026, 8, 31)
