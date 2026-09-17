# SOP: 24-Gap-Closure Build — Kelvin's 7 Locked Decisions
Date: 2026-09-17
Status: Live — deployed, verified, committed, pushed

---

## Scope

After the Phases 3-7 final report, Kelvin made explicit decisions on all
7 open items it raised. This pass implements 1-5 and 7, records item 6
(explicitly not built), and closes out the whole 24-gap-closure run.

## 1. Auth rate limiting — documented, no code

Decision: do not proxy auth through the backend; Supabase's own native
rate limits are the accepted control. Added a new answer to
`docs/customer/security-questionnaire-response.md` right after the
existing "Authentication for the product itself" entry, stating this
plainly as a settled decision (not a gap) and noting Kelvin verifies the
actual Supabase dashboard rate-limit configuration himself — that
configuration lives outside this codebase and this doc doesn't claim to
confirm it.

## 2. past_due — banner, access unchanged

Re-verified `_BLOCKED_SUBSCRIPTION_STATUSES = ("canceled", "suspended",
"pending_payment")` in `api/middleware/auth.py` — `past_due` still
absent, confirmed unchanged. New `PastDueBanner.tsx`: self-fetches
`GET /billing/status`, renders on every dashboard tab (not just
`/billing`) when `subscription_status === 'past_due'`, links straight to
the Stripe billing portal. No dismiss control needed — it clears itself
by no longer rendering the moment the next fetch shows a different
status.

## 3. Downgrade handling — real enforcement replaces the block

This was the largest change. Read `api/routes/workspace_members.py`'s
`deactivate_member` in full before touching it, then extracted its core
mechanism (status update + incident reassignment + one audit row) into
new `core/member_deactivation.py` — `deactivate_member_row(conn,
workspace_id, member_id, member_email, action=...)`. Both the original
admin-triggered route and the new automatic downgrade path now call the
exact same function; `deactivate_member`'s route body shrank to a single
call.

`api/routes/stripe_billing.py`'s `_handle_subscription_updated` no
longer blocks a downgrade — it's always applied. When the new tier's
seat cap is exceeded, the most-recently-added active/invited members
(by `created_at DESC`) are deactivated to fit. **Bug caught before
shipping**: the first draft used `OFFSET new_max_seats` to select which
rows to deactivate — backwards. `ORDER BY created_at DESC OFFSET N`
skips the N *newest* rows and returns the *oldest* ones, which would
have deactivated the wrong members entirely. Fixed to fetch all rows
newest-first and take a plain prefix slice (`rows[:over_count]`) in
Python instead.

One email (`core/email.py`'s new `downgrade_deactivation_html`, sent to
`contact_email` — consistent with every other admin-facing notification
this build has sent) lists exactly who was deactivated and the two
remediation paths Kelvin specified: remove other members to fit, or
upgrade again. The Stripe subscription itself is still never modified
from our side — same constraint as the removed block, now covered by an
explicit regression test (`test_stripe_subscription_itself_is_never_modified_on_downgrade`)
mocking `stripe.Subscription.modify` and asserting it's never called.

**Cleanup**: since nothing will ever set `downgrade_blocked_reason`
again, removed it from `BillingStatusResponse`/`billing_status()` and
the `/billing` page's banner for it, and the frontend `BillingStatus`
type. Left the migration 047 column in place (dropping columns is
riskier than an unused one) but nothing writes to it going forward.

## 4. CI cleanup — verified before touching, not assumed from Kelvin's read

Re-read both `code-quality-gate.yml` and `prompt-version-check.yml` in
full before acting, per the coordinator's explicit "verify against what
the files actually do" instruction. Kelvin's read was exactly right:
`code-quality-gate.yml` runs `code_quality_agent` against changed files
on any PR — the general gate, kept, repointed from `branches: [main]` to
`branches: [master]`. `prompt-version-check.yml` only fires on PRs
touching `prompts/**` and blocks a merge without a version bump — purely
PR-specific, deleted entirely (`git rm`) per the decision that this repo
has never used PRs and won't. `ci.yml` (Phase 7's push-triggered gate)
untouched, remains the one that actually runs on every push regardless
of PR state.

