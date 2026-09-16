# SOP: Onboarding Completeness Build — Items 3-6
Date: 2026-09-16
Status: Live — committed, pushed, Railway + Vercel deployed and verified

---

## Scope

Kelvin's "Onboarding completeness build" spec had six items; items 1-2
(setup checklist, connection test button) are verbatim Phase 6 of a
separate, larger 8-phase build running in a parallel fork/session — not
touched here to avoid duplicate/conflicting work. This SOP covers items
3-6, built and shipped independently.

## What was built

**Item 3 — in-context setup instructions.** `ConnectionsPanel.tsx` had
no webhook URL displayed anywhere before this (confirmed by grepping the
whole frontend). Added:
- A new "Alert Ingestion" card with the real `resource-health-alert`
  webhook URL and expandable Azure/AWS setup panels, sourced **verbatim**
  from `agents/agent_11_resource_health/sop.md`'s own live-verified trace
  (2026-09-15 real Azure Action Group test) — provider registration,
  Webhook-not-Secure-Webhook, Common Alert Schema toggle, `/api/v1` path.
- Expandable instructions on the GitHub card (legacy PAT webhook) and
  Azure DevOps card (service hook event/secret setup).
- Expandable instructions on the Kubernetes card for the separate
  `aks-alert` webhook (distinct from the cluster credential connection
  already there).
- Every URL/value uses the existing `CodeBlock` component, which already
  has copy buttons — no new component needed.
- A member session (Bearer token, no raw workspace token available)
  gets `<your-workspace-token>` as a placeholder in these URLs rather
  than a fabricated value — the raw token literally cannot be recovered
  for that session (see item 4).

**Item 4 — self-serve token management.** Found before writing any code:
`workspaces.workspace_token` stores only a SHA-256 hash (schema comment:
"API auth token (hashed)") — there is no raw token to "reveal" after
issuance, ever, for anyone. Built what's actually real instead of a fake
reveal:
- Migration 040: `workspace_token_last4` + `workspace_token_rotated_at`
  display-hint columns (last4 only ever set at issuance/rotation time).
- `GET /workspace/credentials/token` (masked status) and
  `POST /workspace/credentials/token/rotate` (admin-only, self-serve
  equivalent of `internal_workspaces.py`'s THD-team-only rotate-token) —
  new, customer-facing, admin-role-gated.
- **Necessary prerequisite found mid-build:** `get_connections_status`
  only accepted `get_workspace` (raw token) — a logged-in member session
  got a 401 opening Connections at all, before this fix. Widened to
  `get_workspace_or_member` (one more instance of GAPS.md #22's own
  flagged "roll this out further" follow-up — necessary here since the
  whole point of item 4 is a *logged-in admin* managing the token).
- An audit_events row is written on every rotation (`core/audit.py`'s
  `write_audit_event`).
- Frontend: masked display (`cd_ws_••••••••<last4>`), a one-time reveal
  of the new raw token immediately after rotation with a copy button and
  an explicit "update every alert source now" reminder, and an amber
  warning that there is **no grace period today** — rotation invalidates
  the old token immediately (the 72-hour grace window from Phase 5 of
  the separate 8-phase build doesn't exist in code yet; UI copy
  describes the current real behavior, not that future policy).

**Item 5 — welcome email as a 3-email sequence.** Day 0 unchanged
(existing `stripe_billing.py` send). Added day-2 and day-5
(`core/onboarding_sequence.py`, migration 041's tracking table), gated
on the best real signal available today rather than the not-yet-built
5/5 setup checklist:
- Day 2 ("connect anything") — any `workspace_credentials`
  `*_verified_at`/`github_app_installation_id` column set.
- Day 5 ("verify an alert source") — any row in `alert_ingestion_log`
  for the workspace (written on every real inbound webhook, before any
  processing).
- Runs as a periodic in-process task (same pattern as
  `core/retention.py`), checked every 6h so each email lands within a
  few hours of its target day regardless of checkout time.
- **Documented explicitly as a stand-in**: once the real checklist field
  ships (a separate phase), these two gates should read it directly
  instead of re-deriving the same signal from raw columns.

**Item 6 — setup guide audit.** `docs/customer/setup-guide.md` had zero
mention of the Agent 02/11 alert-webhook setup path at all — added the
same live-verified Azure/AWS steps from `sop.md`, plus a note that the
Kubernetes agent needs both the cluster credential *and* the separate
alert webhook (two different things, easy to miss). No live site page
mirrors this doc (confirmed) — nothing to sync there.

## Verified live, not assumed

- Full backend suite: 1907 passed. The only non-pre-existing failure
  (`test_incidents_workspace_scope.py`, a `KeyError: 'severity'`) is
  caused by the **separate, concurrent Phase 1 fork's own uncommitted
  work** on `api/routes/incidents.py` (confirmed via `git diff` before
  committing — this commit touches zero files that fork touched).
- Frontend: `tsc --noEmit` clean, `next build` clean (31 routes).
- Deployed and confirmed live: Railway build took ~3 min (large
  dependency tree — anthropic/openai/google-cloud/boto3/etc., unrelated
  to this change), then deploy logs showed all 4 `--workers` processes
  starting; exactly one applied migrations 040/041
  (`[Migrate] 2 migration(s) applied: ...`), the other three correctly
  saw `0 pending` — real, live confirmation the advisory-lock tracking
  table works correctly under actual multi-worker concurrency, not just
  in tests.
- `curl .../api/v1/workspace/credentials/token` (no auth) returns `401`,
  not `404` — the new route is genuinely live.
- Vercel `frontend` project auto-deployed to Production, confirmed
  `Ready` via `vercel ls`.

## Working alongside a concurrent fork — a real coordination note

This build ran in the same shared working tree as a separate fork
building Phase 1 of a different 8-phase plan (severity column, etc.) —
not an isolated worktree. Before every commit, `git status`/`git diff`
were checked to confirm zero file overlap, and `git add` was always by
explicit file path (never `-A`/`.`) so the other fork's uncommitted work
was never touched, staged, or committed. Migration numbers were also
checked live immediately before writing new files (040/041 chosen after
confirming 039 was the max on disk at that moment) — no collision
occurred, but this is inherently a race in a shared tree and worth
knowing about if it ever does collide: `db/migrate.py`'s discovery sorts
by numeric prefix only (not `(prefix, filename)` the way the sibling
MSE repo's runner does) — see `db/migrate.py`'s own module docstring;
this file was not touched in this build.

---

## If this breaks again

- **A member session still gets a 401 opening Connections:** confirm
  they're hitting the widened `get_connections_status` — some *other*
  route under `/workspace/credentials/*` may still only accept
  `get_workspace` (this build only widened the one route item 4 needed).
- **Rotate token returns 403 for someone who should be able to:** check
  their `workspace_members.role` — this is deliberately admin-only, not
  admin-or-approver like incident approval.
- **Day-2/day-5 emails never send:** check `RESEND_API_KEY` is set
  (fails closed, logs a warning, same as every other email in this
  codebase) and that `workspaces.contact_email` is actually populated
  for the workspace in question.
