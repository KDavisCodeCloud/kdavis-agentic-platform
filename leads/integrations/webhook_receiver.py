"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

"""
webhook_receiver — receives Systeme.io webhooks back into the platform
(tag changes, sequence conversions, contact updates) and reconciles
them onto the matching `leads` row.

Verification uses a shared-secret header compared with constant-time
equality (SYSTEME_WEBHOOK_SECRET). Swap _verify_secret for Systeme.io's
native HMAC signing if/when that's confirmed available on this account
— the call site (handle_webhook) is the only place that needs to change.

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
    expected = os.getenv("SYSTEME_WEBHOOK_SECRET")
    if not expected:
        # Not configured — accept, but this is a gap to close before go-live,
        # not a silent security decision: every call site logs it.
        log.warning("SYSTEME_WEBHOOK_SECRET not set — accepting webhook without verification")
        return True
    return hmac.compare_digest(provided_secret or "", expected)


def _update_lead_by_email(email: str, product_id: Optional[str], fields: dict, supabase_client: Optional[Any]) -> None:
    client = supabase_client if supabase_client is not None else _get_supabase_client()
    query = client.table(LEADS_TABLE).update(fields).eq("email", email)
    if product_id:
        query = query.eq("product_id", product_id)
    query.execute()


@register_event_handler("contact.created")
def _handle_contact_created(payload: dict, supabase_client: Optional[Any] = None) -> dict:
    contact = payload.get("data", {})
    email = contact.get("email")
    if not email:
        return {"status": "ignored", "reason": "missing email"}
    _update_lead_by_email(email, contact.get("product_id"), {"systeme_contact_id": contact.get("id")}, supabase_client)
    return {"status": "processed", "event_type": "contact.created", "email": email}


@register_event_handler("contact.tag_added")
def _handle_tag_added(payload: dict, supabase_client: Optional[Any] = None) -> dict:
    contact = payload.get("data", {})
    email = contact.get("email")
    if not email:
        return {"status": "ignored", "reason": "missing email"}
    log.info("Systeme.io tag added for %s: %s", email, contact.get("tag"))
    return {"status": "processed", "event_type": "contact.tag_added", "email": email}


@register_event_handler("campaign.subscriber.converted")
def _handle_sequence_conversion(payload: dict, supabase_client: Optional[Any] = None) -> dict:
    contact = payload.get("data", {})
    email = contact.get("email")
    if not email:
        return {"status": "ignored", "reason": "missing email"}
    _update_lead_by_email(email, contact.get("product_id"), {"signup_type": "trial"}, supabase_client)
    return {"status": "processed", "event_type": "campaign.subscriber.converted", "email": email}


def _handle_unrecognized_event(payload: dict, supabase_client: Optional[Any] = None) -> dict:
    event_type = payload.get("event") or payload.get("type")
    log.info("Unrecognized Systeme.io webhook event: %s", event_type)
    return {"status": "ignored", "event_type": event_type}


def handle_webhook(payload: dict, secret_header: Optional[str] = None, *, supabase_client: Optional[Any] = None) -> dict:
    if not verify_webhook_secret(secret_header):
        raise PermissionError("Invalid Systeme.io webhook secret")

    event_type = payload.get("event") or payload.get("type")
    handler = _EVENT_HANDLERS.get(event_type, _handle_unrecognized_event)
    return handler(payload, supabase_client)
