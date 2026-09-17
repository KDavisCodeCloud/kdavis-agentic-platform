# SOP: 24-Gap-Closure Build, Phase 4 — Auth & Member Security
Date: 2026-09-16
Status: Live — deployed, verified, committed, pushed

---

## Scope

Phase 4 of Kelvin's 24-gap-closure build, run under the "autonomous
continuation" directive (Phases 3-7, no external checkpoint between
phases, same internal read-first/build/test/deploy/verify/SOP discipline
per phase).

- Password reset (verify/complete — Kelvin's note said to read Phase A
  of the membership build first, not assume missing or complete)
- MFA via Supabase TOTP (enroll, login challenge, admin-required
  Enterprise setting)
- Member removal/deactivation (assigned incidents return to unassigned,
  audit row)
- Rate limiting on login/signup/password-reset endpoints
- Workspace token last_used_at tracking + optional expiry in dashboard

## What was read before building

- `frontend/src/app/login/page.tsx` and `frontend/src/app/accept-invite/page.tsx`
  in full — confirmed member sign-in is real Supabase
  `signInWithPassword`, and that `/accept-invite` already establishes
  the exact "temporary session via URL fragment, then `updateUser`"
  pattern a password-reset flow needs. Grepped the whole frontend and
  backend for "password"/"reset"/"forgot" first: **no** `/forgot-password`
  or `/reset-password` page existed, no link to either from `/login`, no
  backend awareness of a reset flow at all — confirmed genuinely missing,
  not just unwired, before writing anything.
- `api/routes/workspace_members.py` in full (invite/list/accept) and its
  `_caller_is_authorized_to_invite` RBAC helper, before adding
  deactivation and the MFA-requirement toggle — reused the same helper
  rather than inventing a second admin check.
- `api/middleware/auth.py`'s `get_workspace_member`/`_get_workspace_by_token`
  in full, since both password-reset's practical rate-limiting question
  and MFA enforcement's mechanism depend entirely on how these two
  functions actually authenticate a request.
- `api/routes/workspace_credentials.py`'s existing `WorkspaceTokenStatusResponse`/
  `rotate_workspace_token_self_serve` (onboarding completeness build,
  item 4) before extending it — confirmed `last_used_at`/expiry did not
  exist yet.
- Grepped for existing MFA/TOTP code: none existed (only unrelated AWS-
  IAM-MFA compliance-finding copy in `mock-data.ts`/blog posts).

## Two real, confirmed-missing pieces found before building (not assumed)

