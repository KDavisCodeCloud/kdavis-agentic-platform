"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
asyncpg connection pool singleton for the MCP server.

The MCP server shares the same Postgres database as the main backend
but maintains its own pool — it is a separate process with separate
resource limits. The pool is used only for:
  - API key hash lookups (mcp_api_keys table)
  - Audit log writes (mcp_audit_log table)

All business data queries go through the upstream FastAPI backend.
"""

import logging

import asyncpg

from config import DATABASE_URL

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    if not DATABASE_URL:
        raise EnvironmentError("DATABASE_URL not set — MCP server cannot connect to DB")
    _pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=2,
        max_size=5,
        command_timeout=10,
    )
    log.info("[MCP/DB] Pool created (min=2, max=5)")


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        log.info("[MCP/DB] Pool closed")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call init_pool() during lifespan")
    return _pool
