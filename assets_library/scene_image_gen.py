"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

LinkedIn Asset Vault — scene_image_gen.py

Replaces the old single-shot "post text -> rigid diagram template" image
pipeline with a two-step, relevance-gated one, per Kelvin's 2026-09-15
directive:

  Step A: an LLM reads the APPROVED post text and extracts (1) the core
          visual scene the post actually calls for, in its own words,
          and (2) a scene_type classification (CONTRAST/MOMENT/STORY/
          TECHNICAL) that shapes layout, not content.
  Step B: that scene description (never the raw post text, never a fixed
          template) drives the Gemini image call.
  Gate:   the generated image and the post text go back to the LLM
          (vision) with two questions -- does this image actually match
          this post, and is every visible label/word actually legible
          (not garbled/misspelled)? On NO to either, regenerate once
          from the same scene. Still NO -> flag for manual HITL review
          rather than silently attaching a mismatched or broken-label
          image. The legibility half of the gate was added 2026-09-15
          after the backlog audit found gemini-2.5-flash-image
          reliably nailing the subject but garbling dense technical
          labels ("Orchrestation", "RepicaSets") on nearly every
          diagram -- see gemini_image_gen.py's MODEL docstring for the
          model upgrade that was the other half of that fix.

Explicitly NOT "always generate people" or "never generate diagrams" --
Kelvin's own correction (2026-09-15): "every image is not going to be of
people... the image will be whatever gemini decides it to be based on
the post." The only bar is whether the image is SPECIFIC to this post's
actual content, not a generic reusable stand-in for its general topic.
A diagram that precisely depicts this post's specific mechanism is a
match; a generic illustration that could caption any post on the same
broad subject is not.

Reuses gemini_image_gen.py's REST call, file-path convention, and
creator constants rather than duplicating them -- this module only adds
the scene-extraction and relevance-gate layers on top.

Called from two places:
1. scripts/fix_image_relevance_backlog.py -- one-off backlog repair for
   posts already in the queue with a mismatched image (2026-09-15 audit).
2. api/routes/internal_marketing.py's approval endpoints (added
   2026-09-15) -- the permanent pipeline: fires once, synchronously,
   right after a row's status flips to 'approved', before the row is
   ever eligible for scripts/dispatch_scheduled_posts.py to publish it.
"""

import base64
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

from agents.marketing._shared import get_anthropic_client, sanitize
from assets_library.gemini_image_gen import (
    CREATOR_LINKEDIN,
    CREATOR_NAME,
    _generate_image,
    _target_paths,
)

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")

SCENE_EXTRACTION_SYSTEM_PROMPT = """You read an approved LinkedIn post and describe the single visual \
scene that would most specifically and accurately represent it as an image, plus classify its shape.

Respond with ONLY a JSON object matching this exact shape:
{"scene_description": str, "scene_type": "CONTRAST" | "MOMENT" | "STORY" | "TECHNICAL"}

scene_description: 2-3 sentences. Who or what is shown, what is happening, what tension or \
contrast exists (if any), what the setting is. Ground every detail in THIS post's actual, \
specific content -- names of real tools/services/products it mentions, the real problem it \
describes. Never invent a person, company, number, or outcome the post does not state. Never \
use any human name other than "Kelvin Davis" if a person appears in the scene.

scene_type:
- CONTRAST: the post sets up a before/after, right/wrong, vendor-claim-vs-reality, or \
hype-vs-fact tension.
- MOMENT: the post centers on a single insight, realization, or decision point.
- STORY: the post follows a narrative arc -- a journey, a build session, a sequence of events.
- TECHNICAL: the post explains how something actually works -- architecture, process, mechanism.

Pick the type that best fits even when a post has elements of more than one; this only shapes \
image layout, not content."""

_LAYOUT_INSTRUCTIONS = {
    "CONTRAST": (
        "This post sets up a contrast (before/after, right/wrong, hype vs. reality). If a split "
        "panel with a clear divider makes that contrast legible, use one -- only if the scene "
        "genuinely has two contrasting states to show side by side."
    ),
    "MOMENT": (
        "This post centers on a single insight or decision point. Render one scene, one moment -- "
        "1 to 3 characters if people are part of the scene, no more."
    ),
    "STORY": (
        "This post follows a narrative arc. Render either the single climactic moment of that arc, "
        "or a clean 3-panel progression if the sequence itself is the point -- pick whichever the "
        "scene description actually supports."
    ),
    "TECHNICAL": (
        "This post explains how something works. If showing people interacting with the relevant "
        "systems or screens makes the mechanism clearer, do that. A precisely labeled diagram is "
        "also acceptable when a diagram is genuinely the clearest way to show this specific "
        "mechanism -- but every label must be exact and specific to this post, never a generic "
        "placeholder box."
    ),
}

_IMAGE_PROMPT_TEMPLATE = """Create an image that specifically and clearly depicts this scene, drawn \
from a real LinkedIn post: {scene_description}

{layout_instruction}

Choose whatever visual form communicates this scene most clearly and specifically -- a realistic \
editorial illustration with people, a precisely labeled technical diagram, a screen or system \
visual, or a hybrid of these. Base that choice on what this scene actually shows, never on a \
fixed template. Every element in the image must be specific to this post's actual content, not a \
generic, reusable stand-in for its general topic.

