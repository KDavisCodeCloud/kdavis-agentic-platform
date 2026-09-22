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

## Manually surfaced during item 5 (Azure DevOps connectivity, 2026-09-14)

### 6. `ConnectionsPanel.tsx`'s GitHub card still submits a PAT that the backend retired -- RESOLVED (Phase 3)

Found while adding the Azure DevOps card to this same file, not fixed here
(out of scope for item 5, and a UI-only change deserves its own session).
`PATCH /workspace/credentials/github` was retired to a `410` in the item 4
GitHub App migration (`api/routes/workspace_credentials.py`'s
`connect_github` now always raises, pointing callers at
`GET /workspace/credentials/github-app/install-url` instead) -- but
`ConnectionsPanel.tsx`'s GitHub `SectionCard` still renders a PAT input
wired to `connectGithubPat`/`POST` against that same retired route. Any
real customer who hasn't already connected via a legacy PAT gets a 410
error with no visible path to the actual install flow. Needs: swap the
GitHub card's PAT form for a "Install the Cloud Decoded GitHub App" button
that calls `GET .../github-app/install-url` and redirects, mirroring the
callback handling `github_app_install_callback` already does server-side.

While in the same file: also noticed (and fixed, since it's the exact
response object item 5 was already editing) that `get_connections_status`
computed `github_connected` from `github_pat_verified_at` alone -- a
workspace that connected via the App (no PAT at all) would have shown as
"Not connected" despite being fully connected. Now
`bool(github_pat_verified_at) or bool(github_app_installation_id)`.

### 7. Agents 04 (Migration) & 10 (Dependency Patch) never received a workspace's real GitHub credential -- CRITICAL, two paid tiers

**RESOLVED same session it was found (Phase 1 of the connectivity gap
roadmap, 2026-09-14).** Found while inventorying item 5's blast radius.

`agents/agent_04_migration/workflow.py`'s and
`agents/agent_10_dependency_patch/workflow.py`'s `__init__` used to accept
only `(db_conn, workspace_id, checkpointer)` -- no credential kwargs at
all, unlike agents 01/05/06/08. `api/routes/webhooks.py`'s `_run_migration`
and `_run_dependency_patch` instantiated both workflows with zero
credentials, never calling `build_agent_credentials()`. Worse: **the actual
write action (`create_migration_pr`/`create_patch_pr`) runs on *resume*,
after HITL approval** -- `api/routes/incidents.py`'s `_resume()` -- and
`agent_04_migration`/`agent_10_dependency_patch` were also missing from
`_CREDENTIALED_AGENTS` there, so even a caller who fixed only the
webhooks.py side would still have hit the same gap on approval. Both call
sites needed the fix, not just one.

`MigrationTools`/`DependencyPatchTools` filled the gap with
`os.environ.get("GITHUB_TOKEN", "")` -- the exact env-var-fallback pattern
`core/workspace_credentials.py` deliberately removed everywhere else. Every
real Growth+ customer's migration or dependency-patch PR was either created
using **the platform's own token** against whatever repos it could reach
(a cross-tenant credential leak, if that env var was ever set to anything
real) or failed outright (if unset). Live since these two agents were
built -- not introduced by any change this session.

Fixed: both workflow constructors now accept the same uniform
`github_token`/`aws_session`/`azure_access_token`/`azure_devops_token`
shape every other credentialed agent's constructor accepts (only
`github_token` is actually used by either agent's tools -- the rest are
accepted-and-ignored for uniform `**creds` spreading, matching agents
05/06/08's own convention). `_run_migration`/`_run_dependency_patch` now
call `build_agent_credentials()`. `_CREDENTIALED_AGENTS` in
`api/routes/incidents.py` now includes both agent IDs. The
`os.environ.get("GITHUB_TOKEN", "")` fallback is removed from both
`tools.py` files -- no env-var fallback, matching `CICDTools`/`DriftTools`.

8 new tests: `tests/test_agent04.py`/`test_agent10.py` (constructor threads
`github_token` through, no env fallback even with `GITHUB_TOKEN` set in the
environment), `tests/test_incidents.py` (resume passes the real per-
workspace token, and `None` when unconfigured -- not a borrowed platform
token), `tests/test_webhooks.py` (initial run calls
`build_agent_credentials` and spreads the result). Full suite: 1248
passing (was 1240; same 5 pre-existing, unrelated failures in
`test_agent01_local.py`/`test_internal_agents.py`/`test_security.py`).

**Not done here, tracked separately (Phase 2 of the connectivity roadmap):**
`MigrationTools.create_migration_pr`/`DependencyPatchTools.create_patch_pr`
are still their own hand-rolled direct GitHub REST implementations, a third
copy of the same 5-step flow `core/repo_tools.py`'s `GitHubRepoTools`
already centralizes (alongside `agent_08_drift_detection`'s
`create_drift_pr`). Neither can target Azure DevOps yet despite this
session's `AzureDevOpsRepoTools` existing. Phase 1 only closed the
credential-safety gap; Phase 2 is what makes the `RepoTools` abstraction
(and Azure DevOps support) actually load-bearing for these two agents.

**RESOLVED (Phase 2, same session, 2026-09-14).** `MigrationTools.create_migration_pr`,
`DriftTools.create_drift_pr`, and `DependencyPatchTools.create_patch_pr` no
longer have their own direct GitHub REST implementations -- all three now
delegate branch-creation/commit/PR-open to `core/repo_tools.py` via a new
provider-selection factory, `get_repo_tools(github_token, azure_devops_token,
azure_devops_org) -> RepoTools` (GitHub takes priority when both happen to
be configured; raises the new `NoRepoCredentialError` when neither is).
This is the same real, already-working logic (same branch-naming, same
commit messages, same return shapes -- `MigrationTools` keeps its
historical `"pr_opened"` status string, the other two keep `"pr_created"`),
just reshaped behind the interface instead of three copies of it.

`azure_devops_org` is now also part of `build_agent_credentials()`'s
returned dict (a new `workspaces.azure_devops_org` SELECT column) --
Azure DevOps needs org+PAT together to address a repo, unlike GitHub where
the token alone is enough. Every workflow that receives `**creds` from
`build_agent_credentials()` (agents 01/04/05/06/08/10) had to accept this
new key too, even where unused, to avoid a `TypeError` from the uniform
spread -- same discipline as the other accept-and-ignore creds.

Issue/work-item creation (`create_github_issue`, `create_drift_issue`,
`create_vulnerability_issue`) is deliberately **not** touched -- `RepoTools`
has no issue-creation operation (Azure DevOps "work items" are a different,
larger API shape than GitHub issues), and none of this session's plan
called for adding one. Those three methods stay direct, GitHub-only REST
calls.

18 new/rewritten tests: `tests/test_repo_tools.py` (`get_repo_tools`
provider selection, 5 tests), `tests/test_agent04.py`/`test_agent08.py`/
`test_agent10.py` (each `create_*_pr` rewritten to assert delegation to a
mocked `RepoTools` instance instead of asserting raw httpx call sequences
-- that lower-level behavior is `test_repo_tools.py`'s job now, not
duplicated here -- plus new `azure_devops_org`/`azure_devops_token`
constructor-wiring tests for all three workflows). Full suite: 1256
passing (was 1248; same 5 pre-existing, unrelated failures).

### 8. Phase 3 -- GitHub Connections card fixed, plus a second dead-end found in the same flow

**RESOLVED (Phase 3, same session, 2026-09-14).** `ConnectionsPanel.tsx`'s
GitHub card no longer renders a PAT input. It now calls
`GET /workspace/credentials/github-app/install-url` and navigates the
browser there directly (`window.location.href`), matching the item 4 App
flow. `connectGithubPat`/`mockConnectGithub` (frontend) were dead code
after the swap -- deleted rather than left orphaned, since nothing else
referenced them.

**Second bug found while wiring this up, in the same flow:**
`github_app_install_callback` (the route GitHub's own `setup_url` redirect
lands the customer's real browser on after they click "Install") returned
a bare JSON dict, `{"status": "installed"}`. That's fine for an API call a
frontend `fetch`s and reads a body from -- it is not fine for an actual
browser navigation, which would have shown the customer a blank JSON page
with no way back into the dashboard. Fixed to a real `RedirectResponse` to
`{FRONTEND_URL}/dashboard?connected=github`, matching the exact convention
`api/routes/content.py`'s LinkedIn/X OAuth callbacks already use.

Not done: the dashboard doesn't read `?connected=github` (or LinkedIn/X's
existing `?connected=linkedin`/`?connected=x`, which have the same
non-wired gap already) to auto-select the Connections tab -- landing back
on the dashboard root instead of directly on the tab that shows the new
"Connected" status. Minor, consistent with how the two pre-existing
integrations already behave, not introduced here -- left as its own
small follow-up rather than building new tab-deep-linking behavior nobody
asked for as a side effect of this fix.

3 tests updated/added (`tests/test_workspace_credentials_routes.py`'s
callback test now asserts a redirect, not a JSON body). Full frontend
`next build` clean; full backend suite still 1256 passing.

### 9. Phase 4 -- real per-workspace Kubernetes credentials, plus a critical Agent 02 gap found along the way

