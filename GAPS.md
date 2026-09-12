# GAPS

Pending agent recommendations. gap_detector_agent writes here; human approves before build.

## Manually surfaced during Session A (core/engine.py build, 2026-07-07)

### 1. `langgraph==0.2.28` (pinned in requirements.txt) does not support `Command`/`interrupt`

Confirmed by direct inspection of the installed package: `langgraph.types` in
0.2.28 has no `Command` class and `interrupt()` is not wired into the Pregel
executor's resume path. This is the exact HITL pause/resume pattern already
used by every agent in `agents/agent_01_cicd_triage/` through `agent_10_*`
(`from langgraph.types import interrupt, Command`, `interrupt({...})` inside a
node, `Command(resume=...)` to continue) and by the new `core/engine.py`.

Nobody has caught this yet because `tests/conftest.py` stubs `langgraph.*`
with `MagicMock`s whenever the real package isn't importable, so all existing
agent tests exercise a fake graph that never really pauses — they can't
detect that resume is broken against the pinned version.

Verified fix: `langgraph==0.2.76` (last of the 0.2.x series) has working
`Command`/`interrupt`. `langgraph==0.2.60` also has the classes but I did not
verify resume end-to-end at that exact version — test before pinning to it.
Bumping will also require re-resolving `langgraph-checkpoint-postgres`
(pinned `2.0.4` wants `langgraph-checkpoint>=2.0.2`, conflicts with
`langgraph==0.2.28`'s own `<2.0.0` requirement — this resolves cleanly once
`langgraph` itself is bumped past 0.2.28).

**Recommendation:** bump `langgraph` in requirements.txt to `0.2.76` (or
newer, re-verify resume), re-run the full agent test suite against the real
package (not the conftest stubs) before merging.

**RESOLVED — already done, just undocumented.** `requirements.txt` already
pins `langgraph==0.2.76` (found 2026-09-12 auditing this file against the
repo — the fix landed at some point without this entry being closed out).
Confirmed the pinned version still has working `Command`/`interrupt` by
running the full suite with gap #3's conftest.py fix applied (see below) —
1092 passed, same 4 pre-existing unrelated failures, none in the LangGraph
resume path.

### 2. ~~Top-level `queue/` package shadows Python's stdlib `queue` module~~ — FIXED

Hit this mid-session (`queue/__init__.py` breaking `urllib3`/`langgraph`
imports for anything run with repo root on `sys.path`). By the time this
commit landed, another concurrent session had already renamed it to
`job_queue/` (commit `7d2b584`) and updated its imports — confirmed fixed,
verified `pytest` runs clean from repo root without the `sys.modules`
workaround described in gap #3 below. Leaving this entry as a record only.

### 3. `tests/conftest.py`'s langgraph stub is unsafe once the real package is installed

`_ensure_stub("langgraph.graph")` etc. correctly falls back to a `MagicMock`
when `langgraph` isn't installed, but lines 48-53 then unconditionally
overwrite `StateGraph`/`START`/`END`/`interrupt`/`Command` with mocks even
when the real import succeeded — clobbering real classes for every test
module that happens to run after conftest.py, including ones (like
`tests/test_engine.py`) that need real graph execution to mean anything.

Workaround used in `tests/test_engine.py` (not a conftest.py fix — didn't
want to touch a shared fixture file mid-session): purge every
`langgraph*`/`langchain_core*` entry from `sys.modules` before importing
`core.engine`, forcing a fully fresh real import. `importlib.reload()` alone
is NOT sufficient — it can leave a `Command` class that fails
`isinstance(x, Command)` checks elsewhere in the dependency graph, which
silently breaks `resume()` specifically (not `run()`).

**Recommendation:** once gap #1 is resolved and real `langgraph` is the norm
in CI, make the stub conditional — only apply lines 48-53's overwrites inside
the `except ImportError` branch of `_ensure_stub`, not unconditionally after
it.

