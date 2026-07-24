"""
Coverage for assets_library/asset_selector.py's selection priority logic:
topic match -> exclude recent-use (60d) -> exclude explicit ids ->
prefer is_original -> sort by times_used then last_used_date.
"""
import json
from datetime import date, timedelta

import pytest

import assets_library.asset_selector as selector

TODAY = date(2026, 7, 21)


def _write_index(tmp_path, monkeypatch, entries):
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(entries))
    monkeypatch.setattr(selector, "INDEX_PATH", index_path)


def _entry(**overrides):
    base = {
        "id": "img_001",
        "filename": "ai_agents/foo.png",
        "category": "AI / Agents",
        "topic_tags": ["Guardrails", "LLM"],
        "original_creator": "Alok Sharan",
        "creator_linkedin": "@aloksharan",
        "is_original": False,
        "last_used_date": None,
        "times_used": 0,
        "compatible_post_topics": ["agent safety", "prompt injection"],
    }
    base.update(overrides)
    return base


def test_no_match_returns_null_payload(tmp_path, monkeypatch):
    _write_index(tmp_path, monkeypatch, [_entry(topic_tags=["Kubernetes"], compatible_post_topics=["k8s"])])
    result = selector.select_asset("prompt injection", today=TODAY)
    assert result["image_id"] is None
    assert "no match found" in result["selected_because"]


def test_topic_match_on_tag_returns_image(tmp_path, monkeypatch):
    _write_index(tmp_path, monkeypatch, [_entry()])
    result = selector.select_asset("LLM guardrails", today=TODAY)
    assert result["image_id"] == "img_001"
    assert result["image_path"] == "assets_library/ai_agents/foo.png"
    assert "LLM" in result["selected_because"] or "guardrails" in result["selected_because"]


def test_credit_line_uses_creator_linkedin_handle(tmp_path, monkeypatch):
    _write_index(tmp_path, monkeypatch, [_entry()])
    result = selector.select_asset("LLM", today=TODAY)
    assert result["credit_line"] == "Visual credit: @aloksharan"


def test_original_image_never_gets_a_credit_line(tmp_path, monkeypatch):
    _write_index(tmp_path, monkeypatch, [_entry(is_original=True, filename="my_originals/foo.png")])
    result = selector.select_asset("LLM", today=TODAY)
    assert result["credit_line"] is None
    assert result["is_original"] is True


def test_credit_line_falls_back_to_creator_name_when_handle_missing(tmp_path, monkeypatch):
    _write_index(tmp_path, monkeypatch, [_entry(creator_linkedin=None, original_creator="Alok Sharan")])
    result = selector.select_asset("LLM", today=TODAY)
    assert result["credit_line"] == "Visual credit: Alok Sharan"


def test_recently_used_within_60_days_is_excluded(tmp_path, monkeypatch):
    recent = (TODAY - timedelta(days=10)).isoformat()
    _write_index(tmp_path, monkeypatch, [_entry(last_used_date=recent)])
    result = selector.select_asset("LLM", today=TODAY)
    assert result["image_id"] is None


def test_used_exactly_60_days_ago_is_no_longer_excluded(tmp_path, monkeypatch):
    boundary = (TODAY - timedelta(days=60)).isoformat()
    _write_index(tmp_path, monkeypatch, [_entry(last_used_date=boundary)])
    result = selector.select_asset("LLM", today=TODAY)
    assert result["image_id"] == "img_001"


def test_explicit_exclude_list_is_honored_even_if_topic_matches(tmp_path, monkeypatch):
    _write_index(tmp_path, monkeypatch, [_entry(id="img_001"), _entry(id="img_002", filename="ai_agents/bar.png")])
    result = selector.select_asset("LLM", exclude=["img_001"], today=TODAY)
    assert result["image_id"] == "img_002"


def test_prefers_original_over_non_original_when_both_match(monkeypatch):
    entries = [
        _entry(id="img_001", is_original=False, times_used=0),
        _entry(id="img_002", is_original=True, filename="my_originals/bar.png", times_used=5),
    ]
    monkeypatch.setattr(selector, "_load_index", lambda: entries)
    result = selector.select_asset("LLM", today=TODAY)
    assert result["image_id"] == "img_002"


def test_among_equal_priority_prefers_lower_times_used(monkeypatch):
    entries = [
        _entry(id="img_001", times_used=5),
        _entry(id="img_002", filename="ai_agents/bar.png", times_used=1),
    ]
    monkeypatch.setattr(selector, "_load_index", lambda: entries)
    result = selector.select_asset("LLM", today=TODAY)
    assert result["image_id"] == "img_002"


def test_never_used_null_last_used_date_sorts_before_any_real_date(monkeypatch):
    entries = [
        _entry(id="img_001", times_used=0, last_used_date=(TODAY - timedelta(days=61)).isoformat()),
        _entry(id="img_002", filename="ai_agents/bar.png", times_used=0, last_used_date=None),
    ]
    monkeypatch.setattr(selector, "_load_index", lambda: entries)
    result = selector.select_asset("LLM", today=TODAY)
    assert result["image_id"] == "img_002"
