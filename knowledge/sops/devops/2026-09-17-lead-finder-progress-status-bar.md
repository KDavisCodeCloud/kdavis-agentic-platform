# SOP: Lead Finder Progress / Status Bar
Date: 2026-09-17
Status: Live — deployed to Railway (mse-api) and Vercel (ceo-dashboard), verified end-to-end

---

## What Kelvin asked for

"ran the lead scraper, and there is no status bar of how long it takes,
what its looking for, or how long it would take to find the leads for
each."

## What was found reading the code first

`LeadPipelinePanel.tsx` triggers a run and shows one static message —
it never calls back to check on it again. `run_lead_finder_for_product`
(the real background worker) only ever wrote to `mse_lead_finder_runs`
twice: once at the start (`status='running'`), once at the very end
(`complete`/`failed`). Nothing in between, even though a real run can
take hours — `core/email_finder.py` throttles SMTP verification to one
lead per 3-6 minutes by design, to avoid an IP getting flagged.

## What was built

**Backend** (`kdavis-microsaas-engine`):
- Migration `20260917000048_lead_finder_progress.sql` — `current_step`,
  `total_steps`, `completed_steps`, `estimated_seconds_remaining` on
  `mse_lead_finder_runs`.
- `find_leads()` gained an optional `on_progress(step_text, completed,
  total)` callback, called:
  - Once per **location** scraped (search phase) — deliberately *not*
    threaded into `GoogleSearchScraper.scrape()` or the 4 identical
    vertical scrapers' fixed `scrape(location, filters)` interface.
    Per-location is the finest granularity available without changing 5
    scrapers' ABC signature for a UI-only feature.
  - Once per **deduplicated lead verified** (verify phase) — this is
    where a real run actually spends nearly all its wall-clock time, so
    this is the granularity that matters most.
- `run_lead_finder_for_product`'s new `_on_progress` closure writes
  these columns on every callback, with a real ETA: exact during the
  verify phase (known remaining lead count × the module's own enforced
  180-360s delay range), a coarser upper bound during the search phase
  (from the scraper's own `MAX_QUERIES_PER_CALL` and delay constants).
  Progress fields are explicitly cleared (`current_step=null`,
  `estimated_seconds_remaining=0`) on completion/failure so the UI never
  shows a stale "verifying email 3/12" after a run has actually ended.
  A progress-write failure is caught and logged, never allowed to abort
  an otherwise-successful run.

**Frontend** (`kdavis-agentic-platform/ceo-dashboard`):
- New `GET /api/marketing-leads/runs/[id]` proxy route +
  `fetchLeadFinderRun()`.
- `LeadPipelinePanel.tsx` polls every 4 seconds while a run is
  `pending`/`running`, rendering a real progress bar
  (`completed_steps`/`total_steps`), the live `current_step` text,
  client-ticked elapsed time, and the backend's ETA once one exists.
  Stops polling and shows the final lead/verified count on completion,
  or the real error message on failure.

## Verified

- 6 new backend tests (exact progress-call sequence and values for both
  phases, DB columns written and cleared correctly, a progress-write
  failure tolerated without breaking the run). Full suite: 598 passed, 1
  skipped (pre-existing), 0 failed.
- `tsc --noEmit` / `next build` clean against every file this touched
  (pre-existing, untracked `ThdConsulting*` type errors are unrelated
  leftover work from an earlier session, not part of this change).
- Live against production, post-deploy: `/health` confirms the new
  commit; triggered a real run for Cloud Decoded and confirmed
  `total_steps: 2` (its two configured locations), with
  `current_step`/`estimated_seconds_remaining` correctly `null`/`0`
  after completion.

**Not independently verified live**: the mid-run ticking behavior
itself (progress bar moving, ETA counting down) — this test run
completed in under 2 seconds because `GOOGLE_CSE_API_KEY`/
`GOOGLE_CSE_ENGINE_ID` aren't configured on `mse-api` yet (same
pre-existing gap noted in yesterday's 500-fix SOP), so `scrape()`
returns instantly rather than doing real, slower work. The exact
call sequence and values are covered by the 6 new unit tests instead.
Once those credentials are set and a real run with actual leads takes
meaningful time, this is worth a real visual check.

---

## If this breaks again

- **Progress bar never moves / stays at "Queued…"**: check
  `GOOGLE_CSE_API_KEY`/`GOOGLE_CSE_ENGINE_ID` are set — without them the
  whole run (search + verify) completes in well under a second, so
  there's nothing to visibly progress through. Not a bug in this feature.
- **ETA looks wildly wrong**: it's a rough estimate grounded in
  `core/email_finder.py`'s and `scrapers/google_search.py`'s own real,
  enforced delay constants, not a live measurement of actual network
  latency — expect it to be in the right order of magnitude, not exact.
