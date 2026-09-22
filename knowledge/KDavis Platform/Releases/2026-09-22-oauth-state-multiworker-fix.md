# Release: OAuth State Store — Multi-Worker Bug Fix
Date: 2026-09-22
Products: Cloud Decoded (internal LinkedIn/Canva connect + customer-facing LinkedIn/X connect)
Migrations: 053, 054

## What was reported
Kelvin clicked the LinkedIn reconnect link (from the token-expiry fix
earlier the same day) and got "expired oauth state."

## Root cause
`api/routes/internal_marketing.py`'s `_oauth_state_store` /
`_canva_pkce_store` were plain in-memory Python dicts — the code's own
comment admitted "fine for a single-process, single-owner manual connect
flow." Production runs `uvicorn --workers 4` (Procfile/railway.json): 4
separate OS processes, each with its own memory. The request that mints
a state token lands on one random worker; the OAuth provider's callback
(a separate HTTP request, seconds to minutes later) lands on another
worker with a ~75% chance — a dict on a different process never saw the
state. Not an intermittent timing bug — fails on most tries by
construction, regardless of how fast the user completes the login
screen.

**Found a second copy of the identical bug while investigating**:
`api/routes/content.py`'s customer-facing LinkedIn/X connect flow
(`workspace_social_connections`) has the exact same in-memory dict
pattern, with its own comment admitting the gap ("In production: move to
Redis with TTL" — never done) and, worse, no TTL enforcement at all.
This is paying-customer-facing, not just the internal owner flow — likely
uncredited support friction for anyone who's tried to connect their own
LinkedIn/X account.

## Fix
- Migration 053: `internal_oauth_state` table (owner-only LinkedIn/Canva).
- Migration 054: `workspace_oauth_state` table (customer-facing
  LinkedIn/X), plus added the TTL enforcement that was missing entirely.
- Both call sites now `DELETE ... RETURNING` for atomic single-use
  consumption (a replayed callback fails exactly like an unknown state),
  backed by the same shared Postgres every worker already connects to
  for everything else cross-process in this app — consistent with this
  codebase's own convention (advisory locks, notification queues, etc.),
  not a new Redis dependency despite `redis` being a transitive package
  already installed.

## Outcome
8 new tests, full suite 2150 passed (was 2142), same 4 pre-existing
unrelated failures, zero regressions. Deployed to Railway, `/health`
verified live, both new tables confirmed present via direct Supabase
query.

## If this fails next time
- If "Invalid or expired OAuth state" recurs after this fix, check
  whether `internal_oauth_state`/`workspace_oauth_state` rows are
  actually being written (a DB connectivity issue would surface this
  way) before assuming the multi-worker theory is wrong again.
- The customer-facing content.py fix is untested against a real
  workspace connecting LinkedIn/X end-to-end this session — only unit
  tests on the store/pop helpers. Worth a real click-through next time
  someone's touching that flow.
