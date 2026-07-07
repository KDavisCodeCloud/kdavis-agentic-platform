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
Finance, accounting, tax, and wealth tracking package.

Every module in this package is pure Python (stdlib only) and carries no
runtime dependency on any other part of the platform (core/, db/, agents/
base_agent.py, payments/). Data is passed in and returned as dataclasses —
persistence, LLM routing, and HITL wiring happen in a later integration
session. This keeps the finance logic independently testable and safe to
run before the surrounding infrastructure exists.

These modules organize, track, categorize, and surface financial data.
They never give tax advice, make investment decisions, or act as a CPA or
licensed financial advisor. Every output carries DISCLAIMER.
"""

DISCLAIMER = "For CPA/advisor review only. Not financial advice."

# Confidence below this threshold routes an item to a human decision
# instead of being auto-filed. Matches the platform-wide HITL pause
# threshold documented in CLAUDE.md core/hitl_manager spec.
LOW_CONFIDENCE_THRESHOLD = 0.85


def disclaim(payload: dict) -> dict:
    """Stamp the CPA/advisor disclaimer onto an output dict. Idempotent."""
    payload["disclaimer"] = DISCLAIMER
    return payload
