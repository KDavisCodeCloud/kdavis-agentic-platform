# Micro SaaS Engine — Infrastructure

**All services live as of 2026-07-03.**

---

## Supabase

| Field | Value |
|---|---|
| Project name | `microsaas-prod` |
| Project ref | `gjezchcoyytxcpsbvkrg` |
| Region | (default) |
| Postgres version | 15 |
| CLI linked | Yes — `supabase link --project-ref gjezchcoyytxcpsbvkrg` |

### Tables

| Table | Key Rules |
|---|---|
| `tenants` | RLS on — `tenant_id = current_setting('app.tenant_id')` |
| `usage_events` | RLS on — FK to tenants |
| `milestones` | RLS on |
| `retention_sequences` | RLS on |
| `weekly_digest_log` | RLS on |
| `opportunity_pipeline` | RLS on — CHECK `conservative_mrr_potential >= 4000 OR status = 'rejected'` |

### Migration Files

| File | Description |
|---|---|
| `supabase/migrations/20260703000001_core_schema.sql` | 5 retention tables + RLS policies |
| `supabase/migrations/20260703000002_opportunity_pipeline.sql` | Pipeline table + $4K MRR floor |

**Note:** `gen_random_uuid()` used everywhere — `uuid_generate_v4()` deprecated on Postgres 15.

---

## FastAPI (api/)

| Field | Value |
|---|---|
| Port | 8000 |
| Docs | `http://localhost:8000/docs` |
| Health | `http://localhost:8000/health` |

### Routers

| Router | Path | Auth |
|---|---|---|
| health | `GET /health` | None |
| events | `POST /events` | JWT |
| milestones | `GET /milestones/{tenant_id}` | JWT |
| reengagement | `POST /reengagement/evaluate/{tenant_id}` | JWT |
| research | `POST /research/run`, `GET /research/session/{id}` | JWT |
| stripe (TBD) | `POST /webhooks/stripe` | Stripe-sig |

### Auth Middleware

- `api/middleware/auth.py` — validates Supabase JWT, extracts `tenant_id`
- `api/middleware/tenant_context.py` — sets `app.tenant_id` for RLS
- Public paths (no auth): `/health`, `/docs`, `/openapi.json`, `/redoc`, `/webhooks/stripe`

**Open gap:** `get_supabase_for_request(jwt)` not yet implemented — current client uses service_role (bypasses RLS). Fix in `core/supabase_client.py`.

---

## Next.js 15 (frontend/)

| Field | Value |
|---|---|
| Port | 3000 |
| Framework | Next.js 15.3, React 19, TypeScript |
| Styling | Tailwind CSS + dark theme (`#0a0a0a` bg, `#ededed` text) |
| API connection | `NEXT_PUBLIC_API_URL` env var → FastAPI at `:8000` |

### Pages

| Route | File | Purpose |
|---|---|---|
| `/` | `app/page.tsx` | Redirects to `/dashboard` |
| `/dashboard` | `app/dashboard/page.tsx` | Main dashboard |
| `/milestones` | `app/milestones/page.tsx` | Milestone tracker |
| `/research` | `app/research/page.tsx` | Pipeline viewer |

### Components

- `UsageTracker` — fires `page_view` events to `/events` on every page load
- `MilestoneToast` — toast notification on milestone achievement
- `WeeklySnapshot` — renders latest weekly digest data

---

## n8n 2.28.6

| Field | Value |
|---|---|
| Port | 5678 |
| Node version | v22.23.1 (via nvm) — Node 24 incompatible |
| Start script | `n8n/start-n8n.sh` |

### Workflows

| Workflow | ID | Schedule | Status |
|---|---|---|---|
| Weekly Digest | `wkly-digest-001` | Mon 03:00 UTC (Sun 20:00 MST) | Imported — needs activation |
| Re-engagement | `reengagement-001` | Daily 16:00 UTC (09:00 MST) | Imported — needs activation |

### Setup Remaining (Kelvin)

1. Complete first-run owner setup at `http://localhost:5678`
2. Settings → Credentials → Add new → Supabase → name it `microsaas-supabase`
3. Fill Supabase URL + service_role key
4. Activate both workflows

### Known Patches

- `@langchain/core` package.json in n8n's `node_modules` — added 6 missing subpath exports
- Stubs created for: `utils/uuid`, `language_models/stream`, `runnables/remote`

---

## Stripe

| Field | Value |
|---|---|
| Account | Micro Saas Decoded |
| Account ID | `acct_1TpLcKLIpoJRr7Tc` |
| Mode | Live |
| Secret key | In `.env` as `STRIPE_SECRET_KEY` (sk_live_...) |

**Open gap:** `api/routers/stripe.py` webhook handler not built. Needed events:
- `subscription.created` → create tenant
- `subscription.updated` → update tier
- `subscription.deleted` → mark churned
- `invoice.payment_failed` → log + trigger re-engagement

---

## GitHub

| Field | Value |
|---|---|
| Org | `KDavisCodeCloud` |
| Repo | `kdavis-microsaas-engine` |
| Branch | `main` |
| Visibility | Private |
