# SOP: Email Sequence Pipeline, Critical Approve→Image Bug Fix, Platform Health Checks
Date: 2026-09-16
Status: Live — migration + backend + dashboard bridge shipped; health-check automation shipped

---

## Context

Kelvin asked whether the marketing loop was closed enough to start lead scraping/cold email. Audit found: nothing was live anywhere (Cloud Decoded had zero drafted sequences; MSE had 2 real drafts stuck with no approval UI; Apollo/Systeme.io both blocked on missing/free-tier API keys). He chose to build the Cloud Decoded email pipeline first.

## Task 1 — Email sequence persistence (Cloud Decoded)

`agents/internal/email_sequence_agent.py` was already fully built but its output only ever landed in `internal_agent_runs.result` as an opaque JSON blob — no dedicated table existed for the dashboard to list or approve against. (A schema for this existed once in `infra/supabase/migrations/001_initial_schema.sql`, but that file was never part of this repo's real migration pipeline — `db/migrate.py` only applies `db/migrations/*.sql` — so it was never actually live.)

- `db/migrations/039_email_sequences.sql` (new) — `email_sequences` + `email_sequence_steps`, matching `007_marketing_queues.sql`'s conventions (product_id text, service_role RLS, CHECK-constrained status).
- `api/routes/internal_agents.py`'s `email_sequence_agent` dispatch branch now inserts one `email_sequences` row per sequence (trial_nurture/email_only_nurture/post_churn_winback) and one `email_sequence_steps` row per email (23 total), alongside the existing generic blob write (unchanged).
- Applies automatically on next deploy via the existing migration runner — no manual `apply` step.

## Task 2 — Critical bug found: image-generation-on-approval was dead in production

While building the email pipeline's dashboard side, found that `ceo-dashboard`'s actual approve buttons (`app/api/linkedin-queue/[id]/route.ts` and `.../batch-approve/route.ts`) write straight to Supabase and **never call** `api/routes/internal_marketing.py`'s PATCH/batch-approve endpoints at all — a 2026-07-24 comment in that Next.js code explains the backend wasn't deployed anywhere reachable at the time those routes were written. The backend **is** live on Railway now, but nobody updated the dashboard routes — meaning `_generate_and_gate_image_for_approved_row` (built and reported "done" earlier the same day, see the two 2026-09-15 marketing SOPs) had never actually run for a single real approval.

Fix (Kelvin's chosen design: async, not blocking):
- `api/routes/internal_marketing.py`: new `POST /internal/marketing/linkedin-queue/generate-images` — gated by the shared `X-API-Key` (`require_marketing_api_key`, imported from `api/routes/marketing.py`, same auth model as the working `linkedin-on-demand` precedent) rather than `get_internal_user`, since the caller is server-to-server with no Supabase session JWT. Schedules `_generate_images_in_background` as a FastAPI `BackgroundTasks` job and returns immediately — never blocks the caller on N sequential Gemini+Claude calls.
- `ceo-dashboard/lib/trigger-image-generation.ts` (new) — the fetch wrapper, same `NEXT_PUBLIC_API_URL`/`MARKETING_API_KEY` pattern as `app/api/linkedin-queue/generate/route.ts`. Never throws — a slow/unreachable backend must never fail an approval that already succeeded in Supabase.
- Both `[id]/route.ts` and `batch-approve/route.ts` now call it right after their own Supabase write.

**Lesson recorded for future sessions:** verify which layer (FastAPI backend vs. Next.js route handlers) actually serves a given dashboard action before assuming a backend fix is live — this repo has two independent implementations of the same LinkedIn-queue actions, and only one of them (the Next.js one) is what the deployed dashboard calls today.

## Task 3 — Platform health checks (separate fork, Kelvin's own request mid-session)

Weekly (Monday)/monthly/quarterly automated health sweeps with Slack alerting and an on-demand dashboard button:
- `core/health_check.py` (new) + `.github/workflows/{weekly,monthly,quarterly}-health-check.yml` (new, `workflow_dispatch`-able)
- `api/routes/internal_agents.py` gained a `platform_health_check` dispatch branch (roster + wirable set)
- `ceo-dashboard/components/ui/SystemHealthPanel.tsx` — "Run Full Platform Health Check Now" button
- New required secret: `SLACK_OPS_WEBHOOK_URL` (separate from the existing lead-notification webhook) — sweeps run and produce a report without it, but alerts won't deliver until Kelvin creates it and adds it as a repo secret.

**What's genuinely checkable today:** main backend + DB + frontend status, both satellite services' `/health`, every internal agent's last-run/error-rate from `internal_agent_runs`, monitored GitHub Actions workflow status, TLS cert expiry + Stripe connectivity (monthly), RLS coverage (quarterly).

**Explicitly reported as not-yet-implemented, not faked:** n8n (not deployed anywhere, planning-doc only), inbound email receiving (no webhook/IMAP handler exists), cost/token-spend trending (no time-series table), dependency/CVE scanning (nothing wired into CI).

## Test coverage

100 tests passing across `test_internal_agents.py`, `test_internal_marketing_approval_image_gen.py`, `test_internal_marketing_publish.py`, `test_email_sequence_agent.py`, plus 26 new tests in `test_health_check.py`. `tsc --noEmit` on `ceo-dashboard` shows zero new errors (21 pre-existing errors remain in unrelated, in-progress `ThdConsulting*` files).

## Still open (not built this session, by design)

- Cloud Decoded's first *real* drafted sequence — `email_sequence_agent` needs a completed `research_agent` run to chain from, and zero `research_agent` runs exist in production. `research_agent`'s Reddit scraping is real (public JSON endpoint); G2/LinkedIn/Quora are documented stubs. Next step: actually fire `research_agent` for Cloud Decoded's real niche, then chain `email_sequence_agent` off that real run.
- A dashboard approval panel for `email_sequences`/`email_sequence_steps` (the `LinkedInBatchPanel` pattern is the template to reuse) — not yet built.
- MSE's 2 already-stuck `mse_email_sequences` rows — still unreviewable, deliberately deferred (Kelvin chose Cloud Decoded first).
- Apollo (free-tier, no API access) and Systeme.io (no API key set, and MSE's own notes flag "no campaigns API") — both need Kelvin's direct action on the external accounts, not code.

---

## If this breaks again

- **An approved LinkedIn post has no image and dashboard shows nothing happening:** check the FastAPI backend's logs for `generate-images` calls — if `trigger-image-generation.ts` logged "MARKETING_API_KEY is not configured," that env var is missing on the ceo-dashboard Vercel deployment (it's required for this bridge, not just the on-demand fire button).
- **A future "I fixed the backend" claim about LinkedIn queue behavior:** always check whether `ceo-dashboard/app/api/linkedin-queue/*` (Next.js, direct Supabase) or `api/routes/internal_marketing.py` (FastAPI) is the one actually wired to the button in question — do not assume the FastAPI route is live just because it's deployed.
- **Health check alerts never arrive:** confirm `SLACK_OPS_WEBHOOK_URL` exists as a repo secret — sweeps still run and produce an artifact without it, silently, by design (never blocks the sweep on a missing alert channel).
