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
MKT-10 — Compliance Guard.

Rule-based (no LLM call — a fast, deterministic pre-filter, not another
judgment call) scan every marketing output runs through before MKT-09
puts it in front of a human. Spec: knowledge/Marketing/Marketing-Engine-
Agent-Specs.md's GOVERNANCE section ("Blocks non-compliant output before
HITL": platform ToS risk, brand safety, outreach compliance).

Checks: competitor names used derogatorily, regulated financial claims,
fake-testimonial-shaped content, platform-specific prohibited phrases.

Two things this deliberately does NOT try to do:
- Prove a testimonial is fake. There's no customer database to check
  authenticity against here — it flags anything shaped like an
  attributed quote for a human to verify, rather than claiming to
  detect fakeness it has no way to measure.
- Know real competitor names. None are named anywhere in
  knowledge/Marketing/*.md as of this build (checked before writing
  this) — COMPETITOR_NAMES_BY_PRODUCT below is empty and extensible per
  product_id rather than populated with invented company names.
"""

import logging
import re
from typing import Optional

from agents.marketing._shared import write_audit_log

log = logging.getLogger(__name__)

AGENT_ID = "mkt-10"

# Populate as named competitors are identified per product_id — nothing is
# named anywhere in knowledge/Marketing/*.md as of this build, so there's
# nothing real to hardcode yet. An empty list for a product_id means this
# check never fires for it, not a false pass.
COMPETITOR_NAMES_BY_PRODUCT: dict[str, list[str]] = {}

DEROGATORY_WORDS = (
    "scam", "garbage", "trash", "terrible", "worst", "fraud", "rip off", "rip-off",
    "awful", "sucks", "joke", "incompetent",
)

FINANCIAL_CLAIM_PHRASES = (
    "guaranteed return", "guaranteed returns", "guaranteed income", "guaranteed profit",
    "guaranteed roi", "risk-free", "risk free", "no risk", "zero risk",
    "get rich quick", "double your money", "guaranteed to make money",
    "guaranteed passive income",
)

PLATFORM_PROHIBITED_PHRASES: dict[str, tuple[str, ...]] = {
    "linkedin": (
        "like if you agree", "comment 'yes'", "comment yes below", "tag 3 friends",
        "tag a friend", "dm me for details", "link in comments", "follow for follow",
    ),
    "reddit": (
        "buy now", "limited time offer", "click here", "dm me to purchase", "act now",
    ),
    "x": ("follow for follow", "like and retweet to win", "rt to win"),
    "twitter": ("follow for follow", "like and retweet to win", "rt to win"),
    "newsletter": ("click here now", "act now or lose", "buy now or miss out"),
    "email": ("click here now", "act now or lose", "buy now or miss out"),
}

# Quoted text followed by an attribution dash and a capitalized name — flags
# for manual verification, doesn't claim to detect fakeness.
_TESTIMONIAL_RE = re.compile(r'"[^"]{10,}"\s*[-—~]\s*[A-Z][\w.]*(?:\s+[A-Z][\w.]*){0,3}')
_WORD_RE = re.compile(r"[A-Za-z']+")


def _competitor_derogatory_flags(content: str, product_id: str) -> list[str]:
    names = COMPETITOR_NAMES_BY_PRODUCT.get(product_id, [])
    if not names:
        return []

    lowered = content.lower()
    words = _WORD_RE.findall(lowered)
    flags = []
    for name in names:
        name_tokens = name.lower().split()
        if not name_tokens or name_tokens[0] not in lowered:
            continue
        for i in range(len(words) - len(name_tokens) + 1):
            if words[i:i + len(name_tokens)] != name_tokens:
                continue
            window = words[max(0, i - 6):i + len(name_tokens) + 6]
            if any(bad in window for bad in DEROGATORY_WORDS):
                flags.append(f"competitor_derogatory: '{name}' mentioned near negative language")
            break
    return flags


def _financial_claim_flags(content: str) -> tuple[list[str], str]:
    flags = []
    revised = content
    # Longest-first so e.g. "guaranteed returns" is matched whole rather than
    # leaving a stray "s" after "guaranteed return" matches as its prefix.
    for phrase in sorted(FINANCIAL_CLAIM_PHRASES, key=len, reverse=True):
        if phrase in revised.lower():
            flags.append(f"regulated_financial_claim: '{phrase}'")
            revised = re.sub(re.escape(phrase), "[CLAIM REMOVED]", revised, flags=re.IGNORECASE)
    return flags, revised


def _platform_prohibited_flags(content: str, platform: str) -> tuple[list[str], str]:
    phrases = PLATFORM_PROHIBITED_PHRASES.get(platform.lower(), ())
    flags = []
    revised = content
    for phrase in sorted(phrases, key=len, reverse=True):
        if phrase in revised.lower():
            flags.append(f"platform_prohibited_phrase ({platform}): '{phrase}'")
            revised = re.sub(re.escape(phrase), "[PHRASE REMOVED]", revised, flags=re.IGNORECASE)
    return flags, revised


def _testimonial_flags(content: str) -> list[str]:
    return [f"testimonial_needs_verification: {m[:80]}" for m in _TESTIMONIAL_RE.findall(content)]


def run_compliance_guard(content: str, platform: str, product_id: str) -> dict:
    flags: list[str] = []

    flags.extend(_competitor_derogatory_flags(content, product_id))

    revised = content
    financial_flags, revised = _financial_claim_flags(revised)
    flags.extend(financial_flags)

    platform_flags, revised = _platform_prohibited_flags(revised, platform)
    flags.extend(platform_flags)

    # Checked against the original text, not the redacted copy — redaction
    # only touches financial/prohibited phrases, never quote attribution.
    flags.extend(_testimonial_flags(content))

    passed = not flags
    revised_content: Optional[str] = revised if revised != content else None

    outcome = "passed" if passed else f"flagged: {len(flags)} issue(s)"
    write_audit_log(AGENT_ID, "compliance_scan", resource=platform, outcome=outcome)

    return {"passed": passed, "flags": flags, "revised_content": revised_content}
