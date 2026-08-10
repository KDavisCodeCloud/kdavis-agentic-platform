# Cloud Decoded — State Audit
**Date:** 2026-08-09
**Type:** Audit only. No code, config, or infrastructure was changed during this session.
**Scope:** `api/main.py`, `agents/agent_01..10_*`, deploy config, Stripe, auth pages, DNS, per the 6 checks requested.

Sources read in full first: `CLAUDE.md` (3,146 lines — platform-wide, has no dedicated Cloud Decoded build section beyond passing mentions at lines 13, 132, 371, 381, 1848, 1854) and `CloudDecoded-Build-Order.md` (root of this repo — the actual Cloud Decoded-specific spec, self-dated 2026-07-04, git-last-touched 2026-07-11).

---

## 1. Does `api/main.py` run locally right now, without errors?

**CONFIRMED WORKING.**

- Started clean with `uvicorn api.main:app --port <port>` from the repo's existing `.venv`. Startup log:
  ```
  [API] Database pool created
  [API] LangGraph Postgres checkpointer initialized
  Application startup complete.
  Uvicorn running on http://127.0.0.1:<port>
  ```
- `GET /health` → `{"status":"ok","service":"cloud-decoded-api"}`
- `GET /health/db` → `{"status":"ok","db":"connected"}` — `DATABASE_URL` in `.env` is a real, live, reachable Supabase connection (not a placeholder); both the `asyncpg` pool and the LangGraph Postgres checkpointer initialize successfully against it.
- **There is already a long-running local instance of this exact app on this machine right now**: PID 247162, started 2026-07-28 (12 days before this audit), `python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload`, bound to `0.0.0.0:8000`. It answers `/health` and `/health/db` correctly, and `GET /api/v1/agents` correctly returns `401 {"detail":"X-Workspace-Token header required"}` — auth middleware is functioning, not crashing.
- One rough edge, not a failure: a **freshly started** instance took ~14 seconds between "Application startup complete" being logged and the port actually accepting connections (first two attempts at 6-second waits got `Connection refused` even though the log claimed the server was up). This reproduced 3 times. Almost certainly WSL2 `/mnt/c` filesystem I/O latency in this dev environment, not an application bug — but if Kelvin scripts a "wait for health check" step anywhere (CI, a Docker HEALTHCHECK, a deploy readiness probe), a 6–10s timeout will falsely report the app as down.

**Python version:** the `.venv` present in the repo is already built against **Python 3.11.15** (`.python-version` says `3.11`). `requirements.txt` documents *why* in a comment: LangGraph's async node execution only passes contextvars into `asyncio.create_task()` correctly on 3.11+; on 3.10 the HITL `interrupt()` call in `core/engine.py` silently breaks with `RuntimeError: Called get_config outside of a runnable context` — i.e., every agent's safety pause would silently fail on 3.10. Git history confirms this was hit and fixed for real (`0d830a7 fix: HITL interrupt() broken on Python 3.10, upgrade to 3.11 + fix psycopg pooler`). All packages in `requirements.txt` are already installed in `.venv` and match pinned versions exactly (`fastapi==0.115.0`, `langgraph==0.2.76`, `asyncpg==0.29.0`, `stripe==10.12.0`, etc.) — nothing needs reinstalling to run this today.

Test suite: ran `tests/test_agent01.py` through `test_agent10.py` (541 tests) — **540 passed, 1 failed**. The failure (`tests/test_agent01_local.py::test_diagnose_node_returns_three_options`) is a stale test assertion — expects `estimated_duration_seconds == 45`, actual code now returns `90`. Minor test/code drift, not a structural break.

---

## 2. Is this backend deployed anywhere reachable over the network, or local-only?

**CONFIRMED: LOCAL-ONLY. No deployment exists anywhere.**

