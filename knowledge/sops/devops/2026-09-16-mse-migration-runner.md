# SOP: Migration Runner Added to kdavis-microsaas-engine
Date: 2026-09-16
Status: Live — deployed, verified against production, committed, pushed

---

## Why

Kelvin asked for a full GAPS.md review, then said "go ahead" on the top
recommendation: closing GAPS.md #15 for good. That entry documented a
real production incident in kdavis-agentic-platform (migrations 024-028
committed and deployed but never applied to the live DB — real customer
signups 500'd for hours) and named the systemic fix as "still open."

Checking the actual repo before building anything: **kdavis-agentic-platform's
half was already fixed** — `db/migrate.py` was built the very next day
(2026-09-15), wired into `api/main.py`'s lifespan, and confirmed today
still fully caught up (39 files on disk, 39 rows in its
`schema_migrations` table). The GAPS.md entry just never got marked
resolved — closed that out as part of this work, same as gap #1's own
precedent for a fix that shipped without its entry being updated.

**kdavis-microsaas-engine had no equivalent at all**, and it wasn't
theoretical — this exact session hit it twice: `20260914221640_icp_selling_stage.sql`
and `20260916000045_consulting_infra_icp.sql` both sat committed and
deployed without ever running against production, only caught because a
third migration failed with `UndefinedColumnError` and forced a manual
investigation. That's the real gap this SOP closes.

## What was built

`kdavis-microsaas-engine/core/migrate.py` — same proven pattern as
`db/migrate.py`, adapted for two things that are genuinely different
about this repo:

1. **Separate tracking table and lock constant.** kdavis-agentic-platform
   and kdavis-microsaas-engine share ONE physical Supabase Postgres
   database (`gjezchcoyytxcpsbvkrg`) — confirmed repeatedly this session
   via direct queries. That repo's `schema_migrations` table already
   exists there with 39 rows tracking its own, unrelated migration
   history. This repo's tracking table is `mse_schema_migrations`; its
   advisory lock constant (`918_442_113`) is deliberately different from
   the other repo's (`847_291_055`) so the two apps' boots never contend
   on the same lock.
2. **Rollback-file exclusion.** `supabase/migrations/` has a real manual
   rollback script sitting next to its forward migration
   (`20260831000035_dist_phase8_mse_leads_alter_ROLLBACK.sql`). A naive
   numeric-order auto-apply would have run it as if it were just the
   next pending migration — `_discover_migrations()` explicitly skips
   any filename containing "rollback" (case-insensitive) and logs each
   skip.
3. **Deterministic sort on a same-prefix collision.** Three real
   existing files share the identical timestamp prefix
   `20260830000030` (parallel work merged without renumbering). Sort key
   is `(prefix, filename)` so their relative order doesn't depend on
   filesystem `glob()` return order.

Also new for this repo: `asyncpg==0.29.0` in `requirements.txt` (this
app previously only spoke to Supabase via the REST client, no raw SQL
capability at all) and `DATABASE_URL` on `mse-api`'s Railway service
(never configured before — confirmed via `list-variables` before adding
it). `api/main.py` had no startup hook of any kind before this; it now
has a `lifespan` that runs migrations before the app serves traffic and
fails closed (no try/except) if that raises.

## The bootstrap step — the part that would have made this dangerous to skip

Before deploying any of the above, all 49 pre-existing forward
migrations (the ROLLBACK file excluded) were inserted directly into a
freshly-created `mse_schema_migrations` table via a one-time script run
against production. **Skipping this would have made the runner's first
boot try to replay all 49 files from scratch** — including
`20260909000044_thd_consulting_leads.sql`, which creates a policy
without a `DROP POLICY IF EXISTS` guard first (confirmed earlier this
same session: re-running it throws `DuplicateObjectError`). That's a
guaranteed crash on the exact deploy meant to fix silent migration
drift, on the app's actual production boot.

## Verified live, not assumed

- Ran `run_pending_migrations()` locally against production *after* the
  bootstrap insert, *before* deploying: logged "Schema up to date — 0
  pending migrations." Confirmed the bootstrap actually worked before
  shipping the code that depends on it.
- Railway's GitHub App is still not installed on this repo (same gap
  flagged in the 2026-09-16 dashboard-fix SOP) — `git push` alone did not
  trigger a deploy. Used `railway-agent` to manually trigger a fresh
  deploy of the real commit (`4001a92`).
- Post-deploy: `GET /health` returns `commit_sha: "4001a92..."` — the new
  code is what's actually live, not a stale build.
- Post-deploy: `mse_schema_migrations` still has exactly 49 rows (the
  runner correctly saw nothing pending and touched nothing).
- Post-deploy: `GET /marketing/leads/icp-products` still returns all 9
  products including `cloud-decoded` and `thdagentic-consulting` — no
  data disturbed by the deploy.

---

## If this breaks again

- **A new migration doesn't seem to be taking effect on kdavis-microsaas-engine:**
  check Railway deploy logs for `[Migrate]` lines (note: this app's root
  logger isn't configured for INFO level by default, so `core/migrate.py`'s
  own `log.info` calls may not surface in Railway's log viewer even
  though they ran — `Application startup complete` in uvicorn's own logs
  is the real signal migrations completed without raising; if migrations
  had failed, that line would never print). If genuinely stuck, query
  `mse_schema_migrations` directly to see what's tracked.
- **A future migration needs to intentionally re-run something already
  applied:** don't delete its row from `mse_schema_migrations` and let
  the runner "retry" it — write a new, forward migration file instead.
  This tracking table is a permanent historical record, not a cache.
- **Adding a real rollback script for a future migration:** name it with
  "ROLLBACK" in the filename (case-insensitive) exactly like the existing
  one, so `_discover_migrations()` continues to skip it automatically.
  Anything else risks it being auto-applied as a forward migration.
