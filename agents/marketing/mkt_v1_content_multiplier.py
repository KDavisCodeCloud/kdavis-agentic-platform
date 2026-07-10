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

MKT-10 (compliance guard) doesn't exist in this repo yet — every output
runs through a stub scan that logs "MKT-10 pending" rather than silently
skipping the step the spec calls for.
"""

import json
import logging
from typing import Any, Optional

from agents.marketing._shared import emit_event, get_anthropic_client, insert_queue_row, sanitize, write_audit_log

log = logging.getLogger(__name__)

AGENT_ID = "mkt-v1"
MODEL = "claude-sonnet-4-6"
TABLE_NAME = "content_queue"

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


def _mkt10_compliance_scan(content: dict) -> dict:
    """Stub — MKT-10 (Compliance Guard) is not built in this repo yet.
    Logs the gap rather than silently skipping the step the spec calls for."""
    log.warning("MKT-10 pending — compliance scan skipped for this content_queue insert")
    return {"passed": True, "notes": "MKT-10 not yet built — scan skipped"}


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

        compliance = _mkt10_compliance_scan(drafts)

        insert_queue_row(
            TABLE_NAME,
            {
                "agent_id": AGENT_ID,
                "status": "pending_review",
                "content": drafts,
                "compliance_notes": compliance["notes"],
            },
            supabase_client,
        )

        write_audit_log(AGENT_ID, "content_multiplied", resource=str(target_platforms), outcome="success")
        emit_event(AGENT_ID, "content_multiplied", {"platforms": target_platforms})
        return drafts
    except Exception as exc:
        write_audit_log(AGENT_ID, "content_multiplied", resource=str(target_platforms), outcome=f"failure: {exc}")
        emit_event(AGENT_ID, "content_multiplied_failed", {"error": str(exc)})
        raise