**RESOLVED (Phase 4, same session, 2026-09-14).** Replaced the global
`KUBECONFIG_YAML` + `K8S_CONTEXT_AWS`/`K8S_CONTEXT_AZURE` stopgap with real
per-workspace cluster credentials (migration 025:
`k8s_api_url`/`k8s_token_encrypted`/`k8s_ca_cert_encrypted`/`k8s_verified_at`)
and a new `PATCH /workspace/credentials/k8s` verify-then-store route
(`core.workspace_credentials.verify_k8s_connection`, an authenticated read
against the cluster's `/api` discovery endpoint).

**Second critical gap found while scoping this, same class as GAPS.md #7**:
Agent 02 (K8s Alert Fatigue & Remediation -- available at every tier,
including Starter, unlike agents 04/10 which are Growth+) had *never*
received a per-workspace credential of any kind. `K8sAlertWorkflow.__init__`
took zero credential params; `K8sTools` fell back to
`os.environ["K8S_API_URL"]`/`["K8S_TOKEN"]`/`["GITHUB_TOKEN"]` for
literally every real customer, on both the initial run (`webhooks.py`'s
`_run_k8s_alert_triage`) and the resume path where the actual K8s API
writes and GitOps PR execute (`incidents.py`'s `_resume()` -- agent_02
wasn't even in `_CREDENTIALED_AGENTS`). Same failure mode as #7: broken
outright if the env vars were unset, or a cross-tenant leak if they held
anything real. Fixed identically -- `build_agent_credentials()`/
`build_k8s_credentials()` wired into both call sites, `agent_02_k8s_alert`
added to `_CREDENTIALED_AGENTS`, env-var fallback removed from `K8sTools`.

While already touching `K8sTools`, also routed `create_gitops_pr` through
`core.repo_tools` (the same duplicate-GitHub-implementation treatment
Phase 2 gave agents 04/08/10) and added `k8s_ca_cert` support to its REST
calls (`_verify` property, a per-instance temp CA file) -- without it,
Agent 02 could authenticate but never actually pass TLS verification
against a private-CA cluster (EKS/AKS typical), while `verify_k8s_connection`
at connect-time would have succeeded with the same cert. Never silently
skip TLS verification, so this had to be consistent both places.

Agent 08 (`DriftTools`, kubectl subprocess-based, not REST) keeps its
`k8s_context`/global-kubeconfig fallback for workspaces that haven't
connected their own cluster yet -- `_cluster_flag` (renamed from
`_context_flag`) now prefers a per-workspace kubeconfig
(`core.workspace_credentials.build_kubeconfig`, written to a lazily-created
temp file, `--kubeconfig`) over `--context` when real credentials are
present. `build_kubeconfig` never sets `insecure-skip-tls-verify` either --
omits CA data entirely when none is configured, so kubectl falls back to
the system trust store, same discipline as the REST path.

24 new/updated tests across `tests/test_workspace_credentials.py`
(`verify_k8s_connection`, `build_kubeconfig`, `build_k8s_credentials`),
`tests/test_agent02.py` (credential wiring, `create_gitops_pr` delegation,
the `_verify` property), `tests/test_agent08.py` (`_cluster_flag`
priority), `tests/test_incidents.py`/`test_webhooks.py` (both call sites
for both agents), `tests/test_workspace_credentials_routes.py` (the new
connect route), `tests/test_auth.py` (pinned SQL shape). Full frontend
`next build` clean (new Kubernetes connections card). Full backend suite:
1280 passing (was 1256), same 5 pre-existing unrelated failures.

### 10. Phase 5 -- `workspaces.llm_provider`/BYOK key were never read by any agent, not just the provider preference

**RESOLVED (Phase 5, same session, 2026-09-14).** Scoped in the roadmap as
"wire `llm_provider` into agent LLM routing" -- turned out both halves of
BYOK were dead. `POST /workspaces/llm-key` stores `encrypted_llm_key` +
`llm_provider` at onboarding; `agents/base_agent.py`'s `call_llm()` already
had full `provider_override`/`byok_encrypted_key` plumbing (including a
thread-safe `_byok_env_override` context manager) -- but **every single
diagnose call across all 10 agents left both params at their defaults**,
so every workspace, regardless of what it configured, always ran on the
platform's own Anthropic key. `byok_encrypted_key` was accepted as a
parameter on every workflow's `run()` method but never once read after
that -- not stored, not threaded into the diagnose node, not passed to
`call_llm()`. A fully-built feature with no wire connecting it to anything.

Fixed by making `BaseAgent.__init__` accept `llm_provider`/
`byok_encrypted_key` and store them as instance defaults that `call_llm()`
falls back to when a caller doesn't explicitly override -- rather than
editing every one of the 10 diagnose nodes individually, each of the 10
workflow constructors (already being threaded with credentials all session)
now also accepts and forwards these two to `super().__init__()`. `llm_provider`
added to `workspaces` SELECT queries in both `api/middleware/auth.py` (the
manual-trigger path, `api/routes/agents.py`) and `api/routes/webhooks.py`
(both the per-workspace-token and GitHub-App-installation lookup) so
`workspace.get("llm_provider")` resolves on every dispatch path; all 10
`agent = WorkflowClass(...)` constructor call sites in `webhooks.py` now
pass both. Resume doesn't need this -- confirmed no `_execute_node` across
any of the 10 agents calls `call_llm` (diagnosis only happens once, in
`run()`, before the HITL gate).

**Scripting error caught before it shipped**: an initial sed-free Python
rewrite of all 10 constructors' closing `):` accidentally deleted it in 7
of them (the two new params merged into `super().__init__(...)` as if it
were a 3rd parameter, no syntax boundary between signature and body) --
`py_compile` caught all 7 immediately; fixed with a second scripted pass
restoring the closing paren before running anything else. Full suite run
immediately after confirmed zero regressions -- worth noting only because
it's a real example of "verify programmatic edits before trusting them,"
not because it shipped.

16 new tests: `tests/test_agent01.py` (`call_llm`'s three-tier fallback --
explicit override > workspace default > platform default; BYOK decryption
invoked when only the workspace-level key is set), `tests/test_agent04.py`
(constructor threads both through to `self._llm_provider`/
`self._byok_encrypted_key`), `tests/test_webhooks.py` (constructor call
site receives them from the real `workspace` dict), `tests/test_auth.py`
(pinned SELECT shape). The 10 `webhooks.py` call sites were also reformatted
to multi-line (168-213 char single lines afterward) for readability.
Full backend suite: 1286 passing (was 1280), same 5 pre-existing unrelated
failures.

### 11. Phase 6 -- Enterprise MCP OAuth 2.1 provisioning built; TLS RESOLVED 2026-09-15 (was externally blocked)

**PARTIALLY RESOLVED (Phase 6, same session, 2026-09-14).** Two halves,
one closed, one genuinely can't be from inside a coding session:

**Closed**: `mcp/auth/oauth.py`'s Supabase JWT validation was fully built
and correct (workspace_id/workspace_tier/mcp_scopes read from
`app_metadata`) but nothing in the repo could ever get a real customer
INTO that state -- the only existing Supabase Auth admin-invite code
(`agents/internal/onboarding_agent.py`) is for THD's own internal team
dashboard, a different product/trust relationship entirely. Added
`POST /internal/workspaces/{id}/mcp-invite` to `api/routes/internal_workspaces.py`
(admin-gated via the same `get_internal_user` every other admin lever in
that file already uses) -- a two-step Supabase Admin API call
(`invite_user_by_email` then `update_user_by_id`), not one, because
`invite_user_by_email`'s `options.data` only sets user-editable
`user_metadata`; the `app_metadata` `validate_oauth_token()` actually
trusts can only be set via `update_user_by_id`. Decision (Kelvin,
2026-09-14): admin-provisioned, not self-serve -- Enterprise sells on a
30-90 day B2B cycle to VP-Eng buyers, provisioning happens after a deal
closes. No frontend UI built for this (out of scope for what was asked --
Kelvin can call it directly until/unless a dashboard button is wanted;
`/dashboard/customers` referenced in earlier audit notes doesn't appear to
exist as an actual route in this frontend as of this session, so there
was no natural existing page to bolt a button onto anyway).

**RESOLVED 2026-09-15**: root cause found and fixed. `mcp.theclouddecoded.com`'s
TLS certificate was stuck at `CERTIFICATE_STATUS_TYPE_VALIDATING_OWNERSHIP`
indefinitely -- not "still provisioning," genuinely wedged: `railway domain
certificate retry` refused to run ("only available after certificate
issuance fails," and this domain had never reached a `FAILED` state to
retry from). Deleting and re-adding the custom domain in Railway
(`railway domain delete` / `railway domain mcp.theclouddecoded.com --port
8001`) surfaced the actual cause -- the domain had been created before
Railway required a `_railway-verify.mcp` TXT ownership record, so it had
literally no path to ever complete validation with only the old CNAME in
place. The re-created domain also came with a new CNAME target
(`z7trcyh4.up.railway.app`, replacing the stale `y11fpv8e.up.railway.app`).
Updated both records directly via the Namecheap API (Kelvin supplied an
API key + account username; confirmed this session's IP was already
whitelisted) -- fetched the full existing host-record set first
(`namecheap.domains.dns.getHosts`, only 3 records: `@`/`www` A records
plus the stale `mcp` CNAME, `EmailType=FWD`), then resubmitted the
complete set via `setHosts` with the 2 unrelated records preserved
byte-for-byte, the CNAME updated, and the new TXT record added --
`setHosts` replaces the entire zone, so touching only the intended
records required capturing the full state first, not a partial/additive
call. `EmailType=FWD` passed through explicitly so domain email
forwarding wasn't silently reset. Propagation confirmed directly (Google
and Cloudflare resolvers both correct within ~2 minutes; the live served
certificate's CN switched from Railway's generic `*.up.railway.app`
wildcard to a real Let's Encrypt cert for `mcp.theclouddecoded.com`
within ~4 minutes of the DNS write). Railway's `domain-status` now reports
`CERTIFICATE_STATUS_TYPE_VALID` / `verified: true`; `curl
https://mcp.theclouddecoded.com/health` returns a clean `200`. The final
live SSE MCP tool-call verification (queued since the 2026-09-12 audit)
and an end-to-end test of the OAuth invite flow built above are both
unblocked now, not yet separately exercised in this pass.

10 new tests in `tests/test_internal_workspaces.py` (invite + app_metadata
linking, read-only-scope request, unknown-scope 400, missing-workspace 404,
unconfigured-Supabase 500, invite-failure 502, app_metadata-link-failure
502 with the orphaned-user id surfaced in the error for manual recovery).
Full backend suite: 1293 passing (was 1286), same 5 pre-existing unrelated
failures.

### 12. Phase 7 doc reconciliation + Phases 8-9 GTM content (Kelvin: "draft it all now")

**DONE (same session, 2026-09-14).** `CloudDecoded-Build-Order.md`
reconciled: corrected the MCP TLS claim, corrected a stale claim that a
`/dashboard/customers` admin UI existed (it doesn't — zero frontend code
calls any `/internal/workspaces/*` route; the backend levers are real and
tested but curl-only today), and summarized the whole connectivity build
sequence with GAPS.md cross-references.

Priority 2 (og:image, Features, 10-problems AEO, Comparison, Security)
and Priority 3 (setup guide, agent reference, workflow how-tos, Loom
script, security questionnaire draft, DPA outline) both drafted in full.
Real bug found and fixed while building the og:image: `page.tsx`'s
metadata referenced `/og-image.png`, a file that never existed anywhere
in this repo (no `public/` directory at all) — the homepage's social
share image has been silently broken since the landing page shipped.
Replaced with `app/opengraph-image.tsx` (Next.js's dynamic `ImageResponse`
file convention — generated from the real design tokens, not a static
asset that can drift from them).

Deliberate scope boundaries, not oversights: the Comparison page sticks
to architecture/positioning claims about Microsoft Copilot and AWS
AgentCore rather than specific technical claims about either that
couldn't be verified; the DPA file is explicitly an outline for a real
attorney conversation, not usable contract language, and says so
repeatedly; the security questionnaire response doc marks its
not-yet-confirmed fields (data residency, current sub-processor list,
real incident-response SLA) rather than inventing specifics. The
Features page shows all 10 real agents against the homepage's own
narrower "5 shipping, more in private beta" framing — flagged as a
positioning inconsistency worth a real decision, not silently
reconciled by editing the live homepage.

Full frontend `next build`: clean, 14 routes, zero warnings. Backend
suite unaffected by this phase (docs/frontend only): still 1293 passing.

### 13. Operational readiness fixes (Kelvin: "continue with what still needs to be built") — 2026-09-14

Follow-up to a full operational-readiness assessment (not the engineering
quality — whether the product can onboard/manage/offboard a real paying
customer without manual intervention). Full findings logged in
`knowledge/operator/architecture-decisions/2026-09-14-connectivity-roadmap-and-operational-readiness.md`.

**DONE this pass:**
- `workspaces.contact_email` (migration 026) — required + validated at
  signup. Root-cause fix: nothing in Cloud Decoded's own code could send
  a welcome email or an Enterprise MCP-invite alert without an address to
  send to, and there was no way to identify a customer without going to
  Stripe directly.
- Post-checkout flow: `CheckoutSuccessGate` now redirects to
  `/dashboard?tab=connections&welcome=1` instead of a bare dashboard —
  there was previously no guided path from "just paid" to "has a working
  connected workspace" at all.
- Settings gear icon repointed from `/onboarding` (the stale
  `OnboardingWizard`, which independently creates a NEW unpaid workspace
  if reached from an already-logged-in session) to the Connections tab.
  `OnboardingWizard.tsx` itself is left in place but is now fully
  orphaned — nothing links to it.
- LLM key management got a real home: a new "LLM Key" card in
  `ConnectionsPanel` calling the existing `POST /workspaces/llm-key` —
  previously the *only* place to set/update it was the broken wizard.
- Legacy-PAT migration nudge: `GET /workspace/credentials/status` now
  returns `github_via_legacy_pat`; `ConnectionsPanel`'s GitHub card shows
  an amber "migrate to the GitHub App" banner when true. Closes the
  "legacy PAT workspaces have no prompted migration" gap logged
  previously in this file.
- Real data-deletion path: `POST /internal/workspaces/{id}/purge-data`
  (migration 027) — nulls every credential + PII column, refuses to run
  against a live (non-canceled/suspended) subscription, requires the
  caller to type the exact `company_name` as confirmation. Closes the
  GDPR/CCPA gap `docs/customer/dpa-outline.md` and
  `security-questionnaire-response.md` both flagged as unconfirmed.
- Click-through ToS acceptance: `workspaces.tos_accepted_at` (migration
  028), `POST /workspaces` now requires `tos_accepted: true`. Real
  `/terms` and `/privacy` pages now exist (previously: zero pages, and
  the signup checkbox's state was collected client-side and silently
  discarded — never sent to the backend at all). Linked from the signup
  checkbox and every marketing page's footer.
- Customer-lifecycle SOPs written: `knowledge/sops/customer-ops/` —
  onboarding, offboarding (incl. the new purge-data flow), credential
  rotation, Enterprise MCP invite. Previously zero SOPs existed for any
  Cloud Decoded customer-lifecycle operation.

Tests: 24 new/updated across `test_workspace_credentials_routes.py`,
`test_internal_workspaces.py`, `test_workspaces.py`. Full suite: 1305
passing (was 1293), same 4-5 pre-existing unrelated failures (environment
gaps in this dev sandbox specifically — missing `boto3`/`python-jose`
initially, a `libpq`-dependent test file, none of which are code
regressions; confirmed by installing the two pip-installable ones and
re-running clean). Frontend `next build`: clean, 18 routes.

**Still open, not built this pass:**
- No self-serve "delete my data" button — `purge-data` exists but is
  admin-only/curl-only today, same shape as the other `/internal/workspaces/*`
  levers.
- No per-connector "disconnect" endpoint for an active customer who wants
  to remove just one credential without a full purge — noted in
  `credential-rotation.md`.

**CLOSED same day (2026-09-14, follow-up pass):**
- Welcome/confirmation email + Enterprise MCP tier-change alert — Kelvin
  provided a Resend API key (set as `RESEND_API_KEY` on the Railway
  service, never committed to code). `core/email.py` added:
  `_handle_checkout_completed` (stripe_billing.py) now sends a welcome
  email; `set_workspace_tier` (internal_workspaces.py) now alerts
  `OWNER_ALERT_EMAIL` the moment a workspace's tier actually transitions
  to `enterprise` (not on every PATCH — only a real transition). Both
  call sites treat a send failure as non-fatal (log + continue), matching
  the "a broken email provider must never break checkout or a tier
  change" discipline stated in `core/email.py`'s own docstring. 21 new
  tests (`tests/test_email.py` + additions to
  `tests/test_internal_workspaces.py`/`tests/test_stripe_billing.py`).
  Full suite: 1320 passing.
- GitHub App "the-cloud-decoded" — Kelvin confirmed it's now public.
  Live-verified: `https://github.com/apps/the-cloud-decoded` returns 200.
  Real customers can now install it.

### 14. IaC deploy-failure diagnosis + live resource monitoring, domain-complete (2026-09-15)

Three-phase build (plan mode, `Agent` tool not used — direct implementation)
closing the gap between "Cloud Decoded triages CI/CD pipeline failures"
and "Cloud Decoded surfaces IAM/Networking/Storage/Compute problems at
every stage: deploy time, config drift, and live runtime alerts." Full
detail: `knowledge/operator/architecture-decisions/` entry for this date.

**Phase A — Agent 01 diagnosis prompt** reorganized into four domain
sections (IAM/RBAC/Policy, Networking, Storage, Compute), each with AWS +
Azure ARM/Bicep/Terraform/CloudFormation deploy-failure categories and
cross-resource auth failures. New cross-cutting rule: options must be
domain-aware, never generic; credential-exposure/unusual-auth findings
get investigation steps only, never an auto-proposed fix.

**Phase B — Agent 08 drift detection** documented across the same four
domains (its diff engine was already domain-agnostic, needed no code
changes for most of it). One new capability: `fetch_app_service_state()`
(Azure ARM + Kudu VFS APIs) plus a `live_fetch` payload block in
`_ingest_node`, turning "App Service missing an uploaded file" or
"app settings contain invalid JSON" into normal drift items instead of
requiring the caller to fetch live state themselves.

**Phase C — new Agent 11 (Cloud Resource Health Monitoring)** — genuinely
new agent + new webhook (`/resource-health-alert`), reusing
`aks_alert_webhook`'s proven Azure Monitor Common Alert Schema parsing
for Azure, adding AWS CloudWatch Alarm → SNS handling
(`core/aws_sns.py`: subscription-confirmation handshake + real RSA
signature verification, tested against a self-signed cert generated at
test time, not just mocked). No live cloud-mutation API calls built —
every option is a PR proposal or an investigation issue, gated by HITL
same as everything else in this platform.

**Real bug caught and fixed along the way:** `core/compliance.py`'s
`TIER_LIMITS` gates purely on the numeric position extracted from
`agent_id` (`_extract_agent_number`). Adding Agent 11 without bumping
Growth's `max_agents` from 10 to 11 would have silently made it
Enterprise-only by numbering coincidence, not a deliberate pricing
decision — same issue existed a second time in `api/routes/agents.py`'s
own separate, duplicate tier-limit dict (which also capped Enterprise at
exactly 10, unlike `core/compliance.py`'s `-1`/unlimited). Both fixed;
`agents.py`'s `valid_agents` agent-id-prefix check and `GET /agents`'s
agent listing were also missing Agent 11 entirely and would have 400'd
or hidden it. `core/compliance.py` had zero test coverage before this —
added `tests/test_compliance.py`.

**Not done, flagged not silently changed:** marketing copy
(`frontend/src/app/features/page.tsx`, `problems/page.tsx`) still says
"10 agents" — whether/how to publicly announce Agent 11 is a GTM
decision, not something to fold into a backend build.

**Verification status:** Phase A/B mechanically verified (sanitizer/
diagnose pass-through, live App Service fetch logic unit-tested). Phase
C's SNS signature verification is genuinely cryptographically tested
(real keypair, real sign/verify round trip) but the subscription-
confirmation handshake and Azure Action Group registration have NOT been
live-verified against real AWS/Azure infrastructure — same "needs a real
round trip" caveat the original plan called out before any code was written.

100+ new tests across `tests/test_compliance.py`, `tests/test_aws_sns.py`,
`tests/test_agent11.py`, plus additions to `tests/test_agent01_local.py`,
`tests/test_agent08.py`, `tests/test_webhooks.py`. Full suite: 1388
passing (was 1320 at the start of this build), same 4 pre-existing
unrelated failures, zero regressions.

### 15. CRITICAL — migrations 024–028 were never applied to production; real customer signups were broken — RESOLVED both repos (2026-09-15/2026-09-16)

Found while live-testing Agent 11's new webhook route: a `500` instead of
the expected `403` traced to `asyncpg.exceptions.UndefinedColumnError:
column "encrypted_azure_devops_webhook_secret" does not exist`. Direct
read-only query against the live `workspaces` table (via the
`DATABASE_URL` already present on the Railway service) confirmed **none**
of migrations 024 (Azure DevOps credentials) through 028 (ToS acceptance)
had ever been applied to production — despite all five being committed,
pushed, and deployed earlier in this same session.

**Root cause: there is no migration runner anywhere in the deploy
pipeline.** `api/main.py` has no startup migration step, and no CI/CD
workflow applies `db/migrations/*.sql` on deploy — these files are
committed as documentation of schema intent but nothing ever actually
runs them against the live database. This is a systemic gap, not a
one-off mistake: any future migration will have the same problem unless
this is fixed at the process level (see "still open" below).

**Real, active impact confirmed:** `POST /workspaces`'s `INSERT`
statement references `contact_email` and `tos_accepted_at` — both
missing — meaning every real customer signup attempt failed with a `500`
from the moment the contact-email-capture commit deployed earlier this
session until this fix. Azure DevOps and Kubernetes credential
connections were also broken (their columns missing since migration 024/
025 shipped, days earlier), and the data-purge endpoint (`027`) would
have failed the moment anyone tried it.

**Fix applied (Kelvin approved after being shown the exact scope and
confirming all five migrations are pure `ADD COLUMN IF NOT EXISTS`, no
drops, no data risk):** connected directly to the production Supabase
Postgres instance and applied all five migration files in one
transaction. Verified via `information_schema.columns` that all expected
columns now exist, then live-verified the actual previously-broken flow:
`POST /workspaces` with a full valid payload now returns `201` with a
real workspace token (was `500`), and the resource-health-alert webhook
now returns the correct `403` for an invalid token (was `500`). The
verification workspace created during this test was deleted immediately
after confirming success — production `workspaces` table has no leftover
test data from this.

**RESOLVED, both halves, though this repo's own half went undocumented
for a day (same pattern as gap #1 in this file).** `db/migrate.py` was
actually built the very next day (2026-09-15) — a real
`schema_migrations` tracking table + `pg_advisory_xact_lock`, wired into
`api/main.py`'s lifespan, fails closed on any error. Confirmed today
(2026-09-16) it's genuinely wired in and caught up: 39 migration files on
disk, 39 rows in `schema_migrations`, zero drift. This entry just never
got its "RESOLVED" line written at the time — closing that out now.

**The other half of this gap — kdavis-microsaas-engine had no
equivalent at all — was still open until today (2026-09-16) and bit us
twice in this session** (`20260914221640_icp_selling_stage.sql` and
`20260916000045_consulting_infra_icp.sql` both sat committed and
deployed without ever running against production, caught only by a
direct `UndefinedColumnError` while applying a third migration by hand).
Fixed: that repo now has `core/migrate.py`, the same pattern adapted for
two real differences — a separate `mse_schema_migrations` tracking table
and a separate advisory-lock constant (the two repos share ONE physical
Supabase database; this repo's own `schema_migrations` table already
existed and tracks a completely different migration history), and
explicit exclusion of a real manual rollback file
(`20260831000035_dist_phase8_mse_leads_alter_ROLLBACK.sql`) from
auto-discovery. All 49 pre-existing migrations there were backfilled
into the new tracking table before this shipped — confirmed live,
post-deploy, that the runner sees 0 pending and the app's `/health`
reflects the new commit. Full writeup:
`knowledge/sops/devops/2026-09-16-mse-migration-runner.md`.

Both repos now fail closed at boot if a migration doesn't apply cleanly
— the silent-drift failure mode this entire gap was about should not be
possible in either codebase going forward, for a migration written from
this point on that follows each repo's own `IF NOT EXISTS`/idempotent
convention.

### 16. No error monitoring on Cloud Decoded's own backend — RESOLVED (2026-09-15)

Flagged by the 2026-09-15 operational readiness audit: `api/` and `core/`
had no `sentry_sdk` or equivalent anywhere — an unhandled exception or
crash in Cloud Decoded's own backend had no record beyond raw Railway
container logs, which nobody was watching proactively. Notably ironic for
a product whose entire pitch is catching infrastructure problems for
customers — nothing was watching Cloud Decoded itself.

**Built:** `core/error_tracking.py` — `init_sentry()` reads `SENTRY_DSN`
from the environment and no-ops entirely if it isn't set (local dev and
tests work identically with or without a Sentry account, never raising or
blocking startup on a missing/invalid DSN). Wired into `api/main.py`
before the `FastAPI` app is instantiated (the FastAPI/Starlette
integrations instrument at init time). `capture_exception()` tags every
error with `workspace_id` (and `agent_id` where applicable) via a Sentry
scope, so errors are traceable per tenant — added to all 11 of
`api/routes/webhooks.py`'s `_run_*` background-task functions' existing
`except Exception` blocks (the same functions `api/routes/agents.py`'s
manual-trigger endpoint reuses, so direct-invocation job failures are
covered too). Unhandled exceptions in the synchronous request path are
captured automatically by Sentry's FastAPI/Starlette integrations —
expected control flow (`HTTPException`s like invalid-token 403s,
`SubscriptionError`, `BudgetExceededError`) is deliberately not routed to
Sentry to avoid alert noise on normal business logic.

8 new tests in `tests/test_error_tracking.py` (DSN-unset no-op, DSN-set
init call shape, tag/extra behavior, safe-no-op-when-uninitialized).

### 17. Duplicate tier-limit dict in `api/routes/agents.py` — RESOLVED (2026-09-15)

Flagged by the 2026-09-15 operational readiness audit as residual risk
from entry #14: after Agent 11 shipped, both `core/compliance.py`'s
`WorkspaceComplianceGuard.TIER_LIMITS` and `api/routes/agents.py`'s own
separate `tier_limits` dict (used by `GET /agents`'s `list_agents`) were
bumped to the correct values and made consistent — but the duplication
itself remained. `agents.py`'s copy hardcoded enterprise to a fixed count
(`11`) instead of `compliance.py`'s `-1`/unlimited semantics, so the next
agent added would silently under-list at Enterprise again unless someone
remembered to bump both dicts in lockstep — the exact class of bug that
made Agent 11 briefly Enterprise-only by numbering accident in the first
place.

**Fixed:** `core/compliance.py`'s `TIER_LIMITS` is now the single source
of truth; `list_agents()` reads `WorkspaceComplianceGuard.TIER_LIMITS`
directly instead of keeping its own copy. Handled explicitly: a plain
list slice with `max_agents = -1` (enterprise's unlimited marker) would
silently drop the *last* agent (`all_agents[:-1]`) rather than returning
everything — `list_agents()` now branches on `-1` explicitly rather than
slicing with it.

6 new tests in `tests/test_agents_route_tier_limits.py`, including a
direct regression guard for the `-1`-slice bug (enterprise must see all
11 agents, `agent_11_resource_health` included, not 10). Full suite:
1412 passing (was 1398), same 4 pre-existing unrelated failures, zero
regressions.

### 18. Multi-worker deploy weakens rate limiting; DB connection hold window still spans the LLM call (2026-09-15)

Two real, known items from Phase 8 of the scale-readiness build,
deliberately not fixed in this pass -- flagged rather than silently
shipped or silently skipped.

**Rate limiting is ~4x weaker than configured, per worker.**
`--workers 4` (Procfile, railway.json) means 4 independent OS processes,
each running its own `slowapi.Limiter` with the default in-memory
`MemoryStorage` -- there is no shared counter across workers. A customer
load-balanced across all 4 workers effectively gets ~4x Phase 4's
configured limits (e.g. Starter's 60/min webhook ceiling becomes ~240/min
in practice) before any single worker's counter trips. Checked
`limits` (slowapi's underlying package) for a Postgres-backed storage
option to reuse infrastructure already provisioned, the same pattern
Phase 6 used for the durable queue -- none exists; only Memory,
Memcached, MongoDB, and Redis are supported, and no Redis instance is
provisioned for this service (`REDIS_URL` absent from Railway env vars,
confirmed live). Kelvin's explicit call: ship `--workers 4` anyway
(the pool/semaphore/backpressure work from Phases 5-7 still functions
correctly per-worker regardless), revisit with Redis-backed
`Limiter(storage_uri=REDIS_URL)` once that instance exists.

**DB connection hold window still spans the full `agent.run()` call,
including the LLM round trip.** Every one of `webhooks.py`'s 11 `_run_*`
functions acquires one connection and holds it for the entire agent
workflow execution (ingest → diagnose's LLM call → hitl_gate's DB write)
because each workflow class's constructor takes a single `conn` object
used throughout every node via `self._db`. Narrowing this properly means
every one of the 11 agent workflow classes acquiring/releasing its own
connection per-node instead of being handed one for its whole lifetime
-- a real architectural change touching every agent's constructor and
node methods, not a small tweak, and meaningfully larger in scope and
regression risk than the rest of this phase combined. Not attempted in
this pass. Phase 7's semaphore + Phase 8's pool resize to max_size=20
both reduce how much this matters in practice (more headroom before a
long-held connection becomes contention), but the underlying hold-window
issue is unchanged. Needs its own dedicated pass if it becomes a real
bottleneck under load.

### 19. LLM retry/backoff shipped platform-wide; degraded-incident fallback only built for Agent 11 so far (2026-09-15)

Phase 9, scale-readiness build. `.llm/router.py`'s `complete()` -- the
single entry point every one of the 11 agents' `call_llm()` routes
through -- now retries a transient error (429, 5xx, or a matching SDK
exception name) up to 3 times with exponential backoff + jitter on the
SAME provider before falling through to the existing cross-provider
failover chain (anthropic → openrouter → ollama). This applies to all
11 agents automatically, no per-agent change needed.

**Only Agent 11 also got the "create a real incident instead of
silently dropping the alert" half.** Previously, if `call_llm()` raised
after all providers were exhausted, the exception propagated uncaught
out of `_diagnose_node` -- no incident, no trace beyond a log line +
Sentry capture. Agent 11's `_diagnose_node` now catches that final
failure and returns a normal-shaped degraded diagnosis (`parsed_error`
= "LLM diagnosis unavailable — retry manually", a single `hold` option)
instead of setting `state["error"]` (which `_hitl_gate_node` treats as
"skip creating an incident entirely") -- so a real incident still gets
created and is visible to an operator.

**Deliberately not generalized to Agents 01-10 in this pass** --
Phase 10 (structured logging + failed-run visibility) is already
building a broader, general mechanism for exactly this class of problem
(any diagnose-node failure, not just an LLM-provider-exhausted one,
creating a real `execution_status='failed'` incident instead of being
silently skipped). Building a second, narrower LLM-specific version now
across 10 more agents would mean maintaining two separate fallback
mechanisms doing overlapping jobs. Once Phase 10 lands, Agent 11's
LLM-specific fallback here should be reconciled with it rather than
kept as a separate special case.

**RESOLVED 2026-09-15 (Phase 10).** `core/hitl.py` gained
`create_failed_incident()` and all 11 agents' `_hitl_gate_node` now call
it from the upstream-error branch instead of silently `return {}`-ing --
Agent 11's LLM-exhaustion path (the degraded-diagnosis fallback added
above) was left as-is since it deliberately avoids setting
`state["error"]` at all (producing a normal, non-failed diagnosis
instead), so it doesn't hit `create_failed_incident` and isn't a
duplicate of it -- the two mechanisms are complementary, not competing:
Agent 11 tries to give the operator something actionable when only the
LLM step failed; `create_failed_incident` is the catch-all for every
other kind of node failure, across all 11 agents. `execution_status =
'failed'` is now a real, queryable state platform-wide. Structured JSON
logging (`core/json_logging.py`) also shipped in this phase -- Railway
logs are now one JSON object per line with `extra={}` fields (
`workspace_id`, `agent_id`, `incident_id`, provider/retry fields on LLM
calls, subscription/budget-block reasons on webhook ingestion) promoted
to top-level queryable keys, instead of opaque message strings.

### 20. Row-level security shipped on core tables; full connection-level enforcement deliberately scoped down (2026-09-15)

Phase 11, scale-readiness build. `docs/customer/security-questionnaire-response.md`
told customers "row-level security enforced at the database layer, not
just application logic" while `workspaces`, `incidents`, `audit_events`,
and `token_usage` had **zero** RLS policies -- every query was correct
only insofar as its own `WHERE workspace_id = $N` was correct, with no
database-level backstop. `db/migrations/031_rls_core_tables.sql` fixes
this: all four tables now have `ENABLE ROW LEVEL SECURITY` plus a
`service_role_all` bypass (matches the existing convention in
`005_leads.sql`/`019_cloud_audit_findings.sql`) and a
`workspace_isolation` policy keyed on the `app.current_workspace_id`
session variable, which the new `core/workspace_scope.py`'s
`workspace_scoped_connection()` sets via `set_config(..., true)`
(transaction-local, so it can never leak across Supabase's transaction-
mode pooler onto an unrelated later request).

**Critical caveat, checked rather than assumed:** a Postgres superuser,
or the owner of a table that isn't also `FORCE ROW LEVEL SECURITY`'d,
bypasses RLS policies unconditionally. `db/migrate.py`'s new
`log_security_posture()` queries `pg_roles` for `DATABASE_URL`'s actual
role at every startup and logs `rolsuper`/`rolbypassrls` (+ a WARNING if
either is true) -- this is the real, live answer, not a guess, and it is
checked on every single boot going forward so a future credential
rotation can't silently change this without it showing up in logs.
Migration 031 deliberately does **not** set `FORCE ROW LEVEL SECURITY`:
if `DATABASE_URL`'s role turns out to be the table owner and is not a
superuser, forcing RLS would apply these policies to the app's own
primary connection too -- and since `workspace_scoped_connection()` has
only been wired into two call sites so far (see below), every other
query path would suddenly see zero rows platform-wide. That would have
been a self-inflicted full outage to find out empirically; the safe
version is a startup log line instead.

**Deliberately narrow rollout of `workspace_scoped_connection()` in this
pass** -- only `api/routes/incidents.py`'s `get_incident` and
`list_incidents` (the two customer-facing read paths) use it. Every
other route in the codebase still relies solely on application-layer
`WHERE workspace_id = $N` scoping, unchanged. Wrapping every `db.acquire()`
call site platform-wide (dozens, across ~15 route files, several without
a workspace in scope at all -- e.g. Stripe webhook handlers that look up
a workspace by `stripe_customer_id` before one is known) is a
materially larger change than this phase, and the ROI depends entirely
on the `log_security_posture()` finding above: if the connecting role
bypasses RLS anyway, wrapping more call sites protects other access
paths (Supabase Studio, anon/authenticated keys) but does nothing for
this app's own queries, which already have correct `WHERE` clauses.

**No automated regression test proves the RLS policy itself blocks a
cross-workspace query** -- this test suite has no real Postgres
available (`asyncpg` is stubbed in `tests/conftest.py`, confirmed
"always mocked at DB layer"), so RLS enforcement can only be verified
against a real database, which was done live against production this
session (role posture read via `log_security_posture()`'s log output
post-deploy) rather than captured as a repeatable test. `tests/
test_workspace_scope.py` and the `get_incident`/`list_incidents` tests
in `tests/test_incidents_workspace_scope.py` only pin that the Python
helper sends the right `set_config` call — a genuine future gap worth
flagging: this codebase has no real-Postgres integration test
infrastructure at all (docker-compose/testcontainers/similar), so this
is not unique to RLS and would need a deliberate decision to add before
any DB-level behavior can be regression-tested rather than manually
re-verified each time.

### 21. Incident/audit-event retention + composite indexes shipped; enterprise "configurable" retention still just a sentinel (2026-09-15)

Phase 12, scale-readiness build -- the last of the 12-phase merged
sequence. `core/compliance.py`'s `TIER_LIMITS` (already the single
source of truth for agent/repo/cloud-provider caps, GAPS.md #16) gains
`retention_days`: starter=90, growth=365, enterprise=-1 (the same
"-1 == unlimited" sentinel used for every other tier limit in that
dict). `core/retention.py`'s `run_retention_cleanup()` deletes
`incidents`/`audit_events` rows past that window per-workspace-tier, and
runs as an in-process periodic background task started in `api/main.py`'s
lifespan (once at startup, then every 24h) -- there is no separate
worker/cron service in this deployment to host a scheduled job
elsewhere, and `pg_try_advisory_xact_lock` (transaction-scoped, matching
`db/migrate.py`'s established reasoning for Supabase's transaction-mode
pooler) keeps Phase 8's 4 `--workers` processes from double-deleting.
`db/migrations/032_retention_and_indexes.sql` adds the composite
indexes the plan called for
(`incidents(workspace_id, execution_status, created_at)`,
`audit_events(workspace_id, status, created_at)`) plus a GIN index on
`audit_events.metadata`.

**"Configurable Enterprise" retention is still just the -1 sentinel**,
not a real per-customer override -- the plan named this explicitly
("configurable Enterprise"), and today enterprise simply never deletes
anything, full stop. A real implementation needs a workspace-level
`retention_days_override` column (or similar) plus an admin surface to
set it per customer, and `run_retention_cleanup()` would need to read
that column instead of (or in addition to) the tier default. Not built
here -- no Enterprise customer has asked for a specific number yet, and
guessing a UI/schema shape for a requirement nobody has stated would be
the wrong kind of speculative work for this phase.

**No batching on the DELETE** -- each tier/table pass is a single
unbounded `DELETE ... WHERE created_at < cutoff`, correct and fine at
current table sizes, but if `incidents`/`audit_events` grow into the
range where a single DELETE holds a long-running lock or a large
transaction, this will need chunking (e.g. `DELETE ... LIMIT N` in a
loop, or a helper table of ids to delete in batches). Not a problem
today; flagged so it isn't a surprise later.

**Same real-Postgres test-infrastructure gap as #20** -- `tests/
test_retention.py` pins the SQL/lock/tier-skip shape against a mocked
pool, not a real DELETE against a real database. The advisory-lock
concurrency-safety claim (multiple workers, one wins) and the actual
row-deletion behavior were reasoned from the same proven pattern
`db/migrate.py` already uses in production, not independently verified
against a live multi-worker race in this session.

This closes the merged 12-phase scale-readiness sequence (incidents
schema → ingest fixes → dedup → webhook rate limiting → checkpointer
safety → durable queue → semaphore/timeout → DB pool/workers → LLM
retry → structured logging/failed-run visibility → RLS → retention/
indexes). See DECISIONS.md for the running architectural log across all
12 phases.

### 22. Membership Phase A shipped backend-side; dual-auth rollout deliberately narrow, RBAC enforcement not yet real (2026-09-15)

Membership/SSO/RBAC/SCIM plan, Phase A. Real workspace membership now
exists: `db/migrations/033_workspace_members.sql` adds `workspace_members`
(one row per human, `role` admin|member, `status` invited|active|
deactivated), generalizing the admin-only, Enterprise-only mcp-invite
pattern into `api/routes/workspace_members.py`'s self-serve
`POST /workspace-members/invite` / `GET /workspace-members` /
`POST /workspace-members/accept`. `api/middleware/auth.py` gains
`get_workspace_member()` (validates a Supabase session via
`client.auth.get_user()` -- the same online-validation approach
`internal_auth.py`'s `get_internal_user` already uses, deliberately NOT
`mcp/auth/oauth.py`'s offline JWT decode, since `mcp/` is a separately
deployed service this codebase doesn't import from) and
`get_workspace_or_member()` (tries `X-Workspace-Token`/
`X-MCP-Service-Key` first, falls back to a Bearer session) as a second,
additive auth path -- the existing token path is completely unchanged.

**Only `get_incident`/`list_incidents` (api/routes/incidents.py) accept
`get_workspace_or_member` so far** -- the same two routes Phase 11 wired
for DB-level workspace scoping, and the pair the plan's own Phase A
"Verification" section names (list the same workspace's incidents as two
different logged-in users). `approve_incident`/`reject_incident` and
every other token-gated route in the codebase still take `get_workspace`
only -- a member session cannot yet approve a remediation, view billing,
manage credentials, etc. Rolling `get_workspace_or_member` out further is
mechanical (swap the `Depends()`) but deliberately not done blind across
every route in this pass, matching this session's established
"targeted, not platform-wide" scoping discipline (Phase 10's logging,
Phase 11's RLS wiring).

**No real RBAC enforcement yet -- `role` is stored, not checked, beyond
invite.** `invite_member`'s `_caller_is_authorized_to_invite` is the ONE
place `role == 'admin'` is actually gated on. A `member`-role session can
already read incidents via the dual-auth wiring above with no role check
at all -- fine today (read-only, same data a `viewer` role would see
under Phase C's real RBAC design), but Phase C ("`workspace_members.role`:
`admin | approver | viewer`... map onto real product actions") is where
role actually starts gating write actions. Don't mistake the `role`
column existing for RBAC being built.

**Bootstrap trust model, worth being explicit about:** the very first
invite for a workspace has no admin member yet to authorize it, so
`invite_member` accepts EITHER an active admin member session OR the
bare workspace token (`get_workspace`, no `member_role` key at all) --
meaning anyone holding the shared token (a CI system, a webhook
integration, or the original signup holder) can invite the first human
members. This is the deliberate, minimal bootstrap the plan's own Phase
A description anticipates ("whoever holds the workspace token can invite
the first human member(s)"), not an oversight -- but it does mean the
workspace token remains a full-trust credential for this action, same as
it already is for everything else it can currently do.

**Frontend shipped in a follow-up commit (70b6230)** -- `/login`'s
primary sign-in is now real Supabase email/password
(`supabase.auth.signInWithPassword`), with workspace-token entry kept as
an explicit secondary fallback for the reason above. `/accept-invite`
handles the invite-link → set-password → `POST /workspace-members/accept`
flow. `lib/api.ts`'s `request()` picks the right auth header by token
shape (`cd_ws_` prefix vs. not), so the existing single `token` state
threaded through every dashboard call site carries either credential
with no per-call-site changes. Verified live: `tsc --noEmit` clean,
`next build` succeeds, and both pages confirmed serving the new content
on `theclouddecoded.com` post-deploy (`curl` showed the new "Use a
workspace access token instead" copy on `/login`, `200` on
`/accept-invite`).

**Full literal end-to-end verification NOT performed** -- the plan's own
Phase A verification bar ("a real signup → invite a second user → both
users list the same workspace's incidents, scoped correctly") requires
`SUPABASE_SERVICE_ROLE_KEY` to drive the Supabase Admin API (or a real
email inbox to click a live invite link through), and this session's
local `.env` only carries `SUPABASE_URL`/`DATABASE_URL` -- the service
role key lives in Railway's environment only, and Railway's variable
values are redacted from every tool available in this session (by
design). What WAS verified: all 32 new backend tests (every code path --
bootstrap invite, admin-only gating, duplicate/409, Supabase-failure/502,
accept-invite success and every failure mode) pass against mocks, and
migration 033 + both new endpoints are confirmed live and responding
correctly in production (`401` with no credentials, `200`/correct schema
otherwise). The one thing NOT independently confirmed against a real
Supabase project: that `invite_user_by_email`'s redirect actually lands
on `/accept-invite` and that `detectSessionInUrl` actually picks up the
resulting session client-side, end to end, exactly as designed. Someone
with the Supabase dashboard (or the service role key) should do one real
test invite before telling a real customer this feature exists.

### 23. Membership Phases B (seats) and C (RBAC) shipped; no members-management UI built (2026-09-15)

Membership/SSO/RBAC/SCIM plan, Phases B and C -- run together in one
pass since both are small, additive changes on top of Phase A's
foundation, matching the plan's own sequencing note.

**Phase B (seats):** `core/compliance.py`'s `TIER_LIMITS` (single source
of truth, GAPS.md #16) gains `max_seats`: starter=3, growth=15,
enterprise=-1 (unlimited, same sentinel as every other limit in that
dict). `assert_seat_available()` counts `workspace_members` rows in
`('invited', 'active')` status against the cap -- an unaccepted invite
still occupies a seat, so a workspace can't out-invite its cap and have
them all eventually accept. Wired into `POST /workspace-members/invite`
before the row is created. `GET /workspace-members` now returns
`{members, seats_used, max_seats}` instead of a bare list (safe breaking
change -- this endpoint shipped hours earlier in the same build with no
real consumers yet).

**Phase C (RBAC):** `workspace_members.role` is now `admin | approver |
viewer` (migration 034 renames Phase A's placeholder `'member'` default
to `'viewer'` and fixes up any existing rows). `api/routes/incidents.py`'s
`approve_incident`/`reject_incident` now require `get_workspace_or_member`
plus role `admin` or `approver` for a member session -- `viewer` is
rejected with 403. A token-authenticated caller (no `member_role` key at
all) is completely unaffected, same full-trust model the shared
workspace token already had for every other action.

**No members-management UI was built.** The plan's Phase B item
("dashboard surfaces 'X of Y seats used'") describes a data need, which
`GET /workspace-members`'s new `seats_used`/`max_seats` fields satisfy --
but no frontend page actually calls that endpoint, invites a teammate
through a form, or displays the member list/role/seat count anywhere.
Phase A's frontend work was scoped to login + accept-invite only (GAPS.md
#22); a real "Team" or "Members" settings page is a genuinely separate,
not-yet-started frontend feature. Someone can invite/list/manage members
today only via direct API calls (curl, Postman, or a future UI), not
through the dashboard.

**Role names landed as `admin | approver | viewer`** without the "map
onto real product actions... name TBD with Kelvin" confirmation the plan
called for -- these three names were chosen as the closest fit to the
plan's own text (`workspace_members.role`: `admin | approver | viewer`)
since no further input was available mid-build. Worth a quick sanity
check with Kelvin before these are considered final/customer-facing
language, though changing them later is a cheap rename (VARCHAR column,
no enum type, two `_VALID_ROLES`/`_APPROVAL_ROLES` constants to update).

### 24. Phase D (SSO) storage + admin config shipped; real Supabase provider registration NOT built (2026-09-15)

Membership/SSO/RBAC/SCIM plan, Phase D. `db/migrations/035_workspace_sso_config.sql`
adds `workspace_sso_config` (one row per workspace: `provider_type`
saml|oidc, `email_domain`, `idp_metadata_url`, Fernet-encrypted
`idp_metadata_xml_encrypted`, `supabase_sso_provider_id`, `status`
pending|active|disabled). `api/routes/internal_workspaces.py` gains
`PUT`/`GET /internal/workspaces/{id}/sso-config` -- admin-gated (same
trust model as `mcp-invite`: Enterprise sells on a 30-90 day B2B cycle,
provisioning happens after a deal closes, not via a customer-facing
form). Never echoes the raw metadata XML back, only `has_metadata_xml`.

**The actual "register this as a real SSO provider with Supabase" step
was deliberately NOT built.** The plan's own Phase D text says "use
Supabase Auth's native SSO support... configuring Supabase's SSO
provider integration per customer's IdP" -- that requires calling
Supabase's Management API (`POST /v1/projects/{ref}/config/auth/sso/
providers`), which needs a Supabase **Management API access token**, a
materially different and more privileged credential than
`SUPABASE_SERVICE_ROLE_KEY` (which this session does have access to via
Railway's env, redacted). No Management API token was available in this
session to verify that integration's exact request/response shape
against, and writing untested code that calls a real external
provisioning API on a real Enterprise customer's behalf is the wrong
kind of code to ship without being able to check it actually works.
`set_sso_config` stores configuration and always leaves `status='pending'`
and `supabase_sso_provider_id=NULL` -- a human with Supabase Dashboard
or Management API access still has to complete the real registration and
update this row (or a follow-up build adds that call once a Management
API token is available to test against).

**No `/login` SSO buttons added**, matching that page's own existing
comment (unchanged since before this build): "SSO buttons... deliberately
NOT recreated here: there is no backend for either... shipping buttons
that do nothing would be actively misleading on a page real customers
pay to use." That's still true today -- the backend now stores config
but doesn't yet complete a real SSO login round-trip end to end, so
adding buttons now would be the same mistake the comment already warns
against.

Phase E (SCIM) is still built in this same pass despite this -- see
GAPS.md #25 for why it's real, testable code even though it stays
practically dormant until Phase D's Management API registration step
above is completed by someone with that access.

### 25. Phase E (SCIM 2.0) shipped as real protocol code, closing the merged 5-phase membership plan (2026-09-15)

Membership/SSO/RBAC/SCIM plan, Phase E -- the last of the five phases.
`api/routes/scim.py` implements `GET/POST /scim/v2/Users`,
`GET/PUT/PATCH/DELETE /scim/v2/Users/{id}` -- a deliberately pragmatic
SCIM 2.0 subset (RFC 7643/7644) covering what real IdP connectors
(Okta, Azure AD) actually send: the `userName eq "..."` pre-create dedup
filter, the `active` PATCH deprovision op in both shapes a connector
might send it (`{"path":"active",...}` or `{"value":{"active":...}}`),
and SCIM's own error-response schema -- not full spec coverage (no
Groups resource, no ServiceProviderConfig/Schemas/ResourceTypes
discovery endpoints, no general filter grammar). Maps directly onto
Phase A's `workspace_members` table; new members default to `role='viewer'`
(least privilege); DELETE deactivates rather than hard-deletes, matching
`docs/customer/dpa-outline.md`'s existing "archival, not hard deletion"
model.

Authenticated by a new dedicated `get_workspace_by_scim_token`
dependency (`api/middleware/auth.py`) -- deliberately its own thing, not
folded into `get_workspace_or_member`: a SCIM connector's bearer token
is scoped to exactly one workspace's IdP integration, never a human
session or the shared workspace token. `db/migrations/036_workspace_
scim_token.sql` adds `scim_bearer_token_hash`/`scim_token_created_at` to
`workspace_sso_config` (SHA-256 hash only, same convention as
`workspaces.workspace_token`); `POST /internal/workspaces/{id}/
sso-config/scim-token` (admin-gated, `internal_workspaces.py`) generates
and returns the raw token exactly once, same "shown once" contract as
`rotate-token`. Requires an SSO config row to already exist (409
otherwise) -- a SCIM connector without an SSO connection has nothing to
provision into.

**This code is real and tested (21 new tests across `test_scim.py` and
`test_auth.py`) but practically dormant** until GAPS.md #24's Supabase
Management API registration step is completed by someone with that
access -- no real IdP has a live SSO connection to push SCIM requests
through yet. Building it now rather than waiting was a deliberate call:
the endpoints are pure application code with zero dependency on the
Management API gap (an IdP calling `/scim/v2/Users` needs this
workspace's SCIM token, not Supabase's SSO registration to be live), so
there was no reason to block Phase E's protocol layer on Phase D's
operational follow-up.

**This closes the merged 5-phase Membership/SSO/RBAC/SCIM plan** (A:
workspace membership foundation → B: seats → C: RBAC roles → D: SSO
storage/config → E: SCIM). Combined with GAPS.md #22-#25's honest
accounting of what remains operational (a real end-to-end invite test,
Supabase Management API SSO registration, and a members-management UI),
every phase's code is built, tested, and deployed -- what's left is
operator follow-through with credentials/access this session's tools
don't have, not further engineering.

### 26. MKT-LI1 product content gated by kdavis-microsaas-engine's selling_stage (cross-repo read) (2026-09-15)

Marketing stage-gate follow-up (companion to the `selling_stage` column
added to `kdavis-microsaas-engine`'s `mse_icp_configs`, commit `1c2b716`
in that repo). `agents/marketing/mkt_li1_linkedin_brand.py` gains
`generate_product_content()` — a stage-aware entry point wrapping the
existing (unchanged) `generate_product_launch_post()`. `'active'` routes
straight to the existing full-CTA launch post; `'warming'` drafts a new
mention-only post (`MENTION_ONLY_SYSTEM_PROMPT`) that references the
product in context with no CTA and no URL (code-enforced by stripping
the URL from the model's output if it appears anyway, not just prompt
instruction); `'building'` returns `None` — no LLM call, nothing
queued, nothing generated.

**This is a genuine cross-repo runtime dependency, not just a shared
convention.** `mse_icp_configs` lives entirely in `kdavis-microsaas-
engine`'s own migrations — this repo has no copy of that schema and
doesn't migrate it. The two repos happen to share one Supabase project,
so `_get_product_selling_stage()` is a live table read through this
repo's own Supabase client at generation time. If that table, or the
shared-project assumption, ever changes, this silently (by design —
see below) starts treating every product as `'building'` rather than
failing loudly. Fails closed on any lookup error or missing config row,
same conservative default as the MSE repo's own column default —
the cost of one skipped post is far lower than generating sell copy for
a product not meant to be visible yet, but it does mean a genuine
outage in the cross-repo read (not just "product hasn't been
configured yet") looks identical to "this product is in building
stage" from this function's own return value alone. The `log.warning`
on the lookup-error path is the only signal that distinguishes the two;
worth wiring an actual alert on that log line if this cross-repo
dependency becomes load-bearing for real outreach cadence.

Does not touch Pillar 5 (Enterprise Consulting & AI Platform
Architecture) or any other evergreen-batch pillar — confirmed directly
by reading `PILLAR_TOPIC_SEEDS`/`VOICE_SYSTEM_PROMPT` before writing
anything: Pillar 5 is topical thought-leadership grounding for Kelvin's
own authority content, not tied to any specific `mse_products` row, and
its own prompt already forbids naming a specific product or CTA. There
was nothing product-`selling_stage`-shaped in it to gate.

15 new tests (`tests/test_mkt_li1_selling_stage_gate.py`). Full suite:
1591 passing (was 1576), same 4 pre-existing unrelated failures.

### 27. Webhook integrations Tier 1 shipped (Prometheus/Grafana inbound, Slack/PagerDuty outbound); Tier 2/3 deferred to a future build cycle (2026-09-14)

Kelvin's own three-tier framing, built/deferred exactly as scoped (GCP
explicitly excluded from this pass):

**Tier 1 -- built this pass:** Prometheus Alertmanager and Grafana
unified-alerting webhook formats added to Agent 11's
`/webhooks/resource-health-alert` endpoint (`api/routes/webhooks.py`) --
Grafana's real webhook contact-point schema was verified against its
current docs rather than assumed, and turns out to deliberately mirror
Alertmanager's own payload shape; the only reliable top-level
discriminator is Grafana's `orgId` field, which Alertmanager's own
webhook_config payload never sends (also verified against Prometheus's
own docs). Slack and PagerDuty outbound notifications now fire
best-effort on every incident creation across all 11 agents, wired once
at `core/hitl.py`'s `create_incident()`/`create_failed_incident()` choke
point rather than per-agent. New `workspace_notification_channels` table
(migration 037) plus a self-serve `api/routes/workspace_notifications.py`
(`PATCH /workspace/notifications/slack`, `.../pagerduty`,
`GET /workspace/notifications`) let a workspace configure its own
channels, same `get_workspace` customer-facing auth pattern as
`workspace_credentials.py`, never echoing a decrypted secret back.

**Tier 2 -- next build cycle (not built, no implementation detail
invented):** Datadog inbound webhook, OpsGenie outbound notification,
Atlantis webhook → Agent 01, ArgoCD/Flux webhook → Agent 01/08.

**Tier 3 -- enterprise tier features (not built, no implementation
detail invented):** ServiceNow change record on execution, Jira/Linear
ticket on execution, Microsoft Teams outbound, Terraform Cloud /
Spacelift webhooks, Snyk / Wiz inbound alerts, GuardDuty / Defender for
Cloud inbound.

`workspace_notification_channels.channel_type` is deliberately a
free-text column rather than a fixed two-value enum/CHECK constraint --
see the migration's own comment -- specifically so Tier 2's OpsGenie and
Tier 3's Microsoft Teams outbound channels can register as a new
`channel_type` value plus a new sender function in
`core/notifications.py` when they're built, reusing the exact same
`notify_incident_channels()` fan-out and `workspace_notification_channels`
table without a new migration.

### 28. `audit_events` table has zero application-level writers -- security page's "full audit trail" claim is not backed by the DB (2026-09-15)

**Priority: HIGH.** Found while building the "Handle manually" HITL
resolution path (commit `d7f8855`): before that commit,
**nothing in this codebase ever wrote a row to `audit_events`** --
confirmed by reading every call site across the whole repo, not
assumed. `core/hitl.py`'s `_write_audit_entry()` -- called from
`create_incident`, `create_failed_incident`, `bump_occurrence`,
`approve_incident`, `mark_executed`, `mark_failed` -- despite its name
and its "Rule 9 compliance" docstring comment, appends a line to a
**local markdown file**, `knowledge/operator/llm-audit.md`, not the
database. Same for every `agents/agent_0N_*/workflow.py`'s
`self._write_audit(...)` (via `agents/base_agent.py`'s `_write_audit`)
and every marketing agent's `write_audit_log()` (`agents/marketing/
_shared.py`) -- all markdown-file writers, none touch `audit_events`.

This means every claim on `frontend/src/app/security/page.tsx` and
`docs/customer/security-questionnaire-response.md` about a "full audit
trail" / per-tenant audit logging has, until now, described a table
that exists (migration 001, RLS-covered since migration 031) but is
functionally empty for every real customer action. A customer asking
"show me every action taken on my incidents this month" via direct
Supabase/API access would get nothing back from `audit_events` --the
only place that information actually lived was a single shared
markdown file on the Railway filesystem, not even per-workspace, not
customer-accessible, and not guaranteed to survive a redeploy.

**Fixed, same session.** New `core/audit.py` (`write_audit_event()` +
`schedule_audit_event()`) writes a real `audit_events` row for every
call, alongside the existing markdown writer (kept, per Kelvin's
explicit instruction, as a secondary operator-debugging output — not
removed). Fired via `asyncio.create_task()` from inside
`core/hitl.py`'s `_write_audit_entry()` and `agents/base_agent.py`'s
`_write_audit()` — both stay plain synchronous methods, so every one of
their dozens of existing call sites across `core/hitl.py` and all 11
agent `workflow.py` files needed zero changes. `action` is the existing
descriptive string each call site already passed (`"created"`,
`"ingest"`, `"execute:opt_1"`, etc. — not renamed to match this entry's
earlier illustrative examples, since nothing depends on those exact
strings and renaming would be an unrelated, riskier refactor);
`workspace_id`/`incident_id`/`agent_id`/`status`/`tokens_used` map onto
the columns already provided at each call site. Several of
`core/hitl.py`'s own call sites (`bump_occurrence`/`approve_incident`/
`mark_executed`/`mark_failed`) pass the literal string `"unknown"` for
workspace_id — a pre-existing gap in those methods' own signatures, not
reworked here — so `write_audit_event()` resolves the real workspace_id
via a `SELECT workspace_id FROM incidents WHERE id = $1` fallback
instead of silently dropping those writes (this matters most for
`mark_executed`, the completion event for every successful remediation
across every agent). 14 new tests in `tests/test_core_audit.py` cover
the happy path, the "unknown" fallback, and that every failure mode
(no `DATABASE_URL`, connection failure, insert failure, no running
event loop) is swallowed and never raises back into a caller.
Security page and security-questionnaire-response.md updated in the
same push to reflect that audit logging is now genuinely backed by the
DB table with full per-tenant queryability.

### 29. Every MSE product's ICP config except Cloud Decoded's has empty `locations`/`search_templates` -- "Run Lead Finder Now" silently returns zero leads for all of them (2026-09-16)

Found while adding a real, working ICP config for Cloud Decoded (Kelvin's
request: "the cloud decoded product needs a lead finder also. needs to
be added to the lead pipeline" — see kdavis-microsaas-engine migration
`20260916000046_cloud_decoded_icp.sql`). Queried every existing
`mse_icp_configs` row directly: `ada-title-ii`, `bible-devotional`,
`decodedsix`, and `small-portfolio-hub` all have `locations: []` and
`search_templates: []`. `agents/marketing/mkt_lead_finder.py`'s
`find_leads()` loops `for location in locations: ...` — an empty list
means the loop body never runs, so `run_lead_finder_for_product()`
(the real production entry point behind `POST /marketing/leads/find`,
i.e. the ceo-dashboard "Run Lead Finder Now" button) returns 0 leads,
every time, for every one of these products. Nobody has hit an error —
it just quietly does nothing.

`thdagentic-consulting`'s ICP config (added 2026-09-16, same session as
the consulting cold-outreach build) also has `locations: []`, but that
one has a real reason: its intended lead source is
`find_job_posting_signals()`/`run_job_posting_signal_finder()` (Google
Custom Search against job postings, not the standard people-search
path), which never reads `locations` the same way. The problem: **that
job-posting-signal finder has no wired trigger anywhere** —
`POST /marketing/leads/find` (`api/routers/leads.py`) always calls the
standard `run_lead_finder_for_product`, never
`run_job_posting_signal_finder`. So clicking "Run Lead Finder Now" with
consulting selected also silently returns 0 leads, for a second,
different reason than the other four products.

Not fixed here — out of scope for the Cloud Decoded ICP request, and
per this file's own rule, a gap like this gets surfaced, not built
mid-session. Two separate follow-ups, either of which needs Kelvin's
go-ahead before building:
1. Fill in real `locations`/`search_templates`/`job_titles` for
   `ada-title-ii`, `bible-devotional`, `decodedsix`, `small-portfolio-hub`
   (each needs its own real ICP — this isn't a one-size template).
2. Either wire a real trigger for `run_job_posting_signal_finder()`
   (a new endpoint, or branch `POST /marketing/leads/find` on
   `lead_source`/a per-product flag), or explicitly document that
   consulting's lead generation is Google-CSE-job-posting-signal-only
   and the "Run Lead Finder Now" button should be disabled/relabeled
   for that product until #1 above is decided.

### 30. `document_carousel` LinkedIn posts have never had a real publish path -- silently went out as caption-only text, no error, every time (2026-09-21)

Found investigating Kelvin's report: "LinkedIn content created without
images." Root cause traced to `api/routes/internal_marketing.py`'s
`publish_queue_row` (the function both the manual publish button and
`scripts/dispatch_scheduled_posts.py`'s cron call): it only knows how to
post via `image_brief.image_path` (a single generated/vault image) or a
dormant Canva Autofill branch — anything else falls through to
`post_text()`, `used_image=False`, no error. `document_carousel`-format
posts never populate `image_brief` at all; they carry `carousel_slides`
(per-slide text) and `carousel_pdf_brief` (`{concept, slide_count,
style}`) instead — fields that are drafted in three separate places
(`agents/marketing/mkt_li1_linkedin_brand.py`,
`mkt_v1_content_multiplier.py`, `scripts/generate_showing_signal_week.py`)
but read by **nothing** downstream: no code anywhere renders them into an
actual PDF or image set, and `core/publishers/linkedin.py` has no
document-post function (only `post_text`/`post_image` exist). Every
approved carousel post — and the format rule
(`mkt_li1_linkedin_brand.py`: "use document_carousel when content has
3-8 discrete points") means this is a real, regular fraction of posts,
not an edge case — published as a bare caption with none of its actual
slide content, silently, with the cron reporting success every time.

**Fixed this session:** `publish_queue_row` now raises `PublishError(501,
...)` for `document_carousel` rows instead of silently degrading to
text — the row stays `approved` (retriable) but every dispatch attempt
now fails loud, in both the dashboard and the cron's GitHub Actions log,
until it's resolved. This stops the silent bad outcome; it does not
build real carousel publishing.

**Not built here — surfaced, not built mid-session, per this file's own
rule.** Two separate follow-ups, either needs Kelvin's go-ahead:
1. Build real document/carousel publishing: render `carousel_slides` +
   `carousel_pdf_brief` into an actual multi-page PDF (no renderer
   exists anywhere in this codebase today — this is new, from scratch),
   then post it via LinkedIn's Documents API (register-upload, upload
   the PDF, reference the resulting URN in the post) — a new function in
   `core/publishers/linkedin.py` alongside `post_text`/`post_image`.
2. Or: retire `document_carousel` as a choosable format until #1 is
   built — remove the format rule from the three drafting prompts above
   so the LLM never produces a post this pipeline can't actually
   publish, and manually re-triage whatever `document_carousel` rows
   currently sit `pending_review`/`approved` (re-approve as `text_post`
   with a generated image, or reject).

### 31. Cloud Decoded email lifecycle system — honest gaps from this build (migration 051, 2026-09-21)

Built the full onboarding/dunning/winback/newsletter/etc. email engine
(`core/email_scheduler.py`, `core/marketing_email.py`,
`core/email_content/*.py`). Real, tested, deployed — but several pieces
are deliberately incomplete or unverifiable without Kelvin's own action:

1. **Resend webhook signature verification is unverified against a real
   delivery.** `core/resend_webhook.py` implements Svix's documented
   HMAC scheme from memory (no live docs access this session) and is
   tested against itself (`tests/test_resend_webhook.py`), not against
   an actual Resend webhook payload. Kelvin still needs to configure the
   webhook in the Resend dashboard (pointed at
   `{API_BASE_URL}/api/v1/email/resend-webhook`) before this can be
   exercised for real — if Resend's actual header names or signed-content
   format differ, every real webhook will be rejected until corrected
   against a live delivery.
2. **Quiet-hours timezone is a platform-wide default, not per-recipient.**
   `CD_EMAIL_QUIET_HOURS_TZ` defaults to `America/Phoenix` — the build
   has no way to know an individual subscriber's real timezone, so every
   marketing send observes one shared 06:00-18:00 window regardless of
   where the recipient actually is.
3. **Exit-rules engine vocabulary is limited to two conditions**
   (`workspace_active`, `workspace_canceled`) — `core/email_scheduler.py`'s
   `_evaluate_exit_rules`. The jsonb column supports more, but nothing
   else is implemented or needed by this build's 8 sequences.
4. **`skip_if` for onboarding step 3 (day-4 "fire a test incident") and
   stall-nudge step 2 (day-7 "no first incident") both use
   `has_first_incident`, which checks for ANY incident ever, not
   specifically a test/synthetic one** — a workspace with a real incident
   already (before the email would fire) correctly skips, but there's no
   way to distinguish "fired a real incident" from "fired the specific
   test incident the email asked for." Accepted as good enough for this
   build; a dedicated `is_test` flag on `incidents` would close it.
5. **Stall-nudge step 2's trigger is NOT independently evaluated** — per
   the original build spec's letter, day-7 "no first incident" should be
   its own trigger condition; this build fires it via step 1's
   `delay_days` instead (documented in
   `core/email_content/stall_nudges.py` and `core/email_triggers.py`).
   Practical effect: step 2 fires exactly 4 days after step 1 regardless
   of the workspace's actual signup date, which is close to but not
   exactly "day 7 since signup."
6. **`expansion_agent_ceiling` and `expansion_enterprise_upsell` have no
   wired trigger.** Only `expansion_seat_cap` actually enrolls anyone
   (from `api/routes/workspace_members.py`'s invite endpoint hitting the
   seat cap). No existing "agent-limit ceiling hit" signal exists in this
   codebase to hook (tier gating is a hard block per-call, not a
   countable ceiling a workspace approaches), and "Enterprise upsell"
   criteria was never concretely specified beyond the template copy
   itself. Both templates exist, can be approved/activated, and are
   documented in `docs/internal/email-approval-api.md` — they just never
   fire.
7. **Dunning copy corrects an assumption in the original build spec.**
   The spec assumed "access stays open" while `past_due` — checked
   against `core/compliance.py`'s real `WorkspaceComplianceGuard`, which
   blocks agent execution immediately at `past_due` (not just at eventual
   suspension). `core/email_content/dunning.py`'s copy reflects the real
   behavior instead of the spec's incorrect assumption.
8. **Phase 5 capture is partial.** The newsletter signup block ships on
   every marketing page via the shared footer
   (`frontend/src/components/marketing/SiteChrome.tsx` →
   `NewsletterSignup.tsx`). A dedicated `/newsletter` landing page and the
   lead-magnet-gated security-questionnaire-download flow were **not**
   built this session (time-boxed out of an already large build) — the
   backend (`source='lead_magnet'` → `trust_drip` enrollment) is ready
   for it, but nothing on the frontend gates a real document behind it
   yet.
9. **The old Brevo lead-nurture stack
   (`agents/internal/email_sequence_agent.py`,
   `leads/integrations/brevo_client.py`, `leads/capture/signup_handler.py`
   /`trial_handler.py`, migration 039's `email_sequences` table) was
   confirmed to have zero real callers anywhere in this codebase outside
   its own tests** — not wired to any HTTP route, so "retiring" it this
   session meant leaving it exactly as untouched/dead as it already was,
   not migrating live traffic off of it. Flagged DEPRECATED in
   `DECISIONS.md`, not deleted (its tables and tests still exist).
10. **`hitl` role does not exist in `api/middleware/internal_auth.py`'s
    auth model.** Every `/internal/email/*` endpoint is admin-only in
    practice — Kelvin's plan for his wife to approve templates under a
    `hitl` role needs that role added to `get_internal_user`'s check
    first (a shared dependency other `/internal/*` routes also use — not
    changed here without being asked, see that file's own comment).
11. **Metrics endpoint's `revenue_usd_estimate` is static list pricing,
    not Stripe-accurate** — a workspace's real price can differ from list
    (promo codes, grandfathering). Documented as an estimate in
    `docs/internal/email-approval-api.md`, not fixed to read live Stripe
    prices this build.

### 32. `theclouddecoded.com` is not a verified domain in Resend — no real email of any kind can send right now (2026-09-22)

Discovered live: testing the new LinkedIn-token-expiry alert
(`core/social_token_expiry.py`, migration 052) produced a real send
attempt that Resend rejected with `403 validation_error`: *"The
theclouddecoded.com domain is not verified. Please, add and verify your
domain on https://resend.com/domains."*

This is **not specific to the marketing/`news@` stream** — it blocks
`hello@theclouddecoded.com` (transactional) too, since Resend verifies
at the domain level. Every prior session claim of an email being "sent"
or a send path being "live" meant the code path executed without
crashing and Resend's API was reachable — it did NOT mean the message
was actually delivered, because this specific failure mode (403,
domain unverified) had never actually been exercised against a real
Resend send until this alert fired. Concretely at risk right now:
Cloud Decoded welcome emails, dunning, the enterprise-tier owner alert,
this new token-expiry alert, and the entire email lifecycle system from
migration 051 (onboarding/dunning/winback/newsletter/etc.) — none of it
can actually deliver until this is fixed.

**Kelvin-only, cannot be done from here**: add and verify
`theclouddecoded.com` in the Resend dashboard
(https://resend.com/domains) — this means adding the SPF/DKIM/DMARC DNS
records Resend provides at the domain's DNS host. Until this is done,
every `send_email()` call in this codebase will keep failing with this
same 403, non-fatally (callers already catch `EmailError`), but silently
from Kelvin's perspective unless he's watching logs.

### 33. Double-JSON-encoding pattern found in ~10+ other files, not audited or fixed (2026-09-22)

While root-causing the LinkedIn `image_brief` corruption bug (fixed same
day — see the 2026-09-22 Obsidian release log), a static scan for the
same anti-pattern (`json.dumps(...)` passed directly as a positional arg
to `conn.execute`/`fetchrow`/`fetchval`/`fetch` on a connection where
`core/db.py`'s `register_jsonb_codec` is already applied, double-
encoding the value) turned up the identical shape in at least:
`core/hitl.py` (3 occurrences), `core/notification_retry.py` (2),
`api/routes/incidents.py` (4), `api/routes/internal_agents.py` (3),
`core/email_seed.py`, `core/ingestion_log.py` — likely more; the scan
was stopped once the pattern was clearly systemic rather than exhaustively
enumerated.

**Not investigated further this session, deliberately.** A static
`json.dumps()`-into-`execute()` match can't distinguish a real bug from
a legitimate `text` column intentionally storing a JSON string (a
different, valid pattern) — confirming each occurrence needs individual
investigation (check the target column's actual type, check whether that
specific write path has ever been observed producing bad data) well
beyond what fixing the LinkedIn pipeline required. Guessing wrong risks
introducing a new bug while chasing an unconfirmed one.

`tests/test_no_double_json_encoding.py`'s static guard is deliberately
scoped to `api/routes/internal_marketing.py` only (the one pipeline this
session verified end-to-end against a real Postgres connection) rather
than all of `api/`/`core/`, for the same reason.

Recommend a dedicated session: audit each occurrence's target column
type, confirm real vs. legitimate, fix the real ones, then widen the
static guard test to cover the whole codebase once it won't produce
false positives on legitimate `text` columns.