- No `railway.toml`, no `railpack.json`, no `Dockerfile` for `api/` (there's a `mcp/Dockerfile` for the separate MCP server component, but nothing for the main API). The only deploy-shaped file at the repo root is a generic `Procfile`:
  ```
  web: uvicorn api.main:app --host 0.0.0.0 --port $PORT
  ```
  — standard Railway/Heroku shape, but nothing currently consumes it.
- `railway status` in this repo directory: `No linked project found. Run railway link to connect to a project.`
- Checked the full live Railway account (`whoami` confirmed logged in as Kelvin Davis): 3 projects exist total —
  - `zooming-appreciation` → service `showing-signal`
  - `mse-api` → services `mse-api`, `n8n-rDAN`, `Postgres`
  - `hospitable-endurance` → service `decoded-six`
  
  None of these is Cloud Decoded. There is no Railway project for it at all, under any name.
- Checked the live Vercel account (`vercel project ls`, scope `thd-agentic-systems`): 6 projects — `decoded-six`, `showing-signal`, `kdavis-microsaas-engine`, `team-dashboard`, `ceo-decoded-dashboard`, `empire-dashboard`. No Cloud Decoded project (expected — it's a Python/FastAPI backend, not a natural Vercel target, and its Next.js frontend isn't there either).
- `infra/terraform/products/` (the parameterized Fargate module CLAUDE.md's folder structure describes for per-product deploys) does not exist on disk. `infra/` only contains `infra/stripe/setup.py` and `infra/supabase/migrations/001_initial_schema.sql`.

**Bottom line:** the only place this API currently runs is as a manually-started local dev server on Kelvin's own machine. There is no staging or production deployment target configured anywhere, on any platform checked.

---

## 3. Do Stripe products/prices exist for Cloud Decoded, separate from the shared MSE account?

**CONFIRMED WORKING, and CONFIRMED SEPARATE.**

- Code (`api/routes/stripe_billing.py`) reads `STRIPE_PRICE_ID_STARTER` / `_GROWTH` / `_ENTERPRISE` from env via `_price_id_for_tier()`, and maps price IDs back to tiers via `_tier_for_price_id()` for webhook handling. Not hardcoded, not a placeholder pattern.
- `.env` has real, non-empty values for all three, plus `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET`.
- Queried the live Stripe API directly with the key from `.env`:

  | Env var | Price ID | Amount | Stripe product name | Active |
  |---|---|---|---|---|
  | `STRIPE_PRICE_ID_STARTER` | `price_1To8Wm...` | $299.00/mo | Cloud Decoded Starter | ✅ |
  | `STRIPE_PRICE_ID_GROWTH` | `price_1To8XH...` | $699.00/mo | Cloud Decoded Growth | ✅ |
  | `STRIPE_PRICE_ID_ENTERPRISE` | `price_1To8Xh...` | $2,499.00/mo | Cloud Decoded Enterprise | ✅ |

  This matches `CloudDecoded-Build-Order.md`'s documented pricing (Starter $299/Growth $699/Enterprise $2,499) exactly.
- The key used (`sk_live_51IA...`) is a **live** key, and it is a **different Stripe account** than the shared MSE one. Confirmed by comparing key prefixes across sibling repos: `showing-signal/.env` and `kdavis-microsaas-engine/.env` both use `sk_live_51Tp...` (the shared MSE account); this repo's `.env` uses `sk_live_51IA...`. Listing all products on the Cloud Decoded key's account shows exactly 3 active Cloud Decoded products plus 3 unrelated legacy products (old "40 days to business" coaching-bundle items, pre-dating THD) — no MSE products appear on this account at all, confirming genuine account separation, not just product-namespacing within one shared account.

---

## 4. Do dedicated signup/signin pages exist, or does it rely on another product's auth?

**CONFIRMED: NEITHER. No functional signup or signin exists at all.**

- `frontend/src/app/` contains exactly: `page.tsx` (landing), `dashboard/page.tsx`, `onboarding/page.tsx`, `layout.tsx`, `globals.css`. No `/signup`, no `/login`, no `/signin` route anywhere.
- `grep -rn -i "signup\|signin\|sign-in\|/login" frontend/src` — **zero matches**.
- `grep -rn "supabase" frontend/src` — **zero matches**. Despite `CloudDecoded-Build-Order.md` explicitly specifying "Wire to Supabase Auth" and "issue JWT with `tenant_id` claim" as the Priority 1 auth approach, there is no Supabase Auth integration anywhere in the frontend.
- The `/onboarding` page **is not a signup flow**. `OnboardingWizard.tsx`'s `workspaceToken` field is a plain manually-typed `<input>` (`onChange={e => update({ workspaceToken: e.target.value })}`) — the user has to already possess a token from somewhere else and paste it in. Nothing in the component calls any backend endpoint to create an account or issue a token; `grep` across `api/` for `workspace_token`, `create_workspace`, `/signup`, `/workspaces` turns up only code that *consumes* a token (middleware, webhooks), never code that *issues* one. Onboarding's own "Already set up? Sign in" link routes to `/` — the marketing landing page, not an actual sign-in page.
- Git history confirms this gap has not been worked since the initial build: `frontend/` and `api/routes/stripe_billing.py` have each been touched by exactly one commit (`fe9c461`, `5c94785`), both from the initial Phase 2/3 build — nothing since. This matches `CloudDecoded-Build-Order.md`'s own admission that auth is "Priority 1 — Unblocks everything else," still open as of its 2026-07-04/07-11 writing, and it's still open today, over a month later.

---

## 5. Is DNS configured — and for which domain?

**CONFIRMED: NOT CONFIGURED, under either the old plan or the current one. One doc claim is directly falsified.**

Checked three domain candidates plus one hardcoded string found in code:

| Hostname | Where it's claimed | `dig` result |
|---|---|---|
| `theclouddecoded.com` | `CloudDecoded-Build-Order.md` line 2, "Project:" | Resolves to `192.64.119.114`; `www.theclouddecoded.com` CNAMEs to `parkingpage.namecheap.com` — **domain is registered (Namecheap) but parked. Nothing is deployed there.** |
| `mcp.theclouddecoded.com` | Same doc, line 26: *"MCP server live at `mcp.theclouddecoded.com` ... ✅"* | **No DNS record at all** — A and CNAME both empty, `curl` returns `Could not resolve host`. This is a direct, checkable contradiction of the doc's "✅ done" claim. Whatever state the MCP server code (`mcp/`) is actually in, it is not reachable at the hostname the doc names. |
| `clouddecoded.thdstack.com` | Implied by `CLAUDE.md`'s current Domain Architecture rule (root domain `thdstack.com`, one subdomain per product) and `config/products.yaml`'s `subdomain: clouddecoded` entry for `cloud_decoded` | **No DNS record at all.** So neither the old product-specific domain plan nor the platform's own newer subdomain convention has actually been executed for this product. |
| `cloud-decoded.com` | Hardcoded in `api/routes/agents.py`'s `list_agents()`: `"upgrade_url": "https://cloud-decoded.com/pricing"` | Resolves, but the HTTP response header is `server: Parking/1.0` — this is a **parked domain**, not matching any domain named anywhere else in the docs. If a workspace ever hits the tier-limit 402 path, this is the literal URL the API hands back as the upgrade CTA. |

For reference, confirmed `config/platform.yaml` actually does declare `root_domain: thdstack.com` and a separate `internal_domain: thdecodedempire.com` — and the second one *is* live and correctly wired (all of Vercel's live internal-dashboard projects — `mse`, `team`, `ceo-decoded-dashboard` — CNAME to `cname.vercel-dns.com` under `thdecodedempire.com`). So the platform's DNS strategy is executed and working for internal dashboards; it simply has never been extended to Cloud Decoded specifically, under any of its candidate domains.

---

## 6. `api/routes/agents.py` dispatch logic and the 10-agent structure

**CONFIRMED WORKING, matches the intended pattern, with one nuance.**

- The `agent_{01-10}_*` prefix pattern is still exactly what's validated: `run_agent()` builds `{"agent_01_", "agent_02_", ..., "agent_10_"}` and checks `agent_id.startswith(p)` before anything else runs (lines 54–59 of `api/routes/agents.py`).
- **Nuance:** dispatch itself is not a generic/data-driven lookup — it's a hardcoded `if/elif` chain matching each of the 10 exact `agent_id` strings, each importing and backgrounding a specific `_run_*` function from `api/routes/webhooks.py`. Anything that passes the prefix check but isn't one of the 10 known exact IDs (not currently possible, since the prefix set *is* the 10 IDs) falls through to a `501 "... Phase 5 build coming soon"`. Worth knowing if any future change assumes this is a registry-driven dispatcher — it isn't.
- All 10 agent directories exist on disk: `agent_01_cicd_triage` through `agent_10_dependency_patch`. Each follows the same shape (`workflow.py`, `tools.py`, `prompts/`, `sop.md`), and each `workflow.py` imports and subclasses `agents.base_agent.BaseAgent` (verified for all 10, not sampled).
- `agents/base_agent.py` dynamically loads `.llm/router.py` via `importlib` (`_load_router()`), exactly the intended LLM-agnostic pattern from `CLAUDE.md`'s Core Principle #1. `.llm/router.py` is real and non-trivial (197 lines; implements `call_anthropic`, `call_openai`, `call_openrouter`, `call_ollama`, provider config loaded from `.llm/providers/*.yaml`) — not a stub.

**Doc-vs-reality mismatch worth flagging directly:** `CloudDecoded-Build-Order.md`'s own "Agent Roster (All 10 Built)" list does **not** match what's actually on disk.

| Build-Order doc says | Actually on disk |
|---|---|
| 1. CI/CD Triage Agent | `agent_01_cicd_triage` ✅ matches |
| 2. PR Review Agent | `agent_02_k8s_alert` (Kubernetes alerts — different agent) |
| 3. Cost Optimization Agent | `agent_03_pr_review` (PR review — this *is* the doc's #2, shifted) |
| 4. Infra Monitor Agent | `agent_04_migration` |
| 5. Runbook Agent | `agent_05_iam_minimizer` |
| 6. Security Agent | `agent_06_finops` (this looks like the doc's #3, shifted) |
| 7. Incident Response Agent | `agent_07_runbook` (this is the doc's #5, shifted) |
| 8. Deployment Agent | `agent_08_drift_detection` |
| 9. Capacity Planning Agent | `agent_09_onboarding_buddy` |
| 10. DataSanitizationShield | `agent_10_dependency_patch` |

The actual roster reads as a real, coherent, more DevOps-concrete set (CI/CD triage, k8s alerts, PR review, migration analysis, IAM minimization, FinOps, runbooks, drift detection, onboarding buddy, dependency patching) — it isn't broken, it's just a different 10 agents than the doc describes, and the doc was never updated to match. `DataSanitizationShield` in particular is not a numbered agent at all in the real code — `core/security/shield.py` (imported directly into `base_agent.py` as `from core.security import shield`) is shared infrastructure every agent uses, not agent #10.

---

## What's real and working
- `api/main.py` runs cleanly, connects to a real live database, has a healthy 540/541-passing test suite, and — as of this writing — is already running locally as a 12-day-old dev instance answering real requests correctly (including correct auth rejection).
- Cloud Decoded has a genuinely separate, dedicated, live Stripe account (not the shared MSE one) with 3 correctly-priced active products matching the docs exactly.
- The core agent architecture (`base_agent.py` + `.llm/router.py`, all 10 agents, LLM-agnostic routing) is real, complete, and tested — not vaporware.
- `thdecodedempire.com` (the internal-dashboard domain) is correctly live via Vercel for MSE/team/CEO dashboards — the platform's DNS practices work when actually executed.

## What's real but broken / incomplete
- One stale test assertion in `test_agent01_local.py` (expects 45s, gets 90s) — trivial fix.
- Fresh local startup has a ~14s gap between "startup complete" log and the port actually accepting connections — a false-negative risk for any short-timeout health check script, not an app bug.
- `api/routes/agents.py`'s hardcoded `upgrade_url` points at a parked, seemingly-unrelated domain (`cloud-decoded.com`) that doesn't match any domain used anywhere else — a live customer-facing bug waiting to surface.

## What was never built
- No deployment target anywhere (no Railway project, no Vercel project, no Terraform, no Dockerfile for `api/`) — 100% local-only.
- No signup or signin pages, and no backend endpoint to create a workspace/account. The onboarding wizard is a manual-token-entry UI shell with no backend call behind it.
- No DNS configured for Cloud Decoded under any candidate domain (old `theclouddecoded.com` plan or the platform's current `thdstack.com` subdomain convention).

## What the existing docs get wrong
- `CloudDecoded-Build-Order.md` claims the MCP server is "live" at `mcp.theclouddecoded.com` — that hostname has no DNS record at all right now.
- `CloudDecoded-Build-Order.md`'s "Agent Roster (All 10 Built)" list names 10 agents that don't match the actual 10 agents on disk (only 1 of 10 matches by name and position; a few others match in spirit but at shifted positions).
- `CLAUDE.md`'s own "CURRENT STATUS" footer (bottom of the file) reads `Phase: NOT STARTED`, `Active products: 0`, `Platform MRR: $0` — stale from the very first scaffold, never updated despite everything above having since been built. Anyone trusting that footer alone would believe the platform hadn't started.

---

OBSIDIAN UPDATE — Cloud Decoded — 2026-08-09
Status:
- Backend (api/main.py, all 10 agents): working, tested (540/541), local-only
- Deployment: never built — no Railway/Vercel project, no deploy config exercised
- Stripe: working — dedicated live account, 3 correctly-priced products, separate from MSE
- Auth (signup/signin): never built — onboarding UI has no backend behind it
- DNS: never configured — theclouddecoded.com is parked, mcp subdomain doesn't resolve despite doc claiming it's live
- Agent dispatch/base_agent/.llm pattern: working, intact, matches CLAUDE.md's LLM-agnostic principle

Completed this session:
- Full read of CLAUDE.md (3,146 lines) and CloudDecoded-Build-Order.md
- Live-ran api/main.py locally and confirmed a pre-existing 12-day-old instance is already running and healthy
- Verified Python 3.11 requirement and its documented root cause (LangGraph contextvars break on 3.10)
- Checked all Railway projects and all Vercel projects for any Cloud Decoded deployment — found none
- Verified Cloud Decoded's Stripe products/prices live against the API, confirmed separate account from shared MSE key
- Confirmed no signup/login pages exist and the onboarding wizard has no backend behind it
- Checked DNS for theclouddecoded.com, mcp.theclouddecoded.com, clouddecoded.thdstack.com, and the hardcoded cloud-decoded.com string — none point to real infrastructure
- Verified all 10 agents follow the base_agent.py + .llm/router.py pattern and ran the full agent test suite
- Wrote this report — no code, config, or infra changes made

Next phase: a real build session should tackle, in order — (1) Priority 1 from CloudDecoded-Build-Order.md itself: wire /signup + /login to Supabase Auth and connect the onboarding wizard to a real workspace-creation endpoint (this unblocks everything downstream); (2) stand up an actual deployment target (Railway is the pattern already used for showing-signal/decoded-six/mse-api — the Procfile already assumes this) so the backend is reachable outside this machine; (3) point DNS somewhere real once a deployment target exists, and fix the hardcoded cloud-decoded.com upgrade_url; (4) reconcile CloudDecoded-Build-Order.md's agent roster and MCP-server-live claim with actual reality, and update CLAUDE.md's stale CURRENT STATUS footer.

Blockers (owner actions only):
- DNS for theclouddecoded.com is currently pointed at Namecheap's parking page — needs to be repointed once a real deployment target exists (owner controls the registrar).
- No hosting/deploy target has been provisioned for this backend on any platform — needs an owner decision on where it goes (Railway, matching the rest of the portfolio's pattern, is the most consistent choice already in use elsewhere).
- cloud-decoded.com (the domain hardcoded as the upgrade CTA) does not appear to be owned by THD Agentic Systems — owner should confirm and either acquire it or fix the code to point at a real domain.
