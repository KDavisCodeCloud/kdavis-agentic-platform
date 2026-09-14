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


def enterprise_alert_html(company_name: str, workspace_id: str, contact_email: str | None) -> str:
    return f"""\
<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
  <h1 style="font-size:18px">{company_name} is now Enterprise-tier</h1>
  <p>Workspace <code>{workspace_id}</code> was just set to Enterprise. If they need
  MCP OAuth access, see knowledge/sops/customer-ops/enterprise-mcp-invite.md.</p>
  <p>Contact on file: {contact_email or "(none captured)"}</p>
</div>"""
