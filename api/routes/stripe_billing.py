"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

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
- checkout.session.completed also fires a best-effort welcome email
  (core/email.py) to the workspace's contact_email -- a send failure is
  logged and never allowed to fail the webhook itself.
"""

import logging
import os
from typing import Optional
from uuid import UUID

import stripe
import stripe.error
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.middleware.auth import get_workspace, get_workspace_allow_pending_payment, get_workspace_any_status
from core.compliance import WorkspaceComplianceGuard
from core.email import EmailError, downgrade_deactivation_html, payment_failed_dunning_html, send_email, welcome_email_html
from core.email_enrollment import enroll_by_email, exit_all_by_email, exit_by_email, get_subscriber_id_by_email
from core.member_deactivation import deactivate_member_row

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
    downgrade_blocked_reason: Optional[str] = None,
    clear_downgrade_block: bool = False,
) -> None:
    """
    Update billing-related fields on a workspace row.
    Only non-None kwargs are written so callers can update subsets of fields.

    downgrade_blocked_reason/clear_downgrade_block: 24-gap-closure Phase 7.
    Separate from the tier/status "only if not None" convention above
    since clearing a TEXT column to NULL needs its own explicit signal
    (clear_downgrade_block=True), not just "was None passed."
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
    if downgrade_blocked_reason is not None:
        sets.append(f"downgrade_blocked_reason = ${i}")
        params.append(downgrade_blocked_reason)
        i += 1
    elif clear_downgrade_block:
        sets.append("downgrade_blocked_reason = NULL")

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
    workspace: dict = Depends(get_workspace_allow_pending_payment),
) -> CheckoutResponse:
    """
    Create a Stripe Checkout Session for the requested tier.

    Returns a checkout_url — redirect the user's browser there.
    The workspace tier is updated via the /billing/webhook endpoint
    when Stripe fires checkout.session.completed (asynchronous).

    Frontend should poll GET /billing/status after success redirect
    to confirm the tier has been applied.

    Uses get_workspace_allow_pending_payment, not get_workspace: every
    brand-new signup is 'pending_payment' until this exact call succeeds
    and its checkout completes -- get_workspace's normal block would make
    this endpoint permanently unreachable for the one case it exists for.
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

    # If workspace already has a Stripe customer, attach to avoid duplicate
    # accounts. In "subscription" mode Stripe always creates a customer
    # automatically when none is given -- customer_creation is a "payment"
    # mode-only param and Stripe rejects the request outright if it's set
    # here (confirmed live 2026-09-11: "customer_creation can only be used
    # in payment mode" -- this had never actually been exercised against
    # real Stripe before that).
    if existing_customer:
        params["customer"] = existing_customer

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
      customer.subscription.updated   — reflects tier/status changes;
                                         blocks a downgrade that would
                                         drop below the new tier's seat
                                         cap (Phase 7); maps Stripe's
                                         'unpaid' to this platform's own
                                         'suspended' terminal state
      customer.subscription.deleted   — marks workspace as canceled (data preserved)
      invoice.payment_failed          — marks 'past_due' + sends a
                                         dunning email (Phase 7). Stripe
                                         runs its own retry schedule
                                         (Smart Retries, configured in
                                         the Stripe Dashboard) -- this
                                         handler does not duplicate that,
                                         only reflects status and notifies.
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

    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(db, event["data"]["object"])

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
    workspace: dict = Depends(get_workspace_any_status),
) -> BillingStatusResponse:
    """
    Return current billing tier and subscription status for the workspace.

    Deliberately does not 402 on a blocked subscription status -- a
    workspace needs to be able to see *why* it's locked (pending_payment,
    canceled, suspended) in order to fix it. The frontend polls this after
    a Checkout success redirect to confirm the webhook has fired, and the
    /billing page reads it to render the current plan/status regardless
    of lock state.
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

    await _send_welcome_email(db_pool, workspace_id)
    await _enroll_onboarding_email_sequence(db_pool, workspace_id)


