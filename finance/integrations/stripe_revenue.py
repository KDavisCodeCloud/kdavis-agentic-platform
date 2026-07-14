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
stripe_revenue — pulls charge events from Stripe and maps them into
RevenueEvent records for the revenue_ledger.

Deliberately does not import payments/stripe_provider.py (that's the
live billing-side integration from an earlier session) — this module
talks to the Stripe SDK directly and only reads, never writes to Stripe.
The `stripe` package import is lazy so this module (and anything that
imports it) still loads in environments where the SDK isn't installed.
"""

import os
from datetime import date, datetime, timezone
from typing import Optional

from finance.accounting.revenue_ledger import RevenueEvent, RevenueLedger

# The real, working Stripe secret key in .env is named STRIPE_SECRET_KEY
# (same one api/routes/stripe_billing.py already uses for the commercial
# billing surface) — STRIPE_API_KEY was never a real variable anywhere in
# this repo, just this module's own invented name for it. Fixed rather than
# asking for a second key that would just duplicate the same credential.
STRIPE_API_KEY_ENV_VAR = "STRIPE_SECRET_KEY"


def _stripe_client():
    try:
        import stripe
    except ImportError as exc:
        raise RuntimeError(
            "The 'stripe' package is not installed. Add it to requirements.txt and pip install."
        ) from exc

    api_key = os.getenv(STRIPE_API_KEY_ENV_VAR)
    if not api_key:
        raise RuntimeError(f"{STRIPE_API_KEY_ENV_VAR} is not set in the environment.")

    stripe.api_key = api_key
    return stripe


def _charge_to_revenue_event(charge, product_id: Optional[str]) -> RevenueEvent:
    event_date = datetime.fromtimestamp(charge["created"], tz=timezone.utc).date()
    billing_details = charge.get("billing_details") or {}
    customer_email = billing_details.get("email") or charge.get("receipt_email")
    return RevenueEvent(
        source="stripe",
        amount=round(charge["amount"] / 100, 2),
        event_date=event_date,
        product_id=product_id,
        stripe_event_id=charge["id"],
        customer_email=customer_email,
        description=charge.get("description") or "",
    )


def fetch_charges_since(since: date, product_id: Optional[str] = None, limit: int = 100) -> list[RevenueEvent]:
    """Fetches all successful Stripe charges created on/after `since`."""
    stripe = _stripe_client()
    since_ts = int(datetime(since.year, since.month, since.day, tzinfo=timezone.utc).timestamp())

    events: list[RevenueEvent] = []
    charges = stripe.Charge.list(created={"gte": since_ts}, limit=limit)
    for charge in charges.auto_paging_iter():
        if not charge.get("paid") or charge.get("refunded"):
            continue
        events.append(_charge_to_revenue_event(charge, product_id))
    return events


def sync_to_ledger(ledger: RevenueLedger, since: date, product_id: Optional[str] = None) -> int:
    """Fetches Stripe charges since `since` and records any not already
    present in the ledger (RevenueLedger.record is idempotent on
    stripe_event_id). Returns the count of events fetched."""
    events = fetch_charges_since(since, product_id=product_id)
    for event in events:
        ledger.record(event)
    return len(events)
