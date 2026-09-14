# SOP: Customer Onboarding (Cloud Decoded)
Date created: 2026-09-14
Product: Cloud Decoded
Status: Live

## When this applies
A new customer signs up at `/signup`, pays via Stripe Checkout, and needs
to end up with a working connected workspace. As of 2026-09-14 this is
mostly automatic — this SOP is what to check/do, not a manual setup process.

## What happens automatically
1. `/signup` collects company name + contact email, writes a `pending_payment`
   workspace, and requires the ToS/Privacy checkbox (`tos_accepted_at` is
   recorded — migration 028).
2. `/checkout` starts a Stripe Checkout session for Starter or Growth
   (Enterprise is sales-assisted, see below).
3. Stripe's webhook (`_handle_checkout_completed`,
   `api/routes/stripe_billing.py`) flips `stripe_subscription_status` to
   `active` and sets `product_tier`.
4. The customer lands back on `/dashboard?tab=connections&welcome=1` —
   directly on the Connections tab with a one-time welcome banner, not a
   bare dashboard.
5. They connect GitHub (App install), a cloud account (AWS role / Azure SP),
   and an LLM key themselves from that tab. Nothing on Cloud Decoded's side
   is required for a Starter/Growth signup to become fully connected.

## What to check as the operator
- **No welcome/confirmation email is sent yet** (as of 2026-09-14 — no
  email-sending infrastructure exists in the codebase). If a customer says
  they don't know what to do next, that's why — there's nothing wrong on
  their end. Until email sending is built, proactively check
  `GET /internal/workspaces` after a signup you notice in Stripe and reach
  out manually if a workspace has been `active` for a day+ with no
  connections configured (`GET /workspace/credentials/status` per workspace,
  or just ask).
- **Enterprise signups**: there is no self-serve Enterprise checkout tier
  — `/checkout` only offers Starter/Growth. An Enterprise deal is closed
  manually (sales conversation), then:
  1. Set the tier: `PATCH /internal/workspaces/{id}/tier` with
     `{"tier": "enterprise"}`.
  2. See `enterprise-mcp-invite.md` for provisioning their MCP OAuth access.
- **Legacy PAT nudge**: if a workspace shows `github_via_legacy_pat: true`
  in `GET /workspace/credentials/status`, the dashboard already shows them
  an amber nudge to migrate to the GitHub App — no action needed from you
  unless they ask for help.

## What's still manual (known gaps, tracked in GAPS.md / DECISIONS.md)
- No welcome email automation.
- No proactive "workspace signed up but never connected anything" alert —
  you have to check `GET /internal/workspaces` yourself.
