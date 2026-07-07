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
Stripe setup script — CLAUDE.md Phase 1, Step 13.

Owner runs this manually. It does not run in CI/CD and is not imported by
the running platform. Idempotent: safe to re-run — existing products,
prices, and the webhook endpoint are matched by metadata/URL and skipped
or updated rather than duplicated.

What it does:
  1. Reads the product catalog from config/products.yaml.
  2. For each product missing a Stripe product/price, creates them in
     Stripe and maps the resulting IDs back into products.yaml under
     that product's `stripe:` block.
  3. Creates (or updates) the webhook endpoint at STRIPE_WEBHOOK_URL for
     the events CLAUDE.md's Session 4 spec lists: checkout.session.completed,
     customer.subscription.updated, customer.subscription.deleted,
     invoice.payment_failed, charge.dispute.created.

Requires config/products.yaml to already exist. It does not exist in this
repo yet — running this script today will raise a descriptive error rather
than fail silently or fabricate product data. Expected shape:

    products:
      - id: cloud_decoded
        name: Cloud Decoded
        pricing:
          - tier: starter
            monthly_usd: 299
          - tier: growth
            monthly_usd: 699
        stripe:
          product_id: null      # filled in by this script
          price_ids: {}          # tier -> price_id, filled in by this script

Environment (read only from os.getenv — never hardcoded):
  STRIPE_SECRET_KEY   required
  STRIPE_WEBHOOK_URL   required, e.g. https://api.thdstack.com/api/stripe/webhook
"""

import logging
import os
import sys
from pathlib import Path

import stripe
import yaml

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTS_YAML_PATH = REPO_ROOT / "config" / "products.yaml"

WEBHOOK_EVENTS = [
    "checkout.session.completed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_failed",
    "charge.dispute.created",
]


class StripeSetupError(RuntimeError):
    """Raised for any condition that stops this script from proceeding."""


def _require_env(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise StripeSetupError(
            f"{name} is not set. Read from the environment only — "
            f"export {name} before running this script."
        )
    return value


def load_product_catalog() -> dict:
    if not PRODUCTS_YAML_PATH.exists():
        raise StripeSetupError(
            f"{PRODUCTS_YAML_PATH} does not exist yet. This script maps Stripe "
            "products/prices onto the platform product registry defined there "
            "(see CLAUDE.md folder structure, config/products.yaml). Create it "
            "with at least one product entry — see this file's module "
            "docstring for the expected shape — then re-run."
        )
    with open(PRODUCTS_YAML_PATH, "r") as f:
        catalog = yaml.safe_load(f) or {}
    if "products" not in catalog or not catalog["products"]:
        raise StripeSetupError(
            f"{PRODUCTS_YAML_PATH} has no `products` entries. Add at least one "
            "product before running Stripe setup."
        )
    return catalog


def save_product_catalog(catalog: dict) -> None:
    with open(PRODUCTS_YAML_PATH, "w") as f:
        yaml.safe_dump(catalog, f, sort_keys=False, default_flow_style=False)
    log.info("Wrote updated Stripe mappings to %s", PRODUCTS_YAML_PATH)


def find_existing_stripe_product(product_id: str):
    """Look up a Stripe product previously created for this platform product_id."""
    results = stripe.Product.search(query=f"metadata['platform_product_id']:'{product_id}'")
    return results.data[0] if results.data else None


def ensure_stripe_product(product: dict) -> dict:
    """Create the Stripe product + one price per pricing tier, if missing."""
    product_id = product["id"]
    stripe_block = product.setdefault("stripe", {"product_id": None, "price_ids": {}})

    stripe_product = None
    if stripe_block.get("product_id"):
        try:
            stripe_product = stripe.Product.retrieve(stripe_block["product_id"])
        except stripe.error.InvalidRequestError:
            log.warning(
                "products.yaml references missing Stripe product %s for %s — recreating",
                stripe_block["product_id"], product_id,
            )

    if stripe_product is None:
        stripe_product = find_existing_stripe_product(product_id)

    if stripe_product is None:
        stripe_product = stripe.Product.create(
            name=product["name"],
            metadata={"platform_product_id": product_id},
        )
        log.info("Created Stripe product %s for %s", stripe_product.id, product_id)
    else:
        log.info("Reusing existing Stripe product %s for %s", stripe_product.id, product_id)

    stripe_block["product_id"] = stripe_product.id

    price_ids = stripe_block.setdefault("price_ids", {})
    for tier in product.get("pricing", []):
        tier_name = tier["tier"]
        if tier_name in price_ids and price_ids[tier_name]:
            log.info("Price for %s/%s already mapped (%s) — skipping", product_id, tier_name, price_ids[tier_name])
            continue
        price = stripe.Price.create(
            product=stripe_product.id,
            unit_amount=int(tier["monthly_usd"]) * 100,
            currency="usd",
            recurring={"interval": "month"},
            metadata={"platform_product_id": product_id, "tier": tier_name},
        )
        price_ids[tier_name] = price.id
        log.info("Created price %s for %s/%s ($%s/mo)", price.id, product_id, tier_name, tier["monthly_usd"])

    return product


def ensure_webhook_endpoint(webhook_url: str) -> None:
    existing = stripe.WebhookEndpoint.list(limit=100)
    match = next((ep for ep in existing.data if ep.url == webhook_url), None)

    if match is None:
        endpoint = stripe.WebhookEndpoint.create(
            url=webhook_url,
            enabled_events=WEBHOOK_EVENTS,
        )
        log.info("Created webhook endpoint %s -> %s", endpoint.id, webhook_url)
        log.info(
            "Signing secret: %s — set this as STRIPE_WEBHOOK_SECRET, it is only shown once.",
            endpoint.secret,
        )
        return

    missing_events = set(WEBHOOK_EVENTS) - set(match.enabled_events)
    if missing_events:
        updated = stripe.WebhookEndpoint.modify(
            match.id,
            enabled_events=sorted(set(match.enabled_events) | set(WEBHOOK_EVENTS)),
        )
        log.info("Updated webhook endpoint %s — added events: %s", updated.id, sorted(missing_events))
    else:
        log.info("Webhook endpoint %s already covers all required events", match.id)


def main() -> None:
    stripe.api_key = _require_env("STRIPE_SECRET_KEY")
    webhook_url = _require_env("STRIPE_WEBHOOK_URL")

    catalog = load_product_catalog()
    for product in catalog["products"]:
        ensure_stripe_product(product)
    save_product_catalog(catalog)

    ensure_webhook_endpoint(webhook_url)

    log.info("Stripe setup complete for %d product(s).", len(catalog["products"]))


if __name__ == "__main__":
    try:
        main()
    except StripeSetupError as exc:
        log.error(str(exc))
        sys.exit(1)
