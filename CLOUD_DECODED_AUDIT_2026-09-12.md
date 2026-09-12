# Cloud Decoded — State Audit
**Date:** 2026-09-12
**Type:** Refresh of `CLOUD_DECODED_AUDIT_2026-08-09.md`. Every finding below was independently re-checked against live systems this session (Railway, Vercel, Stripe, DNS, the test suite) — not carried forward from the prior audit or from memory.
**Why now:** The prior audit's headline finding — no deployment, no auth, no DNS — is no longer true. A full paywall + real frontend build shipped between 2026-09-11 and today. This audit exists so the doc catches up to the repo instead of the repo drifting further from the last written record of it.

---

## What changed since 2026-08-09

- **Backend deployed.** Railway project `kdavis-agentic-platform`, service `kdavis-agentic-platform`, live at `https://kdavis-agentic-platform-production.up.railway.app`. Latest deploy `SUCCESS` on commit `5026082`. `/health` → `{"status":"ok","service":"cloud-decoded-api"}`.
- **Real paywall exists.** `POST /workspaces` creates a workspace locked in `pending_payment` by default (migration `021_workspace_pending_payment.sql`); `api/middleware/auth.py`'s `get_workspace` blocks `pending_payment`/`canceled`/`suspended` on every protected route with a 402. The only way out is completing Stripe Checkout, which the webhook flips to `active`. Before this shipped, a workspace was fully functional, free, forever, with zero Stripe involvement — that gap is closed.
- **Token revocation exists.** `api/routes/internal_workspaces.py` (owner/team-auth only): suspend (ToS-violation path, independent of Stripe), reactivate, rotate-token (the real revocation mechanism — old token stops matching the moment the new hash is written). Now has a real UI too: `ceo-dashboard`'s new `/dashboard/customers` page lists every workspace and exposes all three actions.
- **Real marketing/auth pages exist**, built from `Cloud Decoded Hero Design.zip`'s handoff, replacing the bare "paste your workspace token" screen: `/` (landing), `/login`, `/signup`, `/checkout`, `/billing`, and a real `not-found.tsx` (404). The old page's leaked "API online/offline" debug text is gone.
- **A locked workspace now gets a real next step instead of a raw error.** `lib/api.ts`'s shared request layer redirects any 402 to `/billing`, which reads status through a new `get_workspace_any_status` dependency (never blocks) and shows the right action per status: complete signup, reactivate, contact support, or manage billing.
- **Three real bugs were found and fixed by live-testing against production Stripe for the first time** (never caught by unit tests, which all mock `stripe.checkout.Session.create`): a `pending_payment` deadlock that made checkout permanently unreachable for every new signup; `STRIPE_PRICE_ID_*`/`FRONTEND_URL` never set on Railway (checkout redirects were pointing at `localhost:3000`); and an invalid `customer_creation` param Stripe rejects outright in subscription mode.
- **Test suite grew from 541 tests (agents only) to 1096** across the whole backend. Current: **1092 passed, 4 failed** — same 4 pre-existing, unrelated failures as before (`test_diagnose_node_returns_three_options` stale assertion, 3 `test_security.py` redaction-pattern tests). Nothing touched this session introduced a new failure.

---

## 1. Does the backend run, and is it reachable over the network?

**CONFIRMED: yes to both — this is the headline change from the last audit.**

- Deployed on Railway (see above), not local-only. `GET /health` and the full `/api/v1/*` surface are reachable from the public internet.
- The two satellite agent services referenced from Cloud Decoded's own dashboard tabs are also deployed and healthy: `kdavis-compliance-agent-production.up.railway.app` and `kdavis-finops-agent-production.up.railway.app`, both `/health` → 200.
- Full suite: 1092/1096 passing (see above for the 4 pre-existing failures — unrelated to anything shipped this session).

## 2. Frontend — deployed and live, real pages, real paywall

**CONFIRMED WORKING**, superseding the 2026-08-09 finding of "no signup/signin exists at all."

