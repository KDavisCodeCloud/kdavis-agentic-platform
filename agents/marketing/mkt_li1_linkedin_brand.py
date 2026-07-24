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
MKT-LI1 — LinkedIn Personal Brand Agent v2.1.

Builds Kelvin as the authority — his personal brand is the warm
distribution channel for every product launch. Distinct from product
marketing (MKT-V1). Full spec: knowledge/Marketing/Marketing-Engine-Agent-Specs.md.
System prompt: knowledge/Marketing/MKT-LI1-System-Prompt-v2.md.

v2.1 content pillars (per monthly batch of ~12 — see MONTHLY BATCH
CADENCE below for why this replaced the old weekly/10 model):
  Pillar 1: Cloud and AI Execution (40%) — primary authority engine
  Pillar 2: Builder's Journey (30%) — human layer, build-in-public
  Pillar 3: Philosophy, Faith, Gardening (20%) — differentiation layer
  Pillar 4: Product, Business, CTA (10%) — used sparingly

HITL tiers: Tier 2 (wife) = Pillars 1-3 with no product mention.
Tier 3 (Kelvin) = any Pillar 4 post, product mention, pricing, MKT-10 flag.

Veteran and corporate career are texture, not identity — never headline.
Every post runs through MKT-10 (run_compliance_guard) before MKT-09
(queue_for_review) writes it to linkedin_content_queue. This agent never
posts (core/publishers/linkedin.py handles that after HITL approval).

MONTHLY BATCH CADENCE (changed 2026-07-23, replacing the old weekly
4/week model): Kelvin's technical/authority content (the Gemini-illustrated
diagram series) reads as a fixed monthly batch, not a pooled weekly draw —
so MKT-LI1 now generates POSTS_PER_BATCH posts once per batch_month and
reviews/approves them together. Approval is a one-time action; each post
then fires on its own scheduled_for timestamp across the month via
scripts/dispatch_scheduled_posts.py (cron), not an immediate bulk-publish —
see db/migrations/013_linkedin_batch_scheduling.sql.

Image asset vault (added 2026-07-22): for text_post format only (carousel
posts use carousel_pdf_brief instead, untouched by this), selects an
existing curated image from assets_library/ via asset_selector.select_asset()
using this post's topic, and OVERWRITES image_brief with that selection's
payload (image_id/image_path/credit_line/is_original/selected_because) —
the old Canva concept/style/brand_colors shape is not used while the
Canva Autofill integration is parked (per Kelvin's 2026-07-22 directive:
Canva is for original-idea generation only, not in use yet). The selected
image is attached HERE, before HITL queuing, specifically so the human
reviewer sees and can reject the image choice along with the copy — never
re-selected later at publish time, which would let a different image go
live than the one actually reviewed. post_copy is also run through
post_formatter.format_post() here, using this same selection's
credit_line/is_original, so the queued row is the exact text that will be
posted — publish-time uses it verbatim, no reformatting.

