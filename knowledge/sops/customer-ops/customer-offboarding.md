# SOP: Customer Offboarding (Cloud Decoded)
Date created: 2026-09-14
Product: Cloud Decoded
Status: Live

## When this applies
A customer cancels their subscription (self-serve, via Stripe's Customer
Portal) or you suspend a workspace for a ToS violation.

## Self-serve cancellation (customer-initiated)
1. Customer opens `POST /billing/portal` from their dashboard (Stripe's
   hosted Customer Portal) and cancels.
2. Stripe fires `customer.subscription.deleted` →
   `_handle_subscription_deleted` (`api/routes/stripe_billing.py`) sets
   `stripe_subscription_status = 'canceled'`.
3. **Nothing is deleted.** This is intentional — see
   `docs/customer/security-questionnaire-response.md` and the Security
   page. Credentials, audit log, incident history all remain intact so a
   subsequent data-deletion request (see below) can be honored
   unambiguously, and so a customer who resubscribes doesn't lose their
   setup.
4. `_BLOCKED_SUBSCRIPTION_STATUSES` (`api/middleware/auth.py`) blocks API
   access immediately once `stripe_subscription_status` is `canceled`.

## Suspension (operator-initiated, ToS violation)
`POST /internal/workspaces/{id}/suspend` — independent of Stripe (Stripe
has no concept of a ToS violation). Reverse with
`POST /internal/workspaces/{id}/reactivate`.

## If the customer explicitly requests data deletion
Do NOT purge a workspace's data just because it's cancelled — a cancelled
workspace is expected to keep its data until deletion is explicitly
requested (see the Privacy Policy, `/privacy`).

1. Confirm the workspace is `canceled` or `suspended` — the purge route
   refuses to run against a live subscription (`409`).
2. Call `POST /internal/workspaces/{id}/purge-data` with
   `{"confirm_company_name": "<exact company_name>"}`. This is
   destructive and irreversible — it nulls every credential column
   (GitHub App installation, AWS role ARN, Azure SP secret, Azure DevOps
   PAT, K8s token/cert, LLM key) and PII (`contact_email`) and stamps
   `data_purged_at`.
3. What's **kept**: the workspace row itself and its `audit_log`/incident
   history, for billing and audit-trail integrity — this matches what the
   Privacy Policy tells customers to expect ("Billing and audit records
   may be retained after deletion where required for legal, accounting,
   or security-audit purposes").
4. Reply to the customer confirming what was deleted and what was
   retained and why (point them to `/privacy` § Data Retention and
   Deletion if they ask).

## What's still manual
- No self-serve "delete my data" button in the dashboard yet — a request
  has to come to you (email/support) and you run `purge-data` yourself.
- No automated confirmation email after a purge — confirm manually.
