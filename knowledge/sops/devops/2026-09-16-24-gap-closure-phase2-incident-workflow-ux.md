# SOP: 24-Gap-Closure Build, Phase 2 — Incident Workflow UX
Date: 2026-09-16
Status: Live — deployed, verified, committed, pushed

---

## Scope

Phase 2 of Kelvin's 24-gap-closure build, building on Phase 1's schema
(`severity`/`assigned_to`/`incident_comments`/`before_state`, migration
042). Phase-gated: this phase only, full suite must pass, deploy,
checkpoint before Phase 3.

- Assignment UI on incident card (assign to member, filter "assigned to me")
- Comments thread on incident detail
- Bulk select → dismiss / resolve-manually (RBAC-gated same as single ops,
  audit row per incident)
- Search/filter API + dashboard UI: resource_id, resource_name, severity,
  agent, execution_status, date range

## What was read before building (per Kelvin's own instruction)

- `frontend/src/components/IncidentConsole.tsx`/`PipelineTracker.tsx`/
  `RemediationCard.tsx` in full, to understand the real list/detail split
  view and where assignment/comments/bulk-select would actually slot in,
  rather than guessing at a shape.
- The single-incident `reject_incident`/`resolve_incident_manually` RBAC
  gating (`_caller_can_approve_or_reject`, admin/approver only) directly
  in `api/routes/incidents.py`, per Kelvin's explicit instruction not to
  assume the bulk version's gate shape — the bulk endpoint reuses this
  exact same function, not a separate or looser check.
