"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Transactional email via Resend (RESEND_API_KEY) -- closes the "zero email
infrastructure exists anywhere" gap found in the 2026-09-14 operational-
readiness assessment. Two callers as of this writing:
  - api/routes/stripe_billing.py's _handle_checkout_completed -- welcome
    email once a real subscription goes active.
  - api/routes/internal_workspaces.py's set_workspace_tier -- alerts the
    platform owner when a workspace becomes Enterprise-eligible, so the
    Enterprise MCP invite SOP (knowledge/sops/customer-ops/
    enterprise-mcp-invite.md) has something other than manual discovery.

Every call site treats a send failure as non-fatal: a broken email
provider must never break checkout or a tier change. Callers catch
EmailError and log it, they don't let it propagate into their own
response path -- same discipline as sop_agent's "SOP push is non-fatal"
pattern elsewhere in this codebase.
"""

import logging
import os

import httpx

log = logging.getLogger(__name__)

_RESEND_API = "https://api.resend.com/emails"
_DEFAULT_FROM = "Cloud Decoded <hello@theclouddecoded.com>"
_MAX_HTTP_TIMEOUT = 15


class EmailError(Exception):
    """Raised when Resend's API rejects a send or can't be reached. Callers
    must catch this -- it should never be allowed to fail the caller's own
    operation (a checkout webhook, a tier change)."""


async def send_email(to: str, subject: str, html: str, from_addr: str | None = None) -> None:
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        log.warning("[Email] RESEND_API_KEY not set -- skipping send to=%s subject=%r", to, subject)
        return

    async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
        try:
            resp = await client.post(
                _RESEND_API,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "from": from_addr or os.environ.get("RESEND_FROM_EMAIL", _DEFAULT_FROM),
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
            )
        except httpx.RequestError as exc:
            raise EmailError(f"Could not reach Resend: {exc}") from exc

    if resp.status_code >= 300:
        raise EmailError(f"Resend rejected the send ({resp.status_code}): {resp.text[:300]}")

    log.info("[Email] Sent to=%s subject=%r", to, subject)


def welcome_email_html(company_name: str) -> str:
    return f"""\
<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
  <h1 style="font-size:20px">Welcome to Cloud Decoded, {company_name}.</h1>
  <p>Your trial just started. Next step: connect a repo and a cloud account so your
  agents have something real to look at.</p>
  <p><a href="https://theclouddecoded.com/dashboard?tab=connections"
        style="display:inline-block;background:#2f6fe6;color:#fff;padding:10px 18px;
               border-radius:8px;text-decoration:none;font-weight:600">
    Connect your stack →</a></p>
  <p style="font-size:13px;color:#666">Nothing runs against your infrastructure without your
  explicit approval in the HITL Console, every time, no exceptions.</p>
</div>"""


def onboarding_day2_checklist_html(company_name: str) -> str:
    """
    Onboarding completeness build, item 5. Sent ~2 days after checkout
    ONLY if core/onboarding_sequence.py's real signal says this workspace
    hasn't connected anything yet -- see that module's own docstring for
    exactly what "connected anything" means today (a stand-in for the
    real 5/5 setup checklist field, which doesn't exist in the schema
    yet as of this build).
    """
    return f"""\
<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
  <h1 style="font-size:20px">Still time to connect your stack, {company_name}</h1>
  <p>Your Cloud Decoded trial is running, but we haven't seen a repo or cloud
  account connected yet. Nothing runs until at least one is connected.</p>
  <p><a href="https://theclouddecoded.com/dashboard?tab=connections"
        style="display:inline-block;background:#2f6fe6;color:#fff;padding:10px 18px;
               border-radius:8px;text-decoration:none;font-weight:600">
    Connect your stack →</a></p>
  <p style="font-size:13px;color:#666">Most teams start with GitHub (or Azure DevOps) --
  it takes about two minutes and needs no code changes.</p>
</div>"""


def onboarding_day5_setup_help_html(company_name: str) -> str:
    """
    Onboarding completeness build, item 5. Sent ~5 days after checkout
    ONLY if core/onboarding_sequence.py's real signal says no alert
    source has ever actually delivered a webhook to this workspace (a
    real alert_ingestion_log row, not a self-report). Inlines the exact,
    live-verified Azure/AWS setup steps from
    agents/agent_11_resource_health/sop.md rather than a generic
    "check your webhook config" nudge.
    """
    return f"""\
