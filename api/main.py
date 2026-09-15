"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Cloud Decoded — FastAPI application entry point.

Run locally:
    uvicorn api.main:app --reload --port 8000

Production:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 4
"""

# ruff: noqa: E402  -- sys.path/env setup must run before these imports

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
from core.db import register_jsonb_codec
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
from api.routes import internal_workspaces
from api.routes import workspaces
from api.routes import workspace_credentials
from api.routes import audit
from api.routes import finops_agent
from api.routes import compliance_agent
from api.routes import github_app_admin
from core.checkpointer_lock import LockedAsyncPostgresSaver
from core.error_tracking import init_sentry
from core.json_logging import configure_logging
from core.pool_timeout import TimeoutBoundPool

log = logging.getLogger(__name__)

# LOG_FORMAT=json (default) emits one structured JSON object per log line --
# queryable by field (workspace_id, agent_id, incident_id, ...) in Railway's
# log viewer instead of grepping message text. LOG_FORMAT=text keeps the
# original human-readable format for local dev.
configure_logging(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    fmt=os.environ.get("LOG_FORMAT", "json"),
)

# Must run before `FastAPI(...)` is instantiated below -- the FastAPI/
# Starlette integrations instrument at init time. No-ops if SENTRY_DSN
# isn't set (see core/error_tracking.py).
init_sentry()


# ──────────────────────────────────────────────
# Application lifespan — DB pool + LangGraph checkpointer
# ──────────────────────────────────────────────

def _write_kubeconfig_from_env() -> None:
    """
    agents/agent_08_drift_detection/tools.py's fetch_k8s_resource/
    apply_k8s_manifest run `kubectl` as a subprocess -- kubectl reads its
    config from the KUBECONFIG env var (a file path), not from env content
    directly. Railway can't mount an arbitrary file into the container, so
    this writes KUBECONFIG_YAML's raw content (set as a Railway env var,
    holding a real cluster's kubeconfig -- e.g. a ServiceAccount token, not
    a short-lived cloud-CLI-exec-plugin token) to a local file once at
    startup and points KUBECONFIG at it. No-op if KUBECONFIG_YAML isn't set
    (kubectl calls then fail with a clear "no configuration" error, same as
    DriftTools' own allow_kubectl=False graceful-degradation path).
    """
    kubeconfig_yaml = os.environ.get("KUBECONFIG_YAML", "")
    if not kubeconfig_yaml:
        return
    path = "/tmp/kubeconfig"
    with open(path, "w") as f:
        f.write(kubeconfig_yaml)
    os.chmod(path, 0o600)
    os.environ["KUBECONFIG"] = path
    log.info("[API] KUBECONFIG written from KUBECONFIG_YAML env var")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Set up shared resources on startup; tear down on shutdown."""
    _write_kubeconfig_from_env()

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
    # max_size=20 (Phase 8, scale-readiness build -- raised from 10). Each
    # of the 4 uvicorn worker processes (see Procfile/railway.json's
    # --workers 4) gets its OWN pool via its own lifespan() run, so total
    # platform capacity against Supabase's transaction-mode pooler becomes
    # 4 x 20 = 80 connections, up from the single-process 10 this
    # platform ran with until now. Worth confirming against Supabase's
    # own pooler connection ceiling for this project if pool-exhaustion
    # 503s (Phase 7's TimeoutBoundPool + _pool_timeout_handler) show up
    # under real load -- that's the first place to look.
    _raw_db_pool = await asyncpg.create_pool(
        asyncpg_url,
        min_size=2,
        max_size=20,
        command_timeout=60,
        statement_cache_size=0,
        init=register_jsonb_codec,
    )
    # asyncpg has no pool-wide default acquire() timeout (only a per-call
    # one, and every call site in this codebase omits it) -- wrapped so
    # pool exhaustion surfaces as a clear 503 (see _pool_timeout_handler
    # above) after 5s instead of blocking indefinitely. See
    # core/pool_timeout.py's own docstring.
    app.state.db_pool = TimeoutBoundPool(_raw_db_pool)
    log.info("[API] Database pool created")

    # Applies db/migrations/*.sql before anything else touches the DB --
    # built 2026-09-15 after migrations 024-028 were deployed for an
    # entire session without ever actually running against production
    # (no migration runner existed anywhere in the deploy pipeline; real
    # customer signups failed with a 500 for as long as nobody noticed).
    # Fails closed by design: an exception here aborts startup rather than
    # serving traffic against a schema the application code doesn't match.
    # See db/migrate.py's own docstring and GAPS.md #15.
    from db.migrate import run_pending_migrations, log_security_posture
    await run_pending_migrations(app.state.db_pool)

    # Read-only check of whether DATABASE_URL's role actually enforces
    # the RLS policies migration 031 adds, or silently bypasses them
    # (superuser / unforced table owner) -- see db/migrate.py's own
    # docstring and GAPS.md #20.
    await log_security_posture(app.state.db_pool)

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
    _inner_checkpointer = AsyncPostgresSaver(conn=lg_conn)
    await _inner_checkpointer.setup()
    # Wrapped in a lock (core/checkpointer_lock.py) rather than used
    # directly: lg_conn is a single, non-pooled connection shared by
    # every agent workflow on this process -- without serializing access
    # to it, two agent runs whose checkpoint writes land in the same
    # moment risk protocol-level interleaving, not just slowness. See
    # that module's docstring for why this is a lock and not a
    # connection pool.
    app.state.checkpointer = LockedAsyncPostgresSaver(_inner_checkpointer)
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


@app.exception_handler(TimeoutError)
async def _pool_timeout_handler(request: Request, exc: TimeoutError) -> JSONResponse:
    """core/pool_timeout.py gives every db_pool.acquire() a default
    timeout (5s) instead of waiting indefinitely for pool exhaustion --
    this turns the resulting asyncio.TimeoutError into a clear 503
    instead of an unhandled 500."""
    log.warning("[API] DB pool acquire timed out — %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=503,
        content={"detail": "Service temporarily unavailable — database connection pool exhausted. Retry shortly."},
    )

# CORS — ALLOWED_ORIGINS is a comma-separated list; multiple real frontends
# (ceo-dashboard, team-dashboard, Cloud Decoded's customer site) all need
# to call this one backend. FRONTEND_URL alone (single origin) was too
# narrow the moment a second dashboard needed access -- found 2026-07-24
# when ceo-dashboard's LinkedIn batch panel got a CORS-blocked "Failed to
# fetch" because FRONTEND_URL was set to theclouddecoded.com only.
_allowed_origins = [
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS",
        os.environ.get("FRONTEND_URL", "http://localhost:3000"),
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
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
app.include_router(internal_workspaces.router, prefix="/api/v1")
app.include_router(workspaces.router,      prefix="/api/v1")
app.include_router(workspace_credentials.router, prefix="/api/v1")
app.include_router(audit.router,           prefix="/api/v1")
app.include_router(finops_agent.router,    prefix="/api/v1")
app.include_router(compliance_agent.router, prefix="/api/v1")
app.include_router(github_app_admin.router, prefix="/api/v1")


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
