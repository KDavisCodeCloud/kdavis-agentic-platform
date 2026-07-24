"""
Coverage for _draft_post's response parsing (agents/marketing/
mkt_li1_linkedin_brand.py) — found 2026-07-23/24 running the first real
MKT-LI1 batch: Claude wraps its JSON response in a ```json ... ``` fence,
which json.loads() has never tolerated here, so every real call had
always hit the raw-text fallback path (confirmed: all 10 posts in that
first live batch fell back). Claude also sometimes emits literal
unescaped newlines inside string values, which strict-mode json.loads
rejects as invalid control characters despite the content being
perfectly usable.
"""
import json
from unittest.mock import MagicMock

from agents.marketing.mkt_li1_linkedin_brand import _draft_post

VALID_PAYLOAD = {
    "pillar": 1, "topic": "Terraform vs Bicep vs ARM", "hitl_tier": 2,
    "estimated_length": "medium", "post_copy": "line one\nline two",
    "hook_variants": ["a", "b", "c"], "format": "text_post",
    "image_brief": None, "image_description": "Single standalone diagram...",
    "carousel_slides": None, "carousel_pdf_brief": None, "notes": "",
}


def _fake_client(raw_text: str) -> MagicMock:
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[MagicMock(text=raw_text)])
    return client


def test_parses_a_response_wrapped_in_a_json_markdown_fence():
    fenced = "```json\n" + json.dumps(VALID_PAYLOAD) + "\n```"
    result = _draft_post(_fake_client(fenced), "pillar_1", "source", {})

    assert result["topic"] == "Terraform vs Bicep vs ARM"
    assert result["image_description"] == "Single standalone diagram..."


def test_parses_a_bare_fence_with_no_json_language_tag():
    fenced = "```\n" + json.dumps(VALID_PAYLOAD) + "\n```"
    result = _draft_post(_fake_client(fenced), "pillar_1", "source", {})
    assert result["topic"] == "Terraform vs Bicep vs ARM"


def test_parses_unfenced_json_unchanged():
    result = _draft_post(_fake_client(json.dumps(VALID_PAYLOAD)), "pillar_1", "source", {})
    assert result["topic"] == "Terraform vs Bicep vs ARM"


def test_tolerates_literal_unescaped_newlines_inside_string_values():
    # Not valid strict JSON (a real \n control character sitting inside a
    # string literal instead of the two-character escape "\n"), but a real
    # quirk Claude's own JSON output has -- must not fall back over this.
    raw = '{"pillar": 1, "topic": "x", "hitl_tier": 2, "estimated_length": "short", ' \
          '"post_copy": "line one\nline two", "hook_variants": [], "format": "text_post", ' \
          '"image_brief": null, "image_description": null, "carousel_slides": null, ' \
          '"carousel_pdf_brief": null, "notes": ""}'
    result = _draft_post(_fake_client(raw), "pillar_1", "source", {})
    assert result["post_copy"] == "line one\nline two"


def test_still_falls_back_on_genuinely_unparseable_text():
    result = _draft_post(_fake_client("not json at all, just prose."), "pillar_1", "source", {})
    assert result["post_copy"] == "not json at all, just prose."
    assert result["topic"] == "Cloud and AI Execution"
