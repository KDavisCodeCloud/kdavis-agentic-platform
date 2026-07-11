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
