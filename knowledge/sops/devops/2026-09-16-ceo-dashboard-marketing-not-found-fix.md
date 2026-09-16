# SOP: CEO Decoded Marketing Page "Not Found" Errors — Root Cause and Fix
Date: 2026-09-16
Status: Live — committed, pushed, Vercel deployed, MSE redeployed, DB migrations applied

---

## What happened

Kelvin reported the Marketing page's Lead Pipeline and Cold Outreach Tracker
panels showing "Not Found" errors, and asked where the cold outreach /
job-scraper trigger button actually lives on the dashboard so he could
start using it today.

## Root causes (four, all fixed)

1. **Wrong backend URL in 10 Next.js API routes.** `app/api/marketing-leads/*`
   and `app/api/thd-consulting/*` all read `NEXT_PUBLIC_API_URL` — Cloud
   Decoded's own backend var — despite every one of their own comments
   saying they proxy to "the microsaas-engine backend." Cloud Decoded's
   backend has no `/marketing/leads` or `/thd-consulting` routes at all,
   so every call 404'd. `.env.example` has declared a separate
   `NEXT_PUBLIC_MSE_API_URL` for exactly this since it was added; nothing
   ever read it. Fixed: all 10 files switched to `NEXT_PUBLIC_MSE_API_URL`.

2. **`NEXT_PUBLIC_MSE_API_URL` was never set on Vercel production at all**
   — confirmed via `vercel env ls`: only `NEXT_PUBLIC_API_URL` existed.
   Fix #1 alone would have kept failing (falling back to
   `http://localhost:8000`) without this. Added the var via `vercel env add`,
   pointing at mse-api's Railway domain
   (`https://mse-api-production-f8bd.up.railway.app`).

3. **mse-api's Railway service hadn't redeployed since 2026-09-08** — nine
   days of pushes, including today's whole consulting cold-outreach build,
   never went live. Diagnosed via `railway-agent`: Railway's GitHub App is
   not installed on `kdavis-microsaas-engine` (`NO_INSTALLATION`, auto-deploy
   silently disabled). Manually triggered a fresh deploy pulling commit
   `0f54385` (today's consulting ICP work); confirmed `SUCCESS`.
   **Action item for Kelvin: install the Railway GitHub App on
   `kdavis-microsaas-engine` in the Railway dashboard, or every future push
   will need this same manual trigger.**

4. **Two MSE Supabase migrations were never applied to the live database**
   — `20260914221640_icp_selling_stage.sql` and
   `20260916000045_consulting_infra_icp.sql`. MSE has no automated migration
   runner (unlike this repo's `db/migrate.py`), so these just sat in the
   repo. Discovered when applying #4 failed with `UndefinedColumnError:
   selling_stage does not exist`. Applied both directly against the shared
   Supabase project (`gjezchcoyytxcpsbvkrg`) via a one-off asyncpg script,
   in order. Verified afterward: `mse_icp_configs.selling_stage` /
   `min_company_size` / `max_company_size` / `exclude_criteria`,
   `mse_leads.job_posting_url/title/date`, `mse_dm_sequences.touch_3` /
   `touch_3_sent_at` all present; the `thdagentic-consulting` ICP row is
   live with `selling_stage='active'`; CHECK constraints on
   `mse_leads.source` / `mse_dm_sequences.lead_source` include
   `job_posting_signal`.

## Where the cold-outreach button actually is

The "Run Lead Finder Now" and "Send Due Sequences Now" buttons in the
**Lead Pipeline** panel (top of the Marketing page) are the job-posting
scraper / cold-outreach trigger. They always existed
(`LeadPipelinePanel.tsx`) — they were just calling a route that 404'd.
The "Marketing Agents" roster card's "Cold Email: PENDING, Not yet built"
entry was also stale and misleading (it's LinkedIn DMs via MKT-O1/O2, not
email, and it's live) — updated to "Cold Outreach: active" pointing back
at the Lead Pipeline panel.

## Verified end to end

- `curl` against mse-api's live `/marketing/leads/icp-products` with the
  real `MARKETING_API_KEY` returns 200 with all 8 ICP products, including
  the new `thdagentic-consulting` row — confirms backend + DB fix together.
- ceo-dashboard's Vercel production deploy (triggered by this session's
  push) built and went `Ready`.
- `tsc --noEmit` on the touched files: clean. (Two pre-existing, never-
  committed consulting-dashboard component files —
  `ThdConsultingLeadsPanel.tsx` / `ThdConsultingPipelineBoard.tsx` — have
  real type errors against `lib/api.ts`/`lib/types.ts` exports that don't
  exist yet. They're untracked, not part of this commit, and don't affect
  the Vercel build since Vercel only sees pushed commits. Separate,
  pre-existing unfinished work — not addressed here.)

## Still open / residual risk

- **Could not verify `MARKETING_API_KEY`'s value matches between Vercel
  and mse-api's Bearer-auth check** — both sides redact stored secret
  values (Railway and Vercel both hide "Sensitive"-typed vars on read), so
  they couldn't be diffed directly. The route's own comment implies this
  was always meant to be one shared secret across both backends. If the
  Lead Pipeline / Cold Outreach panels come back with a 401 or 500 (not
  "Not Found") after this deploy, that mismatch is the next thing to check
  — compare mse-api's `MARKETING_API_KEY` Railway variable against
  ceo-dashboard's Vercel one directly in each dashboard's UI (values are
  visible there even though CLI reads redact them).
- Vercel deploy was verified via its own `*.vercel.app` production URL —
  there's no custom domain alias (e.g. `app.thdstack.com`) pointed at
  ceo-dashboard yet, only the auto-generated one.

---

## If this breaks again

- **"Not Found" on any `/marketing-leads/*` or `/thd-consulting/*` panel:**
  check `NEXT_PUBLIC_MSE_API_URL` is still set on Vercel (`vercel env ls`)
  and that the route file reads it, not `NEXT_PUBLIC_API_URL`. Two
  completely different backends share this one Next.js app — never
  conflate the vars again.
- **mse-api looks stale after a push:** check Railway's GitHub App
  install status first, before assuming the code is broken —
  `list-deployments` will show the last real deploy's timestamp/commit
  vs. what's actually in `git log`.
- **A new MSE migration "isn't taking effect":** there is no migration
  runner in kdavis-microsaas-engine. Every migration must be applied by
  hand against the shared Supabase project until one is built — flag this
  gap to Kelvin if it comes up again; it's cost real time twice now.
