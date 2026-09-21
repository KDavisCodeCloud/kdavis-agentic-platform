"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

'abandoned_checkout' sequence -- enrolled by
core/email_triggers.py's run_abandoned_checkout_scan once a workspace
has sat at stripe_subscription_status='pending_payment' for 24h. Exits
on checkout completion (api/routes/stripe_billing.py) or workspace
cancellation.
"""

from core.email_content._render import _PRICING_URL, _SECURITY_URL, render_html, render_text

SEQUENCE = {
    "key": "abandoned_checkout",
    "name": "Abandoned checkout",
    "description": "2 emails for a workspace created but never checked out (24h, 72h).",
    "trigger_type": "scheduled_scan",
    "exit_rules": {"exit_on": ["workspace_active", "workspace_canceled"]},
}

TEMPLATES = [
    {
        "key": "abandoned_checkout_1_still_waiting",
        "step_number": 1, "delay_days": 0,
        "subject": "Your Cloud Decoded workspace is still waiting",
        "preheader": "Checkout takes about two minutes -- here's what happens right after.",
        "body_html": render_html(
            "Your workspace is set up, checkout isn't done yet",
            [
                "You started setting up a Cloud Decoded workspace, but checkout never completed -- "
                "nothing's connected or running until it does.",
                "Once checkout finishes: you land straight in the dashboard with a Connections page "
                "ready for your first repo or cloud account, and a welcome email with the exact next "
                "steps. No sales call, no onboarding call required to start.",
            ],
            "Finish checkout", _PRICING_URL,
        ),
        "body_text": render_text(
            "Your workspace is set up, checkout isn't done yet",
            [
                "You started setting up a Cloud Decoded workspace, but checkout never completed. "
                "Once it does, you land straight in the dashboard ready to connect your first repo "
                "or cloud account -- no sales call required.",
            ],
            "Finish checkout", _PRICING_URL,
        ),
        "cta_url": _PRICING_URL,
        "skip_if": None,
    },
    {
        "key": "abandoned_checkout_2_objections",
        "step_number": 2, "delay_days": 2,
        "subject": "The two questions everyone asks before checkout",
        "preheader": "No vendor lock-in, and nothing executes without your approval.",
        "body_html": render_html(
            "The two questions we get most",
            [
                "\"Does this lock us into your platform?\" No -- every remediation is a normal "
                "change against your own infrastructure (a kubectl apply, a Terraform plan, a config "
                "change) executed with your own credentials. Cancel any time and nothing about your "
                "systems depends on Cloud Decoded still running.",
                "\"What actually executes without me looking at it?\" Nothing. Every remediation -- "
                "agent-suggested or hand-typed -- sits in a HITL queue until a human approves it. "
                "There is no autonomous-execution mode to accidentally leave on.",
                "Full architecture on the security page if you want the details before you commit.",
            ],
            "Read the security page", _SECURITY_URL,
        ),
        "body_text": render_text(
            "The two questions we get most",
            [
                "Vendor lock-in: no -- every remediation runs against your own infrastructure with "
                "your own credentials, so canceling leaves nothing dependent on us.",
                "Autonomous execution: none. Every remediation sits in a human-approval queue until "
                "someone approves it, no exceptions.",
            ],
            "Read the security page", _SECURITY_URL,
        ),
        "cta_url": _SECURITY_URL,
        "skip_if": None,
    },
]
