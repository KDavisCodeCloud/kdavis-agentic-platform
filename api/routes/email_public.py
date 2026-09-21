"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Public (unauthenticated) endpoints for the Cloud Decoded email lifecycle
system (migration 051):

POST /email/subscribe    - newsletter / lead-magnet opt-in
GET  /email/unsubscribe  - confirmation page (does NOT unsubscribe --
                            some mail clients/security scanners GET every
                            link in an email; only a human's confirming
                            click or the RFC 8058 one-click POST below
                            actually unsubscribes)
POST /email/unsubscribe  - RFC 8058 one-click target + this page's own
                            confirm-button submit; suppresses + exits
                            every active enrollment
GET  /e/c/{token}        - click-tracking redirect (records the click,
                            302s to the real destination with UTM params)
POST /email/resend-webhook - bounce/complaint -> suppression + enrollment exit

Rate-limited with the shared `limiter` (api/middleware/rate_limiter.py) --
a fixed per-minute string, not the workspace-tier-keyed limits those
routes use, since these are anonymous/pre-workspace requests (falls back
to source IP, same as that limiter's own get_remote_address fallback).
"""

import hashlib
import logging
import re
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from api.middleware.rate_limiter import limiter
from core.click_tracking import append_utm, verify_click_token
from core.email_enrollment import enroll, exit_all_by_email, get_or_create_subscriber
from core.marketing_email import suppress
from core.resend_webhook import WebhookVerificationError, verify_resend_webhook
from core.unsubscribe_token import verify_token

log = logging.getLogger(__name__)
router = APIRouter(tags=["email-public"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PUBLIC_SOURCES = ("newsletter_signup", "lead_magnet")

# lead_magnet signups go through trust_drip first (delivers the gated
# doc, then cross-enrolls into newsletter on completion -- see
# core/email_scheduler.py's _process_one); everyone else goes straight
# into the newsletter's evergreen drip.
_SOURCE_TO_SEQUENCE = {"newsletter_signup": "newsletter", "lead_magnet": "trust_drip"}


class SubscribeRequest(BaseModel):
    email: str
    source: str = "newsletter_signup"


class SubscribeResponse(BaseModel):
    success: bool
    message: str


@router.post("/email/subscribe", response_model=SubscribeResponse)
@limiter.limit("10/minute")
async def subscribe(body: SubscribeRequest, request: Request) -> SubscribeResponse:
    email = body.email.strip().lower()
    if not email or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email address")
    if body.source not in _PUBLIC_SOURCES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"source must be one of {_PUBLIC_SOURCES}")

    generic_message = "You're in -- check your inbox for a confirmation email."

    async with request.app.state.db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT reason FROM cd_email_suppressions WHERE lower(email) = lower($1)", email,
        )
        if existing and existing["reason"] in ("bounce", "complaint"):
            # Don't reveal suppression state to the public, and don't
            # re-enroll an address that's a deliverability risk -- a
            # bounce/complaint hold isn't something a signup form should
            # be able to clear (unlike an unsubscribe/sunset, which is a
            # user's own prior choice they can freely reverse).
            log.info("[EmailPublic] Signup for %s ignored -- held on %s", email, existing["reason"])
            return SubscribeResponse(success=True, message=generic_message)

        if existing:
            await conn.execute("DELETE FROM cd_email_suppressions WHERE lower(email) = lower($1)", email)

        subscriber_id = await get_or_create_subscriber(conn, email, body.source)
        await enroll(conn, subscriber_id, _SOURCE_TO_SEQUENCE[body.source])

    return SubscribeResponse(success=True, message=generic_message)


def _unsubscribe_page(heading: str, body: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Cloud Decoded</title>
<style>
body{{background:#070910;color:#eef2f5;font-family:-apple-system,Segoe UI,sans-serif;
      display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.card{{max-width:420px;padding:32px;text-align:center}}
h1{{font-size:20px;font-weight:700}}
p{{color:#aab4bd;font-size:14px}}
button{{background:#2f6fe6;color:#fff;border:none;border-radius:8px;padding:10px 20px;
        font-size:14px;font-weight:600;cursor:pointer}}
</style></head>
<body><div class="card"><h1>{heading}</h1><p>{body}</p></div></body></html>"""


@router.get("/email/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_confirm_page(token: str, request: Request) -> HTMLResponse:
    email = verify_token(token)
    if not email:
        return HTMLResponse(_unsubscribe_page(
            "Link expired or invalid",
            "This unsubscribe link is no longer valid. Reply to any Cloud Decoded email and we'll remove you by hand.",
        ))

    return HTMLResponse(f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Unsubscribe — Cloud Decoded</title>
<style>
body{{background:#070910;color:#eef2f5;font-family:-apple-system,Segoe UI,sans-serif;
      display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.card{{max-width:420px;padding:32px;text-align:center}}
h1{{font-size:20px;font-weight:700}}
p{{color:#aab4bd;font-size:14px}}
button{{background:#2f6fe6;color:#fff;border:none;border-radius:8px;padding:10px 20px;
        font-size:14px;font-weight:600;cursor:pointer}}
</style></head>
<body><div class="card">
  <h1>Unsubscribe {email}?</h1>
  <p>You'll stop receiving Cloud Decoded marketing emails. Product and billing emails are unaffected.</p>
  <form method="post" action="/api/v1/email/unsubscribe?token={token}">
    <button type="submit">Confirm unsubscribe</button>
  </form>
</div></body></html>""")


@router.post("/email/unsubscribe")
async def unsubscribe_action(token: str, request: Request) -> dict:
    """RFC 8058 one-click target -- mail clients POST here with body
    `List-Unsubscribe=One-Click` (ignored; token in the query string is
    the only input that matters), and this page's own confirm button
    posts here too. Always returns 200 with a generic body -- an
    already-unsubscribed or expired token must not error, per RFC 8058's
    'the receiving server SHOULD process the request and return
    a success status' guidance."""
    email = verify_token(token)
    if not email:
        return {"success": False, "detail": "Invalid or expired link"}

    async with request.app.state.db_pool.acquire() as conn:
        await suppress(conn, email, "unsubscribe")
        await exit_all_by_email(conn, email, "unsubscribed")

    log.info("[EmailPublic] Unsubscribed %s", email)
    return {"success": True}


@router.get("/e/c/{token}")
async def click_redirect(token: str, request: Request) -> RedirectResponse:
    parsed = verify_click_token(token)
    if not parsed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired link")
    send_id_str, destination = parsed
    try:
        send_id = UUID(send_id_str)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired link")

    async with request.app.state.db_pool.acquire() as conn:
        send_row = await conn.fetchrow(
            "SELECT utm_source, utm_medium, utm_campaign FROM cd_email_sends WHERE id = $1", send_id,
        )
        if send_row:
            # A valid, signed token whose send row no longer exists (data
            # cleanup, edge case) still honors the redirect below -- it
            # just can't record a click against a row that isn't there.
            ip_hash = hashlib.sha256((request.client.host if request.client else "unknown").encode()).hexdigest()[:16]
            await conn.execute(
                "INSERT INTO cd_email_clicks (send_id, url, ip_hash) VALUES ($1, $2, $3)",
                send_id, destination, ip_hash,
            )

    final_url = destination
    if send_row:
        final_url = append_utm(
            destination,
            send_row["utm_source"] or "email",
            send_row["utm_medium"] or "unknown",
            send_row["utm_campaign"] or "unknown",
        )
    return RedirectResponse(url=final_url, status_code=status.HTTP_302_FOUND)


@router.post("/email/resend-webhook")
async def resend_webhook(request: Request) -> dict:
    payload = await request.body()
    try:
        verify_resend_webhook(payload, dict(request.headers))
    except WebhookVerificationError as exc:
        log.warning("[EmailPublic] Resend webhook rejected: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    body = await request.json()
    event_type = body.get("type", "")
    data = body.get("data", {}) or {}
    recipients = data.get("to") or []

    reason_by_event = {"email.bounced": "bounce", "email.complained": "complaint"}
    reason = reason_by_event.get(event_type)
    if not reason or not recipients:
        return {"received": True}

    async with request.app.state.db_pool.acquire() as conn:
        for recipient in recipients:
            await suppress(conn, recipient, reason)
            await exit_all_by_email(conn, recipient, reason)

    log.warning("[EmailPublic] Resend %s for %s -- suppressed", event_type, recipients)
    return {"received": True}
