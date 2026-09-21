# SOP: Email Suppression and Deliverability Incident Response (Cloud Decoded)
Date created: 2026-09-21
Product: Cloud Decoded
Status: Live (webhook signature verification unverified against a real
Resend delivery — see GAPS.md #31)

## When this applies
Someone unsubscribes, an email bounces, a recipient marks a message as
spam, or Resend/Google Postmaster/a customer flags a deliverability
problem (rising bounce rate, domain reputation warning, landing in spam).

## How suppression actually works
`cd_email_suppressions` (migration 051) is the single source of truth.
Every marketing send (`core/marketing_email.py`'s `send_marketing_email`)
checks it fresh, every time — never cached. A suppressed address:
- Never receives another marketing-stream send (transactional email —
  welcome, dunning's *transactional* half, downgrade notices — is
  unaffected; only the marketing stream checks this table).
- Has every active `cd_email_enrollments` row exited automatically the
  moment the suppression is written (`core/email_enrollment.py`'s
  `exit_all_by_email`), not just blocked at send time.

Three ways a row gets written:
1. **Self-service unsubscribe** — `GET /email/unsubscribe?token=` shows a
   confirmation page (never mutates state on its own — some mail clients
   prefetch/scan every link in an email, so a bare `GET` must never be
   the thing that unsubscribes someone). The page's own confirm button,
   or a mail client's RFC 8058 one-click action, `POST`s to the same URL,
   which writes `reason='unsubscribe'`.
2. **Resend bounce/complaint webhook** — `POST /email/resend-webhook`
   (`api/routes/email_public.py`), signature-verified via
   `core/resend_webhook.py`. `email.bounced` → `reason='bounce'`,
   `email.complained` → `reason='complaint'`.
3. **Manual** — direct insert with `reason='manual'` for a support-driven
   suppression (e.g. someone emails support asking to be removed instead
   of using the link).

## If Resend webhooks stop suppressing bounces/complaints
1. Confirm the webhook is actually configured in the Resend dashboard,
   pointed at `{API_BASE_URL}/api/v1/email/resend-webhook`, and
   `RESEND_WEBHOOK_SECRET` is set on Railway and matches the webhook's
   signing secret shown in Resend.
2. Check Railway logs for `[EmailPublic] Resend webhook rejected: ...` —
   every `400` from a bad signature logs the specific
   `WebhookVerificationError` message. If Resend's actual header names or
   signed-content format ever changed, this is where it surfaces (see
   GAPS.md #31 — this verification was never exercised against a live
   Resend delivery, only tested against itself).
3. If webhooks are broken, bounces/complaints stop suppressing
   automatically — check Resend's own dashboard for bounce/complaint
   activity directly and suppress manually (`reason='manual'`) as a
   stopgap while the webhook is fixed.

## Reputation-risk checklist (if a real deliverability problem is reported)
1. Pull current suppression counts by reason:
   `SELECT reason, COUNT(*) FROM cd_email_suppressions GROUP BY reason;`
2. Pull recent bounce/failure rate:
   `SELECT status, COUNT(*) FROM cd_email_sends WHERE stream='marketing' AND sent_at >= NOW() - INTERVAL '7 days' GROUP BY status;`
3. If bounce rate looks elevated, deactivate the sequence(s) responsible
   (`POST /internal/email/sequences/{key}/deactivate`) before it does
   more damage to sender reputation, then investigate the specific
   recipients bouncing (stale list segment? a specific domain rejecting?).
4. Check Google Postmaster Tools (once Kelvin has registered the sending
   domains — see GAPS.md/Kelvin-only actions) for domain reputation,
   spam rate, and authentication (SPF/DKIM/DMARC) status directly.
5. The compliance footer (`core/marketing_email.py`'s
   `compliance_footer_html`/`_text`) and RFC 8058
   `List-Unsubscribe`/`List-Unsubscribe-Post` headers are on every
   marketing send unconditionally — if a complaint report claims these
   are missing, that's a bug, not a config issue; check
   `core/marketing_email.py`'s `_unsubscribe_headers` directly.

## Daily send cap
One marketing email per recipient per platform-wide day
(`core/marketing_email.py`'s `daily_cap_reached`, checked against
`cd_email_sends` — transactional sends are exempt). If a recipient
reports getting multiple marketing emails in one day, that's a real bug
in this check, not expected behavior — it should be structurally
impossible.