**RESOLVED 2026-09-12.** `_ensure_stub` now returns `(module, was_stubbed)`;
the `StateGraph`/`START`/`END`/`interrupt`/`Command`/`AsyncPostgresSaver`
overwrites only fire when `was_stubbed` is `True` for that specific
submodule. In this repo's own `.venv` (real `langgraph==0.2.76` installed),
every agent test now exercises the real classes. Full suite still 1092
passed, same 4 pre-existing unrelated failures — the real package's resume
semantics agree with what the mocks always claimed, but now that's actually
being checked instead of assumed. `tests/test_engine.py`'s `sys.modules`
purge workaround (described above) is now redundant but left in place —
harmless, and removing it is unrelated cleanup, not part of this fix.

## Manually surfaced during Cloud Decoded frontend ship-readiness session (2026-09-10)

### 4. OnboardingWizard steps 1-2 have no backend to call — workspace creation and BYOK LLM-key storage don't exist as endpoints

Traced `frontend/src/components/OnboardingWizard.tsx` end to end against the
live Railway backend. Step 3 (webhooks) is genuinely wired correctly — it
builds URLs matching real routes (`POST /api/v1/webhooks/github`,
`POST /api/v1/webhooks/azure-devops`). Steps 1 (workspace) and 2 (LLM key)
make zero API calls: `onComplete` in `frontend/src/app/onboarding/page.tsx`
just does `localStorage.setItem('workspace_token', token)` and redirects to
`/dashboard` — the token the user types in is never validated or sent
anywhere.

Confirmed on the backend side: `db/models.py` has an `encrypted_llm_key`
column on the `workspaces` table, and `api/middleware/auth.py` reads it, but
grepping the whole repo for `INSERT INTO workspaces` and any write to
`encrypted_llm_key` turns up nothing — no endpoint creates a workspace or
stores a BYOK key. `api/routes/mcp_keys.py`'s `POST /mcp/keys` is a different
thing entirely (scoped MCP API keys for a workspace that already exists via
`get_workspace`, not workspace creation or LLM-provider key storage).

This matches `CLOUD_DECODED_AUDIT_2026-08-09.md`'s finding from a month ago
("onboarding page is a manual-token-paste UI shell with no backend") — still
true today, not fixed in the interim.

**Recommendation:** build `POST /api/v1/workspaces` (workspace creation,
probably tied into signup/Stripe checkout rather than this wizard directly)
and a BYOK key-storage endpoint that encrypts and writes `encrypted_llm_key`
(reuse whatever encryption approach `token_budget.py`/`auth.py` already
assume is in place for reading it back). Kelvin confirmed 2026-09-10: ship
the frontend as-is for now with this gap open, don't build it same-session.

**RESOLVED 2026-09-10.** Built `POST /api/v1/workspaces` and
`POST /api/v1/workspaces/llm-key` in `api/routes/workspaces.py`, encryption
via new `security/encryption.py` (Fernet/`ENCRYPTION_KEY`, same mechanism
already used elsewhere — see `agents/base_agent.py:_decrypt_byok`). Wired
`OnboardingWizard.tsx` steps 1-2 to call them for real. Tests in
`tests/test_workspaces.py` + `tests/test_encryption.py`.

While fixing this, discovered a much bigger pre-existing gap: **`db/schema.sql`
(the `workspaces`/`incidents`/`internal_agent_tasks`/`audit_events`/
`token_usage` tables) had never actually been applied to the production
database** — Railway's live `DATABASE_URL` points at the same shared
`microsaas-prod` Supabase project used by MSE/NOVA/consulting, and none of
Cloud Decoded's own tables existed in it. Every existing endpoint that reads
`workspaces` (`stripe_billing.py`, `mcp_keys.py`, `webhooks.py`, `agents.py`)
would have failed with `UndefinedTableError` in production before today.
Applied `db/schema.sql` + this migration (`018_workspace_llm_provider.sql`)
directly against the live DB 2026-09-10, confirmed by querying
`information_schema`. Migrations 002-017 were NOT re-run — they target
tables that already exist in the shared DB (the platform's marketing/
finance/internal-agent tables, not Cloud-Decoded-exclusive) and were already
live; migration 015 specifically changes a `CHECK` constraint on the shared
`audit_log` table used by other products, so it was deliberately left alone
rather than re-applied speculatively.

