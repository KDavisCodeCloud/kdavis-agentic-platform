"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

'winback' sequence -- enrolled by api/routes/stripe_billing.py's
_handle_subscription_deleted. Per the build spec: a canceled workspace
exits every other sequence except this one.
"""

from core.email_content._render import _PRICING_URL, render_html, render_text

SEQUENCE = {
    "key": "winback",
    "name": "Winback",
    "description": "3 emails after cancellation -- exit survey, value recap, offer.",
    "trigger_type": "stripe_event",
    "exit_rules": {"exit_on": ["workspace_active"]},
}

TEMPLATES = [
    {
        "key": "winback_1_exit_survey",
        "step_number": 1, "delay_days": 1,
        "subject": "Sorry to see you go -- one question",
        "preheader": "No pitch here, just want to know what didn't work.",
        "body_html": render_html(
            "One question before you go",
            [
                "Your Cloud Decoded subscription just ended. No pitch in this email -- just one "
                "honest question: what made you cancel? Price, missing a feature you needed, "
                "it just didn't get used, something else entirely?",
                "Reply directly, it goes to a real inbox. Your workspace data is kept, so if you "
                "come back later nothing needs rebuilding.",
            ],
        ),
        "body_text": render_text(
            "One question before you go",
            [
                "Your Cloud Decoded subscription just ended. What made you cancel -- price, a "
                "missing feature, it just didn't get used? Reply and let us know. Your workspace "
                "data is kept either way.",
            ],
        ),
        "cta_url": None,
        "skip_if": None,
    },
    {
        "key": "winback_2_value_recap",
        "step_number": 2, "delay_days": 6,
        "subject": "What's shipped since you left",
        "preheader": "A few things that changed, in case timing was the issue.",
        "body_html": render_html(
            "A quick update, since you left",
            [
                "If the timing was the issue rather than the product itself, a few things have "
                "changed since your subscription ended: the agent roster's grown, RBAC and audit "
                "trail got more granular, and onboarding is faster than it was.",
                "Your old workspace configuration is still there if you want to pick it back up.",
            ],
            "See what's new", _PRICING_URL,
        ),
        "body_text": render_text(
            "A quick update, since you left",
            [
                "If timing was the issue, a few things have changed since you left: a bigger agent "
                "roster, more granular RBAC and audit trail, faster onboarding. Your old workspace "
                "config is still there if you want to pick it back up.",
            ],
            "See what's new", _PRICING_URL,
        ),
        "cta_url": _PRICING_URL,
        "skip_if": None,
    },
    {
        "key": "winback_3_final_check_in",
        "step_number": 3, "delay_days": 15,
        "subject": "Door's still open",
        "preheader": "Last note from us -- always welcome back.",
        "body_html": render_html(
            "Last check-in from us",
            [
                "This is the last email in this sequence -- we don't want to keep filling your "
                "inbox over one canceled subscription.",
                "If something changes on your end, the door's open and your old configuration is "
                "still sitting there waiting.",
            ],
            "Come back any time", _PRICING_URL,
        ),
        "body_text": render_text(
            "Last check-in from us",
            [
                "Last email in this sequence. If something changes on your end, the door's open and "
                "your old configuration is still there.",
            ],
            "Come back any time", _PRICING_URL,
        ),
        "cta_url": _PRICING_URL,
        "skip_if": None,
    },
]
