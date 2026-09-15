"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Real audit_events DB writer — GAPS.md #28. Before this module existed,
nothing in this codebase ever wrote a row to audit_events: core/hitl.py's
_write_audit_entry() and agents/base_agent.py's _write_audit() both, despite
their names and "Rule 9 compliance" docstrings, only ever appended a line to
a local markdown file (knowledge/operator/llm-audit.md) — not the database.
The security page and security-questionnaire-response.md's "full audit
trail" claims were not backed by the DB for any of the 11 agents' actions
until this.

write_audit_event() is called via asyncio.create_task() from both
_write_audit_entry() and _write_audit() so their existing synchronous
call sites (dozens, across core/hitl.py and every agents/agent_0N_*/
workflow.py) need zero changes — the markdown writer stays exactly as it
was (kept deliberately, per instruction, as a secondary operator-debugging
output), this just adds a detached DB write alongside it.

Opens its own short-lived asyncpg connection rather than reusing the
caller's — same DATABASE_URL + statement_cache_size=0 pattern already
proven by core/notifications.py's notify_incident_channels() for exactly
this reason: a detached asyncio.create_task() can easily outlive the
connection the synchronous caller checked out from a request-scoped pool,
and reusing it risks running a query on a connection another request has
since checked back in.
"""

import asyncio
import json
import logging
import os
from typing import Optional
from uuid import UUID

import asyncpg

log = logging.getLogger(__name__)


async def write_audit_event(
    workspace_id: Optional[str],
    action: str,
    status: Optional[str] = None,
    incident_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    tokens_used: int = 0,
    metadata: Optional[dict] = None,
) -> None:
    """
    Best-effort write of one row to audit_events. Never raises — every
    failure (missing DATABASE_URL, connection, or the INSERT itself) is
    caught and logged as a warning, since this always runs detached (via
    asyncio.create_task from a synchronous caller) with nothing left to
    propagate a failure back to.

    workspace_id: several of core/hitl.py's own call sites
    (bump_occurrence/approve_incident/mark_executed/mark_failed) pass the
    literal string "unknown" here, because workspace_id was never
    threaded through those particular HITLGate methods' own signatures —
    a pre-existing gap in hitl.py, not something this module should
    require every one of those callers to be reworked to fix just to get
    a real audit row. When workspace_id isn't a real UUID but a real
    incident_id is, this resolves the workspace via a single extra
    `SELECT workspace_id FROM incidents WHERE id = $1` before the insert,
    rather than silently dropping the write (which is what would happen
    for mark_executed — the completion event for every successful
    remediation across every agent — if this fallback didn't exist).
    """
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        log.warning(
            "[Audit] DATABASE_URL not set — skipping audit_events write for action=%s",
            action, extra={"workspace_id": workspace_id, "action": action},
        )
        return
    asyncpg_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    try:
        conn = await asyncpg.connect(asyncpg_url, statement_cache_size=0)
    except Exception as exc:
        log.warning(
            "[Audit] Could not open DB connection for workspace=%s action=%s: %s",
            workspace_id, action, exc,
            extra={"workspace_id": workspace_id, "action": action},
        )
        return

    try:
        resolved_workspace_id = workspace_id if _looks_like_uuid(workspace_id) else None
        resolved_incident_id = UUID(str(incident_id)) if incident_id and _looks_like_uuid(incident_id) else None

        if resolved_workspace_id is None and resolved_incident_id is not None:
            row = await conn.fetchrow(
                "SELECT workspace_id FROM incidents WHERE id = $1", resolved_incident_id,
            )
            if row:
                resolved_workspace_id = row["workspace_id"]

        if resolved_workspace_id is None:
            log.warning(
                "[Audit] Could not resolve a real workspace_id for action=%s (incident_id=%s) — skipped",
                action, incident_id, extra={"action": action, "incident_id": incident_id},
            )
            return

        await conn.execute(
            """
            INSERT INTO audit_events (workspace_id, agent_id, incident_id, action, status, tokens_used, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            UUID(str(resolved_workspace_id)),
            agent_id,
            resolved_incident_id,
            action,
            status,
            tokens_used,
            json.dumps(metadata) if metadata else None,
        )
    except Exception as exc:
        log.warning(
            "[Audit] audit_events write failed for workspace=%s action=%s: %s",
            workspace_id, action, exc,
            extra={"workspace_id": workspace_id, "action": action},
        )
    finally:
        await conn.close()


def schedule_audit_event(**kwargs) -> None:
    """
    Fire-and-forget wrapper around write_audit_event() for synchronous
    callers (core/hitl.py's _write_audit_entry, agents/base_agent.py's
    _write_audit — both plain `def`, not `async def`, called from dozens
    of existing call sites that must not need to change). Checks for a
    running event loop before constructing the write_audit_event()
    coroutine at all, rather than the more common
    `asyncio.create_task(coro())` inside try/except — that ordering
    still evaluates coro() (creating a real coroutine object) before
    create_task can raise on "no running event loop", which raises a
    'coroutine was never awaited' RuntimeWarning on every synchronous
    caller (e.g. every existing sync unit test that calls
    BaseAgent._write_audit() directly, which most do). Checking first
    avoids ever constructing that orphaned coroutine.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        log.debug("[Audit] No running event loop — skipping audit_events write (markdown log still written)")
        return
    try:
        asyncio.create_task(write_audit_event(**kwargs))
    except Exception as exc:
        log.warning("[Audit] Failed to schedule audit_events write: %s", exc)


def _looks_like_uuid(value: str) -> bool:
    """
    Guards against the handful of internal callers that pass a literal
    "unknown" sentinel instead of a real UUID (core/hitl.py's
    bump_occurrence/approve_incident/mark_executed/mark_failed all call
    _write_audit_entry("unknown", "hitl_gate", ...) — the workspace_id
    isn't threaded through those call sites today). A bad UUID string
    reaching asyncpg's UUID() cast would raise and be swallowed by the
    try/except above anyway, but checking first avoids the wasted
    connection + a noisy warning log for an expected, known case.
    """
    try:
        UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False
