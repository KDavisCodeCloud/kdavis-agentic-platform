"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

"""
Cloud Decoded — FastAPI application entry point.

Run locally:
    uvicorn api.main:app --reload --port 8000

Production:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 4
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# python-dotenv was a declared dependency with no load_dotenv() call anywhere
# in the codebase — every os.environ/os.getenv() read below silently only
# ever saw real process env vars, never .env's contents. Must run before any
# other import in this file touches env-derived config.
load_dotenv()

import asyncpg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from api.middleware.token_meter import TokenMeterMiddleware
from api.middleware.rate_limiter import limiter
from api.middleware.workspace_tier import WorkspaceTierMiddleware
from api.routes import agents, incidents, webhooks
from api.routes import stripe_billing
from api.routes import content
from api.routes import outreach
from api.routes import mcp_keys
from api.routes import gta_hub
from api.routes import marketing
from api.routes import internal_agents
from api.routes import internal_marketing

log = logging.getLogger(__name__)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)


# ──────────────────────────────────────────────
# Application lifespan — DB pool + LangGraph checkpointer
# ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Set up shared resources on startup; tear down on shutdown."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise EnvironmentError("DATABASE_URL not set")

    # Strip SQLAlchemy driver prefix for asyncpg direct connection
    asyncpg_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    # asyncpg pool — used by core/hitl.py, compliance.py, token_budget.py, routes
    #
    # statement_cache_size=0 is not optional: DATABASE_URL points at Supabase's
    # transaction-mode pooler (port 6543), which does not pin a client to one
    # server-side connection across statements. asyncpg's default prepared-
    # statement cache assumes a stable connection and will intermittently raise
    # DuplicatePreparedStatementError the moment two differently-shaped queries
    # land on a connection the pooler has silently recycled — e.g. the INSERT
    # in run_internal_agent() followed by the UPDATE in _execute_internal_agent()
    # a moment later. Found by exercising that exact pattern directly against
    # the live DB; every route using this pool was exposed, not just new ones.
    app.state.db_pool = await asyncpg.create_pool(
        asyncpg_url,
        min_size=2,
        max_size=10,
        command_timeout=60,
        statement_cache_size=0,
    )
    log.info("[API] Database pool created")

    # LangGraph Postgres checkpointer — persists agent workflow state
    # Uses psycopg (separate from asyncpg) — both connect to the same Postgres DB
    #
    # NOT using AsyncPostgresSaver.from_conn_string(): it hardcodes
    # prepare_threshold=0, which means "prepare on first use" - the opposite
    # of what's needed here. Against Supabase's transaction-mode pooler (same
    # DATABASE_URL as the asyncpg pool above), a session-pinned prepared
    # statement left behind by one pooled connection collides with the next
    # request that lands on the same underlying server connection -
    # DuplicatePreparedStatement on checkpointer.setup(). prepare_threshold=
    # None disables server-side prepared statements entirely, same fix as
    # asyncpg's statement_cache_size=0 above, just psycopg's equivalent knob.
    lg_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    lg_conn = await AsyncConnection.connect(
        lg_url, autocommit=True, prepare_threshold=None, row_factory=dict_row
    )
    checkpointer = AsyncPostgresSaver(conn=lg_conn)
    await checkpointer.setup()
    app.state.checkpointer = checkpointer
    log.info("[API] LangGraph Postgres checkpointer initialized")

    app.state.request_counts = {}

    yield

    # Shutdown
    await app.state.db_pool.close()
    await lg_conn.close()
    log.info("[API] Shutdown complete")


# ──────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────

app = FastAPI(
    title="Cloud Decoded API",
    description="Autonomous DevOps agents for mid-market engineering teams.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — tighten in production to FRONTEND_URL
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_URL", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Request metering
app.add_middleware(TokenMeterMiddleware)

# Per-workspace tier lookup — must run before rate limiter decorators fire
app.add_middleware(WorkspaceTierMiddleware)


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

app.include_router(agents.router,          prefix="/api/v1")
app.include_router(incidents.router,       prefix="/api/v1")
app.include_router(webhooks.router,        prefix="/api/v1")
app.include_router(stripe_billing.router,  prefix="/api/v1")
app.include_router(content.router,         prefix="/api/v1")
app.include_router(outreach.router,        prefix="/api/v1")
app.include_router(mcp_keys.router,        prefix="/api/v1")
app.include_router(gta_hub.router)
app.include_router(marketing.router,       prefix="/api/v1")
app.include_router(internal_agents.router, prefix="/api/v1")
app.include_router(internal_marketing.router, prefix="/api/v1")


# ──────────────────────────────────────────────
# Health + diagnostics
# ──────────────────────────────────────────────

@app.get("/health")
async def health(request: Request) -> dict:
    """Liveness probe — returns 200 if API is up."""
    return {"status": "ok", "service": "cloud-decoded-api"}


@app.get("/health/db")
async def health_db(request: Request) -> dict:
    """Readiness probe — checks DB connectivity."""
    try:
        async with request.app.state.db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok", "db": "connected"}
    except Exception as exc:
        log.error("[Health] DB check failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"status": "error", "db": str(exc)},
        )


@app.get("/")
async def root() -> dict:
    return {
        "product": "Cloud Decoded",
        "version": "1.0.0",
        "docs": "/docs",
        "company": "THD Agentic Systems LLC",
    }
