"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

'onboarding' sequence -- enrolled by api/routes/stripe_billing.py's
_enroll_onboarding_email_sequence on checkout.session.completed.

DEDUP NOTE: the original build spec's day-0 "welcome+token+connections
link" step is deliberately NOT a step here -- core/email.py's
welcome_email_html already sends exactly that, synchronously, on the
transactional stream, at the same moment this sequence enrolls (see
api/routes/stripe_billing.py's _handle_checkout_completed). Duplicating
it as this sequence's step 1 would double-send the same welcome content
a few minutes apart. This sequence instead starts at the spec's "day 1"
step; six steps (not seven), day offsets 1/2/4/6/9/14 preserved exactly
via each step's delay_days. Documented in GAPS.md.

Steps 1-2 reuse core/email.py's onboarding_day2_checklist_html /
onboarding_day5_setup_help_html verbatim -- real, previously-live,
specific copy (the day5 one inlines actually-verified Azure/AWS setup
steps) is better than regenerating it from scratch.
"""

from core.email import onboarding_day2_checklist_html, onboarding_day5_setup_help_html
from core.email_content._render import _APP_URL, _MEMBERS_URL, render_html, render_text

SEQUENCE = {
    "key": "onboarding",
    "name": "Onboarding",
    "description": "6 emails driving toward first incident through the HITL approval gate.",
    "trigger_type": "checkout_completed",
    "exit_rules": {"exit_on": ["workspace_canceled"]},
}

_COMPANY = "there"  # generated copy has no per-recipient company_name at template-authoring time -- generic salutation

TEMPLATES = [
    {
        "key": "onboarding_step1_connect_stack",
        "step_number": 1, "delay_days": 1,
        "subject": "Still time to connect your stack",
        "preheader": "Nothing runs until at least one system is connected.",
        "body_html": onboarding_day2_checklist_html(_COMPANY),
        "body_text": "Your Cloud Decoded trial is running, but we haven't seen a repo or cloud account "
                     "connected yet. Nothing runs until at least one is connected.\n\n"
                     f"Connect your stack: {_APP_URL}?tab=connections\n\n"
                     "Most teams start with GitHub (or Azure DevOps) -- it takes about two minutes and "
                     "needs no code changes.",
        "cta_url": f"{_APP_URL}?tab=connections",
        "skip_if": "connected_anything",
    },
    {
        "key": "onboarding_step2_connect_alert_source",
        "step_number": 2, "delay_days": 1,
        "subject": "Let's get an alert source connected",
        "preheader": "Azure Action Group, CloudWatch, or Prometheus/Grafana -- exact setup steps inside.",
        "body_html": onboarding_day5_setup_help_html(_COMPANY),
        "body_text": "You've connected a system, but we haven't received a real alert yet. That's usually "
                     "a webhook registration step, not a Cloud Decoded problem.\n\n"
                     "Azure Monitor: register Microsoft.Insights + Microsoft.AlertsManagement, create an "
                     "Action Group with a Webhook action (not Secure Webhook), turn on the Common Alert "
                     "Schema toggle, point it at your workspace's webhook URL.\n\n"
                     "AWS CloudWatch/SNS: subscribe your workspace's webhook URL as an HTTPS endpoint on "
                     "the SNS topic your Alarms publish to -- the subscription confirms automatically.\n\n"
                     f"Get your webhook URL: {_APP_URL}?tab=connections",
        "cta_url": f"{_APP_URL}?tab=connections",
        "skip_if": "alert_source_verified",
    },
    {
        "key": "onboarding_step3_fire_test_incident",
        "step_number": 3, "delay_days": 2,
        "subject": "Fire a test incident before a real one shows up",
        "preheader": "One deliberate alert now beats debugging the pipeline during a real outage.",
        "body_html": render_html(
            "Fire a test incident on purpose",
            [
                "You've got an alert source wired up. Before a real incident is the first thing "
                "that ever hits it, trigger one on purpose.",
                "Force a test alert from whatever you connected -- a manual CloudWatch alarm state "
                "change, an Azure Action Group test action, or a synthetic alert from your monitoring "
                "stack. Watch it land in your HITL queue with a parsed diagnosis and remediation "
                "options, not just a raw log dump.",
                "This is the two-minute check that means the first real incident isn't also the "
                "first time you've seen the pipeline work end to end.",
            ],
            "Open your incident queue", f"{_APP_URL}?tab=incidents",
        ),
        "body_text": render_text(
            "Fire a test incident on purpose",
            [
                "You've got an alert source wired up. Before a real incident is the first thing "
                "that ever hits it, trigger one on purpose.",
                "Force a test alert -- a manual CloudWatch alarm state change, an Azure Action Group "
                "test action, or a synthetic alert from your monitoring stack -- and watch it land in "
                "your HITL queue with a parsed diagnosis, not a raw log dump.",
            ],
            "Open your incident queue", f"{_APP_URL}?tab=incidents",
        ),
        "cta_url": f"{_APP_URL}?tab=incidents",
        "skip_if": "has_first_incident",
    },
    {
        "key": "onboarding_step4_invite_approvers",
        "step_number": 4, "delay_days": 2,
        "subject": "One person approving everything doesn't scale",
        "preheader": "Invite the people who should actually be reviewing remediations.",
        "body_html": render_html(
            "Invite your approvers",
            [
                "Right now, if you're the only member on this workspace, you're also the only "
                "person who can approve a remediation. That's fine for a trial, not for production.",
                "Workspace roles: admin (full control, including inviting others), approver "
                "(can approve or reject incident remediations), viewer (read-only). Invite the "
                "engineers who'd actually be on call, and give them approver -- not admin -- unless "
                "they need to manage billing or membership too.",
                "Every approval, hold, and rejection is logged with who did it and when -- that log "
                "is what makes 'give the on-call engineer approve access' safe to do on day one.",
            ],
            "Invite your team", _MEMBERS_URL,
        ),
        "body_text": render_text(
            "Invite your approvers",
            [
                "If you're the only member on this workspace, you're also the only person who can "
                "approve a remediation. Invite the engineers who'd actually be on call as 'approver' "
                "role -- full audit trail on every approval, hold, and rejection.",
            ],
            "Invite your team", _MEMBERS_URL,
        ),
        "cta_url": _MEMBERS_URL,
        "skip_if": "has_members",
    },
    {
        "key": "onboarding_step5_manual_resolution_path",
        "step_number": 5, "delay_days": 3,
        "subject": "\"I'll just handle this myself\" is a valid answer",
        "preheader": "Every remediation option ships with a custom-fix field and a full audit trail.",
        "body_html": render_html(
            "Sometimes the right move is doing it yourself",
            [
                "Every incident card gives you remediation options an agent generated -- but there's "
                "also a custom-solution field. Type your own fix, execute it through the same HITL "
                "gate, and it's logged exactly like an agent-suggested one: who approved it, what ran, "
                "when it resolved.",
                "The point was never to force you through agent-suggested fixes. It's that nothing "
                "touches your infrastructure -- agent-suggested or hand-typed -- without your explicit "
                "approval and a permanent record of it.",
            ],
        ),
        "body_text": render_text(
            "Sometimes the right move is doing it yourself",
            [
                "Every incident card has a custom-solution field. Type your own fix, run it through "
                "the same approval gate, and it's logged exactly like an agent-suggested remediation.",
            ],
        ),
        "cta_url": None,
        "skip_if": None,
    },
    {
        "key": "onboarding_step6_thirty_day_checkpoint",
        "step_number": 6, "delay_days": 5,
        "subject": "What good looks like at 30 days",
        "preheader": "A short checklist, and where the docs actually live.",
        "body_html": render_html(
            "Two weeks in -- here's the 30-day bar",
            [
                "By day 30, most teams have: at least one real alert source verified, more than one "
                "approver on the workspace, and a handful of incidents that went through the HITL "
                "queue instead of a 2am manual scramble.",
                "If you're not there yet, nothing's broken -- reply to this email and tell us where "
                "it's stuck; we read every reply.",
                "Full docs, SOPs for every agent, and the permissions manifest live in your dashboard "
                "under Docs.",
            ],
            "Open the docs index", f"{_APP_URL}?tab=docs",
        ),
        "body_text": render_text(
            "Two weeks in -- here's the 30-day bar",
            [
                "By day 30: a real alert source verified, more than one approver, and incidents "
                "going through the HITL queue instead of a manual scramble. If you're not there, "
                "reply and tell us where it's stuck.",
            ],
            "Open the docs index", f"{_APP_URL}?tab=docs",
        ),
        "cta_url": f"{_APP_URL}?tab=docs",
        "skip_if": None,
    },
]