async def _enroll_onboarding_email_sequence(db_pool, workspace_id: str) -> None:
    """
    Email lifecycle system (migration 051): a completed checkout is the
    'onboarding' sequence's enrollment trigger, and exits 'abandoned_checkout'
    (the workspace didn't abandon it after all) and 'trust_drip' (the
    prompt's own build spec calls this exit target 'nurture', but Cloud
    Decoded's real sequence list has no sequence by that name --
    'trust_drip' is the actual pre-sale trust-building sequence a
    converting prospect should stop receiving; 'newsletter' is left
    running since a paying customer can still want the content
    relationship). Also stamps first/last-touch attribution
    if this contact_email was a subscriber who clicked a marketing email in
    the prior 90 days -- Phase 7. Best-effort: never allowed to fail the
    webhook, same discipline as the welcome email above.
    """
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT contact_email FROM workspaces WHERE id = $1", UUID(workspace_id),
            )
            if not row or not row["contact_email"]:
                return
            email = row["contact_email"]

            await enroll_by_email(conn, email, "onboarding", source="checkout", workspace_id=workspace_id)
            await exit_by_email(conn, email, "abandoned_checkout", "converted")
            await exit_by_email(conn, email, "trust_drip", "converted")

            subscriber_id = await get_subscriber_id_by_email(conn, email)
            if subscriber_id:
                touch = await conn.fetchrow(
                    """
                    SELECT s.template_key FROM cd_email_clicks c
                    JOIN cd_email_sends s ON s.id = c.send_id
                    WHERE s.recipient = $1 AND c.clicked_at >= NOW() - INTERVAL '90 days'
                    ORDER BY c.clicked_at ASC
                    """,
                    email,
                )
                if touch:
                    last_touch = await conn.fetchrow(
                        """
                        SELECT s.template_key FROM cd_email_clicks c
                        JOIN cd_email_sends s ON s.id = c.send_id
                        WHERE s.recipient = $1 AND c.clicked_at >= NOW() - INTERVAL '90 days'
                        ORDER BY c.clicked_at DESC
                        """,
                        email,
                    )
                    await conn.execute(
                        "UPDATE workspaces SET first_touch_template = $2, last_touch_template = $3 WHERE id = $1",
                        UUID(workspace_id), touch["template_key"], last_touch["template_key"],
                    )
    except Exception:
        log.warning("[Billing] Email lifecycle enrollment failed for workspace=%s", workspace_id, exc_info=True)