- Vercel project `frontend` (scope `thd-agentic-systems`), aliased to `theclouddecoded.com`. Latest deploy includes the real 404 page and billing UI.
- Verified live: `/`, `/login`, `/signup`, `/checkout`, `/billing` all return 200; a nonexistent path returns a real 404 status with the designed error page (not Next's generic one).
- `POST /workspaces` is real and public (by design — it's the only way to start a signup), returns a locked token; every other route requires payment to unlock. This is the actual fix for the prior audit's "anyone can self-serve a working workspace forever, free" finding.

## 3. Stripe — unchanged, still real, still separate

**CONFIRMED WORKING** — re-verified this session by running an actual signup through to a live `checkout.stripe.com/c/pay/cs_live_...` redirect, not just reading the code.

- Same dedicated live Stripe account as the 2026-08-09 audit found (`sk_live_51IA...`, distinct from the shared MSE account's `sk_live_51Tp...`).
- Same 3 active priced products: Starter $299/mo, Growth $699/mo, Enterprise $2,499/mo.
- `STRIPE_PRICE_ID_STARTER/GROWTH/ENTERPRISE` and `FRONTEND_URL` are now correctly set on the live Railway service (previously only in local `.env` — see "What changed" above).

## 4. DNS — apex fixed, two real gaps remain

**PARTIALLY CONFIRMED — better than 2026-08-09, but not fully clean.**

| Hostname | `dig` result today | Status |
|---|---|---|
| `theclouddecoded.com` | `76.76.21.21` (Vercel) | ✅ Live, serves the real frontend |
| `www.theclouddecoded.com` | `parkingpage.namecheap.com.` | ❌ Still parked — a visitor typing `www.` gets Namecheap's parking page, not the product |
| `mcp.theclouddecoded.com` | `parking.d.parity.domains.` → `2.59.170.19`/`104.219.250.36` | ❌ Still not pointed at real infrastructure — see finding below, this one's bigger than DNS |
| `cloud-decoded.com` (hardcoded in `api/routes/agents.py`'s `upgrade_url`) | Still resolves to a `Parking/1.0` server | ❌ Unchanged from the last audit — still a live customer-facing bug (see below) |

The apex fix is real and closes most of the prior finding, but `www` and the hardcoded `upgrade_url` are two small, easy, still-open loose ends from the same finding — neither takes new infrastructure, just a DNS record and a one-line code fix.

## 5. The MCP server — the single largest remaining gap

**NOT DEPLOYED. This is worse than a DNS gap: the customer-facing UI already promises it works.**

- `mcp/` is a complete, separately-built FastAPI+FastMCP service (OAuth 2.1 discovery endpoints, SSE transport, per-tool kill switches, tier gating, rate limiting) — last touched 2026-08-13, never deployed anywhere, no Railway project, no working DNS for `mcp.theclouddecoded.com`.
- `frontend/src/components/IntegrationsDashboard.tsx` already ships a full "Connect to Claude Code or Cursor" flow: generates real API keys via `POST /mcp/keys`, hands out pre-filled config pointing at `https://mcp.theclouddecoded.com/mcp`, and has a "Test connection" button.
- Net effect: any paying Growth/Enterprise customer who follows Cloud Decoded's own onboarding UI today hits a dead endpoint. This is a real, currently-live broken promise, not a theoretical gap.
- Flagged to Kelvin 2026-09-11/12; deliberately not actioned without a decision, since fixing it means standing up new public-facing infrastructure (new Railway service, new subdomain, a shared secret with the main backend) — a different risk class than the smaller fixes in this audit.

## 6. Agent roster / dispatch — unchanged, doc still wrong

**CONFIRMED UNCHANGED from 2026-08-09** — `CloudDecoded-Build-Order.md` has not been touched since 2026-07-11, before any of this session's or last session's work.

- The real 10-agent roster (`agent_01_cicd_triage` … `agent_10_dependency_patch`) still doesn't match what `CloudDecoded-Build-Order.md`'s "Agent Roster (All 10 Built)" list claims — same mismatch table as the last audit, unresolved.
- The doc's claim that the MCP server is "live at `mcp.theclouddecoded.com`" is still directly false (see #5).
- `CLAUDE.md`'s "CURRENT STATUS" footer (`Phase: NOT STARTED`, `Active products: 0`, `Platform MRR: $0`) is still stale from the initial scaffold.

---

## What's real and working
- Backend deployed, tested (1092/1096), reachable — not local-only anymore.
- Real paywall: no free/unpaid path to a working workspace exists.
- Token revocation with a real admin UI (`ceo-dashboard` → Customers).
- Real marketing/login/signup/checkout/billing/404 pages, verified live in production.
- Stripe: separate live account, correct pricing, real end-to-end checkout verified.
- `theclouddecoded.com` apex is live and correct.

## What's real but broken / incomplete
- `www.theclouddecoded.com` still parked.
- `api/routes/agents.py`'s hardcoded `upgrade_url` still points at a parked, unrelated domain.
- The stale test assertion and 3 security-redaction test failures from before are still present, still unrelated to anything shipped since.

## What was never built
- The MCP server has never been deployed anywhere, despite the dashboard UI already advertising it as working (#5 above — the priority item).
- `CloudDecoded-Build-Order.md` has never been reconciled with the real agent roster or the real (non-)deployment state of the MCP server.
- `CLAUDE.md`'s CURRENT STATUS footer has never been updated.

---

OBSIDIAN UPDATE — Cloud Decoded — 2026-09-12
Status:
- Backend: deployed on Railway, live, tested (1092/1096, 4 pre-existing unrelated failures)
- Paywall: real — workspaces locked until Stripe checkout completes; suspend/reactivate/rotate-token all real, with a ceo-dashboard admin UI
- Frontend: real marketing/login/signup/checkout/billing/404 pages live at theclouddecoded.com
- Stripe: unchanged — separate live account, 3 correctly-priced products, real checkout verified end to end
- DNS: apex fixed and live; www still parked; mcp subdomain still parked (server never deployed)
- MCP server: fully built, never deployed — the biggest open gap, made worse by the dashboard UI already advertising it as working; awaiting Kelvin's decision on deploy vs. pull the UI
- Agent roster / Build-Order doc / CLAUDE.md footer: unchanged, still stale/wrong

Completed this session (and the session immediately before it):
- Closed the paywall gap end to end: migration, auth middleware, revocation endpoints, admin UI
- Built and deployed the real marketing/auth/billing/404 pages from the design handoff
- Found and fixed 3 real production bugs via live Stripe verification (not caught by mocks)
- Found the MCP server gap and flagged it rather than unilaterally deploying new public infrastructure
- Refreshed this audit against live systems (Railway, Vercel, Stripe, DNS, test suite) rather than carrying forward stale claims

Next phase, in order: (1) Kelvin's decision on the MCP server — deploy it for real, or pull the Integrations UI until it's ready; (2) fix `www.theclouddecoded.com` DNS and the hardcoded `upgrade_url` — both small, no new infrastructure; (3) reconcile `CloudDecoded-Build-Order.md`'s agent roster and MCP claims with reality, and update `CLAUDE.md`'s stale footer.

Blockers (owner actions only):
- MCP server deployment is an infrastructure decision, not a code fix — needs Kelvin's call given the new-subdomain/new-service scope.
- `www` DNS and `cloud-decoded.com` domain ownership are registrar-level, owner-controlled.
