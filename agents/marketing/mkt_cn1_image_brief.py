"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

"""
MKT-CN1 — Image Brief Agent.

Takes the lightweight image_brief dict MKT-LI1/MKT-V1 attach to a
text_post and expands it into a full design brief for whichever tool
actually produces the asset: Claude Design (SVG concept diagrams),
Ideogram/Gemini (hand-drawn/sketchnote), or Canva (polished infographic).
Spec: knowledge/Marketing/Marketing-Engine-Agent-Specs.md,
knowledge/Marketing/Visual-Production-Style.md.

knowledge/Marketing/Visual-Production-Style.md's locked hand-drawn
generation prompt is still PENDING (Kelvin hasn't filled it in as of
2026-07-09) — ideogram briefs below flag that gap explicitly rather than
inventing a prompt.
"""

import logging
from typing import Any, Optional

from agents.marketing._shared import get_anthropic_client, sanitize, write_audit_log

log = logging.getLogger(__name__)

AGENT_ID = "mkt-cn1"
MODEL = "claude-sonnet-4-6"

BRAND_COLORS = ["#070910", "#5a96ff", "#2f6fe6", "#f5a623", "#3fd17a"]

DIMENSIONS = {
    "linkedin_square": "1080x1080",
    "linkedin_header": "1200x628",
}

VISUAL_STYLE_DOC = "knowledge/Marketing/Visual-Production-Style.md"

HAND_DRAWN_KEYWORDS = ("hand-drawn", "sketchnote", "sketch", "framework", "mental model", "process map", "how i built")
INFOGRAPHIC_KEYWORDS = ("data", "stat", "chart", "infographic", "comparison table", "numbers")

DESIGN_SYSTEM_PROMPT = """You write design briefs for concept diagrams rendered by Claude Design (SVG).
Brand tokens: background #070910, primary blue #5a96ff / #2f6fe6, amber accent
#f5a623, green accent #3fd17a. Fonts: Space Grotesk (headings), IBM Plex Sans
(body), JetBrains Mono (data/code). Output ONE paragraph: a complete,
specific SVG design prompt describing the concept diagram to render — no
preamble, no markdown."""


def _classify_brief_type(concept: str, requested_type: Optional[str]) -> str:
    if requested_type in ("claude_design", "ideogram", "canva_infographic"):
        return requested_type
    lowered = concept.lower()
    if any(kw in lowered for kw in HAND_DRAWN_KEYWORDS):
        return "ideogram"
    if any(kw in lowered for kw in INFOGRAPHIC_KEYWORDS):
        return "canva_infographic"
    return "claude_design"


def _dimensions_for(post_type: str) -> str:
    return DIMENSIONS["linkedin_header"] if post_type == "header" else DIMENSIONS["linkedin_square"]


def _design_prompt_for_claude_design(client: Any, concept: str) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=DESIGN_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Concept to illustrate: {concept}"}],
    )
    return response.content[0].text if hasattr(response, "content") else str(response)


def run_cn1_image_brief(
    image_brief_input: dict,
    post_type: str = "square",
    anthropic_client: Optional[Any] = None,
) -> dict:
    concept = sanitize(image_brief_input.get("concept", ""), context="mkt-cn1")
    requested_style = image_brief_input.get("style")
    brief_type = _classify_brief_type(concept, image_brief_input.get("brief_type"))
    dimensions = _dimensions_for(post_type)

    try:
        if brief_type == "claude_design":
            client = get_anthropic_client(anthropic_client)
            design_prompt = _design_prompt_for_claude_design(client, concept)
            reference_style = None

        elif brief_type == "ideogram":
            design_prompt = (
                f"Hand-drawn/sketchnote visual for: {concept}. "
                f"Use the locked house-style prompt in {VISUAL_STYLE_DOC} — "
                "NOT YET SET as of this brief; check that file before generating."
            )
            reference_style = f"{VISUAL_STYLE_DOC} (PENDING — locked prompt + reference image not filled in yet)"

        else:  # canva_infographic
            design_prompt = (
                f"Polished Canva infographic for: {concept}. Pull from the saved Decoded Empire Brand Kit "
                "(primary palette, 2 fonts max, logo lockup)."
            )
            reference_style = requested_style or "Decoded Empire Canva Brand Kit"

        brief = {
            "brief_type": brief_type,
            "design_prompt": design_prompt,
            "brand_colors": BRAND_COLORS,
            "dimensions": dimensions,
            "reference_style": reference_style,
        }
        write_audit_log(AGENT_ID, "image_brief_generated", resource=brief_type, outcome="success")
        return brief
    except Exception as exc:
        write_audit_log(AGENT_ID, "image_brief_generated", resource=str(image_brief_input.get("concept")), outcome=f"failure: {exc}")
        raise
