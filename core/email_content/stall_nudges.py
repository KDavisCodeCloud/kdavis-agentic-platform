"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

'stall_nudges' sequence -- enrolled by core/email_triggers.py's
run_stall_nudge_scan (72h after a workspace's first cloud/repo connection
with no alert source verified yet). Step 2 fires via delay_days rather
than a second independent "no incident by day 7" trigger check -- see
that module's own docstring for the documented simplification.
"""

from core.email_content._render import _APP_URL, render_html, render_text

SEQUENCE = {
    "key": "stall_nudges",
    "name": "Stall nudges",
    "description": "2 emails for a workspace that connected something but stalled before the real payoff.",
    "trigger_type": "scheduled_scan",
    "exit_rules": {"exit_on": ["workspace_canceled"]},
}

TEMPLATES = [
    {
        "key": "stall_nudge_1_alert_source",
        "step_number": 1, "delay_days": 0,
        "subject": "You connected something -- one step left",
        "preheader": "No alert source means no incidents means nothing to approve.",
        "body_html": render_html(
            "You're most of the way there",
            [
                "You connected a cloud account or repo a few days ago, but no alert source has "
                "delivered a real webhook yet. Without that, there's nothing for the agents to "
                "triage -- the HITL queue stays empty no matter how well everything else is wired up.",
                "This is usually a 5-minute Action Group or SNS subscription, not a deeper problem. "
                "Your Connections page has the exact webhook URL and the step-by-step for Azure "
                "Monitor, AWS CloudWatch, and Prometheus/Grafana.",
            ],
            "Connect an alert source", f"{_APP_URL}?tab=connections",
        ),
        "body_text": render_text(
            "You're most of the way there",
            [
                "You connected a cloud account or repo, but no alert source has delivered a real "
                "webhook yet -- the HITL queue stays empty until one does. Your Connections page has "
                "the exact setup steps for Azure Monitor, AWS CloudWatch, and Prometheus/Grafana.",
            ],
            "Connect an alert source", f"{_APP_URL}?tab=connections",
        ),
        "cta_url": f"{_APP_URL}?tab=connections",
        "skip_if": "alert_source_verified",
    },
    {
        "key": "stall_nudge_2_first_incident",
        "step_number": 2, "delay_days": 4,
        "subject": "What's blocking your first incident?",
        "preheader": "A week in with nothing in the queue usually means one small config gap.",
        "body_html": render_html(
            "Still nothing in your incident queue?",
            [
                "A week is long enough that if nothing's shown up yet, something specific is "
                "probably blocking it -- not a lack of things going wrong in your infrastructure.",
                "Common causes: the webhook URL doesn't include the workspace token, the alert "
                "source's payload schema isn't one of the three we parse (Common Alert Schema for "
                "Azure, CloudWatch's default SNS format, or a raw Prometheus Alertmanager webhook), "
                "or the subscription confirmation never completed.",
                "Reply to this email with what you connected and we'll look at it directly.",
            ],
            "Check your connections", f"{_APP_URL}?tab=connections",
        ),
        "body_text": render_text(
            "Still nothing in your incident queue?",
            [
                "A week with nothing in the queue is usually a specific config gap -- wrong webhook "
                "token, an unsupported alert payload schema, or an unconfirmed subscription. Reply "
                "and tell us what you connected, or check your Connections page.",
            ],
            "Check your connections", f"{_APP_URL}?tab=connections",
        ),
        "cta_url": f"{_APP_URL}?tab=connections",
        "skip_if": "has_first_incident",
    },
]