- `GET /workspace-members` (already built, GAPS.md #23) to confirm a
  real members-list endpoint existed before building an assignment picker
  against it — it did, and had never been called from the frontend at
  all until now (also GAPS.md #23's own "no members-management UI" gap).

## Two real pre-existing gaps found while building this (fixed, not silently worked around)

- **`agent_id`/`created_at` were referenced throughout the frontend**
  (`PipelineTracker.tsx`'s `agentLabel(incident.agent_id ?? 'agent_01_cicd_triage')`,
  `RemediationCard.tsx`'s execution-log lookup) **but the real
  `GET /incidents`/`GET /incidents/{id}` never actually returned them** —
  only the MOCK_MODE fixtures had these fields. Every real (non-mock)
  incident's agent badge has silently rendered as "Agent 01" regardless
  of which agent actually ran, since before this session. Fixed by adding
  both fields (plus `resource_id`/`resource_name`/`assigned_to`/
  `assigned_to_email`, needed for this phase anyway) to `IncidentResponse`
  and both routes' SELECTs.
- **`rejected` (set by the pre-existing `POST /incidents/{id}/reject`)
  had no frontend representation at all** — not in `IncidentStatus`, not
  in `STATUS_META`, not handled in `PipelineTracker.tsx`'s status maps or
  `RemediationCard.tsx`'s completion panel. Bulk dismiss sets this exact
  status, so it needed a real display path, not a workaround; added it
  everywhere the other terminal statuses are handled.

## What was built

**Backend** (`api/routes/incidents.py`, `db/models.py` — no new migration,
Phase 1's schema already covers everything this phase needs):
- `PATCH /incidents/{id}/assign` — `{member_id: string | null}`, RBAC-gated
  via `_caller_can_approve_or_reject` (a judgment call, not in Kelvin's
  literal spec: assigning work has the same blast radius as approving/
  rejecting, so a 'viewer' session shouldn't be able to reassign either —
  documented in the endpoint's own docstring, not silently decided).
- `GET`/`POST /incidents/{id}/comments` — open to any authenticated
  caller including 'viewer' (a comment thread is a collaborative record,
  not an approval gate). A token-authenticated caller's comments store
  `member_id = NULL`, matching the existing `resolved_by = None for a
  token caller` convention already used elsewhere in this file.
- `POST /incidents/bulk` — `{incident_ids, action: "dismiss"|"resolve_manually", reason?, resolution_note?}`.
  Applies the identical state transition each single-incident endpoint
  already uses, RBAC-gated identically, and writes one real
  `audit_events` row **per incident**, not one for the whole batch — each
  incident's own history must show it was acted on individually. An
  incident that's missing, not in this workspace, or no longer
  `pending_approval` is skipped with a per-item outcome
  (`not_found`/`not_pending`) rather than failing the whole batch.
- `GET /incidents` gained real filters: `severity`, `agent_id`,
  `resource_id`, `resource_name` (ILIKE partial match), `date_from`/
  `date_to`, `assigned_to` (a real member id, or the literal `"me"`,
  resolved server-side to the caller's own `member_id` — the frontend
  never needs to know its own member id to filter by it; a token caller
  gets a 400, not a query that silently matches nothing).

**Frontend**:
- `lib/types.ts`/`lib/api.ts`/`lib/mock-data.ts` extended to match —
  `IncidentFilters`, `WorkspaceMember`, `IncidentComment`,
  `BulkIncidentAction*` types; `SEVERITY_META` display metadata;
  `rejected` added to `IncidentStatus`/`STATUS_META`; mock-mode support
  for every new endpoint (workspace members, comments, bulk action) so
  `NEXT_PUBLIC_MOCK_MODE=true` demos keep working.
- `PipelineTracker.tsx` — checkboxes on `pending_approval` rows only
  (the only status bulk actions apply to), severity badge, assigned-to
  display.
- `IncidentConsole.tsx` — a collapsible search/filter panel (resource
  name, severity, agent, date range, "Assigned to me" toggle) and a bulk
  action bar (shown only when 1+ incidents are checked) with an optional
  shared note/reason field, Dismiss and Resolve Manually buttons.
- `RemediationCard.tsx` — an inline assignee `<select>` in the header
  (fetches `GET /workspace-members` once per mount) and an always-visible
  comments thread in the body (list + post, independent of incident
  status).

## Tests and verification

- Backend: `tests/test_incidents_phase2.py` (new, 21 tests: assign
  success/unassign/invalid-member/incident-not-found/RBAC gate x2,
  comments list/create/empty-body/token-auth/not-found, bulk dismiss/
  resolve/per-incident-audit-rows/not-found/not-pending/mixed-outcomes/
  RBAC/empty-list/invalid-action/malformed-id). Updated
  `tests/test_incidents_workspace_scope.py` for the expanded SELECTs and
  added filter/sort/assigned-to=me tests.
- Full backend suite, re-run after the frontend edits per this phase's
  explicit re-verification step: **1945 passed, same 4 pre-existing
  unrelated failures** (`test_diagnose_node_returns_three_options` + 3
  secret-redaction tests — the same baseline documented throughout this
  session), zero regressions.
- Frontend: `npx tsc --noEmit` clean, `next build` clean (31 routes,
  zero errors), re-confirmed clean again after the 90-minute pause
  before committing.
- A real regression was caught and fixed within this same pass (not
  after): expanding `get_incident`'s SELECT broke an existing test whose
  mocked row lacked the new columns — fixed the test fixture, not the
  new code, after confirming the new code itself was correct. Same class
  of catch as Phase 1's own SOP documents.

## Deliberately not built

- No members-management UI beyond the assignment picker itself (invite/
  remove a member) — that's GAPS.md #23's own separate, larger gap, not
  in Phase 2's literal scope.
- No edit/delete on comments — Kelvin's spec named a comments *thread*
  (list + post); building edit/delete would be unrequested scope.
- No frontend UI for `resource_id` filtering — it's an opaque cloud
  identifier an operator wouldn't type from memory; `resource_name` (a
  real ILIKE search) covers the human-facing case this UI is actually for.
  The backend filter still exists and is tested, for a future API
  consumer that does have the exact id.

---

## If this breaks again

- **A bulk action silently does nothing to an incident:** check the
  response's `results` array for that incident's `outcome` --
  `not_found`/`not_pending` are expected, not a bug, when the incident
  moved out of `pending_approval` between the frontend's last fetch and
  the bulk request landing.
- **An incident's agent badge or timestamp looks wrong on a very old
  incident:** rows created before this session's fixes may genuinely
  have relied on the old always-broken frontend default -- not a new bug.
- **Assignment picker shows "Unassigned" for everyone, or the dropdown
  is empty:** `GET /workspace-members` failing is swallowed silently by
  design (assignment is metadata, not the incident's action flow) --
  check the Network tab / backend logs directly, the UI won't surface it
  on its own beyond an empty dropdown.