async def _send_welcome_email(db_pool, workspace_id: str) -> None:
    """Best-effort welcome email now that the workspace is active. Never
    allowed to fail the webhook -- a broken email provider must not turn
    into a Stripe webhook retry storm or a customer stuck mid-checkout."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT company_name, contact_email FROM workspaces WHERE id = $1",
            UUID(workspace_id),
        )
    if not row or not row["contact_email"]:
        return

    try:
        await send_email(
            to=row["contact_email"],
            subject="Welcome to Cloud Decoded",
            html=welcome_email_html(row["company_name"]),
        )
    except EmailError as exc:
        log.warning("[Billing] Welcome email failed for workspace=%s: %s", workspace_id, exc)


_TIER_RANK = {"starter": 0, "growth": 1, "enterprise": 2}


async def _handle_subscription_updated(db_pool, subscription: dict) -> None:
    """
    customer.subscription.updated — tier change, renewal, or status change.

    Maps the active price ID back to a tier name. If the price ID is
    unrecognized (e.g. a promotional one-off), we preserve the existing
    tier and only update the status.

    24-gap-closure Phase 7:
    - Stripe's own 'unpaid' status (its retry schedule exhausted without
      a successful charge, subscription not canceled) maps to this
      platform's own 'suspended' terminal state -- the actual cutoff at
      the end of the "payment failure -> past_due -> suspended" chain.

    Kelvin's item 3 (2026-09-17), replacing Phase 7's hard downgrade
    block: a downgrade (new tier's rank below the current one) is now
    ALWAYS applied. If it drops the workspace below the new tier's seat
    cap, the most-recently-added active/invited members over the cap are
    deactivated automatically (core/member_deactivation.py -- the exact
    same mechanism Phase 4's admin-triggered deactivation uses: assigned
    incidents return to unassigned, one audit row per member), and the
    workspace's contact_email gets one email listing who was deactivated
    and the two ways to get them back. We still never touch the Stripe
    subscription itself from our side either direction -- Stripe's own
    record and ours now simply agree on the tier, which they didn't
    while the block existed.
    """
    customer_id   = subscription.get("customer")
    stripe_status = subscription.get("status", "active")
    new_status    = "suspended" if stripe_status == "unpaid" else stripe_status

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

    deactivated: list[dict] = []

    if tier is not None:
        async with db_pool.acquire() as conn:
            current_row = await conn.fetchrow(
                "SELECT product_tier FROM workspaces WHERE id = $1", UUID(workspace_id),
            )
            current_tier = (current_row["product_tier"] if current_row else None) or "starter"

            if _TIER_RANK.get(tier, 0) < _TIER_RANK.get(current_tier, 0):
                new_max_seats = WorkspaceComplianceGuard.TIER_LIMITS.get(
                    tier, WorkspaceComplianceGuard.TIER_LIMITS["starter"]
                )["max_seats"]
                if new_max_seats != -1:
                    # Newest first -- the members to deactivate are the
                    # most-recently-added ones over the cap, so they're a
                    # simple prefix slice of this order, not an OFFSET
                    # (OFFSET new_max_seats would skip the newest rows and
                    # keep them, deactivating the OLDEST members instead --
                    # backwards from what this is supposed to do).
                    all_rows = await conn.fetch(
                        "SELECT id, email FROM workspace_members "
                        "WHERE workspace_id = $1 AND status IN ('invited', 'active') "
                        "ORDER BY created_at DESC",
                        UUID(workspace_id),
                    )
                    over_count = len(all_rows) - new_max_seats
                    over_cap_rows = all_rows[:over_count] if over_count > 0 else []
                    for member_row in over_cap_rows:
                        await deactivate_member_row(
                            conn, workspace_id, member_row["id"], member_row["email"],
                            action="member_deactivated_downgrade",
                        )
                        deactivated.append({"id": str(member_row["id"]), "email": member_row["email"]})

    await _update_workspace_billing(
        db_pool,
        workspace_id,
        tier=tier,  # None = no change; non-None = update
        subscription_status=new_status,
        clear_downgrade_block=True,  # this system no longer ever blocks a downgrade
    )

    if deactivated:
        emails = [m["email"] for m in deactivated]
        log.warning(
            "[Billing] Workspace %s downgraded to '%s' -- deactivated %d member(s) over the new seat cap: %s",
            workspace_id, tier, len(deactivated), emails,
        )
        async with db_pool.acquire() as conn:
            contact_row = await conn.fetchrow(
                "SELECT company_name, contact_email FROM workspaces WHERE id = $1", UUID(workspace_id),
            )
        if contact_row and contact_row["contact_email"]:
            try:
                await send_email(
                    contact_row["contact_email"],
                    f"Cloud Decoded — plan changed to {tier}, some members were removed",
                    downgrade_deactivation_html(contact_row["company_name"], tier, emails),
                )
            except EmailError as exc:
                log.warning("[Billing] Downgrade-deactivation email failed for workspace=%s: %s", workspace_id, exc)
        else:
            log.warning("[Billing] Workspace %s has no contact_email -- downgrade-deactivation email not sent", workspace_id)


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

    try:
        async with db_pool.acquire() as conn:
            contact_row = await conn.fetchrow(
                "SELECT contact_email FROM workspaces WHERE id = $1", UUID(workspace_id),
            )
            if contact_row and contact_row["contact_email"]:
                email = contact_row["contact_email"]
                await enroll_by_email(conn, email, "winback", source="checkout", workspace_id=workspace_id)
                # "A canceled workspace exits everything except winback."
                await exit_all_by_email(conn, email, "workspace_canceled", except_sequences=("winback",))
    except Exception:
        log.warning("[Billing] Winback enrollment failed for workspace=%s", workspace_id, exc_info=True)


async def _handle_payment_failed(db_pool, invoice: dict) -> None:
    """
    invoice.payment_failed — 24-gap-closure Phase 7. First real signal
    that a charge failed, generally arriving before (or without ever
    being followed by) a customer.subscription.updated status change --
    Stripe's Smart Retries can keep a subscription 'active' through
    several failed attempts before it ever flips to 'past_due'. Marks
    'past_due' immediately here rather than waiting on that, and sends
    one dunning email per failed invoice (Stripe already dedups its own
    retry cadence -- this fires once per actual failed charge attempt,
    not on a separate schedule of its own).
    """
    customer_id  = invoice.get("customer")
    workspace_id = await _workspace_id_for_customer(db_pool, customer_id)
    if not workspace_id:
        log.warning("[Billing] payment_failed: no workspace for customer %s", customer_id)
        return

    await _update_workspace_billing(db_pool, workspace_id, subscription_status="past_due")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT company_name, contact_email FROM workspaces WHERE id = $1", UUID(workspace_id),
        )
    if row and row["contact_email"]:
        try:
            await send_email(
                row["contact_email"],
                "Cloud Decoded — your payment failed",
                payment_failed_dunning_html(row["company_name"]),
            )
        except EmailError as exc:
            log.warning("[Billing] Dunning email failed for workspace=%s: %s", workspace_id, exc)

        try:
            async with db_pool.acquire() as conn:
                await enroll_by_email(conn, row["contact_email"], "dunning", source="checkout", workspace_id=workspace_id)
        except Exception:
            log.warning("[Billing] Dunning sequence enrollment failed for workspace=%s", workspace_id, exc_info=True)
    else:
        log.warning("[Billing] Workspace %s has no contact_email -- dunning email not sent", workspace_id)

    log.info("[Billing] Workspace %s marked past_due after failed payment", workspace_id[:8])
