"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Migration runner — applies db/migrations/*.sql to the live database on
every app startup (api/main.py's lifespan, immediately after the asyncpg
pool is created, before anything else touches the DB).

Built 2026-09-15 after discovering migrations 024-028 had been committed,
pushed, and deployed for an entire session without ever actually running
against production — there was no migration runner anywhere in the
deploy pipeline, so schema and application code silently drifted apart
and real customer signups failed with a 500 for hours before it was
caught. See GAPS.md #15.

Design:
- A `schema_migrations` tracking table (filename, applied_at) records
  what's already run, so this stays fast on every boot (skip files
  already applied) instead of re-executing 28+ statements on every deploy.
- Everything — the tracking table's own creation, reading what's already
  applied, and running every pending file — happens inside ONE
  transaction, guarded by `pg_advisory_xact_lock` (the transaction-scoped
  advisory lock, not the session-scoped `pg_advisory_lock`/`unlock` pair).
  This matters specifically because DATABASE_URL points at Supabase's
  transaction-mode pooler (see api/main.py's own comment on
  statement_cache_size=0) — a session-scoped lock is not guaranteed to be
  held and released on the same underlying server connection under that
  pooling mode, but a transaction-scoped lock is, because pgbouncer's
  transaction mode does guarantee one stable server connection for the
  lifetime of one transaction. The lock serializes concurrent boots (if
  this service ever scales to >1 replica, two processes must not race to
  apply the same migration) and auto-releases on commit or rollback — no
  manual unlock, so nothing can leak a held lock on a crash.
- Postgres DDL is transactional, so wrapping the whole pending batch in
  one transaction is correct and simpler than one-transaction-per-file:
  either the full batch applies and is recorded together, or none of it
  is — there is no intermediate state where the tracking table disagrees
  with what's actually in the schema. Every migration file's own
  IF NOT EXISTS guards (required by this project's migration-authoring
  convention) mean a retried batch after a transient failure is still
  safe to reapply from the top.
- Fails closed: if a migration's SQL raises, this raises too, and
  api/main.py's lifespan does not complete — the app does not start and
  does not serve traffic against a schema the application code doesn't
  match. A loud crashed deploy here is correct; the alternative (what
  actually happened) is a silent 500 on every signup for as long as
  nobody notices.
"""

import logging
import re
from pathlib import Path

import asyncpg

log = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Arbitrary fixed constant, unique to this app's migration lock -- any
# int64 works, it just has to be the same value every time this module
# runs so concurrent boots actually contend on it.
_ADVISORY_LOCK_ID = 847_291_055

_FILENAME_RE = re.compile(r"^(\d+)_.*\.sql$")


def _discover_migrations() -> list[Path]:
    """Every db/migrations/*.sql file, sorted by its numeric prefix (not
    lexical filename order -- avoids a future 100_ sorting before 99_,
    and raises clearly on a filename that doesn't follow the required
    NNN_description.sql convention instead of silently misordering it)."""
    numbered: list[tuple[int, Path]] = []
    for path in _MIGRATIONS_DIR.glob("*.sql"):
        match = _FILENAME_RE.match(path.name)
        if not match:
            raise ValueError(
                f"Migration file {path.name} doesn't match the required "
                f"NNN_description.sql naming convention -- refusing to guess its order"
            )
        numbered.append((int(match.group(1)), path))
    numbered.sort(key=lambda pair: pair[0])
    return [path for _, path in numbered]


async def run_pending_migrations(pool: asyncpg.Pool) -> list[str]:
    """
    Applies every db/migrations/*.sql file not yet recorded in
    schema_migrations, in numeric order, as one all-or-nothing
    transaction. Returns the list of filenames applied this call (empty
    on a normal boot once the schema is caught up).

    Raises on the first migration that fails, rolling back the entire
    batch -- callers (api/main.py's lifespan) must let this propagate;
    do not catch-and-continue, that is exactly the silent-drift failure
    mode this module exists to prevent.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", _ADVISORY_LOCK_ID)

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            applied_rows = await conn.fetch("SELECT filename FROM schema_migrations")
            already_applied = {r["filename"] for r in applied_rows}

            newly_applied: list[str] = []
            for path in _discover_migrations():
                if path.name in already_applied:
                    continue

                sql = path.read_text()
                log.info("[Migrate] Applying %s ...", path.name)
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (filename) VALUES ($1)",
                    path.name,
                )
                newly_applied.append(path.name)

            if newly_applied:
                log.info(
                    "[Migrate] %d migration(s) applied: %s",
                    len(newly_applied), ", ".join(newly_applied),
                )
            else:
                log.info("[Migrate] Schema up to date — 0 pending migrations")

            return newly_applied


async def log_security_posture(pool: asyncpg.Pool) -> None:
    """
    Read-only diagnostic, run once at every startup after migrations.
    Phase 11, scale-readiness build (GAPS.md #20).

    "Row-level security is enabled on these tables" and "row-level
    security is enforced for THIS application's own queries" are two
    different claims -- a Postgres superuser, or the owner of a table
    that isn't FORCE ROW LEVEL SECURITY'd (migration 031 deliberately
    doesn't force it -- see that file's own comment), silently bypasses
    every RLS policy no matter how correctly it's written. This logs
    which case DATABASE_URL's role is actually in, instead of leaving it
    an assumption baked into a comment that can go stale.
    """
    async with pool.acquire() as conn:
        role_row = await conn.fetchrow(
            "SELECT current_user AS role, rolsuper, rolbypassrls "
            "FROM pg_roles WHERE rolname = current_user"
        )

    log.info(
        "[Security] DB role posture — role=%s superuser=%s bypassrls=%s",
        role_row["role"], role_row["rolsuper"], role_row["rolbypassrls"],
        extra={
            "db_role": role_row["role"],
            "db_role_superuser": role_row["rolsuper"],
            "db_role_bypassrls": role_row["rolbypassrls"],
        },
    )
    if role_row["rolsuper"] or role_row["rolbypassrls"]:
        log.warning(
            "[Security] DATABASE_URL's role bypasses row-level security "
            "entirely for this application's own queries — RLS policies on "
            "workspaces/incidents/audit_events/token_usage protect other "
            "access paths (Supabase Studio, anon/authenticated keys, future "
            "tools connecting as a different role), not this app's own "
            "connection. Application-layer workspace_id scoping remains the "
            "real boundary here. See GAPS.md #20.",
        )