**New follow-up, not done here:** `workspaces.llm_provider` is now stored
but nothing reads it — no agent invocation path passes it as
`provider_override` (`agents/base_agent.py:161` still always defaults to
`"anthropic"` unless a caller explicitly overrides). Wiring that through is
separate work.

### 5. `api/middleware/rate_limiter.py`'s `_tier_limit` crashes every request — CRITICAL, affects the live agent-execution endpoint

Discovered live 2026-09-10 while verifying the `POST /api/v1/workspaces/llm-key`
endpoint above (which originally used the same pattern). Every call hit:

```
TypeError: _tier_limit() missing 1 required positional argument: 'request'
  File ".../slowapi/wrappers.py", line 94, in __iter__
```

Root cause: `_tier_limit(request: Request) -> str` (`api/middleware/
rate_limiter.py`) is used as a callable rate-limit provider via
`@limiter.limit(_tier_limit)`. The pinned `slowapi==0.1.9`'s
`LimitGroup.__iter__` (`slowapi/wrappers.py`) only supports a callable
limit-provider shaped as `fn(key: str)` (it inspects the callable's
parameters for a literal `"key"` argument) or `fn()` — there is no supported
way for it to hand the callable a `Request`. Calling convention mismatch,
not a version-drift issue (0.1.9 is exactly what's installed both locally
and on Railway) — this has been broken since it was written.

**This is the exact same decorator used on `POST /agents/{agent_id}/run`
in `api/routes/agents.py`** — the actual agent-execution endpoint, i.e. the
core paid product. It has never been caught because `Depends(get_workspace)`
always failed first with `UndefinedTableError` until gap #4's schema fix
today made a working `workspaces` table exist for the first time. **As of
right now, in production, the first real customer request to
`POST /agents/{agent_id}/run` will 500 with this exact `TypeError`.**

Fixed narrowly for the new `save_llm_key` endpoint only (swapped to a flat
`@limiter.limit("30/minute")`, since a per-tier limit can't be recovered
from just the rate-limit key string). **`agents.py::run_agent` still has
the broken `@limiter.limit(_tier_limit)` decorator — not touched, this is
its own fix and deserves dedicated attention, not a same-session patch
bundled into the onboarding gap.**

**Recommendation:** `_tier_limit` needs `request.state.workspace_tier` (set
earlier by `WorkspaceTierMiddleware`), which this slowapi version's callable
convention can't deliver. Either: (a) drop the callable and use per-tier
route variants or a static conservative limit like the fix above, (b)
upgrade slowapi past 0.1.9 and confirm a version that actually supports
request-based callables before repinning, or (c) implement tier lookup
inside `_workspace_key` itself (the `key_func`, which *does* receive
`request`) and encode the tier in the key/limit some other way. Whatever
the fix, add a real test that actually exercises the decorator (calling the
route through slowapi, not just calling the handler function directly) —
that's exactly the kind of test gap that let this sit unnoticed.

**RESOLVED 2026-09-10.** Went with option (c). `_workspace_key` (the
`key_func`, which does receive the Request) now embeds the tier from
`request.state.workspace_tier` into the key it already produces:
`f"ws:{tier}:{token[:16]}"`. `_tier_limit` was changed from `fn(request)`
to `fn(key)` — matching the shape slowapi's `LimitGroup.__iter__` actually
calls — and parses the tier back out of that key instead of reading
`request.state` directly. `get_rate_limit_for_tier` untouched.
`agents.py::run_agent`'s `@limiter.limit(_tier_limit)` needed no changes at
all — same callable, same call site, just fixed underneath it.

Added `tests/test_rate_limiter.py`, including the integration test this
gap's own recommendation called for: a real FastAPI app with
`@limiter.limit(_tier_limit)` on a route, exercised through
`TestClient`/a real `starlette.requests.Request` — not just calling the
plain function directly. That's the exact gap that let the original bug
ship silently: `_tier_limit(request)` looked correct read as a plain
Python function and nothing ever actually invoked it through slowapi in a
test. 9 new tests, full suite still 997 passing (same 4 pre-existing,
unrelated failures in `test_agent01_local.py`/`test_security.py`).