Style: professional and credible. Editorial illustration quality similar to HBR or Fast Company \
for narrative or human scenes; clean and precisely labeled for technical content. Warm, \
trustworthy lighting and color. Clean composition, no clutter.

Small text "Kelvin Davis" in a bottom corner if space allows.

Do not produce: generic stock-photo cliches, meaningless abstract art, gradient blobs, or a vague \
illustration that could just as easily caption any other post on this general subject."""

RELEVANCE_GATE_SYSTEM_PROMPT = """You are checking whether a generated image is fit to publish \
alongside the LinkedIn post it was made for. Look at the image and read the post text together, \
then check both of these:

1. Subject match -- does the image actually depict what this specific post is about, not a \
generic scene that could caption any post on the same broad topic.
2. Text legibility -- if the image contains any words, labels, or text, read them closely. Flag \
this as a failure if any word is misspelled, garbled, or nonsensical (e.g. "Orchrestation", \
"RepicaSets", "Abstrcation") -- a diagram that is conceptually right but has broken labels is not \
fit to publish to a technical audience.

Answer starting with exactly "YES" or "NO" on its own (NO if either check fails), then one \
sentence explaining why, naming which check failed if it's a NO."""


def extract_scene_and_classify(post_text: str, anthropic_client: Optional[Any] = None) -> dict:
    client = get_anthropic_client(anthropic_client)
    sanitized = sanitize(post_text, context="scene-image-gen:extract")
    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=SCENE_EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Approved post text:\n{sanitized}"}],
    )
    raw_text = response.content[0].text if hasattr(response, "content") else str(response)
    cleaned = _JSON_FENCE_RE.sub("", raw_text.strip()).strip()
    parsed = json.loads(cleaned, strict=False)
    if parsed.get("scene_type") not in _LAYOUT_INSTRUCTIONS:
        raise ValueError(f"extract_scene_and_classify: unexpected scene_type {parsed.get('scene_type')!r}")
    return parsed


def build_image_prompt(scene_description: str, scene_type: str) -> str:
    return _IMAGE_PROMPT_TEMPLATE.format(
        scene_description=scene_description,
        layout_instruction=_LAYOUT_INSTRUCTIONS[scene_type],
    )


def check_relevance(post_text: str, image_bytes: bytes, anthropic_client: Optional[Any] = None) -> tuple[bool, str]:
    client = get_anthropic_client(anthropic_client)
    sanitized = sanitize(post_text, context="scene-image-gen:gate")
    response = client.messages.create(
        model=MODEL,
        max_tokens=200,
        system=RELEVANCE_GATE_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    },
                },
                {"type": "text", "text": f"Post text:\n{sanitized}\n\nDoes this image match the subject of this post?"},
            ],
        }],
    )
    raw_text = response.content[0].text if hasattr(response, "content") else str(response)
    verdict = raw_text.strip()
    is_match = verdict.upper().startswith("YES")
    return is_match, verdict


def generate_relevant_image(
    post_text: str,
    pillar: str,
    post_topic: str,
    anthropic_client: Optional[Any] = None,
    gemini_api_key: Optional[str] = None,
    file_suffix: Optional[str] = None,
) -> dict:
    """Full two-step + relevance-gate pipeline for one post. Returns a
    dict describing what happened; never raises on a relevance failure
    (that's a valid, expected outcome -- flagged=True) -- only raises on
    a genuine infrastructure failure (Gemini/Claude call errors), same
    "never block the batch, but never lie about success" pattern as the
    rest of this vault's scripts.

    Does not touch Supabase -- the caller attaches image_path to
    whichever row this was generated for, same separation gemini_image_gen.
    py already has between "make the file" and "attach it to a queue row"."""
    import os

    client = get_anthropic_client(anthropic_client)
    api_key = gemini_api_key or os.environ["GEMINI_API_KEY"]

    scene = extract_scene_and_classify(post_text, client)
    prompt = build_image_prompt(scene["scene_description"], scene["scene_type"])

    image_bytes = _generate_image(api_key, prompt)
    is_relevant, reason = check_relevance(post_text, image_bytes, client)
    attempts = 1

    if not is_relevant:
        log.info("scene_image_gen: relevance gate rejected attempt 1 for %r (%s) -- regenerating once", post_topic, reason)
        image_bytes = _generate_image(api_key, prompt)
        is_relevant, reason = check_relevance(post_text, image_bytes, client)
        attempts = 2

    flagged_for_review = not is_relevant
    today = date.today()
    image_path, sidecar_path = _target_paths(pillar, post_topic, today, suffix=file_suffix)
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(image_bytes)

    sidecar_path.write_text(json.dumps({
        "original_creator": CREATOR_NAME,
        "creator_linkedin": CREATOR_LINKEDIN,
        "generated_by": "gemini",
        "generation_date": today.isoformat(),
        "post_topic": post_topic,
        "scene_description": scene["scene_description"],
        "scene_type": scene["scene_type"],
        "image_description": prompt,
        "relevance_gate_attempts": attempts,
        "relevance_gate_passed": is_relevant,
        "relevance_gate_reason": reason,
    }, indent=2))

    return {
        "image_path": image_path,
        "sidecar_path": sidecar_path,
        "scene_description": scene["scene_description"],
        "scene_type": scene["scene_type"],
        "attempts": attempts,
        "relevant": is_relevant,
        "reason": reason,
        "flagged_for_review": flagged_for_review,
    }