Gemini image generation (added 2026-07-23): each drafted post now also
carries image_description — a fully-composed, single-diagram Gemini
prompt (see VOICE_SYSTEM_PROMPT's OUTPUT FORMAT section) for posts whose
topic calls for an original technical diagram rather than a vault photo.
MKT-LI1 itself never calls Gemini — at draft time, select_asset() is
still tried first against the existing vault (a my_originals/ match from
earlier in this same batch run always wins), and image_description just
rides along on the queued row unused if a match was found. When no match
exists yet, generation_available=true on image_brief signals that
assets_library/gemini_image_gen.py can still produce one — it runs after
this agent, in monthly_batch.sh's Step 1.5, and re-attaches the generated
image directly to this exact queue row by id (never by fuzzy topic
re-matching — a monthly technical diagram is bespoke to its own post, not
a shared reusable asset like the vault's other photos).
"""

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from agents.marketing._shared import (
    MARKETING_PRODUCT_ID,
    apportion,
    emit_event,
    get_anthropic_client,
    sanitize,
    write_audit_log,
)
from agents.marketing.mkt_09_hitl_queue_manager import queue_for_review
from agents.marketing.mkt_10_compliance_guard import run_compliance_guard
from assets_library.asset_selector import select_asset
from assets_library.post_formatter import format_post

log = logging.getLogger(__name__)

AGENT_ID = "mkt-li1"
MODEL = "claude-sonnet-4-6"

CONTENT_MIX_RATIO = {"pillar_1": 0.4, "pillar_2": 0.3, "pillar_3": 0.2, "pillar_4": 0.1}
PILLAR_NAMES = {
    "pillar_1": "Cloud and AI Execution",
    "pillar_2": "The Builder's Journey",
    "pillar_3": "Philosophy, Faith, and Gardening",
    "pillar_4": "Product, Business, and CTA",
}
POSTS_PER_BATCH = 12
POST_WEEKDAYS = [1, 2, 3]  # Tue, Wed, Thu (Monday=0) — same cadence feel as the old weekly rotation
POST_HOUR_ET = 9
_ET = ZoneInfo("America/New_York")

VOICE_SYSTEM_PROMPT = """You are MKT-LI1, the LinkedIn content generation agent for Kelvin Davis,
founder of THD Agentic Systems LLC and the Decoded Empire portfolio. Your sole function
is to draft LinkedIn posts that build Kelvin's personal brand as a cloud and AI
practitioner-builder. You do not publish.

WHO KELVIN IS:
Kelvin is a Senior Cloud/DevOps Engineer with 7+ years of multi-cloud experience
(Azure, AWS, Kubernetes, Terraform, IaC) simultaneously building a portfolio of agentic
software products. Not a consultant — a builder documenting the build in public.
Products: Cloud Decoded (LLM-agnostic HITL DevOps), Micro SaaS Engine, DecodedSix (GTA 6
hub), CEO Decoded (internal OS). Exit threshold: $15K MRR for three consecutive months.

Personal philosophy: faith, gardening, fatherhood, craftsman engineering. These are the
operating system behind how and why he builds — not peripheral.

Career history (USAF veteran, Boeing, Honeywell Aerospace, CorVel) is texture. Proves
pattern recognition and real-world engineering depth. NOT his identity, NOT his headline.
Do not lead with it. Do not frame posts around veteran status or corporate credentials.

BRAND VOICE:
Tone: Direct. Grounded. Built not borrowed. "Here's what I built and what I learned"
— not performing expertise. No motivational poster energy. No hustle culture performance.
Point of view: First-person practitioner. Speaks from what he has actually built and seen
in production — not abstractions about what AI "can do."
Register: Conversational but substantive. Senior engineer talking to peers, not a speaker.
Length serves the idea, not the algorithm.

NEVER sound like:
- "As a veteran-owned business..."
- "Proud to share that..." / "Excited to announce..."
- "Thoughts? Drop them below!"
- Generic AI hype without grounding in real architecture
- Corporate credential stacking as authority signal

CONTENT PILLARS:
Pillar 1 (Cloud and AI Execution, 40%): architecture decisions, tradeoffs, lessons;
  LLM-agnostic design; HITL governance, multi-tenant isolation; cloud+AI IaC;
  what enterprises need vs. what vendors sell; real build sessions.
  Structure: problem/observation → what he built → principle → concrete takeaway.

Pillar 2 (Builder's Journey, 30%): how agentic tooling changed his workflow;
  building in public while employed full-time; decisions under resource constraints;
  aerospace/defense/healthcare cloud lessons; engineer → engineer-founder transition.
  Career history appears here as context ("regulated industries"), not credential flex.

Pillar 3 (Philosophy, Faith, Gardening, 20%): garden → company parallels (patience,
  seasons, pruning); faith as OS (Sunday protected, long-view, decisions under pressure,
  legacy); fatherhood/generational apprenticeship (Tuesday build sessions with son).
  Personal, not prescriptive. "This is how I think" — no preaching.

Pillar 4 (Product, Business, CTA, 10%): product launches as story not press release;
  honest research-first takes; business model decisions; direct CTAs that have earned
  their place. Hustle Decoded long arc: plant seeds, don't announce prematurely.

RATIO RULE — every batch of 10: 4 Pillar 1 / 3 Pillar 2 / 2 Pillar 3 / 1 Pillar 4.
Never two consecutive Pillar 4 posts. No more than two consecutive Pillar 1 posts.

HITL TIERS:
Tier 2 (wife can approve): Pillars 1 and 2 with no product mention; all Pillar 3 posts;
  purely educational or personal posts with no CTA.
Tier 3 (Kelvin must approve): any product mention or CTA; pricing/revenue/MRR references;
  responses to named competitors or market events; all Pillar 4; any MKT-10 flagged post.

DO NOT: post anything; decide what publishes; expose internal agent names or architecture
details; generate engagement bait (no "what do you think?", no "share if you agree").

Format rule: use "document_carousel" when content has 3-8 discrete points (framework,
steps, comparison). Otherwise use "text_post". Populate exactly one pair; other is null.

## OUTPUT FORMAT

image_description (text_post only, null for document_carousel): a fully-composed prompt
for a Gemini image-generation call that becomes this post's custom technical diagram.
One Gemini API call renders exactly one image from this string verbatim — it must
describe ONE standalone diagram only, never a grid, collage, or multi-panel composite
(that is what Gemini defaults to when a prompt implies more than one concept at once).

image_description must describe the diagram spatially and specifically:
- Name every node, box, and label
- Describe the layout (left to right, top to bottom, grid, flow)
- Specify arrow directions and what connects to what
- Include real tool/service names and logos where relevant to the post topic

Always start image_description with:
"Single standalone diagram. One concept only. No panels, no grids, no collages.
Full bleed 1080x1080px white background."

Always end image_description with:
"Navy #0A0F1E primary elements, blue #5a96ff highlights, amber #F5A623 callouts and
important labels. Clean sans-serif font. Real cloud provider logos where relevant.
Small text \"Kelvin Davis\" bottom right corner. Professional LinkedIn infographic
style similar to ByteByteGo. White background. No dark backgrounds."

Never use any name other than "Kelvin Davis" anywhere in image_description or post_copy.

Respond with ONLY a JSON object matching this exact shape:
{
  "pillar": 1 | 2 | 3 | 4,
  "topic": str,
  "hitl_tier": 2 | 3,
  "estimated_length": "short" | "medium" | "long",
  "post_copy": str,
  "hook_variants": [str, str, str],
  "format": "text_post" | "document_carousel",
  "image_brief": {"concept": str, "style": str, "brand_colors": [str]} or null,
  "image_description": str or null,
  "carousel_slides": [str, ...] or null,
  "carousel_pdf_brief": {"concept": str, "slide_count": int, "style": str} or null,
  "notes": str
}"""


def _content_pool(research_report: dict, idea_reservoir: list, build_updates: list) -> dict[str, list[dict]]:
    """Buckets source material by pillar key. Never fabricates — a pillar with
    no source material simply yields no post that week."""
    content_angles = research_report.get("content_angles", []) if research_report else []
    pool: dict[str, list[dict]] = {"pillar_1": [], "pillar_2": [], "pillar_3": [], "pillar_4": []}

    for angle in content_angles:
        text = angle.get("angle") if isinstance(angle, dict) else str(angle)
        pool["pillar_1"].append({"text": text, "source": "research_report.content_angles"})

    for idea in idea_reservoir or []:
        raw_type = idea.get("type") if isinstance(idea, dict) else None
        text = idea.get("text") if isinstance(idea, dict) else str(idea)
        # Support both old bucket names and new pillar keys
        pillar_map = {"educational": "pillar_1", "journey": "pillar_2",
                      "repurposed": "pillar_3", "product": "pillar_4"}
        bucket = pillar_map.get(raw_type, raw_type) if raw_type in (list(pillar_map) + list(pool)) else "pillar_2"
        if bucket not in pool:
            bucket = "pillar_2"
        pool[bucket].append({"text": text, "source": "idea_reservoir", "raw": idea})

    for update in build_updates or []:
        text = update.get("text") if isinstance(update, dict) else str(update)
        pool["pillar_2"].append({"text": text, "source": "build_updates", "raw": update})
        if isinstance(update, dict) and update.get("milestone"):
            pool["pillar_4"].append({"text": text, "source": "build_updates", "raw": update})

    return pool


def _build_slots(pool: dict[str, list[dict]], posts_per_batch: int = POSTS_PER_BATCH) -> list[dict]:
    quota = apportion(CONTENT_MIX_RATIO, posts_per_batch)
    slots: list[dict] = []
    for pillar_key, count in quota.items():
        for _ in range(count):
            if not pool[pillar_key]:
                if pillar_key == "pillar_4":
                    continue  # never fabricate a milestone — just drop the slot
                fallback = "pillar_1" if pool["pillar_1"] else None
                if not fallback:
                    continue
                pillar_key = fallback
            if not pool[pillar_key]:
                continue
            slots.append({"pillar_key": pillar_key, "source": pool[pillar_key].pop(0)})
    return slots


def _current_batch_month(today: Optional[date] = None) -> str:
    return (today or date.today()).strftime("%Y-%m")


def _compute_schedule(batch_month: str, count: int) -> list[datetime]:
    """
    Spreads `count` posts across batch_month on POST_WEEKDAYS at
    POST_HOUR_ET, cycling through weeks until every post has a date —
    e.g. 12 posts at 3/week (Tue/Wed/Thu) fills exactly 4 weeks. Falls
    into the following month automatically if a batch is larger than
    the target month can fit on those weekdays alone (never drops a
    post to make it fit).
    """
    year, month = (int(part) for part in batch_month.split("-"))
    first_of_month = date(year, month, 1)

    candidate_dates: list[date] = []
    d = first_of_month
    while len(candidate_dates) < count:
        if d.weekday() in POST_WEEKDAYS:
            candidate_dates.append(d)
        d += timedelta(days=1)

    return [
        datetime(d.year, d.month, d.day, POST_HOUR_ET, 0, tzinfo=_ET)
        for d in candidate_dates
    ]


def _draft_post(client: Any, pillar_key: str, source_text: str, voice_profile: dict) -> dict:
    pillar_name = PILLAR_NAMES.get(pillar_key, pillar_key)
    user_prompt = (
        f"Content pillar for this post: {pillar_name}\n"
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
        log.warning("MKT-LI1: non-JSON model response for pillar=%s, using raw text fallback", pillar_key)
        parsed = {
            "pillar": int(pillar_key.split("_")[1]),
            "topic": pillar_name,
            "hitl_tier": 3 if pillar_key == "pillar_4" else 2,
            "estimated_length": "medium",
            "post_copy": raw_text,
            "hook_variants": [],
            "format": "text_post",
            "image_brief": {"concept": source_text, "style": "Decoded brand", "brand_colors": ["#5a96ff", "#f5a623"]},
            "image_description": None,
            "carousel_slides": None,
            "carousel_pdf_brief": None,
            "notes": "",
        }
    return parsed


def _select_image_for_post(topic: str, image_description: Optional[str] = None) -> Optional[dict]:
    """Returns asset_selector's payload, or None if no curated image matches
    this post's topic AND no Gemini generation is possible for it either (a
    text_post is still valid with neither — MKT-LI1 never fabricates a
    match, same principle as never fabricating a milestone in _build_slots
    above). image_description is passed through only so select_asset can
    set generation_available on its output; it plays no role in matching."""
    result = select_asset(topic, image_description=image_description)
    return result if result["image_id"] or result["generation_available"] else None


def run_li1_brand_agent(
    research_report: dict,
    idea_reservoir: list,
    kelvin_voice_profile: dict,
    build_updates: Optional[list] = None,
    batch_month: Optional[str] = None,
    supabase_client: Optional[Any] = None,
    anthropic_client: Optional[Any] = None,
) -> list[dict]:
    build_updates = build_updates or []
    batch_month = batch_month or _current_batch_month()
    client = get_anthropic_client(anthropic_client)

    pool = _content_pool(research_report, idea_reservoir, build_updates)
    slots = _build_slots(pool)
    schedule = _compute_schedule(batch_month, len(slots))

    posts: list[dict] = []
    try:
        for i, slot in enumerate(slots):
            pillar_key = slot["pillar_key"]
            source_text = sanitize(slot["source"]["text"], context=f"mkt-li1:{pillar_key}")

            draft = _draft_post(client, pillar_key, source_text, kelvin_voice_profile)

            # hitl_tier from model output; pillar_4 always Tier 3 regardless
            hitl_tier = 3 if pillar_key == "pillar_4" else int(draft.get("hitl_tier", 2))

            scheduled_for = schedule[i]
            post = {
                "pillar": draft.get("pillar", int(pillar_key.split("_")[1])),
                "pillar_name": PILLAR_NAMES.get(pillar_key, pillar_key),
                "topic": draft.get("topic", ""),
                "hitl_tier": hitl_tier,
                "estimated_length": draft.get("estimated_length", "medium"),
                "post_copy": draft.get("post_copy", ""),
                "hook_variants": draft.get("hook_variants", []) or [],
                "batch_month": batch_month,
                "scheduled_for": scheduled_for.isoformat(),
                "suggested_post_time": scheduled_for.strftime("%A %-I%p ET"),
                "format": draft.get("format", "text_post"),
                "image_brief": draft.get("image_brief"),
                "image_description": draft.get("image_description"),
                "carousel_slides": draft.get("carousel_slides"),
                "carousel_pdf_brief": draft.get("carousel_pdf_brief"),
                "notes": draft.get("notes", ""),
            }

            compliance = run_compliance_guard(post["post_copy"], platform="linkedin", product_id=MARKETING_PRODUCT_ID)
            if compliance["revised_content"]:
                post["post_copy"] = compliance["revised_content"]

            if post["format"] == "text_post":
                asset = _select_image_for_post(post["topic"], image_description=post["image_description"])
                post["image_brief"] = asset
                formatted_copy, format_warnings = format_post(
                    post["post_copy"],
                    credit_line=asset["credit_line"] if asset else None,
                    is_original=asset["is_original"] if asset else False,
                )
                post["post_copy"] = formatted_copy
                if format_warnings:
                    post["notes"] = (post["notes"] + " | " if post["notes"] else "") + "post_formatter: " + "; ".join(format_warnings)

            content_item = {**post, "agent_id": AGENT_ID}
            if compliance["flags"]:
                content_item["hitl_notes"] = "MKT-10: " + "; ".join(compliance["flags"])
                hitl_tier = 3  # MKT-10 flag always escalates to Tier 3

            queued = queue_for_review(content_item, tier=hitl_tier, product_id=MARKETING_PRODUCT_ID, supabase_client=supabase_client)
            post["id"] = queued.get("id")
            posts.append(post)

        write_audit_log(AGENT_ID, "monthly_batch_generated", resource=f"{len(posts)} posts, batch_month={batch_month}", outcome="success")
        emit_event(AGENT_ID, "monthly_batch_generated", {"post_count": len(posts), "batch_month": batch_month})
        return posts
    except Exception as exc:
        write_audit_log(AGENT_ID, "monthly_batch_generated", resource="linkedin_content_queue", outcome=f"failure: {exc}")
        emit_event(AGENT_ID, "monthly_batch_failed", {"error": str(exc)})
        raise
