"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
MCP audit logger — structured log line + DB write per tool call.

Security rule: argument SHAPES only, never argument VALUES.
  Good: arg_keys=["incident_id", "approver_note"]
  Bad:  arg_values={"incident_id": "abc-123", "approver_note": "approved"}

DB writes go to mcp_audit_log (migration 004).
Structured log line always emitted regardless of DB success.
"""

import logging
from typing import Optional
from uuid import UUID

from auth.models import CallerIdentity
from db import get_pool

log = logging.getLogger(__name__)


async def write_audit(
    tool_name: str,
    caller: CallerIdentity,
    arg_keys: list[str],
    status: str,                    # ok | error | rejected | killed
    latency_ms: int,
    error_code: Optional[str],
) -> None:
    """
    Emit a structured log line and write a row to mcp_audit_log.

    arg_keys: list of argument NAMES that were provided — never the values.
    error_code: short string like "insufficient_scope", "rate_limited", None on success.
    """
    # Structured log line — always emitted (survives DB failures)
    log.info(
        "[MCP/Audit] tool=%s workspace=%s auth=%s subject=%s status=%s "
        "latency_ms=%d arg_count=%d error=%s",
        tool_name,
        caller.workspace_id,
        caller.auth_method,
        caller.subject,
        status,
        latency_ms,
        len(arg_keys),
        error_code or "-",
    )

    # DB write — best-effort, never block the response on failure
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO mcp_audit_log
                  (workspace_id, tool_name, auth_method, caller_subject, user_id,
                   arg_keys, arg_key_count, status, error_code, latency_ms)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                """,
                UUID(caller.workspace_id),
                tool_name,
                caller.auth_method,
                caller.subject,
                caller.user_id,
                arg_keys,
                len(arg_keys),
                status,
                error_code,
                latency_ms,
            )
    except Exception as exc:
        log.error("[MCP/Audit] DB write failed (tool=%s): %s", tool_name, exc)
