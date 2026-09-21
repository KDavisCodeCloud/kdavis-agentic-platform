# Release: Email Campaign System — Full Deploy + Follow-Up Fixes
Date: 2026-09-21
Products: Cloud Decoded, MSE (kdavis-microsaas-engine), CEO Decoded dashboard

## What was built
Continuation of the same session as
`2026-09-21-cloud-decoded-email-lifecycle-system.md`. This entry covers the
rest of that three-workstream build: MSE campaign engine deployment
(including a product-ID reconciliation pass, "W2.5"), the CEO Decoded
Email Campaign HITL queue (W3), and two follow-up correctness fixes Kelvin
asked for after reviewing the initial report.

### W2 — MSE campaign engine + W2.5 reconciliation
Extended the real, existing `mse_email_sequences` table rather than
building a parallel schema (the build spec's assumption didn't match what
was actually in this repo). Reconciled three previously-unrelated ID
spaces (`opportunity_pipeline.id`, `mse_products.id`,
`mse_email_sequences.product_id`) onto `mse_products.id` as canonical —
including creating a registry row for "Showing Signal," a real launched
product that had never been added to `mse_products`. Wired a DB-level
positioning-approval gate (SECURITY DEFINER + trigger, matching the DIST
pattern) and fixed a real production bug found while wiring it: the
campaign fan-out loop had no per-agent isolation, so the new gate would
have silently killed SEO/social generation for every product once email
got blocked. 629 tests passing, zero regressions.

### W3 — CEO Decoded Email Campaign HITL queue
New `/dashboard/email-campaigns` page in `ceo-dashboard/`, merging both
backends' approval queues behind one UI. Added Vitest to this app from
scratch (it had zero test infrastructure before this build) — 21 tests
passing. Left two things honestly unwired rather than guessed at: the
MSE "Generate Campaign" button (the real trigger keys off an ID space the
status endpoint doesn't expose) and `hitl`-role support (doesn't exist
anywhere in the stack yet).

### Deploy troubleshooting (Railway, mse-api)
The mse-api Railway service failed to deploy three times before this
session's changes could go live. Root cause was a genuine, pre-existing
misconfiguration unrelated to any code in this build: the service's
`rootDirectory` setting had drifted from the repo's real structure. Fixed
by inspecting the actual git tree via GitHub's API directly (local `git`
commands were misleading due to this repo's unusual shared-parent-directory
git root) and by re-attaching the service's GitHub source
(`connect-service-source`) after a stale webhook connection stopped
firing on push. Also found and ruled out `railway up`'s local-upload path
as unreliable on this WSL-mounted Windows drive — two unrelated files
(one tracked, one not) both came through corrupted on upload despite
being clean on disk. Added `.railwayignore` as a minor hardening measure
regardless. All three services (kdavis-agentic-platform, mse-api,
ceo-decoded-dashboard) confirmed live via direct health checks after
every deploy in this session, not just deploy-tool status.

## Follow-up fixes (post-initial-report, Kelvin's requests)

1. **MSE API credential — reuse, don't mint.** The initial W3 build had
   ceo-dashboard authenticate to mse-api's admin-JWT-gated
   `/marketing/internal/*` routes via a brand-new static `MSE_API_KEY`
   Kelvin would have had to mint by hand. Kelvin asked to reuse an
   existing credential instead. Fix: ceo-dashboard now signs its own
   short-lived admin JWT server-side
   (`ceo-dashboard/lib/email-campaigns/mse-auth.ts`), using
   `MSE_SUPABASE_JWT_SECRET` — a copy of the *same*
   `SUPABASE_JWT_SECRET` value already provisioned on the mse-api Railway
   service, not a new secret. mse-api's own auth middleware already
   trusts any HS256 token signed with that secret carrying
   `app_metadata.role="admin"`, with no database lookup — the exact
   mechanism that repo's own synthetic test tokens already use. Zero new
   credentials to provision; Kelvin just copies one existing value into
   Vercel.

