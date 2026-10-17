# Release: Loop Map tab in CEO Decoded
Date: 2026-10-17
Repos: kdavis-agentic-platform `1238a37` (master) · kdavis-microsaas-engine `4b85d1c` (main)
Migrations: engine `20261017000065_loop_map.sql`

## What Kelvin asked for
A top-level **Loop Map** tab in CEO Decoded (ceo.thdecodedempire.com), next to
Marketing. It shows every product's marketing loop as a pixel-office track:
- Check off steps and the sprite walks forward.
- Log holes and notes at any step.
- Desk colors show live, verified status from production.
- A 4-week history strip shows how long a step has been stuck.

The design is a port of `docs/design/loop-map-reference.html`, Kelvin's
"Decoded Empire Loop Map" artifact, which I committed into the repo.

## What was built

### Data model (engine migration, admin-only RLS)
- **Tables:**
  - `mse_loop_products` and `mse_loop_stations`, seeded with 6 products and 46 stations.
  - `mse_loop_playbook_templates`, covering four playbooks: signal_outbound, community_search, content and distributor.
  - `mse_loop_progress`, `mse_loop_laps`, `mse_loop_notes` and `mse_loop_status_history`.
- **RLS:** a service-role policy comes first on every table, plus admin SELECT. Notes have no DELETE policy, so holes are resolved and reopened, never deleted.
- **Playbooks:** `mse_loop_apply_playbook()` builds the stations for a new product from a playbook. It refuses if that product already has stations.

### Live status (`GET /marketing/loop-map`)
- **Statuses:** each station is evaluated to working / not_proven / waiting_on_you / blocked / not_built / **unknown**.
  - Each status carries evidence text, a count and a timestamp.
  - Unknown is never green. Any source the API can't read evaluates to unknown and shows the read error as its evidence.
- **Code:** the rules are pure functions in `core/loop_map_rules.py`. Their data comes from `core/loop_map_sources.py`, which loads 16 tables in parallel.
- **External checks, cached for 5 minutes:**
  - DMARC, asked of the domain's authoritative nameserver.
  - Resend domain status.
  - Stripe products and subscriptions.
  - DecodedSix's own Supabase.
- **Counters:** the map and the 8am digest now share one function, `core/outreach_counters.py`, so their numbers can't drift.
- **Writes:** step complete/undo, finish lap, reset lap, add note, and resolve/reopen. Who made each change comes from the session email, sent in the `X-Loop-Actor` header.
- **Hourly snapshot:** an in-process loop in mse-api writes to `mse_loop_status_history`. A database check stops it writing twice within 50 minutes, and each run is logged to `audit_log` as `loop-map`.

### Dashboard
- **Page:** `/dashboard/loop-map`, admin only.
- **Proxy:** `app/api/loop-map/[[...path]]` checks the admin role, then allows only the paths in the `lib/loop-map-paths.ts` allowlist. The snapshot and playbook endpoints are not exposed.
- **Components:** `components/loop-map/` holds the port. The CSS is scoped under `.lm`.
- **Kept from the reference:** sprite, walk and bob animations, speech bubble, reduced-motion handling and the two-click confirms.
- **Additions to the reference:**
  - An Unknown legend color.
  - A 4-week strip under each desk.
  - A weekly funnel for the outbound products.
  - A "where every loop is waiting" strip built from live data.
  - Data refreshes every 60 seconds.

## Verification
- **Writes against production rows** (ADA Title II, actor `claude-code-verification`):
  - complete and undo, finish lap, auto-lap when every step is done, and reset;
  - hole logged, then resolved and reopened;
  - a DELETE on a note returns 404.
  - All 15 test rows were removed afterwards.
- **Hourly job:** first run at 20:25 UTC wrote 46 rows.
- **Tests:** engine 1546 passed plus 26 new; dashboard vitest 31 passed.
- **Migration:** proven locally on pgserver first.
- **Staging:** mse-api's staging environment had disappeared. I recreated it with only mse-api, so a second n8n doesn't run the production crons. It shares the production database.

## Status at ship (production)
- **Consulting:**
  - Finding and qualifying work.
  - Waits on you at Find the Buyer (35 companies) and Approve (3 drafts).
  - Send is **blocked**: there is no DMARC record at `_dmarc.thdstack.com`.
- **Cloud Decoded:**
  - Lead run **blocked**: nothing completed since Oct 4.
  - Send is blocked on DMARC.
  - Sign-up is **blocked**: Resend shows the domain theclouddecoded.com as `failed`.
- **Small Portfolio Hub:**
  - Positioning v5 is waiting on you.
  - Search Console sync has written 0 rows.
  - Sign-ups are **UNKNOWN**, because mse-api has no credentials for SPH's database.
- **DecodedSix:**
  - Writing, approval, publishing and traffic are working.
  - Topics stalled on Sep 17.
  - Search Console is not connected.
  - Earnings are **UNKNOWN**.
- **ADA Title II and Bible apps:** mostly not built.

## Findings logged this session
- **8am LinkedIn Outreach job:**
  - Ran daily from Oct 6 to Oct 17, except **Oct 11, when it errored** (n8n #1054, summary endpoint 500). That day's digest wasn't sent.
  - Created one new sequence in the window: Metr, Oct 12.
  - Skip reasons are logged only at INFO, which production drops, so they aren't stored anywhere.
- **DNS** (authoritative nameservers):
  - `_dmarc.thdstack.com` and `_dmarc.theclouddecoded.com`: NXDOMAIN.
  - theclouddecoded.com: the Resend DKIM and `send` MX/TXT records are all missing.

## If this fails next time
- **A desk shows unknown:** its evidence text names the source that couldn't be read. Check mse-api's environment variables first: `DECODEDSIX_*`, `SPH_*`, `RESEND_API_KEY` and `STRIPE_SECRET_KEY`.
- **The 4-week strips stop filling:** look for `loop-map` rows in `audit_log`. Also confirm `LOOP_MAP_SNAPSHOT_DISABLED` is not set on production.
- **The tab returns 401:** check that the tenant middleware still exempts the `/marketing/loop-map` prefix.

## Open follow-ups
- Set `SPH_SUPABASE_URL` and `SPH_SUPABASE_SERVICE_KEY` on mse-api.
- Add `N8N_API_KEY` to mse-api.
- Persist the 8am skip reasons.
- Update the old staging ID in the engine's `docs/railway-start-command.md`.
- Add DMARC records, and fix theclouddecoded.com's Resend DNS records.
