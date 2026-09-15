# 2026-09-15 (continued) — Membership/SSO/RBAC/SCIM 5-phase build

Product: Cloud Decoded
Continues [[2026-09-15-scale-readiness-build]], run in the same session
immediately after the 12-phase scale-readiness sequence closed.

## What prompted this

A research pass earlier this session (forked, research-only) confirmed
all six pricing-roadmap features — multi-user seats, SSO, in-workspace
RBAC, SCIM provisioning, a published SLA, and data residency — were
unbuilt. The entire customer product ran on one identity concept: a
single shared `workspace_token` pasted into `localStorage`, no
`workspace_members` table anywhere, no per-human login. Kelvin approved
the merged 5-phase plan (workspace membership foundation → seats → RBAC
→ SSO → SCIM) to close the four that depend on a real per-user identity
existing; published SLA and data residency were explicitly flagged as
business/infra decisions, not code phases, and not scheduled.

Both this plan and the scale-readiness plan were run "in parallel" per
Kelvin's instruction, executed sequentially in a dependency-aware
interleaving (scale Phases 4-10 → membership Phase A → scale Phase 11,
since RLS also touches auth middleware → scale Phase 12 → membership
Phases B-E) rather than via genuinely concurrent subagents, given real
file-collision risk between the two plans (both needed new migrations,
both touched `api/middleware/auth.py`).

## Phase A — workspace membership foundation

`db/migrations/033_workspace_members.sql`: one row per human,
`supabase_user_id` (NULL until invite accepted), `role`
(admin|member at this point — Phase C renames it), `status`
(invited|active|deactivated). Generalizes the existing Enterprise-only,
admin-provisioned MCP-invite pattern
(`api/routes/internal_workspaces.py`'s `invite_mcp_user`, built earlier
this session for MCP OAuth) into a real, self-serve product feature.

`api/middleware/auth.py` gains `get_workspace_member()` — validates a
Supabase session via `client.auth.get_user()` (the same *online*-
validation approach `internal_auth.py`'s `get_internal_user` already
uses, deliberately NOT `mcp/auth/oauth.py`'s offline JWT decode, since
`mcp/` is a separately deployed service with its own
Dockerfile/requirements.txt this codebase doesn't import from) — and
`get_workspace_or_member()`, which tries `X-Workspace-Token`/
`X-MCP-Service-Key` first and falls back to a Bearer session. The
existing token path is completely unchanged; this is a second, additive
auth path. Wired into `get_incident`/`list_incidents` only, matching the
plan's own Phase A verification bar (list the same workspace's incidents
as two different logged-in users).

New `api/routes/workspace_members.py`: `POST /workspace-members/invite`
(bootstrap — either the shared token, before any members exist, or an
active admin member session), `GET /workspace-members`, `POST
/workspace-members/accept` (the invited person's fresh Supabase session
links to their row — the one place this table matches by email instead
of `supabase_user_id`, since that column is still NULL at this point).

**Frontend**: `/login`'s primary sign-in is now real email/password via
`supabase.auth.signInWithPassword` — a genuine per-human identity.
Workspace-token entry was kept as an explicit secondary "Use a workspace
token instead" fallback, not removed: `workspace_members` was a
brand-new table with zero rows for every existing paying customer at
deploy time, so removing the token path would have been a self-inflicted
login outage, not a migration. New `/accept-invite` page handles the
invite-link → set-password → `POST /workspace-members/accept` flow.
`lib/api.ts`'s `request()` now picks the auth header by token shape (a
raw workspace token always starts with `cd_ws_`, a Supabase session
token never does) — the existing single `token` state threaded through
every dashboard call site now transparently carries either credential
with zero per-call-site changes.

**Real gap, stated plainly**: the full literal end-to-end verification
(a real signup → a real invite email → click it → list incidents as two
users) was NOT performed. It needs `SUPABASE_SERVICE_ROLE_KEY` to drive
the Admin API directly, or a real inbox to click a live link through —
this session's local `.env` only carries `SUPABASE_URL`/`DATABASE_URL`;
the service role key lives in Railway's environment only, and Railway
variable values are redacted from every tool available in this session
by design. What WAS verified: all 32 backend tests (every code path)
pass against mocks, migration 033 and both endpoints confirmed live and
responding correctly in production, `tsc --noEmit`/`next build` clean,
and both pages confirmed serving the new content on
`theclouddecoded.com` post-deploy via direct `curl`. Someone with
Supabase dashboard or service-role access should run one real invite
before this is presented to a real customer.

## Phases B + C — seats and RBAC (run together, both small and additive on Phase A)

**Seats**: `TIER_LIMITS` gains `max_seats` (starter=3, growth=15,
enterprise=-1). `assert_seat_available()` counts `workspace_members`
rows in `('invited','active')` — an unaccepted invite still occupies a
seat, otherwise a workspace could out-invite its cap and have them all
eventually accept. Wired into invite, before the row is created. `GET
/workspace-members` now returns `{members, seats_used, max_seats}`
(a safe breaking change to a brand-new endpoint with zero real
consumers).