## 5. Frontend lockfile committed

`frontend/package-lock.json` was blanket-`.gitignore`d
(`package-lock.json` with no path scoping) — this is what caused Phase
7's CI verification pass to need the `npm install` workaround in the
first place. Found two *other* lockfiles in the repo while fixing this
(`team-dashboard/`, `empire-dashboard/`) and checked each individually
rather than blindly un-ignoring the blanket pattern:
`empire-dashboard/package-lock.json` was already tracked before the
ignore rule existed (unaffected either way); `team-dashboard/`'s was
never asked about, so the gitignore was rewritten to a scoped
`/team-dashboard/package-lock.json` entry that leaves that one alone.
Regenerated `frontend/package-lock.json` fresh (`npm install
--package-lock-only`) so it's genuinely in sync with `package.json`
before committing it, force-added it, switched `ci.yml` back to
`npm ci` with npm caching re-enabled (the original cache failure was
because the lockfile didn't exist in a fresh checkout at all — now it
does). Verified locally: `npm ci` against the exact committed lockfile
succeeds clean. Confirmed against a real GitHub Actions run, not just
local — see Verification below.

## 6. Org layer — LOCKED DECISION recorded, nothing built

Per Kelvin's explicit instruction: no schema or code was touched.
Recorded in two places: `CloudDecoded-Build-Order.md` gained a full "Org
Layer — LOCKED DECISION" section (organizations are identity/grouping
only; billing stays strictly per-workspace, permanently — not just for
a first version; lists the concrete future schema shape so a later
session doesn't have to re-derive it: relax
`workspace_members.supabase_user_id`'s `UNIQUE` constraint, new
`organizations` table, workspace switcher, org-level member list as an
aggregate view). `CLAUDE.md`'s `CURRENT STATUS` footer got a short
pointer to that section so the decision surfaces on every session start,
not just for whoever happens to open the build-order doc.

## 7. Missing contact_email — non-dismissible banner + a way to fix it

Confirmed the real gap first: `contact_email` is required at self-serve
signup (`workspaces.py`'s `CreateWorkspaceRequest`) but optional on the
admin/MCP-invite path (`internal_workspaces.py`) — so only
Enterprise-via-admin-invite workspaces can actually hit this. Building
just the banner without a way to act on it would have been a dead end,
so also added `PATCH /workspaces/contact-email` (admin-gated, same
convention as every other workspace-settings endpoint) and a new
`has_contact_email` field on `GET /workspace/credentials/status`. New
`ContactEmailBanner.tsx` — deliberately has no dismiss/close control
anywhere in the component, matching "non-dismissible" literally, not
just visually prominent. Clears the moment `setContactEmail` succeeds
and the next fetch reflects it.

## Verification

- Full backend suite: 2044 passed (new tests across
  `test_stripe_billing.py`, `test_workspace_members.py`,
  `test_workspaces.py`, `test_workspace_credentials_routes.py`, and new
  `test_member_deactivation.py`), same 4 pre-existing unrelated
  failures, zero regressions.
- `npx tsc --noEmit`: clean. `next build`: clean, 33 routes.
- `npm ci` verified locally against the exact committed lockfile.
- Deployed: Railway (commit `7a640e1`).
- `.github/workflows/ci.yml` run on this exact commit verified green on
  GitHub Actions itself, not assumed from the local runs alone.

## If this fails next time

- If a downgrade-triggered deactivation email never arrives: same class
  of gap as Phase 5/7's own — check `contact_email` is actually set. The
  new item-7 banner is exactly the mitigation for this now existing.
- If the wrong members get deactivated on a downgrade: re-check the
  `created_at DESC` + prefix-slice logic in
  `_handle_subscription_updated` against the OFFSET bug documented
  above — it's an easy mistake to reintroduce if this code is ever
  touched again without re-reading why it's written the way it is.
- If `code-quality-gate.yml` still never fires: confirm this repo has
  actually opened a PR at all yet (`gh pr list --state all`) — the
  branch-name fix only fixes the trigger condition; a `pull_request`
  event still requires an actual PR to exist, which per Kelvin's own
  decision this repo may never have.
