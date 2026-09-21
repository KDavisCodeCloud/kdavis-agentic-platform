"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

'expansion' templates -- per the build spec these are 3 independent
single-shot emails (seat cap, agent ceiling, Enterprise MCP/SSO upsell),
each triggered by a different threshold being hit, not a sequential
day0/dayN drip for one enrollment reason. Modeled here as three separate
one-step sequences (expansion_seat_cap / expansion_agent_ceiling /
expansion_enterprise_upsell) rather than forcing them into
core/email_scheduler.py's step-based drip engine, which assumes ordered
steps for a single enrollment reason.

WIRING STATUS (see GAPS.md): only expansion_seat_cap is actually wired to
a trigger this build (api/routes/workspace_members.py's invite endpoint,
on a SubscriptionError from the seat cap). expansion_agent_ceiling and
expansion_enterprise_upsell have no call site wired -- no existing
"agent-limit ceiling hit" signal was found in this codebase to hook
(agent execution is gated by tier, not a countable "ceiling" a workspace
approaches and crosses), and "Enterprise MCP/SSO upsell" criteria was
never concretely specified beyond the template's own copy. Both
templates exist and can be approved/activated, but nothing will enroll a
subscriber into them until a trigger is built.
"""

from core.email_content._render import _MEMBERS_URL, _PRICING_URL, render_html, render_text

SEQUENCES = [
    {
        "key": "expansion_seat_cap",
        "name": "Expansion -- seat cap",
        "description": "Fires when a workspace hits its tier's seat limit on an invite attempt.",
        "trigger_type": "seat_cap_hit",
        "exit_rules": {"exit_on": []},
    },
    {
        "key": "expansion_agent_ceiling",
        "name": "Expansion -- agent ceiling",
        "description": "Not wired to a trigger this build -- see module docstring.",
        "trigger_type": "manual",
        "exit_rules": {"exit_on": []},
    },
    {
        "key": "expansion_enterprise_upsell",
        "name": "Expansion -- Enterprise MCP/SSO",
        "description": "Not wired to a trigger this build -- see module docstring.",
        "trigger_type": "manual",
        "exit_rules": {"exit_on": []},
    },
]

TEMPLATES = [
    {
        "key": "expansion_seat_cap_email",
        "sequence_key": "expansion_seat_cap", "step_number": 1, "delay_days": 0,
        "subject": "You're at your seat limit",
        "preheader": "Upgrading adds seats -- nothing else changes.",
        "body_html": render_html(
            "You just hit your plan's seat limit",
            [
                "Someone tried to invite a new member and your workspace is at its tier's seat cap. "
                "Upgrading to the next tier raises the limit immediately -- nothing else about your "
                "setup, agents, or history changes.",
                "If a member left or is no longer active, deactivating them also frees a seat without "
                "needing to upgrade.",
            ],
            "Manage members or upgrade", _MEMBERS_URL,
        ),
        "body_text": render_text(
            "You just hit your plan's seat limit",
            [
                "Someone tried to invite a new member and your workspace is at its tier's seat cap. "
                "Upgrading raises the limit immediately, or deactivate an inactive member to free a "
                "seat instead.",
            ],
            "Manage members or upgrade", _MEMBERS_URL,
        ),
        "cta_url": _MEMBERS_URL,
        "skip_if": None,
    },
    {
        "key": "expansion_agent_ceiling_email",
        "sequence_key": "expansion_agent_ceiling", "step_number": 1, "delay_days": 0,
        "subject": "Your tier's agent roster has more room",
        "preheader": "Growth and Enterprise unlock the rest of the roster.",
        "body_html": render_html(
            "There's more roster available",
            [
                "Your current tier caps how many of the agent roster you can run. If you're finding "
                "the ones you have useful, the next tier up unlocks the rest -- IAM minimization, "
                "FinOps cost optimization, drift detection, dependency patching, and more, all on the "
                "same HITL-gated model you're already using.",
            ],
            "See tier comparison", _PRICING_URL,
        ),
        "body_text": render_text(
            "There's more roster available",
            [
                "Your current tier caps the agent roster. The next tier unlocks the rest -- IAM "
                "minimization, FinOps, drift detection, dependency patching -- on the same HITL model.",
            ],
            "See tier comparison", _PRICING_URL,
        ),
        "cta_url": _PRICING_URL,
        "skip_if": None,
    },
    {
        "key": "expansion_enterprise_upsell_email",
        "sequence_key": "expansion_enterprise_upsell", "step_number": 1, "delay_days": 0,
        "subject": "SSO and MCP access for your team",
        "preheader": "Enterprise tier adds SCIM, SSO, and MCP OAuth access.",
        "body_html": render_html(
            "Worth a look at Enterprise",
            [
                "Enterprise tier adds SCIM provisioning, SSO, unlimited seats, and MCP OAuth access "
                "for connecting your own tools directly -- useful once a workspace has grown past a "
                "handful of manually-invited members.",
                "Reply to this email and we'll walk through what an Enterprise setup would actually "
                "look like for your team.",
            ],
            "See tier comparison", _PRICING_URL,
        ),
        "body_text": render_text(
            "Worth a look at Enterprise",
            [
                "Enterprise tier adds SCIM provisioning, SSO, unlimited seats, and MCP OAuth access. "
                "Reply and we'll walk through what that looks like for your team.",
            ],
            "See tier comparison", _PRICING_URL,
        ),
        "cta_url": _PRICING_URL,
        "skip_if": None,
    },
]
