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
MKT-V1 — Content Multiplier.

Takes ONE research_report and fans it out to platform-specific drafts:
LinkedIn (text_post or document_carousel + image_brief for MKT-CN1),
Reddit, X/Twitter thread, short-form video script. Spec:
knowledge/Marketing/Marketing-Engine-Agent-Specs.md.

CRITICAL RULE, never relax: community posts (Reddit) are DRAFT ONLY.
`reddit_post["draft_only"]` is always True — this agent never posts to
Reddit, a human does. Ban risk + reputation risk.

Each platform's draft runs through MKT-10 (run_compliance_guard) before
MKT-09 (queue_for_review) writes it to content_queue — tier 2 (wife
reviews product marketing). content_json stays the original structured
draft even when MKT-10 flags something: revised_content is a redacted
copy of the flat string MKT-10 was fed (json.dumps of the draft), and
re-parsing that back into structured JSON on every phrase-redaction is a
real risk of corrupting the draft the human is about to review — flags
go in mkt10_notes instead, so nothing is silently auto-edited.
"""

import json
import logging
from typing import Any, Optional

from agents.marketing._shared import (
    MARKETING_PRODUCT_ID,
    emit_event,
    get_anthropic_client,
    sanitize,
    write_audit_log,
)
from agents.marketing.mkt_09_hitl_queue_manager import queue_for_review
from agents.marketing.mkt_10_compliance_guard import run_compliance_guard

log = logging.getLogger(__name__)

AGENT_ID = "mkt-v1"
MODEL = "claude-sonnet-4-6"

MULTIPLIER_SYSTEM_PROMPT = """You adapt one research report into platform-specific
marketing drafts for the same underlying story, in brand voice, one per
platform's format and norms.

LinkedIn: use "document_carousel" when the content has 3-8 discrete points
(framework, step-by-step, comparison) — output carousel_slides (one string per
slide) and a carousel_pdf_brief; otherwise "text_post" with an image_brief.
Populate exactly one of the two pairs per post; the other is null.

Reddit: value-first, non-promotional, genuinely useful to that community — this
is a DRAFT a human will review and post manually, never automated.

X/Twitter: a thread, one idea per tweet, short.

Video script: hook / body / cta, for a short-form video.

Respond with ONLY a JSON object matching this exact shape:
{
  "linkedin_post": {
    "body": str,
    "format": "text_post" | "document_carousel",
    "image_brief": {"concept": str, "style": str} or null,
    "hook_variants": [str, str, str],
    "carousel_slides": [str, ...] or null,
    "carousel_pdf_brief": {"concept": str, "slide_count": int} or null
  },
  "reddit_post": {"subreddit": str, "body": str, "value_framing": str},
  "x_thread": [str, ...],
  "video_script": {"hook": str, "body": str, "cta": str}
}"""


def _draft_multiplied_content(client: Any, research_report: dict, brand_voice_profile: dict, high_performers: list, target_platforms: list) -> dict:
    user_prompt = (
        f"Research report (sanitized): {json.dumps(research_report, default=str)}\n"
        f"Brand voice profile: {json.dumps(brand_voice_profile, default=str)}\n"
        f"Target platforms: {target_platforms}\n"
        f"Past top performers to learn tone from: {json.dumps(high_performers or [], default=str)}\n\n"
        "Produce the fanned-out drafts."
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=2500,
        system=MULTIPLIER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw_text = response.content[0].text if hasattr(response, "content") else str(response)
    try:
        return json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        log.warning("MKT-V1: non-JSON model response, returning empty-shell drafts")
        return {
            "linkedin_post": {"body": raw_text, "format": "text_post", "image_brief": None, "hook_variants": [], "carousel_slides": None, "carousel_pdf_brief": None},
            "reddit_post": {"subreddit": "", "body": "", "value_framing": ""},
            "x_thread": [],
            "video_script": {"hook": "", "body": "", "cta": ""},
        }


def run_v1_content_multiplier(
    research_report: dict,
    brand_voice_profile: dict,
    target_platforms: list,
    high_performers: Optional[list] = None,
    supabase_client: Optional[Any] = None,
    anthropic_client: Optional[Any] = None,
) -> dict:
    client = get_anthropic_client(anthropic_client)

    sanitized_report = {
        **research_report,
        "pain_language": [
            {**p, "phrase": sanitize(p.get("phrase", ""), context="mkt-v1")} if isinstance(p, dict) else sanitize(p, context="mkt-v1")
            for p in research_report.get("pain_language", [])
        ],
    }

    try:
        drafts = _draft_multiplied_content(client, sanitized_report, brand_voice_profile, high_performers or [], target_platforms)

        # Never relax: draft_only is hardcoded True regardless of what the model returned.
        reddit_post = drafts.get("reddit_post", {}) or {}
        reddit_post["draft_only"] = True
        drafts["reddit_post"] = reddit_post

        # content_queue is one row per platform (platform TEXT NOT NULL) —
        # see db/migrations/007_marketing_queues.sql.
        platform_content = {
            "linkedin": drafts.get("linkedin_post"),
            "reddit": drafts.get("reddit_post"),
            "x": drafts.get("x_thread"),
            "video": drafts.get("video_script"),
        }
        for platform, content in platform_content.items():
            if not content:
                continue

            compliance = run_compliance_guard(
                json.dumps(content, default=str), platform=platform, product_id=MARKETING_PRODUCT_ID,
            )

            queue_for_review(
                {
                    "agent_id": AGENT_ID,
                    "platform": platform,
                    "content_json": content,
                    "mkt10_passed": compliance["passed"],
                    "mkt10_notes": "; ".join(compliance["flags"]) if compliance["flags"] else None,
                },
                tier=2,
                product_id=MARKETING_PRODUCT_ID,
                supabase_client=supabase_client,
            )

        write_audit_log(AGENT_ID, "content_multiplied", resource=str(target_platforms), outcome="success")
        emit_event(AGENT_ID, "content_multiplied", {"platforms": target_platforms})
        return drafts
    except Exception as exc:
        write_audit_log(AGENT_ID, "content_multiplied", resource=str(target_platforms), outcome=f"failure: {exc}")
        emit_event(AGENT_ID, "content_multiplied_failed", {"error": str(exc)})
        raise
