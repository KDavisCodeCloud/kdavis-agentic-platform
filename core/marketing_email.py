"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Cloud Decoded email lifecycle system -- compliance layer (migration 051).
Every marketing-stream send in this platform goes through
send_marketing_email() below; core/email.py's plain send_email() remains
the transactional-only path (welcome, dunning, downgrade, day2/day5 --
unchanged) and must never be used directly for anything enrolled in a
cd_email_sequences sequence.

Enforced here, in order, before a single byte reaches Resend:
  1. template must be status='approved' -- pending_approval/retired never
     send, no override path exists.
  2. recipient must not be in cd_email_suppressions (unsubscribe/bounce/
     complaint/sunset/manual) -- checked fresh on every send, not cached.
  3. recipient must not already have a 'sent' marketing send in the last
     24h (platform-wide cap, transactional exempt).
  4. every send gets the RFC 8058 List-Unsubscribe / List-Unsubscribe-Post
     headers and an appended compliance footer (physical mailing address
     from CD_COMPLIANCE_MAILING_ADDRESS + the same unsubscribe link).

Every outcome -- sent, suppressed, or failed -- writes exactly one
cd_email_sends row, so the daily-cap check and the metrics endpoint both
read a single, complete ledger; nothing about a send is ever silent.
"""

import logging
import os
from typing import Optional
from uuid import UUID, uuid4

from core.click_tracking import rewrite_cta_text, rewrite_links_html
from core.email import EmailError, send_email
from core.unsubscribe_token import make_token

log = logging.getLogger(__name__)

_UNSUBSCRIBE_PATH = "/api/v1/email/unsubscribe"
_DAILY_CAP_INTERVAL = "24 hours"


def _api_base_url() -> str:
    return os.environ.get("API_BASE_URL", "http://localhost:8000")


def unsubscribe_url(email: str) -> str:
    token = make_token(email)
    return f"{_api_base_url()}{_UNSUBSCRIBE_PATH}?token={token}"


def compliance_footer_html(email: str) -> str:
    address = os.environ.get("CD_COMPLIANCE_MAILING_ADDRESS", "")
    url = unsubscribe_url(email)
    address_line = f"<p>{address}</p>" if address else ""
    return f"""
<hr style="border:none;border-top:1px solid #e2e2e2;margin:32px 0 12px">
<div style="font-size:11px;color:#8a8a8a;font-family:-apple-system,Segoe UI,sans-serif">
  {address_line}
  <p>You're receiving this because you signed up at theclouddecoded.com.
  <a href="{url}" style="color:#8a8a8a">Unsubscribe</a></p>
