"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Public demo sandbox (24-gap-closure build, Phase 6). Backs GET /demo
(api/routes/demo.py) -- an unauthenticated visitor gets a scoped,
time-limited session in ONE demo workspace. Since migration 059 each
session owns its own copy of the 8 synthetic incidents
(incidents.demo_session_id), and every demo-reachable incident query in
api/routes/incidents.py is filtered to it via demo_scope_clause, so
visitors never see or change each other's state.

This module is the single source of truth for the seed data --
scripts/seed_demo_incidents.py imports DEMO_INCIDENTS and
insert_demo_incidents from here rather than duplicating them (that
script is now a thin CLI wrapper for manual/local use; the live app
never shells out to it).

Structural guarantees that real execution is impossible from the demo
workspace -- all three hold independently; any one alone would already
be sufficient:
  1. No cloud credential column is ever populated here (every
     encrypted_*/aws_*/azure_*/github_*/k8s_* column on the workspaces
     row stays NULL).
  2. aws_connection_mode / azure_connection_mode are set to 'read_only'
     at creation -- api/routes/incidents.py's _reject_if_read_only_
     connection rejects any execute-mode action for agent_05/agent_06
     before it ever reaches an agent.
  3. Every seeded incident carries is_test = true (migration 046) --
     approve_incident short-circuits is_test rows to a simulated
     'executed' result before ever calling build_agent_credentials or
     an agent's resume(), regardless of connection mode.

