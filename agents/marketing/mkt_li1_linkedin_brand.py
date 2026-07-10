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
MKT-LI1 — LinkedIn Personal Brand Agent.

Builds Kelvin as the authority — his personal brand is the warm
distribution channel for every product launch. Distinct from product
marketing (MKT-V1). Spec: knowledge/Marketing/Marketing-Engine-Agent-Specs.md.

Voice positioning (corrected 2026-07-09 — do not revert): the narrow
lane is multi-cloud IaC, Kubernetes, agentic systems, platform
engineering. Kelvin's differentiator is that deep cloud/AI expertise
paired with a fully human builder's life — gardening, faith, and how
those shape the business, systems, and motivations behind the empire.
USAF service is part of the journey and can surface naturally; it is
NOT the headline angle and posts should not lead with it. This was a
direct correction to the original spec docs, which are now updated to
match (Marketing-Engine-Agent-Specs.md, Idea-Reservoir.md,
MASTER-Marketing-Strategy.md).

Content mix (40/30/20/10, maps to the macro 70/20/10 growth/authority/
conversion ratio): 40% educational, 30% journey/build-in-public, 20%
repurposed concept graphics, 10% soft product/milestone — product posts
only fire when build_updates actually contains a real milestone; never
fabricated. Every post lands in linkedin_content_queue with
status='pending_review' — Kelvin approves his own posts (Tier 3). This
agent never posts (core/publishers/linkedin.py is the actual publisher,
called downstream only after HITL approval).
"""

import json
import logging
from typing import Any, Optional

from agents.marketing._shared import (
    apportion,
    emit_event,
    get_anthropic_client,
    insert_queue_row,
    sanitize,
    write_audit_log,
)

log = logging.getLogger(__name__)

AGENT_ID = "mkt-li1"
MODEL = "claude-sonnet-4-6"
TABLE_NAME = "linkedin_content_queue"

CONTENT_MIX_RATIO = {"educational": 0.4, "journey": 0.3, "repurposed": 0.2, "product": 0.1}
POSTS_PER_WEEK = 4
POST_TIMES = ["Tuesday 8am ET", "Wednesday 9am ET", "Thursday 8am ET", "Monday 9am ET"]

NARROW_LANE = "multi-cloud IaC, Kubernetes, agentic systems, platform engineering"

VOICE_SYSTEM_PROMPT = f"""You are ghostwriting LinkedIn posts for Kelvin Davis, in his voice.

Narrow lane (do not dilute): {NARROW_LANE}.

Kelvin's differentiator: deep cloud/AI/agentic-systems expertise paired with a
fully human builder's life — gardening, faith, and how those shape the
business, systems, and motivations behind what he's building. That combination
is the moat. His USAF background is part of the journey and can come up
naturally and briefly — it is NOT the headline, NOT the hook, and posts must
never lead with it or frame it as the differentiator.

Voice: direct, technical, no fluff, builder's perspective. "How I did it," not
"how to" — his specific experience, not generic advice.

Every post: SEO+AEO framing even on LinkedIn — entity-based, first sentence is
a direct, concrete answer/claim, not a throat-clearing hook.

Format rule: use "document_carousel" when the content has 3-8 discrete points
(a framework, step-by-step process, or comparison) — output carousel_slides
(one short string per slide) and a carousel_pdf_brief for a Canva/Figma
document-post design. Otherwise use "text_post" — output an image_brief for a
single supporting graphic. Populate exactly one of the two pairs; the other
must be null.

