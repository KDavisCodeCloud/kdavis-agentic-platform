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
Copy-quality rules shared by every agent that drafts customer-facing prose
(content_agent, email_sequence_agent). Kept in one place — duplicating a
buzzword list or a word-count check in two agents is exactly the kind of
thing code_quality_agent (CLAUDE.md Phase 2, step 26) flags as a DRY
violation.
"""

BANNED_BUZZWORDS = (
    "ai-powered",
    "ai powered",
    "revolutionary",
    "game-changing",
    "game changing",
)


def scan_buzzwords(text: str) -> list[str]:
    """Case-insensitive substring scan. Returns the banned phrases present in text."""
    lowered = text.lower()
    return [phrase for phrase in BANNED_BUZZWORDS if phrase in lowered]


def word_count(text: str) -> int:
    return len(text.split())
