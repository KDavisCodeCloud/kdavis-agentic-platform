"""
Coverage for assets_library/asset_logger.py -- updates last_used_date and
increments times_used for a matched entry, atomically, and raises
(never silently no-ops) if the id doesn't exist.
"""
import json

import pytest

import assets_library.asset_logger as logger


def _write_index(tmp_path, monkeypatch, entries):
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(entries))
    monkeypatch.setattr(logger, "INDEX_PATH", index_path)
    return index_path


def test_logs_usage_and_increments_count(tmp_path, monkeypatch):
    index_path = _write_index(tmp_path, monkeypatch, [
        {"id": "img_001", "times_used": 2, "last_used_date": "2026-05-01"}
    ])
    entry = logger.log_usage("img_001", "2026-07-21")
    assert entry["times_used"] == 3
    assert entry["last_used_date"] == "2026-07-21"

    on_disk = json.loads(index_path.read_text())
    assert on_disk[0]["times_used"] == 3
    assert on_disk[0]["last_used_date"] == "2026-07-21"


def test_defaults_to_today_when_no_date_given(tmp_path, monkeypatch):
    from datetime import date
    _write_index(tmp_path, monkeypatch, [{"id": "img_001", "times_used": 0, "last_used_date": None}])
    entry = logger.log_usage("img_001")
    assert entry["last_used_date"] == date.today().isoformat()


def test_raises_when_id_not_found(tmp_path, monkeypatch):
    _write_index(tmp_path, monkeypatch, [{"id": "img_001", "times_used": 0, "last_used_date": None}])
    with pytest.raises(ValueError, match="img_999"):
        logger.log_usage("img_999")


def test_only_updates_the_matching_entry(tmp_path, monkeypatch):
    index_path = _write_index(tmp_path, monkeypatch, [
        {"id": "img_001", "times_used": 1, "last_used_date": None},
        {"id": "img_002", "times_used": 1, "last_used_date": None},
    ])
    logger.log_usage("img_001", "2026-07-21")
    on_disk = json.loads(index_path.read_text())
    assert on_disk[0]["times_used"] == 2
    assert on_disk[1]["times_used"] == 1
    assert on_disk[1]["last_used_date"] is None
