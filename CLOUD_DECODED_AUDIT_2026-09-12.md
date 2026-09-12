# Cloud Decoded — State Audit
**Date:** 2026-09-12 (full-day rewrite — supersedes the earlier version of this same file)
**Type:** Refresh of `CLOUD_DECODED_AUDIT_2026-08-09.md`. Every finding below was independently re-checked against live systems (Railway, Vercel, Stripe, DNS, the test suite, real API calls) — not carried forward from a prior audit or from memory.
**Why a rewrite, not another append:** This file was updated twice earlier today as gaps closed one at a time. By end of day the delta is large enough (MCP server deployed, all 5 small gaps closed, a full Azure rollout across 4 repos) that a clean rewrite is more useful than a fourth stacked diff.

---

## What changed today (2026-09-11 → 2026-09-12, in order)

1. **Paywall closed.** Every new workspace locks (`pending_payment`) until Stripe checkout completes; suspend/reactivate/rotate-token are real, with a `ceo-dashboard` admin UI (`/dashboard/customers`).
2. **Real marketing/auth pages shipped**, replacing the bare "paste your token" screen: `/`, `/login`, `/signup`, `/checkout`, `/billing`, a real `not-found.tsx`.
3. **Three real Stripe bugs found and fixed** by live-testing production Stripe for the first time (a `pending_payment` checkout deadlock, missing `STRIPE_PRICE_ID_*`/`FRONTEND_URL` on Railway, an invalid `customer_creation` param).
4. **Five smaller gaps closed**: `www.theclouddecoded.com` DNS, a hardcoded parked-domain `upgrade_url`, a LangGraph test stub that silently clobbered the real installed package, two stale `GAPS.md` entries, `ContentPipeline.tsx`'s raw-fetch inconsistency.
5. **A sixth, more serious bug found while fixing #4**: migration 004 (`mcp_api_keys`/`mcp_audit_log`) had never been applied to the live DB — the *already-deployed* `POST /mcp/keys` endpoint was 500ing for any real customer. Fixed; confirmed with a real generated key.
6. **The MCP server is now deployed** — new Railway service `cloud-decoded-mcp`, shared secret wired to the main backend, DNS pointed at `mcp.theclouddecoded.com`, 24 new auth tests (was 0), core key-generation flow verified end to end. **TLS certificate issuance is still pending** as of this writing — DNS is correct and propagated; Railway's own docs say this normally completes within an hour but can take up to 72. Not a configuration problem, just genuinely not done yet.
7. **A full Azure rollout across 4 repos** (`kdavis-cloud-audit`, `kdavis-finops-agent`, `kdavis-compliance-agent`, `kdavis-agentic-platform`) — see its own section below. Live-verified end to end with a real throwaway workspace and a real Azure SDK error surfacing correctly through all four layers.

---

## 1. Backend — deployed, tested, healthy

- Railway project `kdavis-agentic-platform`, live at `https://kdavis-agentic-platform-production.up.railway.app`. `/health` → ok.
- Satellite agent services also deployed and healthy: `kdavis-finops-agent-production.up.railway.app`, `kdavis-compliance-agent-production.up.railway.app`, and the new `cloud-decoded-mcp` service (DNS correct, TLS pending).
- Full suite: **1099 passed, 4 failed** — same 4 pre-existing, unrelated failures as every prior audit (`test_diagnose_node_returns_three_options`, 3 `test_security.py` redaction tests). Nothing shipped today introduced a new failure.

## 2. Frontend — deployed, live, real paywall

- Vercel project `frontend`, aliased to `theclouddecoded.com`, `www.theclouddecoded.com`, and `mcp.theclouddecoded.com`.
- Verified live: `/`, `/login`, `/signup`, `/checkout`, `/billing` all 200; a nonexistent path returns the real designed 404, not Next's generic one; `/mcp/keys` no longer 500s.
- `POST /workspaces` is public by design (the only way to start a signup); every other route requires payment.

## 3. Stripe — unchanged, still real, still separate

- Same dedicated live account, 3 correctly-priced products (Starter $299/Growth $699/Enterprise $2,499). Real end-to-end checkout re-verified this session.

## 4. DNS — fully resolved

| Hostname | Status |
|---|---|
| `theclouddecoded.com` | ✅ Live, Vercel |
| `www.theclouddecoded.com` | ✅ Fixed today — was parked, now points at the same Vercel deployment |
| `mcp.theclouddecoded.com` | ✅ DNS correct, propagated; TLS cert still issuing |
| `cloud-decoded.com` (hardcoded `upgrade_url`) | ✅ Fixed today — now points at `theclouddecoded.com/#pricing` |

## 5. The MCP server — deployed, one thing outstanding

