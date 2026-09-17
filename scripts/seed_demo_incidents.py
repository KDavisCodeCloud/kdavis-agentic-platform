"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

24-gap-closure build, Phase 6 -- demo/sandbox mode seed script. Inserts
8-10 synthetic incidents (incidents.is_test = true, migration 046)
directly into a target workspace so a prospect or trial customer can see
a realistic, populated HITL Console immediately, without waiting for
real cloud activity.

Approve/reject on these rows genuinely works (api/routes/incidents.py's
approve_incident already short-circuits is_test rows to a simulated
"executed" result instead of resuming any real agent workflow -- see
that route's own comment) -- so this is not a fake read-only demo, it's
real interaction against rows that simply can never trigger a real
cloud-side action. Reject/dismiss already never executed anything for
ANY incident (including real ones), so nothing extra was needed there.

Usage:
    python -m scripts.seed_demo_incidents <workspace_id> [--wipe-first]

--wipe-first deletes any existing is_test rows for this workspace before
seeding, so re-running the script is idempotent instead of accumulating
duplicates on every demo reset.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import asyncpg

# One realistic-looking synthetic incident per row -- varied agents,
# severities, and resource names so a seeded console doesn't look
# obviously copy-pasted. agent_id values are real registered agents
# (not the "system_*" sentinels used by the connection-test button)
# specifically so the demo shows off actual per-agent remediation
# option copy, even though is_test=true still blocks real execution.
_DEMO_INCIDENTS = [
    {
        "agent_id": "agent_01_cicd_triage", "severity": "high",
        "resource_name": "deploy-pipeline-prod", "cloud_provider": "aws",
        "parsed_error": "Deployment pipeline failing at the integration-test stage — 3 consecutive runs.",
        "remediation_options": [
            {"id": "opt_1", "title": "Re-run failed jobs", "description": "Re-runs only the failed test jobs."},
            {"id": "opt_2", "title": "Roll back to last green commit", "description": "Reverts to the last passing deploy."},
        ],
    },
    {
        "agent_id": "agent_02_k8s_alert", "severity": "critical",
        "resource_name": "checkout-service", "cloud_provider": "aws",
        "parsed_error": "Pod checkout-service-7f9d8 in CrashLoopBackOff — OOMKilled 5 times in 10 minutes.",
        "remediation_options": [
            {"id": "opt_1", "title": "Increase memory limit", "description": "Bumps the pod memory limit by 50%."},
            {"id": "opt_2", "title": "Roll back to previous image", "description": "Reverts to the last known-stable image tag."},
        ],
    },
    {
        "agent_id": "agent_03_pr_review", "severity": "medium",
        "resource_name": "PR #482", "cloud_provider": None,
        "parsed_error": "PR introduces a hardcoded API key in config/settings.py.",
        "remediation_options": [
            {"id": "opt_1", "title": "Request changes", "description": "Comments on the PR requesting the secret be moved to env vars."},
        ],
    },
    {
        "agent_id": "agent_05_iam_minimizer", "severity": "medium",
        "resource_name": "role/data-pipeline-worker", "cloud_provider": "aws",
        "parsed_error": "IAM role has s3:* on all buckets; only 2 buckets are actually accessed in the last 90 days.",
        "remediation_options": [
            {"id": "opt_1", "title": "Scope down to the 2 used buckets", "description": "Replaces the wildcard policy with least-privilege access."},
        ],
    },
    {
        "agent_id": "agent_06_finops", "severity": "low",
        "resource_name": "i-0a1b2c3d4e5f", "cloud_provider": "aws",
        "parsed_error": "EC2 instance has been idle (<3% CPU) for 14 days — estimated $210/mo waste.",
        "remediation_options": [
            {"id": "opt_1", "title": "Stop the instance", "description": "Stops (not terminates) the idle instance."},
            {"id": "opt_2", "title": "Downsize to a smaller instance type", "description": "Right-sizes based on actual usage."},
        ],
    },
    {
        "agent_id": "agent_08_drift_detection", "severity": "high",
        "resource_name": "aks-prod-cluster", "cloud_provider": "azure",
        "parsed_error": "Live cluster config has drifted from the Terraform state — a NetworkPolicy was manually deleted.",
        "remediation_options": [
            {"id": "opt_1", "title": "Re-apply Terraform", "description": "Re-applies the last known-good Terraform state."},
        ],
    },
    {
        "agent_id": "agent_10_dependency_patch", "severity": "critical",
        "resource_name": "package.json", "cloud_provider": None,
        "parsed_error": "lodash@4.17.15 has a known critical prototype-pollution CVE (CVE-2020-8203).",
        "remediation_options": [
            {"id": "opt_1", "title": "Patch to lodash@4.17.21", "description": "Opens a PR bumping the dependency to the patched version."},
        ],
    },
    {
        "agent_id": "agent_11_resource_health", "severity": "medium",
        "resource_name": "rds-prod-primary", "cloud_provider": "aws",
        "parsed_error": "RDS free storage space below 10% and trending down — projected full in 6 days.",
        "remediation_options": [
            {"id": "opt_1", "title": "Increase allocated storage", "description": "Bumps allocated storage by 25%."},
        ],
    },
]


async def seed(workspace_id: str, wipe_first: bool) -> None:
    url = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    ws_uuid = UUID(workspace_id)
    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        row = await conn.fetchrow("SELECT id FROM workspaces WHERE id = $1", ws_uuid)
        if not row:
            print(f"No workspace found with id {workspace_id}", file=sys.stderr)
            sys.exit(1)

        if wipe_first:
            deleted = await conn.execute(
                "DELETE FROM incidents WHERE workspace_id = $1 AND is_test = true", ws_uuid,
            )
            print(f"Wiped existing test incidents: {deleted}")

        now = datetime.now(timezone.utc)
        for i, spec in enumerate(_DEMO_INCIDENTS):
            created_at = now - timedelta(hours=len(_DEMO_INCIDENTS) - i)
            await conn.execute(
                """
                INSERT INTO incidents (
                    workspace_id, agent_id, cloud_provider, raw_log_hash,
                    parsed_error, remediation_options, execution_status,
                    resource_name, severity, is_test, last_seen_at, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, 'pending_approval', $7, $8, true, $9, $9)
                """,
                ws_uuid,
                spec["agent_id"],
                spec["cloud_provider"],
                f"demo-seed-{i}",
                spec["parsed_error"],
                json.dumps(spec["remediation_options"]),
                spec["resource_name"],
                spec["severity"],
                created_at,
            )

        print(f"Seeded {len(_DEMO_INCIDENTS)} demo incidents for workspace {workspace_id}")
    finally:
        await conn.close()


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    workspace_id = sys.argv[1]
    wipe_first = "--wipe-first" in sys.argv
    asyncio.run(seed(workspace_id, wipe_first))


if __name__ == "__main__":
    main()
