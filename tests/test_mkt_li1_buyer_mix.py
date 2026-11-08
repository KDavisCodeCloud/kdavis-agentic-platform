"""
MKT-LI1 v3.0 (2026-11-08, buyer-targeting fix Phase 7): the evergreen mix is
50% Buyer Pain, 25% Proof, 25% Authority & Opinion; the voice writes to the
budget owner; every post ends on its category CTA.
"""
import pytest

import agents.marketing.mkt_li1_linkedin_brand as li1
from agents.marketing._shared import apportion


def test_mix_ratio_is_50_25_25():
    assert li1.CONTENT_MIX_RATIO == {"pillar_6": 0.5, "pillar_7": 0.25, "pillar_8": 0.25}
    assert abs(sum(li1.CONTENT_MIX_RATIO.values()) - 1.0) < 1e-9


@pytest.mark.parametrize("n,expect", [(12, (6, 3, 3)), (4, (2, 1, 1)), (8, (4, 2, 2))])
def test_apportioned_batches_keep_the_mix(n, expect):
    q = apportion(li1.CONTENT_MIX_RATIO, n)
    assert (q["pillar_6"], q["pillar_7"], q["pillar_8"]) == expect


def test_a_full_pool_fills_the_monthly_batch_at_the_mix():
    pool = {k: [{"text": f"{k}-{i}", "source": "t"} for i in range(20)] for k in li1.CONTENT_MIX_RATIO}
    slots = li1._build_slots(pool, posts_per_batch=12)
    counts = {k: sum(1 for s in slots if s["pillar_key"] == k) for k in li1.CONTENT_MIX_RATIO}
    assert counts == {"pillar_6": 6, "pillar_7": 3, "pillar_8": 3}


def test_a_dry_pillar_is_dropped_not_backfilled_from_another():
    pool = {"pillar_6": [{"text": "a", "source": "t"}], "pillar_7": [], "pillar_8": []}
    slots = li1._build_slots(pool, posts_per_batch=12)
    assert [s["pillar_key"] for s in slots] == ["pillar_6"]


def test_pool_routes_sources_to_the_new_pillars():
    pool = li1._content_pool(
        {"content_angles": [{"angle": "cost of an open platform seat"}]},
        [{"type": "proof", "text": "built X"}, {"type": "educational", "text": "IaC take"},
         {"type": "enterprise", "text": "audit risk"}],
        [{"text": "shipped the HITL gate", "milestone": True}],
    )
    assert [x["text"] for x in pool["pillar_6"]] == ["cost of an open platform seat", "audit risk"]
    assert [x["text"] for x in pool["pillar_7"]] == ["built X", "shipped the HITL gate"]
    assert [x["text"] for x in pool["pillar_8"]] == ["IaC take"]


@pytest.mark.parametrize("key,line", [
    ("pillar_6", li1.BUYER_PAIN_CLOSING_LINE),
    ("pillar_7", li1.PROOF_CLOSING_LINE),
    ("pillar_8", li1.WORKING_WITH_ME_CLOSING_LINE),
])
def test_every_category_ends_on_its_cta(key, line):
    out = li1._apply_closing_line("Body.", is_cta_post=False, closing=li1.closing_line_for(key))
    assert out.endswith(line)
    assert out.count(line) == 1


def test_buyer_pain_cta_is_one_low_friction_ask():
    assert "15-minute call" in li1.BUYER_PAIN_CLOSING_LINE
    assert li1.BUYER_PAIN_CLOSING_LINE.count("?") <= 1


def test_voice_writes_to_the_budget_owner_without_invented_metrics():
    p = li1.VOICE_SYSTEM_PROMPT
    assert "THE READER IS THE BUDGET OWNER" in p
    assert "NO INVENTED METRICS" in p
    assert "builder\ntalking to another builder" not in p and "builder talking to another builder" not in p
    assert "aerospace/defense/healthcare cloud lessons" not in p


def test_legacy_pillar_focus_still_resolves_but_is_out_of_the_mix():
    for legacy in ("pillar_1", "pillar_2", "pillar_3", "pillar_4", "pillar_5"):
        assert legacy in li1.PILLAR_TOPIC_SEEDS and legacy not in li1.CONTENT_MIX_RATIO
    with pytest.raises(ValueError):
        li1.generate_on_demand_posts(1, pillar_focus="pillar_9")
