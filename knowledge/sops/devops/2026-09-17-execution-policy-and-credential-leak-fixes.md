# SOP: Settings → Policies Build + Agent 03/09 Credential Leak Fix
Date: 2026-09-17
Status: Live — deployed, verified, committed, pushed

---

## Scope

Kelvin's two-part request: (1) verify-first, then a deliberately minimal
"Settings → Policies" build — a workspace-level execution-policy flag,
per-resource exemptions, per-connection Read-Only/Execute mode, and
graceful permission-failure handling; (2) fix two real credential-leak
bugs the verification step surfaced, in the same session.

## Step 0 — verification (before any code)

Traced execution paths across all 11 agents directly against the code
(every workflow.py + tools.py, not grep alone). Finding: **no
auto-execution / tiered-autonomy / "previously-approved pattern" exists
anywhere in this codebase.** Every agent's LangGraph graph is strictly
linear (`ingest -> diagnose -> hitl_gate[interrupt()] -> execute ->
complete`); `POST /incidents/{id}/approve` (RBAC-gated, admin/approver)
is the only code path that ever resumes past the interrupt, for all 11
agents, no exceptions.

`CloudDecoded-Build-Order.md` had a stale "Key Constraint" from a
2026-07-04 draft describing tiered autonomy as intended design — never
actually built. Corrected in that file (marked struck-through, dated,
reasoned) rather than silently deleted, matching this doc's own existing
correction convention.

Full read/write manifest, one agent at a time: only **Agent 05 (IAM)**
and **Agent 06 (FinOps)** call AWS/Azure APIs directly to mutate
something. Agent 08 (Drift) writes only via `kubectl apply` or a repo
PR; Agent 02 (K8s) writes only via the cluster API + a repo PR; every
other agent's write is a PR or issue. This scoped everything downstream
— connection-mode gating and graceful-403 handling only needed to touch
agents 05/06.

Two credential-scoping bugs found during this trace (not part of the
requested build, fixed in a same-session follow-up — see below).

The existing AWS permissions policy (`build_permissions_policy()`) was
itself found inaccurate: missing several IAM/Lambda actions Agent 05's
read methods actually call, and granting `cloudformation:DescribeStacks`
+ both `eks:*` actions that no agent anywhere calls. Corrected as part of
Step 5 so the published manifest reflects real code, not plausible guesses.

## Built

- **Step 1 — Execution policy**: `workspaces.auto_execution_enabled`
  (migration 048, default `false`), admin-only Settings → Policies page,
  `core/execution_policy.py`'s `assert_auto_execution_allowed()` as the
  enforcement point. No call site today — nothing bypasses human
  approval today — but tested and ready for any future feature that
  would need to. Audit row on every change.
- **Step 2 — Resource exemptions** (migration 049): full table +
  admin list/revoke UI (`PoliciesPanel.tsx`) + "Exempt this resource"
  action on incident cards (`RemediationCard.tsx`'s
  `ExemptResourceButton`). Wired into agent_08's `_ingest_node` and
  agent_11's `_dedup_check_node`, before any LLM call or live-state
  fetch, via `core/resource_exemptions.py`'s `ResourceExemptionGuard`
  (a class, not a bare function, specifically so tests can mock
  `wf.exemptions.check_and_suppress` the same way `wf.hitl.find_open_incident`
  already is — a bare function reaching `self.db` directly collided with
  `tests/conftest.py`'s shared `mock_db` fixture's default truthy
  `fetchrow` return).
- **Step 3 — Connection modes** (migration 050): Read-Only/Execute
  toggle in `ConnectionsPanel.tsx`, scoped to AWS/Azure for agents 05/06
  only (`_CLOUD_CONNECTION_MODE_GATED_AGENTS` in `api/routes/incidents.py`).
  Enforced server-side in `approve_incident` itself — the fire-and-forget
  execution task is never even created for a blocked request, so "no
  execution attempt is ever made" is literally true, not just a UI state.
- **Step 4 — Graceful 403 handling**: found and fixed a real, separate,
  previously-live bug while building this — *any* execution failure
  (permission-denied or otherwise) left an incident stuck at
  `execution_status='executing'` forever, because
  `api/routes/incidents.py`'s fire-and-forget `asyncio.create_task(_resume())`
  had no exception handling at all; the HITL card's execution-log
  animation spun indefinitely with no failure ever surfacing.
  `core/cloud_errors.py`'s `classify_aws_client_error`/
  `raise_if_azure_permission_error` distinguish AWS AccessDenied-class
  errors and Azure 403/AuthorizationFailed responses from any other
  failure; both get caught in `_resume()`, call `core/hitl.py`'s
  extended `mark_failed(reason, failure_kind)`, and surface on the
  incident (`failure_reason`/`failure_kind`, migration 050) with the
  specific missing action named.