Demo sessions are NOT workspace_members rows. api/middleware/auth.py's
_get_workspace_by_demo_session resolves an X-Demo-Session-Token to a
workspace dict with member_role='approver' hardcoded in Python (never
persisted) -- Approve/Reject/Resolve-manually work, but there is no real
membership, so nothing here ever appears in workspace_members.py's
Members list. That dependency is wired into ONLY a handful of
api/routes/incidents.py routes; Settings/Members/Billing/Connections
routes never learn to parse X-Demo-Session-Token at all, so a demo
session cannot authenticate there structurally, not by a role check
that could later be loosened by mistake -- see tests/test_demo_sandbox.py.
"""

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

log = logging.getLogger(__name__)

# A raw demo session token always starts with this prefix -- mirrors
# frontend/src/lib/api.ts's own _DEMO_SESSION_TOKEN_PREFIX constant
# (kept in sync manually; frontend/src/lib/api.ts documents the pairing).
# request() there picks X-Demo-Session-Token by this shape, exactly like
# it already picks X-Workspace-Token vs Authorization: Bearer by the
# existing 'cd_ws_' prefix.
DEMO_SESSION_TOKEN_PREFIX = "cd_demo_"

DEMO_SESSION_TTL = timedelta(hours=24)
DEMO_RESET_INTERVAL_SECONDS = 30 * 60

# This app runs 4 --workers processes per deploy (api/main.py's lifespan
# starts one _demo_reset_loop per worker), so every reset pass is guarded
# by pg_try_advisory_xact_lock, same pattern as core/retention.py's
# _RETENTION_LOCK_ID -- without it all 4 workers would redundantly wipe
# and reseed the same demo workspace on every 30-minute tick. Distinct
# constant, never collides with any other advisory lock in this codebase
# (see the full list in those other modules' own _LOCK_ID constants).
_DEMO_RESET_LOCK_ID = 305_827_961

_DEMO_COMPANY_NAME = "Cloud Decoded Demo Workspace"

# One realistic-looking synthetic incident per row -- varied agents,
# severities, and resource names so a seeded console doesn't look
# obviously copy-pasted. agent_id values are real registered agents
# (not the "system_*" sentinels used by the connection-test button)
# specifically so the demo shows off actual per-agent remediation
# option copy, even though is_test=true still blocks real execution.
#
# Every remediation_options dict below MUST carry impact + docs_url --
# db.models.RemediationOption requires both with no default. Found live
# (2026-09-27, first real GET /incidents call against seeded demo data):
# this seed data was missing both fields entirely, silently 500ing every
# list_incidents/get_incident call for any workspace seeded from it --
# a pre-existing bug in the original scripts/seed_demo_incidents.py data,
# inherited when it moved here, never caught before because nothing had
# ever actually listed incidents against seeded rows through this exact
# Pydantic-validating code path until GET /demo's live verification.
DEMO_INCIDENTS = [
    {
        "agent_id": "agent_01_cicd_triage", "severity": "high",
        "resource_name": "deploy-pipeline-prod", "cloud_provider": "aws",
        "parsed_error": "Deployment pipeline failing at the integration-test stage — 3 consecutive runs.",
        "remediation_options": [
            {"id": "opt_1", "title": "Re-run failed jobs", "description": "Re-runs only the failed test jobs.",
             "impact": "low", "docs_url": "https://docs.github.com/en/actions/managing-workflow-runs/re-running-workflows-and-jobs"},
            {"id": "opt_2", "title": "Roll back to last green commit", "description": "Reverts to the last passing deploy.",
             "impact": "medium", "docs_url": "https://docs.github.com/en/actions"},
        ],
    },
    {
        "agent_id": "agent_02_k8s_alert", "severity": "critical",
        "resource_name": "checkout-service", "cloud_provider": "aws",
        "parsed_error": "Pod checkout-service-7f9d8 in CrashLoopBackOff — OOMKilled 5 times in 10 minutes.",
        "remediation_options": [
            {"id": "opt_1", "title": "Increase memory limit", "description": "Bumps the pod memory limit by 50%.",
             "impact": "low", "docs_url": "https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/"},
            {"id": "opt_2", "title": "Roll back to previous image", "description": "Reverts to the last known-stable image tag.",
             "impact": "medium", "docs_url": "https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#rolling-back-a-deployment"},
        ],
    },
    {
        "agent_id": "agent_03_pr_review", "severity": "medium",
        "resource_name": "PR #482", "cloud_provider": None,
        "parsed_error": "PR introduces a hardcoded API key in config/settings.py.",
        "remediation_options": [
            {"id": "opt_1", "title": "Request changes", "description": "Comments on the PR requesting the secret be moved to env vars.",
             "impact": "low", "docs_url": "https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/reviewing-proposed-changes-in-a-pull-request"},
        ],
    },
    {
        "agent_id": "agent_05_iam_minimizer", "severity": "medium",
        "resource_name": "role/data-pipeline-worker", "cloud_provider": "aws",
        "parsed_error": "IAM role has s3:* on all buckets; only 2 buckets are actually accessed in the last 90 days.",
        "remediation_options": [
            {"id": "opt_1", "title": "Scope down to the 2 used buckets", "description": "Replaces the wildcard policy with least-privilege access.",
             "impact": "medium", "docs_url": "https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html#grant-least-privilege"},
        ],
    },
    {
        "agent_id": "agent_06_finops", "severity": "low",
        "resource_name": "i-0a1b2c3d4e5f", "cloud_provider": "aws",
        "parsed_error": "EC2 instance has been idle (<3% CPU) for 14 days — estimated $210/mo waste.",
        "remediation_options": [
            {"id": "opt_1", "title": "Stop the instance", "description": "Stops (not terminates) the idle instance.",
             "impact": "low", "docs_url": "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/Stop_Start.html"},
            {"id": "opt_2", "title": "Downsize to a smaller instance type", "description": "Right-sizes based on actual usage.",
             "impact": "medium", "docs_url": "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-resize.html"},
        ],
    },
    {
        "agent_id": "agent_08_drift_detection", "severity": "high",
        "resource_name": "aks-prod-cluster", "cloud_provider": "azure",
        "parsed_error": "Live cluster config has drifted from the Terraform state — a NetworkPolicy was manually deleted.",
        "remediation_options": [
            {"id": "opt_1", "title": "Re-apply Terraform", "description": "Re-applies the last known-good Terraform state.",
             "impact": "medium", "docs_url": "https://developer.hashicorp.com/terraform/cli/commands/apply"},
        ],
    },
    {
        "agent_id": "agent_10_dependency_patch", "severity": "critical",
        "resource_name": "package.json", "cloud_provider": None,
        "parsed_error": "lodash@4.17.15 has a known critical prototype-pollution CVE (CVE-2020-8203).",
        "remediation_options": [
            {"id": "opt_1", "title": "Patch to lodash@4.17.21", "description": "Opens a PR bumping the dependency to the patched version.",
             "impact": "low", "docs_url": "https://nvd.nist.gov/vuln/detail/CVE-2020-8203"},
        ],
    },
    {
        "agent_id": "agent_11_resource_health", "severity": "medium",
        "resource_name": "rds-prod-primary", "cloud_provider": "aws",
        "parsed_error": "RDS free storage space below 10% and trending down — projected full in 6 days.",
        "remediation_options": [
            {"id": "opt_1", "title": "Increase allocated storage", "description": "Bumps allocated storage by 25%.",
             "impact": "medium", "docs_url": "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PIOPS.StorageTypes.html#USER_PIOPS.Autoscaling"},
        ],
    },
]


def hash_demo_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def get_or_create_demo_workspace(conn) -> UUID:
    """
    Idempotent: returns the existing singleton demo workspace
    (workspaces.is_demo_workspace, migration 057's partial unique index)
    if one exists, otherwise creates it. The generated workspace_token is
    never handed to anyone -- demo visitors authenticate via
    demo_sessions/X-Demo-Session-Token instead (see get_workspace_or_
    member_or_demo) -- it exists only because workspace_token is
    UNIQUE NOT NULL on every workspaces row.
    """
    row = await conn.fetchrow("SELECT id FROM workspaces WHERE is_demo_workspace = true LIMIT 1")
    if row:
        return row["id"]

    raw_token = "cd_ws_" + secrets.token_urlsafe(32)
    row = await conn.fetchrow(
        """
        INSERT INTO workspaces (
            company_name, workspace_token, stripe_subscription_status,
            product_tier, is_demo_workspace, aws_connection_mode, azure_connection_mode
        ) VALUES ($1, $2, 'active', 'enterprise', true, 'read_only', 'read_only')
        RETURNING id
        """,
        _DEMO_COMPANY_NAME, hash_demo_token(raw_token),
    )
    log.info("[DemoSandbox] Created demo workspace %s", row["id"])
    return row["id"]


async def insert_demo_incidents(
    conn, workspace_id: UUID, wipe_first: bool = True, demo_session_id: Optional[UUID] = None,
) -> int:
    """Shared by the CLI script (demo_session_id=None, seeding a real
    prospect's workspace) and create_demo_session (one copy per visitor,
    migration 059). --wipe-first makes re-running this idempotent instead
    of accumulating duplicates. With a demo_session_id it wipes only that
    session's rows, never another visitor's."""
    if wipe_first:
        if demo_session_id is None:
            deleted = await conn.execute(
                "DELETE FROM incidents WHERE workspace_id = $1 AND is_test = true", workspace_id,
            )
        else:
            deleted = await conn.execute(
                "DELETE FROM incidents WHERE workspace_id = $1 AND is_test = true AND demo_session_id = $2",
                workspace_id, demo_session_id,
            )
        log.info("[DemoSandbox] Wiped existing test incidents for %s: %s", workspace_id, deleted)

    now = datetime.now(timezone.utc)
    for i, spec in enumerate(DEMO_INCIDENTS):
        created_at = now - timedelta(hours=len(DEMO_INCIDENTS) - i)
        await conn.execute(
            """
            INSERT INTO incidents (
                workspace_id, agent_id, cloud_provider, raw_log_hash,
                parsed_error, remediation_options, execution_status,
                resource_name, severity, is_test, last_seen_at, created_at,
                demo_session_id
            ) VALUES ($1, $2, $3, $4, $5, $6, 'pending_approval', $7, $8, true, $9, $9, $10)
            """,
            workspace_id,
            spec["agent_id"],
            spec["cloud_provider"],
            f"demo-seed-{i}",
            spec["parsed_error"],
            json.dumps(spec["remediation_options"]),
            spec["resource_name"],
            spec["severity"],
            created_at,
            demo_session_id,
        )
    return len(DEMO_INCIDENTS)


async def run_demo_reset(pool) -> None:
    """
    Scheduled entry point -- api/main.py's _demo_reset_loop runs this
    every DEMO_RESET_INTERVAL_SECONDS (30 min). Since migration 059 every
    visitor has their own incidents, so there is no shared baseline to
    restore: this pass only prunes expired demo_sessions rows. Their
    incidents (and those incidents' comments) go with them via
    ON DELETE CASCADE. It also removes any stray session-less test rows in
    the demo workspace, which no demo visitor can see anyway.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            got_lock = await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)", _DEMO_RESET_LOCK_ID)
            if not got_lock:
                log.info("[DemoSandbox] Another worker holds the reset lock — skipping this cycle")
                return

            workspace_id = await get_or_create_demo_workspace(conn)
            pruned = await conn.execute("DELETE FROM demo_sessions WHERE expires_at < NOW()")
            orphans = await conn.execute(
                "DELETE FROM incidents WHERE workspace_id = $1 AND is_test = true AND demo_session_id IS NULL",
                workspace_id,
            )

    log.info(
        "[DemoSandbox] Pruned demo workspace %s (expired sessions: %s, session-less test incidents: %s)",
        workspace_id, pruned, orphans,
    )


async def create_demo_session(pool, attribution: Optional[dict] = None) -> tuple[str, datetime]:
    """
    GET /demo's entry point. Always creates a NEW session/token for the
    visitor (never reuses another visitor's token) in the one demo
    workspace, and seeds that session its own copy of the baseline
    incidents (migration 059). The session row and its incidents are
    written in one transaction, so a visitor never gets a token whose
    console is empty. No other visitor's incidents are read or touched.

    attribution (migration 060): optional ref/utm_* from the visitor's
    ?ref= / UTM link, validated by core.funnel_events and stored on the
    session so server-recorded demo events inherit them.
    """
    from core.funnel_events import clean_ref, clean_utm  # noqa: PLC0415 -- keeps this module's import graph unchanged

    attribution = attribution or {}
    async with pool.acquire() as conn:
        async with conn.transaction():
            workspace_id = await get_or_create_demo_workspace(conn)

            raw_token = DEMO_SESSION_TOKEN_PREFIX + secrets.token_urlsafe(32)
            expires_at = datetime.now(timezone.utc) + DEMO_SESSION_TTL
            session_id = await conn.fetchval(
                """
                INSERT INTO demo_sessions (
                    workspace_id, session_token_hash, expires_at,
                    ref, utm_source, utm_medium, utm_campaign
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                workspace_id, hash_demo_token(raw_token), expires_at,
                clean_ref(attribution.get("ref")),
                clean_utm(attribution.get("utm_source")),
                clean_utm(attribution.get("utm_medium")),
                clean_utm(attribution.get("utm_campaign")),
            )
            await insert_demo_incidents(conn, workspace_id, wipe_first=False, demo_session_id=session_id)

    return raw_token, expires_at


async def resolve_demo_session(pool, raw_token: str) -> Optional[dict]:
    """
    Validates an X-Demo-Session-Token. Returns None (never raises) on
    anything wrong -- api/middleware/auth.py's
    _get_workspace_by_demo_session turns that into the appropriate HTTP
    error; this function is pure lookup logic so it's independently
    testable without a Request object.
    """
    if not raw_token or not raw_token.startswith(DEMO_SESSION_TOKEN_PREFIX):
        return None

    token_hash = hash_demo_token(raw_token)
    async with pool.acquire() as conn:
        session_row = await conn.fetchrow(
            "SELECT id, workspace_id, expires_at FROM demo_sessions WHERE session_token_hash = $1",
            token_hash,
        )
        if not session_row:
            return None
        if session_row["expires_at"] <= datetime.now(timezone.utc):
            return None

        # Deliberately only the columns get_workspace_member/get_workspace
        # already expose -- see api/middleware/auth.py's
        # _WORKSPACE_SELECT_COLUMNS. Selecting '*' here would risk a demo
        # dict silently gaining a field real sessions don't carry.
        from api.middleware.auth import _WORKSPACE_SELECT_COLUMNS  # noqa: PLC0415 -- avoids a module import cycle at load time

        workspace_row = await conn.fetchrow(
            f"SELECT {_WORKSPACE_SELECT_COLUMNS} FROM workspaces WHERE id = $1",
            session_row["workspace_id"],
        )

    if not workspace_row:
        return None

    result = dict(workspace_row)
    result["member_id"] = None
    result["member_role"] = "approver"
    result["member_email"] = "Demo Visitor"
    result["is_demo_session"] = True
    # Migration 059: api/routes/incidents.py scopes every demo-reachable
    # incident lookup to this session's own rows via demo_scope_clause.
    result["demo_session_id"] = session_row["id"]
    return result


def demo_scope_clause(workspace: dict, param_index: int, column: str = "demo_session_id") -> tuple[str, list]:
    """
    SQL fragment + params that restrict an incidents query to the calling
    demo visitor's own rows. Returns ("", []) for every real workspace or
    member session, so real-customer queries are unchanged.

    Fails closed: a demo identity without a session id raises instead of
    falling back to unscoped access to every visitor's incidents.
    """
    if not workspace.get("is_demo_session"):
        return "", []
    session_id = workspace.get("demo_session_id")
    if not session_id:
        raise RuntimeError("Demo session identity is missing demo_session_id; refusing an unscoped incidents query")
    return f" AND {column} = ${param_index}", [session_id]
