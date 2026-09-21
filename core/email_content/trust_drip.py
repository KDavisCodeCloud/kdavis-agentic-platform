"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

'trust_drip' sequence -- enrolled by the lead-magnet capture path
(api/routes/email_public.py's /email/subscribe with source='lead_magnet',
delivering the gated security-questionnaire doc). Cross-enrolls into
'newsletter' on completion (core/email_scheduler.py's _process_one).
Also exited by checkout completion (stripe_billing.py) -- a converting
prospect doesn't need more convincing.
"""

from core.email_content._render import _SECURITY_URL, render_html, render_text

SEQUENCE = {
    "key": "trust_drip",
    "name": "Trust drip",
    "description": "4 emails over 12 days building the security/architecture case for a pre-sale prospect.",
    "trigger_type": "lead_magnet_capture",
    "exit_rules": {"exit_on": ["workspace_active"]},
}

_QUESTIONNAIRE_URL = "https://theclouddecoded.com/security#questionnaire"

TEMPLATES = [
    {
        "key": "trust_drip_1_rls_tenant_isolation",
        "step_number": 1, "delay_days": 0,
        "subject": "How tenant isolation actually works here",
        "preheader": "Every query runs through Postgres row-level security, not application-layer trust.",
        "body_html": render_html(
            "Tenant isolation, not a promise -- a database policy",
            [
                "The doc you asked for is attached below. Before you read it, here's the one thing "
                "worth knowing about how we isolate customer data: every table that holds customer "
                "data has row-level security policies enforced by Postgres itself, not just "
                "application code remembering to filter by workspace_id.",
                "That matters because application bugs happen. A missing WHERE clause in a bad "
                "deploy still can't cross a tenant boundary Postgres itself enforces at the row level.",
            ],
            "Read the full doc", _SECURITY_URL,
        ),
        "body_text": render_text(
            "Tenant isolation, not a promise -- a database policy",
            [
                "Every table holding customer data has row-level security enforced by Postgres "
                "itself, not just application code remembering to filter correctly. An application "
                "bug still can't cross a tenant boundary the database itself enforces.",
            ],
            "Read the full doc", _SECURITY_URL,
        ),
        "cta_url": _SECURITY_URL,
        "skip_if": None,
    },
    {
        "key": "trust_drip_2_hitl_audit_trail",
        "step_number": 2, "delay_days": 4,
        "subject": "Nothing executes without approval -- here's the actual mechanism",
        "preheader": "Every remediation option is a proposal until a human clicks approve.",
        "body_html": render_html(
            "The HITL gate isn't a setting you can turn off",
            [
                "Every incident an agent diagnoses produces a set of remediation options -- it never "
                "produces an executed change. A human has to pick an option (or type a custom fix) "
                "and approve it before anything runs against real infrastructure.",
                "That approval, the option chosen, who approved it, and the outcome are all written "
                "to an append-only audit log. There's no autonomous-execution mode to accidentally "
                "leave on, and no way to disable the approval step from a support ticket or a config "
                "flag -- it's the actual architecture, not a policy on top of one that could execute "
                "on its own.",
            ],
        ),
        "body_text": render_text(
            "The HITL gate isn't a setting you can turn off",
            [
                "Every diagnosis produces remediation options, never an executed change. A human "
                "picks and approves before anything runs. Every approval and outcome writes to an "
                "append-only audit log -- there's no autonomous mode to accidentally leave on.",
            ],
        ),
        "cta_url": None,
        "skip_if": None,
    },
    {
        "key": "trust_drip_3_permissions_manifest",
        "step_number": 3, "delay_days": 4,
        "subject": "The exact permissions each agent asks for",
        "preheader": "Read-only by default, with a manifest listing every scope.",
        "body_html": render_html(
            "You can see exactly what each agent can touch",
            [
                "Every agent's required permissions are documented in a manifest -- exact IAM "
                "actions, exact Kubernetes verbs, exact repo scopes. Nothing implicit, nothing "
                "'trust us, we need broad access.'",
                "A read-only mode is also available: agents diagnose and propose remediations "
                "without holding any write credentials at all, useful for a security team that wants "
                "to evaluate the diagnosis quality before granting write access to anything.",
            ],
            "See the permissions manifest", f"{_SECURITY_URL}#permissions",
        ),
        "body_text": render_text(
            "You can see exactly what each agent can touch",
            [
                "Every agent's required permissions are documented in a manifest -- exact IAM "
                "actions, exact Kubernetes verbs, exact repo scopes. A read-only mode is also "
                "available for evaluating diagnosis quality before granting any write access.",
            ],
            "See the permissions manifest", f"{_SECURITY_URL}#permissions",
        ),
        "cta_url": f"{_SECURITY_URL}#permissions",
        "skip_if": None,
    },
    {
        "key": "trust_drip_4_dpa_questionnaire",
        "step_number": 4, "delay_days": 4,
        "subject": "DPA and security questionnaire -- happy to walk through it",
        "preheader": "If your security team needs a completed questionnaire, let's talk directly.",
        "body_html": render_html(
            "If your team needs the paperwork done properly",
            [
                "A Data Processing Agreement and a completed security questionnaire are both "
                "available -- most of what's in ours is the same architecture covered in the last "
                "few emails, formalized for a security review.",
                "If it's easier to walk through it live rather than pass documents back and forth, "
                "reply to this email and we'll set up time.",
            ],
            "Request the questionnaire", _QUESTIONNAIRE_URL,
        ),
        "body_text": render_text(
            "If your team needs the paperwork done properly",
            [
                "A DPA and completed security questionnaire are both available. If it's easier to "
                "walk through it live, reply to this email and we'll set up time.",
            ],
            "Request the questionnaire", _QUESTIONNAIRE_URL,
        ),
        "cta_url": _QUESTIONNAIRE_URL,
        "skip_if": None,
    },
]
