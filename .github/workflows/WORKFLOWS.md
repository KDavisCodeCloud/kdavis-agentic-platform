# GitHub Actions — Plain-English Guide

This is the starting point for understanding everything that runs
automatically in this repo. If you're new here (hi — this means you,
future team member), read this before touching `.github/workflows/`.

Every workflow file has one job and one trigger. You approve work in
the dashboard. GitHub Actions executes it. Check the Actions tab
(`github.com/KDavisCodeCloud/agentic-platform` → Actions) the same
way you'd check the dashboard — every run shows status, trigger,
duration, and logs.

---

## deploy.yml

**Trigger:** push to `main`

**What it does:**
1. Runs lint (`ruff`), type check (`mypy`), and `pytest` — if anything
   fails, the deploy stops here and nothing ships
2. Builds the Docker image from `infra/docker/Dockerfile.product`
3. Pushes the image to AWS ECR
4. Renders and updates the Fargate task definition to use the new image
5. Deploys to ECS/Fargate — rolling update, zero downtime
6. Notifies the dashboard so `release_notes_agent` can document the deploy

**You see it in:** Actions tab → `deploy.yml` → latest run
**You interact with it:** automatically, every time a PR merges to `main`

**Required repo secrets:** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_REGION`, `ECR_REPOSITORY`, `ECS_CLUSTER`, `ECS_SERVICE`,
`ECS_TASK_DEFINITION`, `ECS_CONTAINER_NAME`, `DASHBOARD_WEBHOOK_URL`,
`DASHBOARD_WEBHOOK_TOKEN`

---

## gitea-mirror.yml

**Trigger:** push to any branch

**What it does:** pushes the identical ref to the internal Gitea
server, simultaneously with GitHub. This is the private mirror —
GitHub stays the public portfolio repo, Gitea holds the same history
internally.

**You see it in:** Actions tab → `gitea-mirror.yml` (should always be green)
**You interact with it:** you don't — it's fully automatic

**Required repo secrets:** `GITEA_SSH_PRIVATE_KEY`, `GITEA_HOST`,
`GITEA_REMOTE_URL`, `DASHBOARD_WEBHOOK_URL`, `DASHBOARD_WEBHOOK_TOKEN`

---

## prompt-version-check.yml

**Trigger:** any PR to `main` touching `prompts/**`

**What it does:**
1. Diffs the PR against `main` for everything under `prompts/`
2. For each agent's prompt directory that changed, verifies a new
   `vX.Y.Z.md` file was added (not just edited in place)
3. Verifies that agent's `CHANGELOG.md` was updated in the same PR
4. Blocks the merge and comments on the PR if either check fails

**You see it in:** Actions tab → `prompt-version-check.yml`
**You interact with it:** bump the version filename and update
`CHANGELOG.md` before opening the PR — see `prompts/VERSIONING.md`

**Required permissions:** none beyond default `GITHUB_TOKEN`
(needs `pull-requests: write` to comment, already granted in the file)

---

## code-quality-gate.yml

**Trigger:** any PR opened or updated targeting `main`

**What it does:**
1. Checks out the PR branch, diffs changed `.py`/`.ts`/`.tsx` files only (fast)
2. Runs `code_quality_agent` against just those changed files
3. Posts the full report as a PR comment
4. **BLOCKING** issues (DRY violations, dead code): PR status fails,
   cannot merge until fixed or overridden via a dashboard HITL card
   with a documented reason
5. **NON-BLOCKING** issues (bloat, readability, dependency bloat,
   inconsistency): PR passes, issues are written to the `tech_debt`
   Supabase table for the weekly digest
6. Either way, creates a decision card in the dashboard HITL queue

**You see it in:** Actions tab → `code-quality-gate.yml`
**You interact with it:** review the dashboard decision card, fix
blocking issues or approve the override, then re-push to re-trigger

**Required repo secrets:** `DASHBOARD_WEBHOOK_URL`, `DASHBOARD_WEBHOOK_TOKEN`

---

## weekly-sweep.yml

**Trigger:** cron, every Monday 11:00 UTC (6:00am US Central Standard
Time — shift the cron expression if daylight saving time or your
timezone changes), plus manual dispatch

**What it does:**
1. Runs `code_quality_agent` as a full sweep of the entire codebase
   (not just changed files — this is the deep pass)
2. Runs `gap_detector_agent` to find missing agent coverage
3. Runs `portfolio_monitor` for the weekly MRR/churn/signup digest
4. All three post a dashboard card for Monday morning review

**You see it in:** Actions tab → `weekly-sweep.yml` → Monday runs
**You interact with it:** Monday morning dashboard review session

**Required repo secrets:** `DASHBOARD_WEBHOOK_URL`, `DASHBOARD_WEBHOOK_TOKEN`

---

## email-sequence-deploy.yml

**Trigger:** manual dispatch only — you trigger it yourself after
approving an email sequence in the dashboard HITL queue

**What it does:**
1. Takes `product_id` (required) and `sequence_id` (optional — defaults
   to the latest approved sequence for that product) as inputs
2. Reads the approved sequence from the Supabase `email_sequences` /
   `email_sequence_steps` tables
3. Calls the Systeme.io API to create or update the sequence and tag
4. Confirms the deployment back to the dashboard

**You see it in:** Actions tab → `email-sequence-deploy.yml` → manual runs
**You interact with it:** after approving a sequence in the dashboard,
go to Actions → `email-sequence-deploy.yml` → **Run workflow** →
fill in `product_id`

**Required repo secrets:** `SYSTEME_IO_API_KEY`, `SUPABASE_URL`,
`SUPABASE_KEY`, `DASHBOARD_WEBHOOK_URL`, `DASHBOARD_WEBHOOK_TOKEN`

---

## sop-sync.yml

**Trigger:** `repository_dispatch` (event type `sop_created`), fired
by a Supabase database webhook the moment a row is inserted into the
`sops` table. Manual `workflow_dispatch` (with a `sop_id` input) is
kept as a fallback to re-sync a specific SOP by hand.

**What it does:** calls `obsidian/vault_sync.py` to push the SOP
markdown into the correct Obsidian vault folder
(`/KDavis Platform/SOPs/{agent_name}/{date}-{task}.md`)

**You see it in:** Actions tab → `sop-sync.yml`
**You interact with it:** you don't, normally — `sop_agent` triggers
this automatically after every agent run. Use manual dispatch only to
re-sync a SOP that failed to push.

**One-time setup required:** in Supabase Dashboard → Database →
Webhooks, add an INSERT webhook on the `sops` table that POSTs to
`https://api.github.com/repos/KDavisCodeCloud/agentic-platform/dispatches`
with header `Authorization: Bearer <PAT with repo scope>` and body
`{"event_type": "sop_created", "client_payload": {"sop_id": "<row id>"}}`.

**Required repo secrets:** `SUPABASE_URL`, `SUPABASE_KEY`,
`OBSIDIAN_VAULT_PATH`, `OBSIDIAN_REST_API_KEY`,
`DASHBOARD_WEBHOOK_URL`, `DASHBOARD_WEBHOOK_TOKEN`

---

## Setting up notifications

Settings → Notifications → Actions:
- Enable **failed workflow runs** (immediate)
- Enable **successful deploys** (digest)

This gives a daily email digest of what ran, without noise.

## Keeping this file current

Update this file every time a workflow is added, renamed, or its
trigger/secrets change. This is the map — if it drifts from reality,
the next person (including future-you) loses the whole point of it.
