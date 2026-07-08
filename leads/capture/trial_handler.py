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
trial_handler — processes /trial/[product] starts. Builds on
signup_handler.process_signup() (signup_type="trial") for the shared
lead-writing/CRM-sync logic, then creates the Stripe customer and
14-day trial subscription and writes stripe_customer_id back onto the
lead row.

Unlike the visitor_capture webhook / Systeme.io sync in signup_handler
(best-effort, never blocks signup), a Stripe failure here IS fatal —
a trial that silently didn't get a subscription is a real defect the
caller must see, so this raises rather than swallowing the error.

stripe_price_id is required and must be passed explicitly by the
caller (e.g. resolved from config/products.yaml's product->price
mapping) — this module does not guess or hardcode a price ID.
"""

import logging
import os
from typing import Any, Optional

from leads.capture.signup_handler import (
    LEADS_TABLE,
    SignupPayload,
    _get_supabase_client,
    process_signup,
    validate_signup_payload,
)
from leads.integrations.systeme_io import SystemeIOClient

log = logging.getLogger(__name__)

DEFAULT_TRIAL_DAYS = 14


def _get_stripe_module() -> Any:
    import stripe

    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    return stripe


def _create_stripe_trial(payload: SignupPayload, stripe_price_id: str, trial_days: int, stripe_module: Optional[Any]) -> dict:
    stripe = stripe_module if stripe_module is not None else _get_stripe_module()

    customer = stripe.Customer.create(
        email=payload.email,
        name=payload.first_name,
        metadata={"product_id": payload.product_id},
    )
    customer_id = customer["id"] if isinstance(customer, dict) else customer.id

    subscription = stripe.Subscription.create(
        customer=customer_id,
        items=[{"price": stripe_price_id}],
        trial_period_days=trial_days,
        metadata={"product_id": payload.product_id},
    )
    subscription_id = subscription["id"] if isinstance(subscription, dict) else subscription.id

    return {"stripe_customer_id": customer_id, "stripe_subscription_id": subscription_id}


def _attach_stripe_customer(lead: dict, product_id: str, stripe_customer_id: str, supabase_client: Optional[Any]) -> None:
    client = supabase_client if supabase_client is not None else _get_supabase_client()
    client.table(LEADS_TABLE).update({"stripe_customer_id": stripe_customer_id}).eq("email", lead["email"]).eq("product_id", product_id).execute()


def process_trial_start(
    data: dict,
    *,
    stripe_price_id: str,
    trial_days: int = DEFAULT_TRIAL_DAYS,
    supabase_client: Optional[Any] = None,
    systeme_client: Optional[SystemeIOClient] = None,
    visitor_capture_webhook_url: Optional[str] = None,
    http_client: Optional[Any] = None,
    stripe_module: Optional[Any] = None,
) -> dict:
    if not stripe_price_id:
        raise ValueError("stripe_price_id is required to start a trial")

    trial_data = dict(data)
    trial_data["signup_type"] = "trial"
    payload = validate_signup_payload(trial_data)

    signup_result = process_signup(
        trial_data,
        supabase_client=supabase_client,
        systeme_client=systeme_client,
        visitor_capture_webhook_url=visitor_capture_webhook_url,
        http_client=http_client,
    )

    stripe_result = _create_stripe_trial(payload, stripe_price_id, trial_days, stripe_module)
    _attach_stripe_customer(signup_result["lead"], payload.product_id, stripe_result["stripe_customer_id"], supabase_client)

    lead = dict(signup_result["lead"])
    lead["stripe_customer_id"] = stripe_result["stripe_customer_id"]

    return {
        "lead": lead,
        "stripe_customer_id": stripe_result["stripe_customer_id"],
        "stripe_subscription_id": stripe_result["stripe_subscription_id"],
        "trial_days": trial_days,
        "warnings": signup_result["warnings"],
    }