- New `cloud-decoded-mcp` Railway service, built from `mcp/`'s existing Dockerfile. Fixed a real deploy bug along the way: the Dockerfile hardcodes port 8001 instead of reading Railway's injected `$PORT`, so the healthcheck was probing the wrong port — fixed by setting `PORT=8001` explicitly (Railway's documented fix).
- 24 new tests (`test_apikey.py`, `test_oauth.py`) — was 0 coverage on this service before today.
- Core integration confirmed working: generated a real `cd_mcp_...` API key against a throwaway test workspace, successfully, using the now-fixed migration 004.
- **Outstanding: TLS certificate still provisioning.** Not a config issue — DNS is correct and propagated. Final live tool-call verification (a real SSE call through the deployed server) is blocked on this, not on anything else.
- **Known limitation, not a bug**: Enterprise-tier MCP access requires OAuth 2.1, which requires a per-customer Supabase Auth account — and Cloud Decoded's real auth model is one shared workspace token per company, no per-user accounts. The tier gate (`OAUTH_REQUIRED_TIERS = {"enterprise"}`) is correctly coded; there's just no real path for an Enterprise customer to use it yet. Starter/Growth via API key works today.

## 6. Azure rollout — 4 repos, live-verified

Full context: Kelvin resolved a local `az login` MFA/token-cache issue partway through this session, which triggered scoping and building Azure support across the whole FinOps/Compliance product line. Four repos, in dependency order:

- **`kdavis-cloud-audit`**: Azure provider (`AzureProvider`) was already complete from a prior session (Phase 2B, 95 tests). **Correction found live this session**: `az account show` succeeding does **not** mean a real ARM token can be acquired — `az account get-access-token --resource https://management.azure.com/` still hits the original `AADSTS50076` MFA Conditional Access error. The planned new `_collect_regulatory_compliance` collector (Defender for Cloud's Regulatory Compliance API, which returns pass/fail already labeled with real CIS control IDs) is still blocked on this. See the step-by-step fix instructions below.
- **`kdavis-finops-agent`**: real Azure Service Principal onboarding shipped — `core/azure_onboarding.py`, `security/encryption.py`, migration 002, new `PATCH /tenants/{id}/azure-credentials` route, scan dispatch branches on an explicit `connected_provider` column. 49 tests (was 26).
- **`kdavis-compliance-agent`**: same onboarding scaffolding. Azure *scanning* deliberately returns `501` until a real CIS Microsoft Azure Foundations Benchmark mapping exists — matches this repo's own "never invent a pass/fail for a control this scan can't verify" discipline, same reasoning that kept AWS Phase 1 to 4 controls instead of guessing at 62. 56 tests (was 33).
- **`kdavis-agentic-platform`**: the actual customer-facing path — `AgentConnectFlow.tsx` now has a real AWS/Azure toggle with a working Service Principal form, proxied through new `POST /finops-agent/verify-azure` and `/compliance-agent/verify-azure` routes. Without this piece, the backend work would have been unreachable by any real customer.
- **Two real bugs caught by this rollout's own review before shipping**: both `finops-agent` and `compliance-agent` hardcoded the literal string `'aws'` in their scan-insert SQL regardless of actual provider; both `get_tenant()` middleware functions were missing the new Azure columns from their SELECT, invisible to every existing test since they all bypass that query with hand-built fake dicts. New `test_auth.py` in both repos now pins the real SQL shape.
- **Live-verified end to end**: created a real throwaway workspace, called the full proxy chain (platform → client → finops-agent → Azure SDK) with fake credentials, and got back a real Azure authentication error correctly surfaced through all four layers as a 400 — not a crash. Test workspace and its tenant row deleted immediately after.

## 7. Agent roster / dispatch doc mismatch — unchanged, still wrong

- `CloudDecoded-Build-Order.md` (untouched since 2026-07-11) still names the wrong 10-agent roster and still claims the MCP server is "live" — that claim is now closer to true than it's ever been (deployed, TLS pending) but still not accurate as written.
- `CLAUDE.md`'s "CURRENT STATUS" footer is still the original scaffold placeholder.

---

## What's real and working
- Backend, frontend, Stripe, DNS (all four hostnames), token revocation with a real admin UI.
- The MCP server is deployed and its core integration verified — TLS is the only thing left.
- Azure Service Principal onboarding is real and live-verified for both FinOps and Compliance.

## What's real but incomplete
- MCP server TLS certificate still provisioning (no action needed, just time).
- Compliance's Azure CIS mapping doesn't exist yet — onboarding works, scanning returns 501.
- Enterprise-tier MCP access has no real path (needs per-customer accounts that don't exist).

## What was never built / still blocked
- `kdavis-cloud-audit`'s regulatory-compliance collector — blocked on a real Azure `az login` with MFA actually completing (see instructions below).
- `CloudDecoded-Build-Order.md` and `CLAUDE.md`'s status footer remain unreconciled with reality.

---

OBSIDIAN UPDATE — Cloud Decoded — 2026-09-12 (full day)
Status:
- Backend/frontend/Stripe/DNS: all real, live, verified (1099/1103 tests passing across the main repo)
- MCP server: deployed, core integration verified, TLS cert still issuing
- Azure: real onboarding live for FinOps + Compliance across all 4 repos; Compliance's actual CIS-Azure scanning still gated on a new upstream collector, itself blocked on a real `az login` MFA completion
- Agent roster / Build-Order doc / CLAUDE.md footer: still stale, unreconciled

Completed today: paywall, real pages, 3 Stripe bugs, 5 small gaps + 1 more serious one (mcp_api_keys migration) found while fixing them, MCP server deployed with real test coverage, full 4-repo Azure rollout live-verified end to end.

Next: (1) Kelvin completes a real `az login` with MFA — unblocks the regulatory-compliance collector and the CIS Azure mapping; (2) once TLS clears on `cloud-decoded-mcp`, do the final live SSE tool-call verification; (3) reconcile `CloudDecoded-Build-Order.md`/`CLAUDE.md`'s stale claims with reality.

Blockers (owner actions only):
- Azure `az login` MFA completion — see step-by-step instructions delivered alongside this audit update.
- MCP server TLS — no action needed, just Railway/Let's Encrypt latency.
