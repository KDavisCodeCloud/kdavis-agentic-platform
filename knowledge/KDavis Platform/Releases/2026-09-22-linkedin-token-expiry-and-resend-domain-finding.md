# Release: LinkedIn Token Expiry Fix + Critical Resend Domain Finding
Date: 2026-09-22
Product: Cloud Decoded (internal marketing pipeline)
Migration: 052

## What was reported
Kelvin: "approved linkedin posts are not posting as scheduled. I need a
root cause and a fix."

## Root cause
`api/routes/internal_marketing.py`'s `linkedin_callback` never captured
LinkedIn's `expires_in` from the OAuth token exchange. LinkedIn's
access token under this app's product config (`openid profile
w_member_social` scopes, no `offline_access`/Marketing Developer
Platform partner approval) has a fixed ~60-day lifetime with **no
refresh token support** — it must be manually re-authorized periodically,
and this codebase had zero tracking of when that was due.

The token was last connected 2026-07-21. It expired ~2026-09-19. Every
run of `.github/workflows/linkedin-dispatch.yml` (the 15-min cron that
publishes approved, scheduled `linkedin_content_queue` rows) since then
failed closed with a `401` from LinkedIn's Images API
(`POST /rest/images?action=initializeUpload`) — confirmed via the
workflow's own GitHub Actions logs, pulled directly via `gh api`. Nothing
alerted Kelvin; he only found out because posts stopped appearing.

## Fix
1. **Migration 052**: `internal_social_connections` gets `expires_at` +
   `expiry_warned_at`. Backfilled the current LinkedIn row's `expires_at`
   from `updated_at + 60 days` (a reconstruction confirmed accurate by
   the live 401 itself).
2. `linkedin_callback` now captures and persists real `expires_in` on
   every (re)connect.
3. New `core/social_token_expiry.py`, mirroring `core/credential_expiry.py`'s
   existing warn-then-escalate pattern (that module covers per-workspace
   Azure credentials; this covers the single-row, owner-only LinkedIn
   connection — no `workspace_id`, so `OWNER_ALERT_EMAIL` directly rather
   than a HITL incident). Runs hourly (not daily, unlike credential_expiry
   — the point is catching an already-broken state in hours, not days):
   warns 14 days before expiry, and re-alerts at most once/day once
   actually expired.
4. Wired into `api/main.py`'s existing background-loop startup pattern
   (`_social_token_expiry_loop`, alongside `_credential_expiry_loop` and
   the email lifecycle system's loops).

Checked Canva's equivalent OAuth callback for the same gap — it already
captures `expires_in` and stores a refresh token, so it wasn't affected.
LinkedIn was the one blind spot.

## Immediate unblock (still needed — this fix prevents recurrence, it
doesn't retroactively fix today)
Kelvin needs to manually reconnect:
`GET {API_BASE_URL}/api/v1/internal/marketing/connect/linkedin?key=<ADMIN_BOOTSTRAP_KEY>`
— requires logging into LinkedIn as himself and approving the connection
again. No way to automate this; LinkedIn's OAuth for these scopes has no
refresh path.

## Critical finding surfaced while testing the fix (GAPS.md #32)
The new alert's first live run produced a real Resend API call, which
was rejected: `403 validation_error — "The theclouddecoded.com domain is
not verified. Please, add and verify your domain on
https://resend.com/domains."`

This is a domain-level block in Resend, not scoped to the marketing
`news@` stream — it also blocks `hello@theclouddecoded.com`
(transactional). **No real email has actually been delivered from this
platform** — every prior "sent" or "live" claim this build session meant
the code path executed and Resend's API was reachable, not that Resend
accepted the send. Welcome emails, dunning, the enterprise-tier alert,
this new token-expiry alert, and the entire migration-051 email
lifecycle system are all affected. Kelvin-only fix: verify
`theclouddecoded.com` in the Resend dashboard (adds SPF/DKIM/DMARC DNS
records at the domain's DNS host) — nothing on the code side can resolve
this.

## Outcome
8 new tests, full suite 2142 passed (was 2134), same 4 pre-existing
unrelated failures, zero regressions. Deployed to Railway, `/health`
verified live, migration 052 confirmed applied via direct Supabase query
(`expires_at` backfilled correctly to 2026-09-19).

## If this fails next time
- If a "LinkedIn posting token expired" email never arrives despite the
  token being expired, check the Resend domain-verification status
  first (GAPS.md #32) before assuming `core/social_token_expiry.py` is
  broken — the check-and-log path works (confirmed live); only the
  actual email delivery is blocked externally right now.
- Once Resend is verified, re-run a quick check that the alert actually
  lands in Kelvin's inbox, not just that the code stops logging the 403.