<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:560px;margin:0 auto;color:#1a1a1a">
  <h1 style="font-size:20px">{company_name}, let's get an alert source connected</h1>
  <p>You've connected a system, but we haven't received a real alert yet --
  that's usually a webhook registration step, not a Cloud Decoded problem. Here's
  exactly how to wire it up:</p>

  <h2 style="font-size:15px;margin-top:20px">Azure Monitor</h2>
  <ol style="font-size:13px;color:#333;padding-left:20px">
    <li>Register the resource providers first: <code>Microsoft.Insights</code> and
    <code>Microsoft.AlertsManagement</code>. An unregistered provider is the most
    common reason a fresh Action Group's webhook silently never fires.</li>
    <li>Create an Action Group with an action of type <strong>Webhook</strong> --
    not "Secure Webhook" (that requires an Azure AD handshake we don't implement).</li>
    <li>Turn the <strong>Common Alert Schema</strong> toggle ON. This isn't optional --
    the legacy schema is silently dropped, not an error.</li>
    <li>Use your workspace's webhook URL from Connections (includes the
    <code>/api/v1</code> prefix and your token).</li>
    <li>Test it: Action Group → Test action group → Metric alert sample.</li>
  </ol>

  <h2 style="font-size:15px;margin-top:20px">AWS CloudWatch / SNS</h2>
  <p style="font-size:13px;color:#333">Subscribe your workspace's webhook URL as an
  HTTPS endpoint on an SNS topic that your CloudWatch Alarms publish to. The
  subscription confirms automatically -- nothing further needed on your side.</p>

  <p><a href="https://theclouddecoded.com/dashboard?tab=connections"
        style="display:inline-block;background:#2f6fe6;color:#fff;padding:10px 18px;
               border-radius:8px;text-decoration:none;font-weight:600">
    Get your webhook URL →</a></p>
  <p style="font-size:13px;color:#666">Reply to this email if you'd like a hand setting
  this up -- happy to help directly.</p>
</div>"""


def enterprise_alert_html(company_name: str, workspace_id: str, contact_email: str | None) -> str:
    return f"""\
<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
  <h1 style="font-size:18px">{company_name} is now Enterprise-tier</h1>
  <p>Workspace <code>{workspace_id}</code> was just set to Enterprise. If they need
  MCP OAuth access, see knowledge/sops/customer-ops/enterprise-mcp-invite.md.</p>
  <p>Contact on file: {contact_email or "(none captured)"}</p>
</div>"""


def downgrade_deactivation_html(company_name: str, new_tier: str, deactivated_emails: list[str]) -> str:
    """
    Kelvin's item 3, 2026-09-17 -- replaces the Phase 7 hard downgrade
    block: a Stripe downgrade that drops a workspace below its new
    tier's seat cap is now applied, and the most-recently-added members
    over the cap are deactivated automatically
    (api/routes/stripe_billing.py's _handle_subscription_updated, via
    core/member_deactivation.py -- the same mechanism Phase 4's manual
    deactivation uses). This email is the only notice the workspace
    gets that it happened.
    """
    members_list = "".join(f"<li>{email}</li>" for email in deactivated_emails)
    return f"""\
<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
  <h1 style="font-size:20px">Your plan changed to {new_tier} — some members were removed</h1>
  <p>{company_name} downgraded to the <strong>{new_tier}</strong> plan, which has a lower seat limit
  than your previous plan. The most recently added members over that limit have been
  deactivated to bring you within it:</p>
  <ul>{members_list}</ul>
  <p>Their assigned incidents were returned to unassigned — nothing was lost, just
  reassigned. To restore access:</p>
  <ul>
    <li>Remove other members to make room, then re-invite them, or</li>
    <li>Upgrade your plan again to fit everyone</li>
  </ul>
  <p><a href="https://theclouddecoded.com/dashboard?tab=members"
        style="display:inline-block;background:#2f6fe6;color:#fff;padding:10px 18px;
               border-radius:8px;text-decoration:none;font-weight:600">
    Manage members →</a></p>
</div>"""


def payment_failed_dunning_html(company_name: str) -> str:
    """
    24-gap-closure Phase 7 -- sent on every Stripe invoice.payment_failed
    event (api/routes/stripe_billing.py's _handle_payment_failed). Stripe
    itself retries the charge on its own configured schedule (Smart
    Retries) -- this email exists so the customer knows to fix their
    payment method before those retries run out, not to duplicate
    Stripe's own retry logic.
    """
    return f"""\
<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
  <h1 style="font-size:20px">We couldn't charge your card, {company_name}</h1>
  <p>Your most recent Cloud Decoded payment failed. We'll retry automatically over the
  next several days, but if your card has expired or changed, update it now to avoid
  any interruption.</p>
  <p><a href="https://theclouddecoded.com/billing"
        style="display:inline-block;background:#2f6fe6;color:#fff;padding:10px 18px;
               border-radius:8px;text-decoration:none;font-weight:600">
    Update payment method →</a></p>
  <p style="font-size:13px;color:#666">If retries are exhausted without a successful
  charge, access to your workspace will be suspended until payment is resolved.</p>
</div>"""
