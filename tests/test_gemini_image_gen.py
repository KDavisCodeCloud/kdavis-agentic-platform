"""
Coverage for assets_library/gemini_image_gen.py's pure logic: filename
slugging/targeting, idempotent skip-if-exists, never-block-on-failure,
and the sidecar metadata shape (Kelvin Davis, never "King Kelz" — see
memory/feedback_no_king_kelz.md).

Network (Gemini REST call) and Supabase re-attach are mocked throughout;
this covers the file-write/skip/failure-isolation logic, not real image
generation or a real DB write.
"""
import base64
import json
from datetime import date
from unittest.mock import MagicMock, patch

import assets_library.gemini_image_gen as gig


def test_slugify_lowercases_and_replaces_non_alnum():
    assert gig._slugify("Kubernetes Cert Path!") == "kubernetes-cert-path"


def test_slugify_empty_input_falls_back_to_untitled():
    assert gig._slugify("   ---   ") == "untitled"


def test_target_paths_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(gig, "MY_ORIGINALS_ROOT", tmp_path)
    image_path, sidecar_path = gig._target_paths("Cloud and AI Execution", "K8s Cert Path", date(2026, 8, 4))
    assert image_path == tmp_path / "cloud-and-ai-execution" / "k8s-cert-path_20260804.png"
    assert sidecar_path == image_path.with_suffix(".json")


def _brief(**overrides):
    base = {"post_topic": "K8s Cert Path", "pillar": "Cloud and AI Execution",
            "image_description": "Single standalone diagram...", "queue_id": "queue-1"}
    base.update(overrides)
    return base


def _fake_gemini_response(png_bytes=b"fakepngbytes"):
    return {
        "candidates": [{
            "content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": base64.b64encode(png_bytes).decode()}}]}
        }]
    }


def test_generate_batch_writes_image_and_sidecar_with_kelvin_davis_credit(tmp_path, monkeypatch):
    monkeypatch.setattr(gig, "MY_ORIGINALS_ROOT", tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    mock_response = MagicMock()
    mock_response.json.return_value = _fake_gemini_response()
    mock_response.raise_for_status = MagicMock()

    with patch("assets_library.gemini_image_gen.requests.post", return_value=mock_response), \
         patch("assets_library.gemini_image_gen._reattach_to_queue_row", return_value=True) as mock_reattach, \
         patch("assets_library.gemini_image_gen.subprocess.run") as mock_indexer:
        summary = gig.generate_batch([_brief()])

    assert summary == {"generated": 1, "skipped_existing": 0, "failed": 0, "reattached": 1, "failures": []}

    image_path = tmp_path / "cloud-and-ai-execution" / f"k8s-cert-path_{date.today().strftime('%Y%m%d')}.png"
    sidecar_path = image_path.with_suffix(".json")
    assert image_path.read_bytes() == b"fakepngbytes"

    sidecar = json.loads(sidecar_path.read_text())
    assert sidecar["original_creator"] == "Kelvin Davis"
    assert "king kelz" not in json.dumps(sidecar).lower()
    assert sidecar["generated_by"] == "gemini"

    mock_reattach.assert_called_once()
    mock_indexer.assert_called_once()


def test_generate_batch_is_idempotent_skips_existing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(gig, "MY_ORIGINALS_ROOT", tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    existing_dir = tmp_path / "cloud-and-ai-execution"
    existing_dir.mkdir(parents=True)
    (existing_dir / f"k8s-cert-path_{date.today().strftime('%Y%m%d')}.png").write_bytes(b"already-here")

    with patch("assets_library.gemini_image_gen.requests.post") as mock_post:
        summary = gig.generate_batch([_brief()])

    assert summary["skipped_existing"] == 1
    assert summary["generated"] == 0
    mock_post.assert_not_called()


def test_generate_batch_never_blocks_on_one_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(gig, "MY_ORIGINALS_ROOT", tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    failing_response = MagicMock()
    failing_response.raise_for_status.side_effect = Exception("Gemini API down")

    ok_response = MagicMock()
    ok_response.json.return_value = _fake_gemini_response()
    ok_response.raise_for_status = MagicMock()

    with patch("assets_library.gemini_image_gen.requests.post", side_effect=[failing_response, ok_response]), \
         patch("assets_library.gemini_image_gen._reattach_to_queue_row", return_value=False), \
         patch("assets_library.gemini_image_gen.subprocess.run"):
        summary = gig.generate_batch([
            _brief(post_topic="Broken Diagram", queue_id="queue-broken"),
            _brief(post_topic="Working Diagram", queue_id="queue-ok"),
        ])

    assert summary["failed"] == 1
    assert summary["generated"] == 1
    assert "Broken Diagram" in summary["failures"][0]


def test_generate_batch_skips_items_with_no_image_description(tmp_path, monkeypatch):
    monkeypatch.setattr(gig, "MY_ORIGINALS_ROOT", tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    with patch("assets_library.gemini_image_gen.requests.post") as mock_post:
        summary = gig.generate_batch([_brief(image_description=None)])

    assert summary["generated"] == 0
    mock_post.assert_not_called()
