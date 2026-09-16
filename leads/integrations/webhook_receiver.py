"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

webhook_receiver — receives Brevo webhooks back into the platform
(contact updates, unsubscribes, email engagement events) and reconciles
them onto the matching `leads` row. Replaces the old Systeme.io webhook
receiver (removed 2026-09-16, Brevo replaces Systeme.io as this
platform's email provider).

Event names/payload shapes below are Brevo's real, documented webhook
event types (contact/email events — see Brevo's webhook docs for the
authoritative payload shape per event; verify field names against a
real captured payload before depending on anything beyond `email` and
`event`, same "best-effort, confirm before relying on it in production"
caveat the old Systeme.io version carried).

Verification uses a shared-secret header compared with constant-time
equality (BREVO_WEBHOOK_SECRET). Swap _verify_secret for Brevo's native
signing if/when that's confirmed available on this account — the call
site (handle_webhook) is the only place that needs to change.

Route wiring (mounting this behind an actual HTTP endpoint) is out of
scope here, same as signup_handler/trial_handler — this exposes a
plain, testable dispatch function a route layer calls into.
"""

import hmac
import logging
import os
from typing import Any, Callable, Optional

from leads.capture.signup_handler import LEADS_TABLE, _get_supabase_client

log = logging.getLogger(__name__)

EventHandler = Callable[[dict, Optional[Any]], dict]
_EVENT_HANDLERS: dict[str, EventHandler] = {}


def register_event_handler(event_type: str) -> Callable[[EventHandler], EventHandler]:
    def decorator(handler: EventHandler) -> EventHandler:
        _EVENT_HANDLERS[event_type] = handler
        return handler

    return decorator


def verify_webhook_secret(provided_secret: Optional[str]) -> bool:
    expected = os.getenv("BREVO_WEBHOOK_SECRET")
    if not expected:
        # Not configured — accept, but this is a gap to close before go-live,
        # not a silent security decision: every call site logs it.
        log.warning("BREVO_WEBHOOK_SECRET not set — accepting webhook without verification")
        return True
    return hmac.compare_digest(provided_secret or "", expected)


def _update_lead_by_email(email: str, product_id: Optional[str], fields: dict, supabase_client: Optional[Any]) -> None:
    client = supabase_client if supabase_client is not None else _get_supabase_client()
    query = client.table(LEADS_TABLE).update(fields).eq("email", email)
    if product_id:
        query = query.eq("product_id", product_id)
    query.execute()


@register_event_handler("contact_updated")
def _handle_contact_updated(payload: dict, supabase_client: Optional[Any] = None) -> dict:
    contact = payload.get("data", {})
    email = contact.get("email")
    if not email:
        return {"status": "ignored", "reason": "missing email"}
    _update_lead_by_email(email, contact.get("product_id"), {"brevo_contact_id": contact.get("id")}, supabase_client)
    return {"status": "processed", "event_type": "contact_updated", "email": email}


@register_event_handler("unsubscribed")
def _handle_unsubscribed(payload: dict, supabase_client: Optional[Any] = None) -> dict:
    """Brevo's real, documented email-event webhook type — fires when a
    contact unsubscribes from a campaign/automation. Marks the lead
    churned so nothing downstream keeps treating them as active; the
    actual suppression (never emailing them again) is Brevo's own job
    once they're unsubscribed account-wide, this is just this platform's
    own record staying in sync."""
    contact = payload.get("data", {})
    email = contact.get("email")
    if not email:
        return {"status": "ignored", "reason": "missing email"}
    _update_lead_by_email(email, contact.get("product_id"), {"stage": "churned"}, supabase_client)
    return {"status": "processed", "event_type": "unsubscribed", "email": email}


def _handle_unrecognized_event(payload: dict, supabase_client: Optional[Any] = None) -> dict:
    event_type = payload.get("event") or payload.get("type")
    log.info("Unrecognized Brevo webhook event: %s", event_type)
    return {"status": "ignored", "event_type": event_type}


def handle_webhook(payload: dict, secret_header: Optional[str] = None, *, supabase_client: Optional[Any] = None) -> dict:
    if not verify_webhook_secret(secret_header):
        raise PermissionError("Invalid Brevo webhook secret")

    event_type = payload.get("event") or payload.get("type")
    handler = _EVENT_HANDLERS.get(event_type, _handle_unrecognized_event)
    return handler(payload, supabase_client)