2. **Newsletter sending domain — corrected a documentation error, not a
   code bug.** Kelvin pointed out the newsletter shouldn't need a
   separate domain. On inspection, the code was already right:
   `news@theclouddecoded.com` and `hello@theclouddecoded.com` are the
   same root domain (`theclouddecoded.com`), already verified in Resend —
   SPF/DKIM/DMARC apply at the domain level, not per mailbox, so no new
   domain verification was ever actually required. The bug was in
   `core/email.py`'s own docstring (and this session's summary to
   Kelvin), which incorrectly called `news@` a "subdomain" needing
   separate verification. Corrected the docstring; the Kelvin-only action
   list no longer includes verifying a second domain for marketing sends.

## Decisions made
See `DECISIONS.md` 2026-09-21 entries for the pre-build sign-offs
(Brevo retirement, onboarding-cron migration, three-workstream scope).
Both follow-up fixes above were direct corrections requested by Kelvin
after reviewing the initial build report — no new architectural decision,
just fixing an over-engineered credential and a doc error.

## Outcome
All three services deployed and independently health-checked live:
- `kdavis-agentic-platform-production.up.railway.app/health` → `ok`
- `mse-api-production-f8bd.up.railway.app/health` → `ok`, confirmed via
  direct Supabase REST query that migrations 051-053 actually applied
  (not just that the process started)
- `ceo-decoded-dashboard` (Vercel) → `/dashboard/email-campaigns` resolves
  (redirects to `/login`, correct for an unauthenticated request)

Full Kelvin-only action list is in the session's final chat summary, not
duplicated here — it changes as items get done and shouldn't rot in two
places.

## Post-release fix: MSE_SUPABASE_JWT_SECRET copied, CD_UNSUBSCRIBE_SECRET generated
Same day, after Kelvin started using the live queue:
- Copied the existing `SUPABASE_JWT_SECRET` value from mse-api's Railway
  env into ceo-dashboard's Vercel production env as
  `MSE_SUPABASE_JWT_SECRET`, redeployed (`vercel redeploy`, since the
  local-upload path hits the same rootDirectory-relative confusion
  Railway did — redeploying a known-good prior build is the reliable
  path for this project too). MSE panel confirmed populated afterward.
- Kelvin reported "requests not coming in" on the Approval Queue.
  Traced via live Railway logs to a real 500:
  `GET /api/v1/internal/email/templates/{key}` (single-template detail,
  used for the queue's expand/preview) crashes with
  `UnsubscribeConfigError: CD_UNSUBSCRIBE_SECRET is not set` — the detail
  endpoint renders a real compliance-footer preview including an
  unsubscribe link, and `core/unsubscribe_token.py` fails closed by
  design when that secret is missing (same as the scheduler). This was
  always going to block real sends too, so not just a preview-only bug.
  `CD_COMPLIANCE_MAILING_ADDRESS` degrades gracefully by contrast (blank
  line, no crash) — only the unsubscribe secret is a hard dependency.
  Generated a random secret (`secrets.token_urlsafe(48)`) and set it via
  Railway MCP directly — this is a pure cryptographic value with no
  business decision attached (unlike the mailing address, a real fact
  only Kelvin has), so no reason to make it a Kelvin-only action. Service
  redeployed automatically on the variable set; detail endpoint confirmed
  fixed (401 on a bad token instead of 500).

## If this fails next time
- If the MSE panel in `/dashboard/email-campaigns` 500s with
  "MSE_SUPABASE_JWT_SECRET is not configured," check Vercel production
  env first — the fix above should already cover this, but a redeploy
  target/environment mismatch could un-set it.
- If mse-api fails to deploy again with a `railpack prepare` error,
  check `rootDirectory` first (should be `kdavis-microsaas-engine`) before
  assuming it's a code issue — this exact failure mode already burned
  significant time once this session from a wrong assumption in the
  other direction.
- mse-api's GitHub push does NOT reliably auto-trigger a Railway
  redeploy as of this session — use `connect-service-source` (MCP) or
  the Railway dashboard's manual redeploy, not just `git push`, until
  that connection is confirmed fixed.