- **Password reset**: genuinely absent end to end — no page, no link, no
  backend piece. Built `/forgot-password` (calls Supabase's
  `resetPasswordForEmail`) and `/reset-password` (mirrors
  `/accept-invite`'s set-password UI, calls `updateUser`), plus a
  "Forgot password?" link on `/login`. No backend endpoint needed at
  all — Supabase Auth owns the whole flow, including its own email
  template (configured in the Supabase dashboard, **not**
  `core/email.py`, which only sends this app's own outbound
  notifications) — documented explicitly so this isn't mistaken for a
  gap later.
- **Workspace token `last_used_at`/expiry**: confirmed absent
  (`WorkspaceTokenStatusResponse` only ever had `last4`/`rotated_at`).
  Built both: `last_used_at` touched fire-and-forget (detached
  short-lived `asyncpg.connect`, same pattern as `core/notifications.py`)
  on every token-authenticated request, and an optional
  `workspace_token_expires_at` checked before the touch so an expired
  token is rejected (403) and never recorded as "used".

## What was built

**Migration 044**: `workspaces.workspace_token_last_used_at`,
`workspaces.workspace_token_expires_at`, `workspaces.require_mfa BOOLEAN
DEFAULT false`; `workspace_members.deactivated_at`.

**`api/middleware/auth.py`**: `_WORKSPACE_SELECT_COLUMNS` extended (3
new columns). `_get_workspace_by_token` now checks
`workspace_token_expires_at` (403 if past) before firing a detached
`_touch_workspace_token_last_used` task. `get_workspace_member` checks
`workspace_row["require_mfa"]`; if set, decodes the already-verified
session JWT's `aal` claim via `python-jose`'s `get_unverified_claims`
(safe — the token's validity was already confirmed moments earlier via
an online `client.auth.get_user()` call) and rejects (401,
`detail="mfa_required"`) anything short of `aal2`.

**`api/routes/workspace_members.py`**: `POST /{id}/deactivate` (admin-
only via the existing `_caller_is_authorized_to_invite`; self-
deactivation blocked; sets `status='deactivated'`+`deactivated_at`;
`UPDATE incidents SET assigned_to = NULL WHERE assigned_to = $1` in the
same transaction; one `write_audit_event` row). `PATCH
/settings/require-mfa` (admin-only, Enterprise-tier-only, matching
`core/compliance.py`'s existing tier-gating convention). `@limiter.limit`
added to `invite_member` (20/min) and `accept_invite` (10/min).

**`api/routes/workspace_credentials.py`**: `WorkspaceTokenStatusResponse`
extended with `last_used_at`/`expires_at`; new `PATCH
/token/expiry` (admin-only, rejects a past timestamp outright);
`ConnectionsStatusResponse` extended with `product_tier`/`require_mfa`
so the frontend can gate the Enterprise toggle and show its current
state without a second round trip.

**Frontend**: `/forgot-password`, `/reset-password` (new pages); `/login`
gained a "Forgot password?" link and an MFA challenge step (checks
`auth.mfa.getAuthenticatorAssuranceLevel()` after password sign-in,
challenges the verified TOTP factor if a step-up is required); new
`MembersPanel.tsx` (member list/invite/deactivate, personal TOTP
enroll/disable via `auth.mfa.enroll/challenge/verify/unenroll`,
Enterprise "require MFA" toggle) wired as a new "Members" dashboard tab;
`ConnectionsPanel.tsx`'s existing Workspace Token card extended with
last-used/expiry display and a set/clear-expiry control.

## Self-lockout guard added after the fact

Caught while writing this SOP, before shipping: `require_mfa` enforcement
checks the caller's *own* session `aal` at request time, so an admin who
turns the setting on without ever having enrolled a verified TOTP factor
would be rejected by their own very next request — no other admin
session, no factor to step up with, genuinely locked out. Fixed in
`set_require_mfa`: turning it ON now requires the caller's own Bearer
token already carry `aal2` (proof a verified factor exists and this
session already stepped up with it) — 400 otherwise, with a message
telling them to enroll first. Turning it OFF is never blocked. Covered
by `TestSetRequireMfa::test_enabling_without_own_aal2_session_rejected`.

## Design call flagged, not silently decided

**Rate limiting on login/signup/password-reset**: only `invite_member`
and `accept_invite` actually hit this FastAPI backend and could be
rate-limited with the existing slowapi `limiter`. Member sign-in
(`signInWithPassword`), password reset (`resetPasswordForEmail`,
`updateUser`), and MFA enroll/challenge/verify all call Supabase Auth
**directly from the browser** — they never reach this backend at all, so
`@limiter.limit` cannot apply to them here. `POST /workspaces` (the real
"signup" endpoint — company/workspace creation) was **already**
rate-limited at 5/min before this phase (pre-existing, confirmed, not
newly added). Documented rather than building a decorator on a route
that doesn't exist. **Flag for Kelvin**: if backend-side rate limiting
on member login/password-reset specifically is wanted, that requires
proxying those Supabase Auth calls through this backend instead of
calling Supabase directly from the browser — a real architecture
change, not a one-line addition, and out of this phase's scope to
decide unilaterally.

## Verification

- Full backend suite: 1992 passed (+16 new tests across
  `test_auth.py`/`test_workspace_members.py`), same 4 pre-existing
  unrelated failures, zero regressions.
- `npx tsc --noEmit`: clean. `next build`: clean, 33 routes (was 31).
- Deployed: Railway (commit `997d0f7`) — `SUCCESS`.
- Live-verified via `curl`: `/forgot-password` and `/reset-password` both
  200 on the Vercel frontend; `PATCH /workspace-members/settings/require-mfa`
  and `POST /workspace-members/{id}/deactivate` both 401 (real
  auth-gated routes, not 404s) against the Railway backend.

## If this fails next time

- If a *different* member (not the admin who flipped the switch) reports
  being locked out after `require_mfa` was turned on: that member never
  enrolled their own factor — the self-lockout guard only proves the
  *enabling* admin had a verified factor, not that every other member
  does. That member needs another admin (or the same one) to reach them
  outside the product to walk through enrollment, since this endpoint
  has no bulk-enrollment-required flow. Worth surfacing as a dashboard
  banner in a later pass if this comes up in practice.
- If `workspace_token_last_used_at` never updates: check the detached
  task actually fires — `asyncio.create_task(_touch_workspace_token_last_used(...))`
  runs fire-and-forget with no error path back to the request, so a
  silently failing DB connection there would never surface anywhere
  except a `[Auth] Failed to update workspace_token_last_used_at`
  warning in the logs.