</div>"""


def compliance_footer_text(email: str) -> str:
    address = os.environ.get("CD_COMPLIANCE_MAILING_ADDRESS", "")
    url = unsubscribe_url(email)
    lines = []
    if address:
        lines.append(address)
    lines.append(f"Unsubscribe: {url}")
    return "\n\n---\n" + "\n".join(lines)


def _unsubscribe_headers(email: str) -> dict:
    url = unsubscribe_url(email)
    return {
        "List-Unsubscribe": f"<{url}>, <mailto:unsubscribe@theclouddecoded.com?subject=unsubscribe>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


async def is_suppressed(conn, email: str) -> bool:
    row = await conn.fetchrow(
        "SELECT 1 FROM cd_email_suppressions WHERE lower(email) = lower($1)", email,
    )
    return row is not None


async def daily_cap_reached(conn, email: str) -> bool:
    row = await conn.fetchrow(
        f"""
        SELECT 1 FROM cd_email_sends
        WHERE recipient = $1 AND stream = 'marketing' AND status = 'sent'
          AND sent_at >= NOW() - INTERVAL '{_DAILY_CAP_INTERVAL}'
        LIMIT 1
        """,
        email,
    )
    return row is not None


async def suppress(conn, email: str, reason: str) -> None:
    """Insert-or-refresh a suppression row. Never raises -- called from
    the unsubscribe endpoint and the bounce/complaint webhook, both of
    which must succeed even if this write races with another."""
    await conn.execute(
        """
        INSERT INTO cd_email_suppressions (email, reason)
        VALUES ($1, $2)
        ON CONFLICT (lower(email)) DO UPDATE SET reason = EXCLUDED.reason, created_at = NOW()
        """,
        email.strip().lower(), reason,
    )


async def _record_send(
    conn, *, send_id: UUID, enrollment_id: Optional[str], template_key: str, recipient: str,
    stream: str, status: str, resend_message_id: Optional[str],
    utm_source: Optional[str], utm_medium: Optional[str], utm_campaign: Optional[str],
) -> None:
    await conn.execute(
        """
        INSERT INTO cd_email_sends
            (id, enrollment_id, template_key, recipient, stream, resend_message_id,
             status, utm_source, utm_medium, utm_campaign)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """,
        send_id, UUID(enrollment_id) if enrollment_id else None, template_key, recipient, stream,
        resend_message_id, status, utm_source, utm_medium, utm_campaign,
    )


async def send_marketing_email(
    conn,
    *,
    recipient: str,
    template: dict,
    enrollment_id: Optional[str] = None,
) -> str:
    """
    Sends one marketing-stream email for `template` (a cd_email_templates
    row -- must have status='approved') to `recipient`, enforcing
    suppression + daily cap, appending the compliance footer, rewriting
    body links for click tracking, and setting RFC 8058 headers. Always
    records a cd_email_sends row.

    Returns 'sent', 'suppressed', or 'failed'. Raises ValueError if the
    template isn't approved (a caller bug -- the scheduler must never
    reach this with a non-approved template) and
    core.unsubscribe_token.UnsubscribeConfigError if CD_UNSUBSCRIBE_SECRET
    isn't set (fail-closed -- no marketing email may go out without a
    working unsubscribe link; the caller should stop its whole batch on
    this, not skip just one row).
    """
    if template["status"] != "approved":
        raise ValueError(
            f"send_marketing_email called with non-approved template {template['key']!r} "
            f"(status={template['status']!r}) -- this is a caller bug"
        )

    # Generated up front (not left to the DB default) -- the click-tracking
    # link rewrite below needs to bake this exact id into every redirect
    # URL before the row exists, so a click can be attributed the moment
    # it happens rather than requiring a second lookup.
    send_id = uuid4()
    template_key = template["key"]
    utm_medium = template["sequence_key"]
    utm_campaign = template_key

    if await is_suppressed(conn, recipient):
        await _record_send(
            conn, send_id=send_id, enrollment_id=enrollment_id, template_key=template_key, recipient=recipient,
            stream="marketing", status="suppressed", resend_message_id=None,
            utm_source="email", utm_medium=utm_medium, utm_campaign=utm_campaign,
        )
        return "suppressed"

    if await daily_cap_reached(conn, recipient):
        await _record_send(
            conn, send_id=send_id, enrollment_id=enrollment_id, template_key=template_key, recipient=recipient,
            stream="marketing", status="suppressed", resend_message_id=None,
            utm_source="email", utm_medium=utm_medium, utm_campaign=utm_campaign,
        )
        return "suppressed"

    api_base = _api_base_url()
    tracked_html = rewrite_links_html(template["body_html"], str(send_id), api_base)
    tracked_text = rewrite_cta_text(template["body_text"], str(send_id), template.get("cta_url"), api_base)
    html = tracked_html + compliance_footer_html(recipient)
    text = tracked_text + compliance_footer_text(recipient)
    headers = _unsubscribe_headers(recipient)

    try:
        message_id = await send_email(
            to=recipient, subject=template["subject"], html=html, text=text,
            stream="marketing", headers=headers,
        )
    except EmailError as exc:
        log.warning("[MarketingEmail] Send failed template=%s recipient=%s: %s", template_key, recipient, exc)
        await _record_send(
            conn, send_id=send_id, enrollment_id=enrollment_id, template_key=template_key, recipient=recipient,
            stream="marketing", status="failed", resend_message_id=None,
            utm_source="email", utm_medium=utm_medium, utm_campaign=utm_campaign,
        )
        return "failed"

    await _record_send(
        conn, send_id=send_id, enrollment_id=enrollment_id, template_key=template_key, recipient=recipient,
        stream="marketing", status="sent", resend_message_id=message_id,
        utm_source="email", utm_medium=utm_medium, utm_campaign=utm_campaign,
    )
    return "sent"
