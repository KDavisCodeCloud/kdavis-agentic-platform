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
MKT-N1 — Newsletter Agent.

Builds a weekly branded newsletter per product/brand from research_report.
Two variants: "cloud_decoded" (platform eng / agentic systems, Kelvin's
builder voice) and "decodedsix" (GTA 6 news angle, Confirmed vs Rumored
framing). Spec: knowledge/Marketing/Marketing-Engine-Agent-Specs.md.

Never auto-sends — every draft lands in newsletter_queue with
status='draft'. Wife approves via HITL (Tier 2) before any send.
"""

import json
import logging
from typing import Any, Optional

from agents.marketing._shared import emit_event, get_anthropic_client, insert_queue_row, sanitize, write_audit_log

log = logging.getLogger(__name__)

AGENT_ID = "mkt-n1"
MODEL = "claude-sonnet-4-6"
TABLE_NAME = "newsletter_queue"

VALID_VARIANTS = ("cloud_decoded", "decodedsix")
SEND_TIME = "Tuesday or Wednesday (best open rates)"

VARIANT_BRIEFS = {
    "cloud_decoded": (
        "Cloud Decoded variant: platform engineering / agentic systems angle, "
        "Kelvin's direct builder voice, no fluff."
    ),
    "decodedsix": (
        "DecodedSix variant: lead with the GTA 6 news angle. Label every claim "
        "CONFIRMED or RUMORED — never blur the two."
    ),
}

NEWSLETTER_SYSTEM_PROMPT = """You write a weekly branded email newsletter from a research
report. AEO rule: each subject line must directly answer "what happened this
week in [the niche]" — a concrete claim, not a teaser.

Respond with ONLY a JSON object matching this exact shape:
{
  "subject_lines": [str, str, str],
  "hook_paragraph": str,
  "story_summaries": [str, ...],
  "builders_note": str,
  "cta": str
}"""


def _draft_newsletter(client: Any, research_report: dict, brand_voice_profile: dict, variant: str) -> dict:
    user_prompt = (
        f"{VARIANT_BRIEFS[variant]}\n"
        f"Research report (sanitized): {json.dumps(research_report, default=str)}\n"
        f"Brand voice profile: {json.dumps(brand_voice_profile, default=str)}\n\n"
        "Draft this week's newsletter."
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=NEWSLETTER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw_text = response.content[0].text if hasattr(response, "content") else str(response)
    try:
        return json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        log.warning("MKT-N1: non-JSON model response for variant=%s, using raw text fallback", variant)
        return {
            "subject_lines": [],
            "hook_paragraph": raw_text,
            "story_summaries": [],
            "builders_note": "",
            "cta": "",
        }


def run_n1_newsletter(
    research_report: dict,
    brand_voice_profile: dict,
    list_segment: str,
    variant: str = "cloud_decoded",
    supabase_client: Optional[Any] = None,
    anthropic_client: Optional[Any] = None,
) -> dict:
    if variant not in VALID_VARIANTS:
        raise ValueError(f"variant must be one of {VALID_VARIANTS}, got {variant!r}")

    client = get_anthropic_client(anthropic_client)

    sanitized_report = dict(research_report)
    if "trending_topics" in sanitized_report:
        sanitized_report["trending_topics"] = [
            {**t, "why_it_matters": sanitize(t.get("why_it_matters", ""), context="mkt-n1")} if isinstance(t, dict) else sanitize(t, context="mkt-n1")
            for t in sanitized_report["trending_topics"]
        ]

    try:
        draft = _draft_newsletter(client, sanitized_report, brand_voice_profile, variant)

        newsletter = {
            "subject_lines": draft.get("subject_lines", []),
            "hook_paragraph": draft.get("hook_paragraph", ""),
            "story_summaries": draft.get("story_summaries", []),
            "builders_note": draft.get("builders_note", ""),
            "cta": draft.get("cta", ""),
            "list_segment": list_segment,
        }

        insert_queue_row(
            TABLE_NAME,
            {
                "agent_id": AGENT_ID,
                "product_id": variant,
                "variant": variant,
                "status": "draft",
                "content_json": newsletter,
            },
            supabase_client,
        )

        write_audit_log(AGENT_ID, "newsletter_drafted", resource=variant, outcome="success")
        emit_event(AGENT_ID, "newsletter_drafted", {"variant": variant, "list_segment": list_segment})
        return newsletter
    except Exception as exc:
        write_audit_log(AGENT_ID, "newsletter_drafted", resource=variant, outcome=f"failure: {exc}")
        emit_event(AGENT_ID, "newsletter_drafted_failed", {"variant": variant, "error": str(exc)})
        raise
