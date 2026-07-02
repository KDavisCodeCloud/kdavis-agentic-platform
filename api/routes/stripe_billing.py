"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
Stripe billing routes.

POST /billing/checkout  — create a hosted Checkout Session for a tier
POST /billing/webhook   — receive Stripe events (signature verified; unsigned rejected)
POST /billing/portal    — create a hosted Customer Portal session for self-service
GET  /billing/status    — current tier and subscription status for the workspace

Design notes:
- We use Stripe-hosted Checkout and Customer Portal exclusively.
  There is no custom payment UI to maintain.
- The webhook is the authoritative source of truth for tier updates,
  not the success redirect. Frontend polls /billing/status after checkout.
- workspace.stripe_customer_id is set on first checkout.session.completed
  and is used for all subsequent portal and subscription event lookups.
- On cancellation/downgrade: workspace data is NEVER deleted. Only
  stripe_subscription_status and product_tier are updated.
"""

import logging
import os
from typing import Optional
from uuid import UUID

import stripe
import stripe.error
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.middleware.auth import get_workspace

log = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])


# ── Stripe configuration ──────────────────────────────────────────────────────

def _stripe_key() -> str:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe not configured — STRIPE_SECRET_KEY missing",
        )
    return key


def _webhook_secret() -> str:
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe webhook not configured — STRIPE_WEBHOOK_SECRET missing",
        )
    return secret


_FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")

_TIER_ENV_KEYS = {
    "starter":    "STRIPE_PRICE_ID_STARTER",
    "growth":     "STRIPE_PRICE_ID_GROWTH",
    "enterprise": "STRIPE_PRICE_ID_ENTERPRISE",
}

_VALID_TIERS = set(_TIER_ENV_KEYS.keys())


def _price_id_for_tier(tier: str) -> str:
    """Return Stripe Price ID for the given tier. Raises if not configured."""
    env_key = _TIER_ENV_KEYS.get(tier)
    if not env_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown tier '{tier}'. Valid tiers: {', '.join(_VALID_TIERS)}",
        )
    price_id = os.environ.get(env_key, "")
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Stripe price not configured for tier '{tier}' (set {env_key})",
        )
    return price_id


def _tier_for_price_id(price_id: str) -> Optional[str]:
    """Reverse-map a Stripe Price ID to a tier name. Returns None if unrecognized."""
    for tier, env_key in _TIER_ENV_KEYS.items():
        if os.environ.get(env_key) == price_id:
            return tier
    return None


# ── Request / response schemas ────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    tier: str  # "starter" | "growth" | "enterprise"


class CheckoutResponse(BaseModel):
    checkout_url: str
    tier: str


class PortalResponse(BaseModel):
    portal_url: str


class BillingStatusResponse(BaseModel):
    tier: str
    subscription_status: str
    has_billing_account: bool


# ── Database helpers ──────────────────────────────────────────────────────────

async def _update_workspace_billing(
    db_pool,
    workspace_id: str,
    *,
    stripe_customer_id: Optional[str] = None,
    tier: Optional[str] = None,
    subscription_status: Optional[str] = None,
) -> None:
    """
    Update billing-related fields on a workspace row.
    Only non-None kwargs are written so callers can update subsets of fields.
    """
    sets: list[str] = []
    params: list = []
    i = 1

    if stripe_customer_id is not None:
        sets.append(f"stripe_customer_id = ${i}")
        params.append(stripe_customer_id)
        i += 1
    if tier is not None and tier in _VALID_TIERS:
        sets.append(f"product_tier = ${i}")
        params.append(tier)
        i += 1
    if subscription_status is not None:
        sets.append(f"stripe_subscription_status = ${i}")
        params.append(subscription_status)
        i += 1

    if not sets:
        return

    sets.append("updated_at = NOW()")
    params.append(UUID(workspace_id))
    sql = f"UPDATE workspaces SET {', '.join(sets)} WHERE id = ${i}"

    async with db_pool.acquire() as conn:
        await conn.execute(sql, *params)

    log.info(
        "[Billing] Workspace %s updated — tier=%s status=%s",
        workspace_id[:8], tier, subscription_status,
    )


async def _workspace_id_for_customer(db_pool, stripe_customer_id: str) -> Optional[str]:
    """Return workspace.id (as string) for a given stripe_customer_id, or None."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM workspaces WHERE stripe_customer_id = $1",
            stripe_customer_id,
        )
    return str(row["id"]) if row else None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout_session(
    body: CheckoutRequest,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> CheckoutResponse:
    """
    Create a Stripe Checkout Session for the requested tier.

    Returns a checkout_url — redirect the user's browser there.
    The workspace tier is updated via the /billing/webhook endpoint
    when Stripe fires checkout.session.completed (asynchronous).

    Frontend should poll GET /billing/status after success redirect
    to confirm the tier has been applied.
    """
    tier = body.tier.lower()
    if tier not in _VALID_TIERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown tier '{tier}'. Valid: {', '.join(_VALID_TIERS)}",
        )

    stripe.api_key = _stripe_key()
    price_id = _price_id_for_tier(tier)
    workspace_id = str(workspace["id"])
    existing_customer = workspace.get("stripe_customer_id")

    params: dict = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        # client_reference_id links this session to our workspace on webhook
        "client_reference_id": workspace_id,
        "metadata": {
            "tier": tier,
            "workspace_id": workspace_id,
        },
        "subscription_data": {
            # Metadata on the subscription itself — survives session expiry
            "metadata": {"tier": tier, "workspace_id": workspace_id},
        },
        "success_url": (
            f"{_FRONTEND_URL}/dashboard"
            f"?checkout_success=1&tier={tier}&session_id={{CHECKOUT_SESSION_ID}}"
        ),
        "cancel_url": f"{_FRONTEND_URL}/#pricing",
        "allow_promotion_codes": True,
        "billing_address_collection": "required",
    }

    # If workspace already has a Stripe customer, attach to avoid duplicate accounts
    if existing_customer:
        params["customer"] = existing_customer
    else:
        params["customer_creation"] = "always"

    try:
        session = stripe.checkout.Session.create(**params)
    except stripe.error.StripeError as exc:
        log.error("[Billing] Stripe Checkout error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe error: {exc.user_message or str(exc)}",
        )

    log.info("[Billing] Checkout session created — workspace=%s tier=%s", workspace_id[:8], tier)
    return CheckoutResponse(checkout_url=session.url, tier=tier)


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request) -> dict:
    """
    Receive Stripe webhook events.

    Stripe-Signature header is verified using STRIPE_WEBHOOK_SECRET.
    Payloads without a valid signature are rejected with HTTP 400.

    Handles:
      checkout.session.completed      — activates workspace tier
      customer.subscription.updated   — reflects tier/status changes
      customer.subscription.deleted   — marks workspace as canceled (data preserved)
    """
    # Read raw bytes BEFORE any JSON parsing — required for signature verification
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    if not webhook_secret:
        log.error("[Billing] STRIPE_WEBHOOK_SECRET not set — webhook handler disabled")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook endpoint not configured",
        )

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except stripe.error.SignatureVerificationError:
        log.warning("[Billing] Invalid Stripe webhook signature — payload rejected")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature",
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed webhook payload",
        )

    db = request.app.state.db_pool
    event_type: str = event["type"]
    log.info("[Billing] Stripe event: %s  id=%s", event_type, event.get("id", "?"))

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(db, event["data"]["object"])

    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(db, event["data"]["object"])

    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(db, event["data"]["object"])

    else:
        log.debug("[Billing] Unhandled event type: %s", event_type)

    return {"received": True}


