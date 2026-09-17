# SOP: 24-Gap-Closure Build, Phase 5 — Credential Lifecycle
Date: 2026-09-16
Status: Live — deployed, verified, committed, pushed

---

## Scope

Phase 5 of Kelvin's 24-gap-closure build, run under the "autonomous
continuation" directive (Phases 3-7, same internal
read-first/build/test/deploy/verify/SOP discipline per phase, no
external checkpoint between phases).

- `credential_expires_at` captured at connection time (Azure SP secret,
  Azure DevOps PAT; document why AWS is N/A)
- Daily check: expiring within 14 days → email + banner; expired →
  critical incident
- Webhook token rotation grace window (old token valid 72h, rotation
  response includes an alert-source checklist, banner until window
  closes)

## A genuine premise mismatch, found before building on top of it

The spec's note said "the onboarding-completeness fork already built
rotation UI copy describing this 72h policy; enforcement code must
match what that UI already promises." Read `ConnectionsPanel.tsx`'s
actual live copy before assuming that was true — it wasn't: the
existing banner said *"The old token stopped working immediately; it
does **not** stay valid for a grace period today."* — the opposite of
a 72h promise. `api/routes/workspace_credentials.py`'s own docstring on
`rotate_workspace_token_self_serve` *did* say a caller was "expected to
show the 72-hour inbound-webhook grace-window notice," but the frontend
was never actually built to match that docstring's aspiration.

Rather than either (a) building enforcement to match a UI promise that
didn't exist, or (b) skipping the feature because the premise was
wrong, built the real thing Kelvin's spec independently asked for —
grace-window enforcement — and **corrected** the misleading "no grace
period" copy to describe the now-true policy. Flagging this explicitly
rather than silently proceeding as if the premise had been accurate.

## What was read before building

- `api/routes/workspace_credentials.py`'s `connect_azure`/
  `connect_azure_devops` in full, and their `ConnectAzureRequest`/
  `ConnectAzureDevOpsRequest` models, before adding an expiry field —
  confirmed neither existed yet.
- `api/middleware/auth.py`'s `_get_workspace_by_token` (already modified
  in Phase 4 for the token-expiry check) before adding the grace-window
  fallback query, to slot it in at the right point relative to the
  existing expiry check.
- `core/hitl.py`'s `HITLGate.create_incident` in full — confirmed it
  already fires notification fan-out (`_fire_notification`) and audit
  logging (`_write_audit_entry`) on creation, and that passing a
  pre-generated `incident_id` makes a repeat call a clean no-op via its
  own `ON CONFLICT (id) DO NOTHING` — meaning the daily expiry check
  needs no separate "already flagged" state for the expired-incident
  case, reusing an existing idempotency mechanism instead of building a
  parallel one.
- `workspaces.contact_email` (migration 026) confirmed as the real
  existing field to send expiry-warning emails to, rather than
  inventing a new one.

## What was built

**Migration 045**: `workspaces.azure_client_secret_expires_at` +
`_expiry_warned_at`; `azure_devops_pat_expires_at` + `_expiry_warned_at`;
`previous_workspace_token_hash` + `previous_workspace_token_expires_at`.

**`core/credential_expiry.py`** (new): `run_credential_expiry_check`,
advisory-lock-gated (`_LOCK_ID = 503_918_642`, distinct from every other
existing lock constant in this codebase). For each of the two credential
types: expired → `HITLGate.create_incident(severity="critical",
agent_id="system_credential_lifecycle", incident_id=<deterministic
uuid5>)`; expiring within 14 days and not yet warned → one email via
`core/email.py`, then marks `*_expiry_warned_at`. New daily periodic
loop in `api/main.py`, same pattern as retention/onboarding/notification
loops.

**`api/routes/workspace_credentials.py`**: `ConnectAzureRequest` gained
`client_secret_expires_at`, `ConnectAzureDevOpsRequest` gained
`pat_expires_at` (both optional — a workspace connected before this
phase, or a customer who doesn't know their credential's expiry, isn't
blocked; simply gets no warning/incident for that credential, same as
today). Both connect handlers clear the corresponding `*_warned_at` flag
on reconnect so the next expiry cycle warns again. `connect_aws_role`
got a docstring explaining why AWS has no equivalent field.
`rotate_workspace_token_self_serve` now moves the outgoing hash to
`previous_workspace_token_hash` with a 72h expiry in the same UPDATE
(reads the pre-update `workspace_token` value — no extra read
needed) and returns `grace_period_ends_at` + a static
`alert_source_checklist`. `get_workspace_token_status` surfaces
`grace_period_ends_at` too (only while still open) so the banner
survives a page reload, not just the one-time rotate response.

**`api/middleware/auth.py`**: `_get_workspace_by_token` falls back to
`previous_workspace_token_hash` (checked for expiry) when the primary
lookup misses — the actual grace-window enforcement.

**Frontend**: Azure SP and Azure DevOps connect forms gained an optional
expiry date input each. The Workspace Token card's rotation banner now
states the real 72h policy (with the actual close timestamp) and lists
the alert-source checklist; a second banner (driven by
`tokenStatus.grace_period_ends_at`, not local rotation state) shows
after a page reload while a grace window is still open.

## Test-fixture-drift bugs caught and fixed (same class as every prior
phase's SOP documents — fixed the fixtures, not the new code)

- Extending `rotate_workspace_token_self_serve`'s `RETURNING` clause to
  include `previous_workspace_token_expires_at` broke 4 existing tests
  whose mocked `fetchrow_return` only had `workspace_token_rotated_at`.
  Fixed all 4 fixtures; also updated
  `test_new_token_is_hashed_before_storage_not_stored_raw`'s SQL-shape
  assertion (`"UPDATE workspaces SET workspace_token"` no longer matches
  literally since `previous_workspace_token_hash` is now the first SET
  clause) to check for the actual new shape instead of loosening it.

## Verification

- Full backend suite: 2007 passed (+22 new tests across
  `test_auth.py`/`test_workspace_credentials_routes.py`/
  `test_credential_expiry.py`), same 4 pre-existing unrelated failures,
  zero regressions.
- `npx tsc --noEmit`: clean. `next build`: clean, 33 routes (unchanged
  route count — no new pages this phase, only new fields on existing
  forms/panels).
- Deployed: Railway (commit `c47408c`).

## If this fails next time

- If a workspace's expiry warning email never arrives: check
  `contact_email` is actually set (migration 026, optional at signup) —
  a missing one is logged as a warning, not surfaced anywhere in the
  dashboard today. That's a real gap for the final report: no
  UI nudge exists yet to tell a workspace "we can't warn you about
  credential expiry because you have no contact email on file."
- If the same expired-credential incident appears to "reappear" after
  being resolved: check whether the deterministic `incident_id` was
  reused — resolving/dismissing the incident doesn't clear the
  underlying `*_expires_at` column, so the next daily pass will compute
  the SAME id again and `ON CONFLICT DO NOTHING` will silently no-op
  instead of creating a fresh incident for what might now be a
  genuinely new occurrence (e.g. reconnected, then expired again months
  later — same slug, same workspace, same deterministic id). This
  works correctly for the common case (nothing new is created while
  the same incident is still open) but is worth a closer look if a
  customer disputes not seeing a second alert after reconnecting and
  re-expiring — flagged in the final report as a design tradeoff, not
  silently assumed safe.
