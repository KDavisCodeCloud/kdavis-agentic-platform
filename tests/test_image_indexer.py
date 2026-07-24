"""
Coverage for assets_library/image_indexer.py: idempotent scanning
(never re-tags or duplicates an already-indexed file), id numbering,
is_original detection from the my_originals/ folder, and atomic writes.
The real Anthropic vision call is mocked -- these tests cover the
scanning/indexing logic, not Claude's actual tagging quality.
"""
import json
from unittest.mock import MagicMock, patch

from PIL import Image

import assets_library.image_indexer as indexer


def _make_png(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (10, 10), color="blue").save(path, format="PNG")


def _fake_tag_response(category="AI / Agents", tags=None):
    payload = {
        "category": category,
        "topic_tags": tags or ["Guardrails", "LLM"],
        "compatible_post_topics": ["agent safety", "prompt injection"],
        "original_creator": "Alok Sharan",
        "creator_linkedin": "@aloksharan",
    }
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps(payload))]
    return response


def test_scans_and_tags_a_new_image(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "ASSETS_ROOT", tmp_path)
    monkeypatch.setattr(indexer, "INDEX_PATH", tmp_path / "index.json")
    (tmp_path / "index.json").write_text("[]")
    _make_png(tmp_path / "ai_agents" / "foo.png")

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tag_response()

    with patch("assets_library.image_indexer.Anthropic", return_value=fake_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}):
        indexer.main()

    entries = json.loads((tmp_path / "index.json").read_text())
    assert len(entries) == 1
    assert entries[0]["id"] == "img_001"
    assert entries[0]["filename"] == "ai_agents/foo.png"
    assert entries[0]["is_original"] is False
    assert entries[0]["last_used_date"] is None
    assert entries[0]["times_used"] == 0


def test_is_original_true_for_my_originals_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "ASSETS_ROOT", tmp_path)
    monkeypatch.setattr(indexer, "INDEX_PATH", tmp_path / "index.json")
    (tmp_path / "index.json").write_text("[]")
    _make_png(tmp_path / "my_originals" / "mine.png")

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tag_response(category="Original")

    with patch("assets_library.image_indexer.Anthropic", return_value=fake_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}):
        indexer.main()

    entries = json.loads((tmp_path / "index.json").read_text())
    assert entries[0]["is_original"] is True


def test_running_twice_never_duplicates_or_retags(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "ASSETS_ROOT", tmp_path)
    monkeypatch.setattr(indexer, "INDEX_PATH", tmp_path / "index.json")
    (tmp_path / "index.json").write_text("[]")
    _make_png(tmp_path / "ai_agents" / "foo.png")

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tag_response()

    with patch("assets_library.image_indexer.Anthropic", return_value=fake_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}):
        indexer.main()
        indexer.main()

    entries = json.loads((tmp_path / "index.json").read_text())
    assert len(entries) == 1
    assert fake_client.messages.create.call_count == 1


def test_next_id_continues_from_highest_existing_id(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "ASSETS_ROOT", tmp_path)
    monkeypatch.setattr(indexer, "INDEX_PATH", tmp_path / "index.json")
    (tmp_path / "index.json").write_text(json.dumps([
        {"id": "img_003", "filename": "ai_agents/existing.png"}
    ]))
    _make_png(tmp_path / "ai_agents" / "existing.png")  # already indexed, skipped
    _make_png(tmp_path / "ai_agents" / "new_one.png")   # new, should become img_004

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tag_response()

    with patch("assets_library.image_indexer.Anthropic", return_value=fake_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}):
        indexer.main()

    entries = json.loads((tmp_path / "index.json").read_text())
    ids = {e["id"] for e in entries}
    assert ids == {"img_003", "img_004"}


def test_sidecar_json_overrides_creator_fields_but_not_vision_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "ASSETS_ROOT", tmp_path)
    monkeypatch.setattr(indexer, "INDEX_PATH", tmp_path / "index.json")
    (tmp_path / "index.json").write_text("[]")
    image_path = tmp_path / "system_design" / "kubernetes.jpg"
    _make_png(image_path)
    (tmp_path / "system_design" / "kubernetes.json").write_text(json.dumps({
        "original_creator": "ByteByteGo", "creator_linkedin": "@bytebytego",
    }))

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tag_response(
        category="System Design", tags=["Kubernetes", "Containers"]
    )

    with patch("assets_library.image_indexer.Anthropic", return_value=fake_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}):
        indexer.main()

    entries = json.loads((tmp_path / "index.json").read_text())
    entry = entries[0]
    # Sidecar wins for attribution...
    assert entry["original_creator"] == "ByteByteGo"
    assert entry["creator_linkedin"] == "@bytebytego"
    # ...but category/tags still come from vision, not the sidecar.
    assert entry["category"] == "System Design"
    assert entry["topic_tags"] == ["Kubernetes", "Containers"]


def test_no_sidecar_falls_back_to_vision_for_creator_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "ASSETS_ROOT", tmp_path)
    monkeypatch.setattr(indexer, "INDEX_PATH", tmp_path / "index.json")
    (tmp_path / "index.json").write_text("[]")
    _make_png(tmp_path / "ai_agents" / "foo.png")  # no sidecar written

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tag_response()  # default creator: Alok Sharan / @aloksharan

    with patch("assets_library.image_indexer.Anthropic", return_value=fake_client), \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "fake-key"}):
        indexer.main()

    entries = json.loads((tmp_path / "index.json").read_text())
    assert entries[0]["original_creator"] == "Alok Sharan"
    assert entries[0]["creator_linkedin"] == "@aloksharan"


def test_rejects_a_corrupt_or_non_image_file(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "ASSETS_ROOT", tmp_path)
    monkeypatch.setattr(indexer, "INDEX_PATH", tmp_path / "index.json")
    (tmp_path / "index.json").write_text("[]")
    bad_path = tmp_path / "ai_agents" / "not_really_an_image.png"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("this is not image data")

    import pytest
    with pytest.raises(ValueError, match="does not appear to be a valid image"):
        indexer._detect_media_type(bad_path)