@router.post("/portal", response_model=PortalResponse)
async def create_customer_portal(
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> PortalResponse:
    """
    Create a Stripe Customer Portal session for self-service billing.

    The portal allows the customer to upgrade, downgrade, or cancel their
    subscription without any custom UI on our end. Returns a portal_url
    — open this in the user's browser (new tab or redirect).

    Requires that the workspace has completed Checkout at least once
    (stripe_customer_id must be set).
    """
    customer_id = workspace.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No billing account found for this workspace. "
                "Complete checkout first at /billing/checkout."
            ),
        )

    stripe.api_key = _stripe_key()

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{_FRONTEND_URL}/dashboard",
        )
    except stripe.error.StripeError as exc:
        log.error("[Billing] Stripe Portal error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe error: {exc.user_message or str(exc)}",
        )

    return PortalResponse(portal_url=session.url)


@router.get("/status", response_model=BillingStatusResponse)
async def billing_status(
    workspace: dict = Depends(get_workspace),
) -> BillingStatusResponse:
    """
    Return current billing tier and subscription status for the workspace.

    The frontend polls this after a Checkout success redirect to confirm
    the webhook has fired and the tier has been applied.
    """
    return BillingStatusResponse(
        tier=workspace.get("product_tier", "starter"),
        subscription_status=workspace.get("stripe_subscription_status", "trialing"),
        has_billing_account=bool(workspace.get("stripe_customer_id")),
    )


