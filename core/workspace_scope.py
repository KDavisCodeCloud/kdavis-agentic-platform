"""
core/workspace_scope.py
Phase 11, scale-readiness build -- database-level workspace isolation.

Every query in this codebase already scopes itself with an explicit
WHERE workspace_id = $N -- application-layer isolation, correct as far
as it goes, but it depends on every future query author never forgetting
that clause. db/migrations/031_rls_core_tables.sql adds real Postgres
row-level security policies to workspaces/incidents/audit_events/
token_usage keyed on the `app.current_workspace_id` session variable --
a query that runs inside workspace_scoped_connection() gets that
variable set and is blocked by the database itself from ever returning
another workspace's rows, even if its own WHERE clause is wrong or
missing entirely.

Important caveat (see GAPS.md #20): this only has teeth if the
Postgres role DATABASE_URL connects as is not a superuser and does not
own these tables outright (table owners bypass RLS unless the table
is also FORCE ROW LEVEL SECURITY'd, which migration 031 deliberately
does NOT set -- see that migration's own comment for why forcing it
blind could have taken the whole app down). db/migrate.py logs the
actual role posture (superuser/bypassrls) once at every startup so
this is a checked fact, not an assumption.
"""

from contextlib import asynccontextmanager

import asyncpg


@asynccontextmanager
async def workspace_scoped_connection(pool: asyncpg.Pool, workspace_id: str):
    """
    Acquires a connection, opens a transaction, and sets
    app.current_workspace_id to workspace_id for the lifetime of that
    transaction (set_config's third arg -- is_local=true -- scopes it to
    the current transaction only, which is what makes this safe under
    Supabase's transaction-mode pooler: the setting never outlives the
    transaction, so it can never leak onto a pooled connection some
    unrelated later request picks up).

    Use for read/write paths where a real, DB-enforced tenant boundary
    is worth the extra round trip -- not a blanket replacement for
    db.acquire() everywhere (see this module's docstring and GAPS.md #20
    for why this hasn't been rolled out to every call site yet).
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_workspace_id', $1, true)",
                str(workspace_id),
            )
            yield conn
