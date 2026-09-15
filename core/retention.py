"""
core/retention.py
Phase 12, scale-readiness build -- incident/audit-event retention.

Deletes incidents and audit_events older than the workspace's tier-based
retention window: 90 days (starter), 365 days (growth), never (enterprise
-- core/compliance.py's WorkspaceComplianceGuard.TIER_LIMITS["enterprise"]
["retention_days"] == -1, the same "-1 == unlimited" sentinel used for
every other tier limit in that dict).

Runs as a periodic in-process background task (api/main.py's lifespan
starts it, one iteration at startup then every 24h) rather than a
separate cron service -- this platform runs as Railway web-service
workers only, no worker/cron service exists to host a scheduled job
elsewhere. Phase 8 made that 4 worker processes per deploy, so every
iteration is guarded by pg_try_advisory_xact_lock (transaction-scoped,
non-blocking): if another worker already grabbed the lock for this
cycle, the rest just skip it instead of piling up redundant/overlapping
DELETEs. Transaction-scoped, not session-scoped (pg_try_advisory_lock),
for the same reason db/migrate.py uses pg_advisory_xact_lock instead of
the session-scoped pair -- DATABASE_URL points at Supabase's
transaction-mode pooler, which does not guarantee a session-scoped
lock's acquire and release happen on the same underlying server
connection, but does guarantee one stable connection for the lifetime
of a single transaction.
"""

import logging

import asyncpg

from core.compliance import WorkspaceComplianceGuard

log = logging.getLogger(__name__)

# Distinct from db/migrate.py's _ADVISORY_LOCK_ID (847_291_055) -- must
# never collide with it or any other advisory lock this app takes, or
# unrelated operations would block/skip each other.
_RETENTION_LOCK_ID = 592_014_773

_RETAINED_TABLES = ("incidents", "audit_events")


async def run_retention_cleanup(pool: asyncpg.Pool) -> dict:
    """
    One cleanup pass: for every tier with a finite retention_days, delete
    incidents/audit_events rows older than that many days, scoped to
    workspaces on that tier. Returns {table: rows_deleted} -- empty dict
    if another worker already holds the lock this cycle (not an error,
    just "someone else is doing this run").
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            got_lock = await conn.fetchval(
                "SELECT pg_try_advisory_xact_lock($1)", _RETENTION_LOCK_ID
            )
            if not got_lock:
                log.info("[Retention] Another worker holds the retention lock — skipping this cycle")
                return {}

            deleted: dict[str, int] = {table: 0 for table in _RETAINED_TABLES}

            for tier, limits in WorkspaceComplianceGuard.TIER_LIMITS.items():
                retention_days = limits.get("retention_days", -1)
                if retention_days == -1:
                    continue  # unlimited for this tier -- nothing to delete

                for table in _RETAINED_TABLES:
                    result = await conn.execute(
                        f"""
                        DELETE FROM {table} t
                        USING workspaces w
                        WHERE t.workspace_id = w.id
                          AND w.product_tier = $1
                          AND t.created_at < NOW() - ($2 || ' days')::interval
                        """,
                        tier,
                        str(retention_days),
                    )
                    # asyncpg execute() returns "DELETE <n>"
                    count = int(result.split()[-1])
                    deleted[table] += count

            total = sum(deleted.values())
            if total:
                log.info(
                    "[Retention] Cleanup pass deleted %d row(s): %s",
                    total, deleted,
                    extra={"retention_deleted": deleted, "retention_deleted_total": total},
                )
            else:
                log.info("[Retention] Cleanup pass — nothing past retention this cycle")

            return deleted