# ── Webhook event handlers ────────────────────────────────────────────────────

async def _handle_checkout_completed(db_pool, session: dict) -> None:
    """
    checkout.session.completed — customer successfully paid.
    Activates the workspace on the correct tier.
    """
    workspace_id = session.get("client_reference_id")
    customer_id  = session.get("customer")
    metadata     = session.get("metadata") or {}
    tier         = metadata.get("tier", "starter")

    if not workspace_id:
        log.error("[Billing] checkout.session.completed: missing client_reference_id — cannot update workspace")
        return

    if tier not in _VALID_TIERS:
        log.error("[Billing] checkout.session.completed: unrecognized tier '%s'", tier)
        tier = "starter"

    await _update_workspace_billing(
        db_pool,
        workspace_id,
        stripe_customer_id=customer_id,
        tier=tier,
        subscription_status="active",
    )


async def _handle_subscription_updated(db_pool, subscription: dict) -> None:
    """
    customer.subscription.updated — tier change, renewal, or status change.

    Maps the active price ID back to a tier name. If the price ID is
    unrecognized (e.g. a promotional one-off), we preserve the existing
    tier and only update the status.
    """
    customer_id = subscription.get("customer")
    new_status  = subscription.get("status", "active")

    workspace_id = await _workspace_id_for_customer(db_pool, customer_id)
    if not workspace_id:
        log.warning("[Billing] subscription.updated: no workspace for customer %s", customer_id)
        return

    # Derive tier from first subscription item's price ID
    tier: Optional[str] = None
    items_data = (subscription.get("items") or {}).get("data", [])
    if items_data:
        price_id = (items_data[0].get("price") or {}).get("id")
        if price_id:
            tier = _tier_for_price_id(price_id)
            if not tier:
                log.warning(
                    "[Billing] subscription.updated: unrecognized price_id '%s' for customer %s"
                    " — status updated, tier preserved",
                    price_id, customer_id,
                )

    await _update_workspace_billing(
        db_pool,
        workspace_id,
        tier=tier,  # None = no change; non-None = update
        subscription_status=new_status,
    )


async def _handle_subscription_deleted(db_pool, subscription: dict) -> None:
    """
    customer.subscription.deleted — subscription fully canceled.
    Marks workspace as canceled. All data is preserved — no deletes.
    """
    customer_id  = subscription.get("customer")
    workspace_id = await _workspace_id_for_customer(db_pool, customer_id)
    if not workspace_id:
        log.warning("[Billing] subscription.deleted: no workspace for customer %s", customer_id)
        return

    await _update_workspace_billing(
        db_pool,
        workspace_id,
        subscription_status="canceled",
    )
    log.info("[Billing] Workspace %s subscription canceled — all data preserved", workspace_id[:8])
