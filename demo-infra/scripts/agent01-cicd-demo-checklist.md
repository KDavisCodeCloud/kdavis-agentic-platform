# Agent 01 (CI/CD Triage) — live demo checklist

Real, live-verified 2026-09-13 end to end. Follow this exact sequence when
recording — no improvising, every step below is a real action against real
infrastructure (GitHub Actions on `clouddecoded-demo-cicd`, the real Cloud
Decoded platform on Railway).

## One-time setup (already done, kept for re-use)

- Dedicated repo: `https://github.com/KDavisCodeCloud/clouddecoded-demo-cicd`
  (private). One workflow, `.github/workflows/ci.yml`, runs `pytest tests/`.
- Kelvin's real platform workspace (id `97e058c8-b101-4ae1-b58f-15987995898e`,
  Enterprise tier) has a GitHub webhook registered on this repo:
  `POST /api/v1/webhooks/github?token=<workspace_token>`, event
  `workflow_run`, secret = the workspace's per-workspace webhook secret
  (`PATCH /workspace/credentials/github`'s one-time response).
- Credentials are in `phase2_credentials.md` in this session's scratchpad —
  move to a password manager, they are not re-derivable from the API.

## Recording sequence

1. **Show the repo at rest**: `tests/test_math.py` has 2 passing tests,
   the last CI run on `main` is green.

2. **Break it**: append a new test with a deliberately wrong assertion
   (e.g. `assert add(2, 2) == 5`) to `tests/test_math.py`, commit, push
   to `main`.
   ```bash
   git add -A && git commit -m "Break the pipeline on purpose (Cloud Decoded Agent 01 live demo)"
   git push origin main
   ```

3. **Show the real GitHub Actions failure** (`gh run list` /
   the Actions tab) — this is genuine, not staged.

4. **Show the real webhook firing**: GitHub's real `workflow_run` webhook
   POSTs to the platform within seconds of the run completing. No manual
   trigger needed once the webhook is registered.

5. **Show the real incident appearing** — either in the real dashboard's
   HITL Console tab, or via:
   ```bash
   curl -s "https://kdavis-agentic-platform-production.up.railway.app/api/v1/incidents?status_filter=pending_approval" \
     -H "X-Workspace-Token: <workspace_token>"
   ```
   The `parsed_error` and `options` are real LLM output (Claude Haiku via
   the platform's own router), not canned text.

6. **Approve a real fix** — `opt_1` or `opt_2` both dispatch to the same
   real tool, `rerun_failed_jobs_only` (a real GitHub REST API call):
   ```bash
   curl -s -X POST "https://kdavis-agentic-platform-production.up.railway.app/api/v1/incidents/<incident_id>/approve" \
     -H "X-Workspace-Token: <workspace_token>" \
     -H "Content-Type: application/json" \
     -d '{"selected_option_id": "opt_2"}'
   ```

7. **Prove the mutation was real**, not a status-field fake:
   ```bash
   gh api repos/KDavisCodeCloud/clouddecoded-demo-cicd/actions/runs/<run_id> --jq '{status, conclusion, run_attempt}'
   ```
   `run_attempt` increments from 1 to 2 — GitHub actually reran the job
   because Cloud Decoded told it to, on your approval.

8. **The honest part of the story**: the rerun fails again, because the
   underlying bug is a real logic error, not a flaky test — the agent's
   job is triage and retry, not writing code. State this on camera; it's
   the credible, non-oversold version of what this agent actually does.

9. **Push the real fix**: correct the assertion, commit, push.
   ```bash
   git add -A && git commit -m "Real fix: correct the deliberately broken assertion (pipeline green again)"
   git push origin main
   ```

10. **Show the pipeline green again** — real, same repo, same workflow.

## What NOT to do when re-recording

- Don't reuse an incident that already went through `approve` once —
  LangGraph's checkpoint for that thread has already run past the
  interrupt; re-approving a stuck/already-executed incident does nothing
  new. Trigger a fresh break (a new push) for a clean incident every time.
- Don't skip step 8 — showing the honest retry-then-still-fails result
  before the real human fix is what makes the demo credible instead of
  looking staged.
