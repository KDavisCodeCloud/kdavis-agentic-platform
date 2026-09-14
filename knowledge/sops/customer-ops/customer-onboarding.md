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
- **Welcome email**: as of 2026-09-14 (later same day), `checkout.session.completed`
  fires a real welcome email (`core/email.py`, via Resend) to the
  workspace's `contact_email` pointing them at the Connections tab. It's
  best-effort — a send failure is logged, not retried. If a customer says
  they never got it, or if `RESEND_API_KEY` is ever unset on Railway,
  fall back to checking manually: `GET /internal/workspaces` and reach
  out if a workspace has been `active` for a day+ with no connections
  configured (`GET /workspace/credentials/status` per workspace).
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
- No proactive "workspace signed up but never connected anything" alert —
  you have to check `GET /internal/workspaces` yourself. (Welcome email
  itself is automated as of 2026-09-14 — see above.)