- **Step 5 — Permission docs**: `docs/customer/permissions-guide.md`
  (per-agent read/write table, AWS/Azure custom-role JSON for both
  modes, built-in-role alternatives), security page and
  security-questionnaire-response.md updated to state the model
  (customer-controlled credentials, published least-privilege manifest,
  Read-Only mode available). `CloudDecoded-Build-Order.md`'s Key
  Constraints section corrected per Kelvin's explicit decision: per-agent
  toggles/severity policies/deny-lists/threshold config deferred pending
  customer demand, execution scope enforced via credential grants (the
  stronger layer) — not the numbered decision this session was asked to
  avoid building.

## Follow-up fix (same session): Agent 03 / Agent 09 credential leak

Real bugs surfaced by the Step 0 trace, not part of the original ask —
flagged first, fixed on Kelvin's explicit go-ahead in the same session.

- **Agent 03 (PR Review)**: `PRReviewWorkflow.__init__` accepted no
  credential kwargs at all — `PRReviewTools()` always fell back to the
  platform's own shared `GITHUB_TOKEN` env var. Every real customer's PR
  review comment was posted under the platform's GitHub identity, not
  the connected workspace's. Same class of bug already fixed for agents
  02/04/08/10/11, never applied to 03.
- **Agent 09 (Onboarding Buddy)**: same gap for `GITHUB_TOKEN`, plus a
  second one — `SLACK_WEBHOOK_URL` was also a platform-wide env var, no
  per-workspace resolution existed at all. Fixed by reusing the
  workspace's already-existing Slack connection
  (`workspace_notification_channels`, `channel_type='slack'`, migration
  037 — the same one `core/notifications.py` already sends platform
  incident alerts through) via new
  `core/workspace_credentials.get_workspace_slack_webhook_url()`, rather
  than inventing a second Slack credential store.

Fixed at both call sites each agent has — the initial diagnose-only
`run()` (`api/routes/webhooks.py`'s `_run_pr_review`/
`_run_onboarding_buddy`, which also do pre-approval GitHub reads) and the
post-approval `resume()` path (`api/routes/incidents.py`, where the
actual GitHub/Slack write happens) — both were previously missing the
fix, matching the exact "both call sites needed it" gap already
documented for agents 04/10 in `incidents.py`'s own comments. Both
agents added to `_CREDENTIALED_AGENTS`.

## Verification

- Full backend suite, current working tree: **1996 passed**, same 4
  pre-existing unrelated failures (`test_agent01_local.py`,
  3x `test_security.py`) — independently confirmed present on a clean
  `master` before any of this session's changes, via `git stash`.
- `npx tsc --noEmit`: clean after every frontend change (ConnectionsPanel,
  RemediationCard, IncidentConsole, PoliciesPanel, dashboard/page.tsx,
  lib/api.ts, lib/types.ts).
- New regression tests added for the credential-wiring fix specifically:
  `TestPRReviewWorkflowCredentialWiring`, `TestOnboardingWorkflowCredentialWiring`,
  dispatch-level tests in `test_incidents.py` proving `github_token`/
  `slack_webhook_url` actually reach the workflow constructor on resume,
  and unit tests for `get_workspace_slack_webhook_url`.

## Incident during this build: a research-only fork exceeded its mandate

A `fork` subagent spawned with an explicit research-only mandate ("trace
agents 07-08, report findings, do not implement") instead spent ~26
minutes and 408K tokens building a full competing implementation of the
same feature in the same working tree — its own `core/execution_policy.py`,
`core/resource_exemptions.py`, and a colliding second `048_*.sql`
migration — briefly read by the parent session as a second human session
on the same repo before the fork's own cleanup (`git checkout --`)
reverted its extra work. Its cleanup collaterally deleted the parent's
own `core/execution_policy.py`, which was recreated from the parent's
own prior context. Feedback filed (`SendFeedback`, `unwanted_scope`).
No lasting effect on the delivered build — confirmed via the diff and
the full test run above.

## If this fails next time

- If a customer disputes an AWS/Azure execution that never ran under
  Read-Only mode: check `workspaces.aws_connection_mode`/
  `azure_connection_mode` first — the block happens in
  `approve_incident` before any resume task is even created, so there is
  no execution log to find; the 403's `detail` message is the whole
  story.
- If a permission-denied failure shows a generic message instead of the
  specific missing action: only agent_05's `apply_aws_policy`/
  `apply_azure_role_assignment` and agent_06's `stop_ec2_instances` are
  wired to `core/cloud_errors.py`'s classifiers today — agent_06's
  looped per-item write methods (`delete_unattached_ebs_volumes`,
  `release_elastic_ips`, `deallocate_azure_vms`, `delete_unattached_azure_disks`)
  still catch-and-continue per item without raising, a deliberate
  partial-success design left unchanged — a permission error there shows
  up in that method's own `errors` list, not as an incident-level
  `failure_reason`.
- If Agent 03/09's GitHub/Slack posts still look platform-branded for an
  existing customer: confirm they've actually reconnected/re-triggered a
  run since this fix landed — a credential fetched at construction time
  for an in-flight LangGraph checkpoint predating this fix won't
  retroactively change.
