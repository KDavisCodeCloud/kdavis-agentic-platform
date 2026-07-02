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

import asyncpg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
    app.state.db_pool = await asyncpg.create_pool(
        asyncpg_url,
        min_size=2,
        max_size=10,
        command_timeout=60,
    )
    log.info("[API] Database pool created")

    # LangGraph Postgres checkpointer — persists agent workflow state
    # Uses psycopg (separate from asyncpg) — both connect to the same Postgres DB
    lg_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    checkpointer_cm = AsyncPostgresSaver.from_conn_string(lg_url)
    checkpointer = await checkpointer_cm.__aenter__()
    await checkpointer.setup()
    app.state.checkpointer = checkpointer
    log.info("[API] LangGraph Postgres checkpointer initialized")

    app.state.request_counts = {}

    yield

    # Shutdown
    await app.state.db_pool.close()
    await checkpointer_cm.__aexit__(None, None, None)
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