Respond with ONLY a JSON object matching this exact shape:
{{
  "post_copy": str,
  "hook_variants": [str, str, str],
  "format": "text_post" | "document_carousel",
  "image_brief": {{"concept": str, "style": str, "brand_colors": [str]}} or null,
  "carousel_slides": [str, ...] or null,
  "carousel_pdf_brief": {{"concept": str, "slide_count": int, "style": str}} or null
}}"""


def _content_pool(research_report: dict, idea_reservoir: list, build_updates: list) -> dict[str, list[dict]]:
    """Buckets available source material by content_type so slot-filling
    has something to draw from per type. Never fabricates — a type with
    no source material simply yields no post that week."""
    content_angles = research_report.get("content_angles", []) if research_report else []
    pool: dict[str, list[dict]] = {"educational": [], "journey": [], "repurposed": [], "product": []}

    for angle in content_angles:
        text = angle.get("angle") if isinstance(angle, dict) else str(angle)
        pool["educational"].append({"text": text, "source": "research_report.content_angles"})
        pool["repurposed"].append({"text": text, "source": "research_report.content_angles"})

    for idea in idea_reservoir or []:
        idea_type = idea.get("type") if isinstance(idea, dict) else None
        text = idea.get("text") if isinstance(idea, dict) else str(idea)
        bucket = idea_type if idea_type in pool else "journey"
        pool[bucket].append({"text": text, "source": "idea_reservoir", "raw": idea})

    for update in build_updates or []:
        text = update.get("text") if isinstance(update, dict) else str(update)
        pool["journey"].append({"text": text, "source": "build_updates", "raw": update})
        if isinstance(update, dict) and update.get("milestone"):
            pool["product"].append({"text": text, "source": "build_updates", "raw": update})

    return pool


def _build_slots(pool: dict[str, list[dict]], posts_per_week: int = POSTS_PER_WEEK) -> list[dict]:
    quota = apportion(CONTENT_MIX_RATIO, posts_per_week)
    slots: list[dict] = []
    for content_type, count in quota.items():
        for _ in range(count):
            if not pool[content_type]:
                if content_type == "product":
                    continue  # never fabricate a milestone — just drop the slot
                fallback_type = "educational" if pool["educational"] else None
                if not fallback_type:
                    continue
                content_type = fallback_type
            if not pool[content_type]:
                continue
            slots.append({"content_type": content_type, "source": pool[content_type].pop(0)})
    return slots


def _draft_post(client: Any, content_type: str, source_text: str, voice_profile: dict) -> dict:
    user_prompt = (
        f"Content type for this post: {content_type}\n"
        f"Source material (already sanitized): {source_text}\n"
        f"Kelvin's voice profile notes: {json.dumps(voice_profile, default=str)}\n\n"
        "Write one LinkedIn post."
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=VOICE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw_text = response.content[0].text if hasattr(response, "content") else str(response)
    try:
        parsed = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        log.warning("MKT-LI1: non-JSON model response for content_type=%s, using raw text fallback", content_type)
        parsed = {
            "post_copy": raw_text,
            "hook_variants": [],
            "format": "text_post",
            "image_brief": {"concept": source_text, "style": "Decoded brand", "brand_colors": ["#5a96ff", "#f5a623"]},
            "carousel_slides": None,
            "carousel_pdf_brief": None,
        }
    return parsed


def run_li1_brand_agent(
    research_report: dict,
    idea_reservoir: list,
    kelvin_voice_profile: dict,
    build_updates: Optional[list] = None,
    supabase_client: Optional[Any] = None,
    anthropic_client: Optional[Any] = None,
) -> list[dict]:
    build_updates = build_updates or []
    client = get_anthropic_client(anthropic_client)

    pool = _content_pool(research_report, idea_reservoir, build_updates)
    slots = _build_slots(pool)

    posts: list[dict] = []
    try:
        for i, slot in enumerate(slots):
            content_type = slot["content_type"]
            source_text = sanitize(slot["source"]["text"], context=f"mkt-li1:{content_type}")

            draft = _draft_post(client, content_type, source_text, kelvin_voice_profile)

            post = {
                "post_copy": draft.get("post_copy", ""),
                "hook_variants": draft.get("hook_variants", []) or [],
                "suggested_post_time": POST_TIMES[i % len(POST_TIMES)],
                "format": draft.get("format", "text_post"),
                "content_type": content_type,
                "image_brief": draft.get("image_brief"),
                "carousel_slides": draft.get("carousel_slides"),
                "carousel_pdf_brief": draft.get("carousel_pdf_brief"),
            }
            posts.append(post)

            insert_queue_row(TABLE_NAME, {**post, "agent_id": AGENT_ID, "status": "pending_review"}, supabase_client)

        write_audit_log(AGENT_ID, "weekly_calendar_generated", resource=f"{len(posts)} posts", outcome="success")
        emit_event(AGENT_ID, "weekly_calendar_generated", {"post_count": len(posts)})
        return posts
    except Exception as exc:
        write_audit_log(AGENT_ID, "weekly_calendar_generated", resource="linkedin_content_queue", outcome=f"failure: {exc}")
        emit_event(AGENT_ID, "weekly_calendar_failed", {"error": str(exc)})
        raise