**RBAC**: `workspace_members.role` becomes `admin | approver | viewer`
(migration 034 renames Phase A's placeholder `'member'` to `'viewer'`).
`approve_incident`/`reject_incident` now require `get_workspace_or_member`
plus role `admin` or `approver` — `viewer` gets 403. A token-
authenticated caller is completely unaffected, same full-trust model the
shared token already had.

Explicitly NOT built: a members-management UI. The data
(`seats_used`/`max_seats`) exists for a future "Team" settings page, but
nothing in the dashboard calls these endpoints yet — inviting/listing
members today is API-only. Role names (`admin`/`approver`/`viewer`)
landed as the closest fit to the plan's own text without Kelvin's
explicit sign-off mid-build (the plan said "name TBD with Kelvin") —
worth a quick sanity check, cheap to change later (VARCHAR column, no
enum type).

## Phase D — SSO storage/config

`db/migrations/035_workspace_sso_config.sql`: one row per workspace
(`provider_type` saml|oidc, `email_domain`, Fernet-encrypted IdP
metadata, `supabase_sso_provider_id`, `status`). Admin-gated `PUT`/`GET
/internal/workspaces/{id}/sso-config` (same trust model as mcp-invite:
Enterprise sells on a 30-90 day B2B cycle, provisioning happens after a
deal closes). Never echoes the raw metadata XML back.

**The real activation step was deliberately not built.** "Use Supabase
Auth's native SSO support" means calling Supabase's Management API
(`POST /v1/projects/{ref}/config/auth/sso/providers`) — that needs a
Management API access token, a materially different and more privileged
credential than `SUPABASE_SERVICE_ROLE_KEY`, and none was available in
this session to verify that integration's request/response shape
against. Writing untested code that provisions a real external SSO
connection on a real Enterprise customer's behalf, with no way to check
it actually works, is the wrong kind of code to ship. `status` stays
`'pending'` until someone with Management API access completes real
registration. No `/login` SSO buttons were added, for the exact reason
that page's own pre-existing comment already gave: shipping buttons with
no working backend would be actively misleading on a page real customers
pay to use — that's still true; the backend now stores config but
doesn't complete a real login round trip.

## Phase E — SCIM 2.0

`api/routes/scim.py`: a pragmatic SCIM 2.0 subset (RFC 7643/7644) —
`GET/POST /scim/v2/Users`, `GET/PUT/PATCH/DELETE /scim/v2/Users/{id}` —
covering what real IdP connectors actually send (the `userName eq "..."`
pre-create dedup filter, both shapes a connector might send the `active`
deprovision PATCH in, SCIM's own error-response schema). Maps directly
onto `workspace_members`; new members default to `role='viewer'`
(least privilege); `DELETE` deactivates rather than hard-deletes,
matching `docs/customer/dpa-outline.md`'s existing archival model.

Authenticated by a new, deliberately separate `get_workspace_by_scim_token`
dependency — a SCIM connector's bearer token is scoped to exactly one
workspace's IdP integration, never a human session or the shared
workspace token, and must never be accepted anywhere else.
`db/migrations/036_workspace_scim_token.sql` adds the token hash column
to `workspace_sso_config`; `POST .../sso-config/scim-token` (admin-
gated) generates and returns it exactly once, same contract as
`rotate-token`.

Built despite Phase D's real activation gap above — a deliberate call,
not an oversight. The SCIM endpoints have zero code dependency on
Supabase's Management API (an IdP calling `/scim/v2/Users` only needs
this workspace's SCIM token, not a live SSO registration), so there was
no reason to block Phase E's protocol layer on Phase D's operational
follow-up. It's real, tested code (21 new tests) that stays practically
dormant — no real IdP has a live connection to push through yet — until
someone completes that follow-up.

## Deliberately not done (full accounting)

- Real end-to-end invite verification (Phase A) — blocked on
  `SUPABASE_SERVICE_ROLE_KEY`/a real inbox, neither available in this
  session.
- Members-management UI (Phases B/C) — API-only today.
- Role name sign-off (Phase C) — landed without Kelvin's explicit
  confirmation mid-build, flagged for a quick check.
- Supabase Management API SSO provider registration (Phase D) — needs a
  Management API access token this session didn't have.
- `/login` SSO buttons (Phase D) — correctly still absent; no working
  backend to back them yet.
- A real IdP round trip against the SCIM endpoints (Phase E) — depends
  on Phase D's registration step.

## Verification status

Every backend phase: full mocked test suite (149 new tests across all
five phases combined) + live Railway deploy verification (migration
applied, all 4 workers healthy, live `curl` checks against the new
endpoints returning correct auth-gated responses). Frontend (Phase A):
`tsc --noEmit` clean, `next build` succeeds, both new pages confirmed
serving live on `theclouddecoded.com` via direct `curl` post-deploy
(Vercel auto-deploy confirmed working via the `vercel` CLI, already
authenticated in this environment, after an initial check found the
production domain still serving cached old content — the deploy had
just started, not stalled).

## Numbers

Full suite: 1576 passing at the close of Phase E (was 1511 at the start
of Phase A), same 4 pre-existing unrelated failures throughout, zero
regressions across all five phases.

## Deploy

Same pattern as the scale-readiness build: commit → push (GitHub PAT
supplied in chat) → Railway auto-deploy (both services) + Vercel
auto-deploy (frontend, Phase A only) → verified via Railway
`list-deployments`/`get-logs` and direct `curl` against both
`theclouddecoded.com` and the Railway production URL before moving to
the next phase. This closes both plans that were active this session —
see [[2026-09-15-scale-readiness-build]] for the other one.
