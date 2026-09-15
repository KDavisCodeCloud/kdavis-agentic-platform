"""
Coverage for assets_library/scene_image_gen.py's two-step scene
extraction + relevance-gate pipeline (added 2026-09-15, replacing the
old single-shot diagram-template image generation per Kelvin's
directive). Anthropic and Gemini calls are mocked throughout -- this
covers the extraction/classification parsing, prompt composition, and
the gate/regenerate-once/flag-for-review state machine, not real model
output.
"""
import json
from datetime import date
from unittest.mock import MagicMock, patch

import assets_library.scene_image_gen as sig


def _claude_text_response(text: str) -> MagicMock:
    response = MagicMock()
    response.content = [MagicMock(text=text)]
    return response


def _scene_json(scene_type="TECHNICAL", scene_description="A test scene."):
    return json.dumps({"scene_description": scene_description, "scene_type": scene_type})


def test_extract_scene_and_classify_strips_json_fence_and_parses():
    client = MagicMock()
    client.messages.create.return_value = _claude_text_response(
        f"```json\n{_scene_json(scene_type='CONTRAST', scene_description='Two engineers disagree.')}\n```"
    )
    result = sig.extract_scene_and_classify("some post text", anthropic_client=client)
    assert result == {"scene_description": "Two engineers disagree.", "scene_type": "CONTRAST"}


def test_extract_scene_and_classify_rejects_unknown_scene_type():
    client = MagicMock()
    client.messages.create.return_value = _claude_text_response(
        json.dumps({"scene_description": "x", "scene_type": "DIAGRAM"})
    )
    try:
        sig.extract_scene_and_classify("some post text", anthropic_client=client)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_build_image_prompt_includes_scene_and_matching_layout():
    prompt = sig.build_image_prompt("A specific scene.", "CONTRAST")
    assert "A specific scene." in prompt
    assert sig._LAYOUT_INSTRUCTIONS["CONTRAST"] in prompt
    # never a rigid "must show people" mandate, per Kelvin's 2026-09-15 correction
    assert "must show people" not in prompt.lower()


def test_check_relevance_parses_yes():
    client = MagicMock()
    client.messages.create.return_value = _claude_text_response("YES. The image shows the exact CI/CD pipeline described.")
    is_match, reason = sig.check_relevance("post text", b"fakepng", anthropic_client=client)
    assert is_match is True
    assert reason.startswith("YES")


def test_check_relevance_parses_no():
    client = MagicMock()
    client.messages.create.return_value = _claude_text_response("NO. The image is a generic diagram unrelated to this post.")
    is_match, reason = sig.check_relevance("post text", b"fakepng", anthropic_client=client)
    assert is_match is False


def test_generate_relevant_image_passes_gate_on_first_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(sig, "_target_paths", lambda pillar, topic, today, suffix=None: (
        tmp_path / "img.png", tmp_path / "img.json"
    ))
    client = MagicMock()
    client.messages.create.side_effect = [
        _claude_text_response(_scene_json()),  # extract_scene_and_classify
        _claude_text_response("YES. Matches."),  # check_relevance
    ]

    with patch("assets_library.scene_image_gen._generate_image", return_value=b"pngbytes") as mock_gen:
        result = sig.generate_relevant_image(
            "post text", "Cloud and AI Execution", "Some Topic",
            anthropic_client=client, gemini_api_key="fake-key",
        )

    assert result["attempts"] == 1
    assert result["relevant"] is True
    assert result["flagged_for_review"] is False
    mock_gen.assert_called_once()
    assert (tmp_path / "img.png").read_bytes() == b"pngbytes"
    sidecar = json.loads((tmp_path / "img.json").read_text())
    assert sidecar["relevance_gate_attempts"] == 1
    assert sidecar["relevance_gate_passed"] is True
    assert sidecar["scene_type"] == "TECHNICAL"


def test_generate_relevant_image_regenerates_once_then_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(sig, "_target_paths", lambda pillar, topic, today, suffix=None: (
        tmp_path / "img.png", tmp_path / "img.json"
    ))
    client = MagicMock()
    client.messages.create.side_effect = [
        _claude_text_response(_scene_json()),       # extract_scene_and_classify
        _claude_text_response("NO. Wrong subject."),  # check_relevance attempt 1
        _claude_text_response("YES. Matches now."),   # check_relevance attempt 2
    ]

    with patch("assets_library.scene_image_gen._generate_image", side_effect=[b"first", b"second"]) as mock_gen:
        result = sig.generate_relevant_image(
            "post text", "Cloud and AI Execution", "Some Topic",
            anthropic_client=client, gemini_api_key="fake-key",
        )

    assert mock_gen.call_count == 2
    assert result["attempts"] == 2
    assert result["relevant"] is True
    assert result["flagged_for_review"] is False
    assert (tmp_path / "img.png").read_bytes() == b"second"


def test_generate_relevant_image_flags_for_review_after_second_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(sig, "_target_paths", lambda pillar, topic, today, suffix=None: (
        tmp_path / "img.png", tmp_path / "img.json"
    ))
    client = MagicMock()
    client.messages.create.side_effect = [
        _claude_text_response(_scene_json()),
        _claude_text_response("NO. Wrong subject."),
        _claude_text_response("NO. Still wrong."),
    ]

    with patch("assets_library.scene_image_gen._generate_image", side_effect=[b"first", b"second"]):
        result = sig.generate_relevant_image(
            "post text", "Cloud and AI Execution", "Some Topic",
            anthropic_client=client, gemini_api_key="fake-key",
        )

    assert result["attempts"] == 2
    assert result["relevant"] is False
    assert result["flagged_for_review"] is True
    # file still written -- caller decides what to do with a flagged image, this layer never silently drops it
    assert (tmp_path / "img.png").exists()
