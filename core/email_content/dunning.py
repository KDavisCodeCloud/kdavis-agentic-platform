"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

'dunning' sequence -- enrolled by api/routes/stripe_billing.py's
_handle_payment_failed, next to the existing synchronous
payment_failed_dunning_html transactional email (unchanged; that one
fires immediately per failed charge, this sequence is the follow-up
cadence).

GROUNDING CORRECTION vs. the original build spec: the spec assumed
"access stays open" while past_due -- checked against
core/compliance.py's real WorkspaceComplianceGuard._BLOCKED_STATUSES,
which includes 'past_due' (agent execution is blocked immediately, not
just at some later suspension point). This sequence's copy reflects that
real behavior instead of the spec's incorrect assumption -- see GAPS.md.
"""

from core.email_content._render import _BILLING_URL, render_html, render_text

SEQUENCE = {
    "key": "dunning",
    "name": "Dunning",
    "description": "3 emails following a failed payment, in step with Stripe's own retry schedule.",
    "trigger_type": "stripe_event",
    "exit_rules": {"exit_on": ["workspace_canceled"]},
}

TEMPLATES = [
    {
        "key": "dunning_1_helpful",
        "step_number": 1, "delay_days": 0,
        "subject": "Quick fix: update your payment method",
        "preheader": "Agents are paused on this workspace until the charge goes through.",
        "body_html": render_html(
            "Your agents are paused until this is fixed",
            [
                "Your last payment didn't go through, and your workspace is paused -- no agent runs "
                "will execute until it's resolved. This is usually an expired card or a bank decline, "
                "not anything wrong on our end.",
                "Nothing about your workspace or its history is affected. Update your card and "
                "everything resumes immediately, no re-setup needed.",
            ],
            "Update payment method", _BILLING_URL,
        ),
        "body_text": render_text(
            "Your agents are paused until this is fixed",
            [
                "Your last payment didn't go through and your workspace is paused -- no agent runs "
                "execute until it's resolved. Usually just an expired card. Update it and everything "
                "resumes immediately.",
            ],
            "Update payment method", _BILLING_URL,
        ),
        "cta_url": _BILLING_URL,
        "skip_if": None,
    },
    {
        "key": "dunning_2_direct",
        "step_number": 2, "delay_days": 3,
        "subject": "Still paused -- your card needs an update",
        "preheader": "Three days in. Two minutes to fix.",
        "body_html": render_html(
            "This is still blocking your agents",
            [
                "Three days since the failed charge, and your workspace is still paused. Stripe is "
                "retrying the charge automatically on its own schedule, but there's no reason to wait "
                "on that if the card just needs updating.",
                "Two minutes in the billing portal fixes it -- no need to contact support unless "
                "something's actually wrong with the account.",
            ],
            "Update payment method", _BILLING_URL,
        ),
        "body_text": render_text(
            "This is still blocking your agents",
            [
                "Three days since the failed charge and your workspace is still paused. Stripe keeps "
                "retrying automatically, but updating your card directly is faster.",
            ],
            "Update payment method", _BILLING_URL,
        ),
        "cta_url": _BILLING_URL,
        "skip_if": None,
    },
    {
        "key": "dunning_3_suspension_warning",
        "step_number": 3, "delay_days": 4,
        "subject": "Your workspace is close to full suspension",
        "preheader": "Once Stripe's retries run out, we can't keep this open.",
        "body_html": render_html(
            "One more retry window before suspension",
            [
                "A week of failed payment attempts. Once Stripe's own retry schedule runs out without "
                "a successful charge, the subscription moves to suspended -- at that point the "
                "workspace is fully locked, not just paused.",
                "Nothing is deleted at that point either, and updating your card at any time (even "
                "after suspension) picks everything back up. But there's no reason to let it get there "
                "if the fix is this small.",
            ],
            "Update payment method", _BILLING_URL,
        ),
        "body_text": render_text(
            "One more retry window before suspension",
            [
                "A week of failed attempts. Once Stripe's retry schedule runs out, the subscription "
                "moves to fully suspended, not just paused. Nothing is deleted, and updating your "
                "card at any point picks everything back up -- but no reason to let it get there.",
            ],
            "Update payment method", _BILLING_URL,
        ),
        "cta_url": _BILLING_URL,
        "skip_if": None,
    },
]
