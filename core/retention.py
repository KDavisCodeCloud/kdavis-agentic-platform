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

# alert_ingestion_log holds raw, unsanitized webhook payloads (migration 030).
# They're only needed while an alert is being processed, so they get a short,
# tier-independent window (2026-11-18 claims audit decision). Each workspace's
# FIRST row is kept, with its payload replaced, because core/setup_checklist.py
# reads MIN(received_at) / existence to show the alert source as verified.
ALERT_PAYLOAD_RETENTION_DAYS = 30
_SCRUBBED_PAYLOAD = '{"removed": "raw payload deleted after the retention window"}'


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

            deleted.update(await _purge_alert_ingestion_log(conn))

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


async def _purge_alert_ingestion_log(conn) -> dict:
    """
    Delete alert_ingestion_log rows older than ALERT_PAYLOAD_RETENTION_DAYS,
    except each workspace's first row, whose raw payload is replaced instead.
    Unprocessed rows are included: a payload that old was never going to be
    retried. Runs inside run_retention_cleanup's locked transaction.
    """
    days = str(ALERT_PAYLOAD_RETENTION_DAYS)
    first_rows = (
        "SELECT DISTINCT ON (workspace_id) id FROM alert_ingestion_log "
        "WHERE workspace_id IS NOT NULL ORDER BY workspace_id, received_at, id"
    )
    deleted = await conn.execute(
        f"""
        DELETE FROM alert_ingestion_log
        WHERE received_at < NOW() - ($1 || ' days')::interval
          AND id NOT IN ({first_rows})
        """,
        days,
    )
    scrubbed = await conn.execute(
        f"""
        UPDATE alert_ingestion_log
        SET raw_payload = $2::text::jsonb
        WHERE received_at < NOW() - ($1 || ' days')::interval
          AND id IN ({first_rows})
          AND raw_payload <> $2::text::jsonb
        """,
        days,
        _SCRUBBED_PAYLOAD,
    )
    return {
        "alert_ingestion_log": int(deleted.split()[-1]),
        "alert_ingestion_log_scrubbed": int(scrubbed.split()[-1]),
    }
