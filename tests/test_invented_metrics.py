"""
tests/test_invented_metrics.py

Code-enforced NO INVENTED METRICS for MKT-LI1 (2026-11-09).
"""

import json
from unittest.mock import MagicMock

import pytest

import agents.marketing.mkt_li1_linkedin_brand as li1
from agents.marketing.invented_metrics import unsourced_metrics


@pytest.mark.parametrize("text,expect", [
    ("We lost four months to it.", ["four months"]),
    ("Paged at 2am again.", ["2am"]),
    ("It took three hours a week.", ["three hours"]),
    ("Cut spend 40% and saved $120K.", ["40%", "$120K"]),
    ("A team of 6 engineers.", ["6 engineers"]),
    ("Two quarters of roadmap slipped.", ["Two quarters"]),
])
def test_invented_figures_are_caught(text, expect):
    assert unsourced_metrics(text, "no numbers here") == expect


def test_figures_in_the_source_are_allowed_as_digits_or_words():
    src = "The migration took 4 months and paged the team at 2am; 40% of alerts were noise."
    assert unsourced_metrics("Four months, a 2am page, 40% noise.", src) == []


def test_number_word_in_source_allows_the_digit_form():
    assert unsourced_metrics("It took 3 weeks.", "three weeks of drift") == []


def test_plain_prose_is_clean():
    text = ("Nobody owns that cloud bill. Hours every week go to triage, "
            "and one team carries the pager. The tagging strategy from 2022 stopped meaning anything.")
    assert unsourced_metrics(text, "") == []


def test_cta_duration_is_not_a_metric():
    assert unsourced_metrics("Worth a 15-minute call?", "") == []


def test_stock_phrases_allow_only_stated_metrics_not_bare_numbers():
    stock = "Kelvin spent 15 years implementing systems. Step 4 is the soft plug. Here are 3 reasons."
    assert unsourced_metrics("After fifteen years of this...", "", stock_phrases=stock) == []
    # "4" and "3" are in the stock text but only as structure, so they source nothing.
    assert unsourced_metrics("Four months, 3 engineers.", "", stock_phrases=stock) == ["Four months", "3 engineers"]


def test_non_string_text_is_ignored():
    assert unsourced_metrics(None, "x") == []
    assert unsourced_metrics(MagicMock(), "x") == []


def _resp(post_copy: str):
    r = MagicMock()
    r.content = [MagicMock(text=json.dumps({"pillar": 6, "stance": "HIRING", "post_copy": post_copy}))]
    return r


class TestDraftPost:
    def test_clean_draft_makes_one_call(self):
        client = MagicMock()
        client.messages.create.return_value = _resp("Nobody owns the bill. Hours every week.")
        out = li1._draft_post(client, "pillar_6", "source with no figures", {})
        assert client.messages.create.call_count == 1
        assert out["invented_metrics"] == []

    def test_invented_figure_triggers_one_retry_naming_it(self):
        client = MagicMock()
        client.messages.create.side_effect = [_resp("We lost four months."), _resp("We lost a quarter of roadmap.")]
        out = li1._draft_post(client, "pillar_6", "source", {})
        assert client.messages.create.call_count == 2
        retry_msgs = client.messages.create.call_args_list[1].kwargs["messages"]
        assert "four months" in retry_msgs[-1]["content"]
        assert out["invented_metrics"] == []
        assert out["post_copy"] == "We lost a quarter of roadmap."

    def test_figure_surviving_the_retry_is_reported(self):
        client = MagicMock()
        client.messages.create.return_value = _resp("Paged at 2am.")
        out = li1._draft_post(client, "pillar_6", "source", {})
        assert client.messages.create.call_count == 2
        assert out["invented_metrics"] == ["2am"]


def test_flag_escalates_to_tier_3_and_keeps_existing_notes():
    post = {"hitl_notes": "MKT-10: tone", "hitl_tier": 2}
    assert li1._flag_invented_metrics(post, ["2am"], 2) == 3
    assert post["hitl_tier"] == 3
    assert post["hitl_notes"].startswith("MKT-10: tone | INVENTED METRICS")
    assert "2am" in post["hitl_notes"]


def test_no_hits_leaves_post_alone():
    post = {"hitl_tier": 2}
    assert li1._flag_invented_metrics(post, [], 2) == 2
    assert "hitl_notes" not in post
