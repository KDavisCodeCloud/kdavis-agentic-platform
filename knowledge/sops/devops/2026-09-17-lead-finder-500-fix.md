# SOP: "Run Lead Finder Now" 500 Error — Root Cause and Fix
Date: 2026-09-17
Status: Live — fixed, deployed, verified end-to-end in production

---

## What happened

Kelvin reported "Triggering lead finder failed: 500" when clicking "Run
Lead Finder Now" for Cloud Decoded on the CEO Decoded dashboard's Lead
Pipeline panel.

## Root cause

`mse_lead_finder_runs` (migration `20260814000024_lead_finder.sql`) was
created with:

```sql
status TEXT NOT NULL DEFAULT 'running'
  CHECK (status IN ('running', 'complete', 'failed'))
```

But `api/routers/leads.py`'s `POST /marketing/leads/find` — the real
endpoint the dashboard's button calls — inserts the row with
`status='pending'` *before* the background task starts, specifically so
a caller polling `GET /marketing/leads/runs/{run_id}` can distinguish
"queued, not started yet" from "actively running." Confirmed by reading
`agents/marketing/mkt_lead_finder.py`'s `run_lead_finder_for_product`,
which flips `'pending'` → `'running'` itself once the background worker
actually begins (line ~286). `'pending'` was always the intended design
— the CHECK constraint was just never updated when the API-route
trigger path was built on top of the table's original,
`run_lead_finder_for_product`-only design.

**This almost certainly means the manual button has never worked for
any product, not just Cloud Decoded.** The weekly n8n cron calls
`run_lead_finder_for_product` directly with no `run_id` — that code path
inserts a fresh row with `status='running'` immediately (never
`'pending'`), so the cron path was never affected and nobody had reason
to notice. Cloud Decoded getting a real, usable ICP config yesterday is
what finally put a human in front of the button for the first time.

## Fix

`supabase/migrations/20260917000047_lead_finder_runs_pending_status.sql`
— `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` to add `'pending'` to
the allowed set. Applied automatically by the migration runner
(`core/migrate.py`, built yesterday specifically for this class of
problem) on deploy — no manual DB script needed this time, which is
exactly what that runner exists for.

## Verified end-to-end against production

1. Reproduced the exact 500 directly (`curl POST /marketing/leads/find`
   with Cloud Decoded's `product_id`) before writing any fix, and pulled
   the real Railway traceback confirming
   `postgrest.exceptions.APIError` code `23514` on
   `mse_lead_finder_runs_status_check`.
2. After deploy: `/health` confirms the new commit is live.
3. Re-ran the exact same request: `200` with a real `run_id` and
   `status: "pending"`.
4. Polled `GET /marketing/leads/runs/{run_id}` ~8 seconds later:
   `status: "complete"`, `error_message: null` — full
   `pending → running → complete` lifecycle confirmed working, not just
   the initial insert.

`leads_found: 0` on this run is expected and unrelated —
`scrapers/google_search.py`'s `GoogleSearchScraper.scrape()` returns `[]`
gracefully (by design) if `GOOGLE_CSE_API_KEY`/`GOOGLE_CSE_ENGINE_ID`
aren't configured on `mse-api`, rather than erroring. Worth checking
those are set if Kelvin expects real leads back from a run, but that's a
separate, non-blocking item from today's fix.

---

## If this breaks again

- **Any other product's "Run Lead Finder Now" still 500s**: same
  constraint, same fix, already applied — check `mse_schema_migrations`
  for `20260917000047_lead_finder_runs_pending_status.sql` to confirm it
  actually landed rather than assuming.
- **A run stays stuck on `pending` forever**: check
  `GOOGLE_CSE_API_KEY`/`GOOGLE_CSE_ENGINE_ID` are set — not this bug, a
  separate missing-credential gap.
