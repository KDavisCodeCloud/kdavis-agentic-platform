# SOP: Cloud Decoded Added to the Lead Pipeline's Lead Finder
Date: 2026-09-16
Status: Live — migration applied to shared DB, verified via live API, committed, pushed

---

## What Kelvin asked for

"the cloud decoded product needs a lead finder also. needs to be added
to the lead pipeline." — the same Lead Pipeline panel on the CEO Decoded
Marketing page fixed earlier today (see
`2026-09-16-ceo-dashboard-marketing-not-found-fix.md`).

## What was built

One migration in `kdavis-microsaas-engine`:
`supabase/migrations/20260916000046_cloud_decoded_icp.sql`

- A new `mse_products` row: `slug='cloud-decoded'`, `status='active'`.
  This is a **scoped, deliberate exception** to the standing rule (see
  `20260914221640_icp_selling_stage.sql`'s own comment) that Cloud
  Decoded has no `mse_products` row because it's architecturally
  separate — own repo, own Stripe account. This row adds nothing beyond
  what the lead-finder machinery needs to key off a product id: no
  Stripe coupling, no `campaign_builds` entry, no billing linkage. Cloud
  Decoded's own checkout/subscription flow in `kdavis-agentic-platform`
  is completely untouched.
- A real `mse_icp_configs` row, keyed to that product, with the ICP
  already documented in `kdavis-agentic-platform/CLAUDE.md`'s per-product
  design-personality section ("B2B DevOps / Enterprise Infrastructure...
  VP Engineering, Head of Platform"):
  - `job_titles`: VP Engineering, Head of Platform, Director of Platform
    Engineering, Head of Infrastructure, VP Infrastructure
  - `locations`: United States, Remote (a national/remote-first
    enterprise SaaS sale, not a local-market product)
  - `search_templates`: three Google Custom Search queries using the
    `{title}`/`{location}` placeholders `scrapers/google_search.py`'s
    `scrape()` actually requires (read directly, not assumed) — one
    direct LinkedIn-profile search for the ICP title, two company-site
    searches for teams likely running the kind of infrastructure Cloud
    Decoded's 11-agent roster addresses.
  - `min_company_size: 100` (excludes tiny startups without inventing an
    upper bound — Enterprise tier customers can be any size above that).
  - `selling_stage: 'active'`.

No frontend change needed. `LeadPipelinePanel.tsx`'s product dropdown
(`listIcpProducts()` → `GET /marketing/leads/icp-products`) is already
fully dynamic — it lists whatever the backend returns. Once the DB row
existed, Cloud Decoded just appeared.

## Verified

- Direct DB query after applying the migration: the `cloud-decoded` row
  and its ICP config are present with the exact values above.
- Live `curl` against `mse-api`'s real `/marketing/leads/icp-products`
  endpoint (same one the dashboard calls) returns Cloud Decoded in the
  product list.
- No redeploy needed anywhere — this is pure data (the migration was
  applied directly to the shared Supabase DB; `mse-api`'s code already
  reads ICP configs generically, no code change), and the dashboard
  route was already fixed and deployed earlier today.

## A real gap found while doing this (flagged, not fixed)

Every other product's ICP config (`ada-title-ii`, `bible-devotional`,
`decodedsix`, `small-portfolio-hub`) has empty `locations` and
`search_templates` — meaning "Run Lead Finder Now" silently returns
zero leads for all of them today, always has. Cloud Decoded's config,
built just now, is the first genuinely functional one in the whole
system. Written up as GAPS.md #29, with a second, related finding: the
consulting ICP's job-posting-signal lead source
(`run_job_posting_signal_finder`) has no wired trigger at all — the
"Run Lead Finder Now" button always calls the *other* finder function,
so consulting also silently returns zero leads, for a different reason.
Neither is fixed here — both need Kelvin's go-ahead on the real ICP data
and, for consulting, an actual design decision about which lead source
that button should trigger.

---

## If this breaks again

- **Cloud Decoded's Lead Finder run returns 0 leads:** check
  `GOOGLE_CSE_API_KEY`/`GOOGLE_CSE_ENGINE_ID` are set on `mse-api` —
  `scrapers/google_search.py`'s `scrape()` returns `[]` silently (by
  design) if either is missing, same "skip gracefully" shape as every
  other not-yet-configured integration in this codebase.
- **A different product's Lead Finder also returns 0 leads:** check
  GAPS.md #29 first — this is very likely the same pre-existing empty-ICP
  issue, not a new bug.
