"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
Internal agent execution — owner/team-only. Completely separate from the
customer-facing POST /agents/{agent_id}/run + X-Workspace-Token path in
api/routes/agents.py: different auth (api.middleware.internal_auth,
Supabase session JWT + admin role), different table (internal_agent_runs,
not incidents/workspaces), different prefix. Do not share code paths with
that file.

POST /internal/agents/{agent_id}/run   — fire an agents/internal/* agent
GET  /internal/agents/runs/{run_id}    — poll a run's status/result

Most agents/internal/* classes take structured data (product metrics
snapshots, agent-run records, a completed research_agent output, etc.) as
method arguments rather than fetching their own data — this is intentional,
documented in several of those files' own docstrings as deferred to a later
integration session. Only agents that are genuinely fireable from a bare
JSON payload today get a real dispatch branch in _execute_internal_agent;
everything else in _KNOWN_INTERNAL_AGENTS is recognized (so it 501s with a
specific reason instead of 400ing as "unknown") but not yet wired. Extend
_WIRABLE_AGENTS + _execute_internal_agent's branches as each agent's real
data source gets built, not before.
"""

import json
import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.middleware.internal_auth import get_internal_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/agents", tags=["internal-agents"])


class InternalAgentRunRequest(BaseModel):
    payload: dict = {}


class InternalAgentRunResponse(BaseModel):
    run_id: str
    agent_id: str
    status: str
    message: str


# Every real agent in agents/internal/ as of this pass (excludes the
# _copy_rules helper module, which isn't an agent). No filesystem
# introspection here on purpose — avoids import-time side effects from
# scanning arbitrary modules. Keep in sync with
# ceo-dashboard/lib/api.ts's INTERNAL_AGENT_IDS.
_KNOWN_INTERNAL_AGENTS = {
    "accounting_agent", "chat_router_agent", "code_quality_agent",
    "content_agent", "email_sequence_agent", "finance_assistant_agent",
    "gap_detector_agent", "onboarding_agent", "portfolio_monitor",
    "release_notes_agent", "research_agent", "revenue_intelligence_agent",
    "sop_agent", "tax_agent", "visitor_capture_agent", "wealth_agent",
}

# Agents with a real dispatch branch below. See module docstring for why
# the rest aren't here yet.
_WIRABLE_AGENTS = {"research_agent"}

_NOT_WIRED_REASONS = {
    "portfolio_monitor": (
        "daily_digest() takes pre-built product-metrics snapshots as input — "
        "there's no Stripe/MRR query layer in this codebase yet to fetch them."
    ),
    "gap_detector_agent": (
        "weekly_scan() takes agent_runs/hitl_corrections/chat_queries/roster "
        "records supplied by the caller — no query layer exists yet to pull "
        "those from the DB."
    ),
    "content_agent": (
        "build_package() takes a completed research_agent output as input — "
        "chain it after a research_agent run once approved, it's not "
        "fireable standalone."
    ),
    "email_sequence_agent": (
        "draft_all_sequences() takes a completed research_agent output as "
        "input, same as content_agent — not fireable standalone."
    ),
    "sop_agent": (
        "run() takes an existing agent_run record as input, not something a "
        "bare fire-button payload has on hand."
    ),
}

_DEFAULT_NOT_WIRED_REASON = (
    "constructor/entry point takes structured data this API doesn't fetch "
    "yet — needs its own integration pass, deferred by design per this "
    "agent's own docstring."
)


@router.post("/{agent_id}/run", response_model=InternalAgentRunResponse)
async def run_internal_agent(
    agent_id: str,
    body: InternalAgentRunRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_internal_user),
) -> InternalAgentRunResponse:
    if agent_id not in _KNOWN_INTERNAL_AGENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown internal agent '{agent_id}'",
        )

    if agent_id not in _WIRABLE_AGENTS:
        reason = _NOT_WIRED_REASONS.get(agent_id, _DEFAULT_NOT_WIRED_REASON)
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"'{agent_id}' isn't wired for on-demand firing yet — {reason}",
        )

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO internal_agent_runs
                (agent_id, requested_by, requested_by_email, payload, status)
            VALUES ($1, $2, $3, $4::jsonb, 'executing')
            RETURNING id
            """,
            agent_id, user["id"], user["email"], json.dumps(body.payload),
        )
    run_id = row["id"]

    background_tasks.add_task(
        _execute_internal_agent, request.app, str(run_id), agent_id, body.payload
    )

    return InternalAgentRunResponse(
        run_id=str(run_id),
        agent_id=agent_id,
        status="executing",
        message="Agent started. Poll GET /internal/agents/runs/{run_id} for result.",
    )


async def _execute_internal_agent(app, run_id: str, agent_id: str, payload: dict) -> None:
    """Runs in the background. The run row already exists (created
    synchronously in run_internal_agent before this task is scheduled) —
    unlike api/routes/agents.py's agent_01-10 path, callers never poll
    against a placeholder "pending" id here."""
    db = app.state.db_pool
    try:
        if agent_id == "research_agent":
            from agents.internal.research_agent import ResearchAgent

            niche = payload.get("niche")
            if not niche or not str(niche).strip():
                raise ValueError("payload.niche is required to run research_agent")
            hypothesis = payload.get("hypothesis")
            result = ResearchAgent().run(niche=niche, hypothesis=hypothesis)
        else:
            # Unreachable: run_internal_agent already gates on _WIRABLE_AGENTS.
            raise ValueError(f"No execution branch wired for '{agent_id}'")

        async with db.acquire() as conn:
            await conn.execute(
                "UPDATE internal_agent_runs SET status = 'executed', result = $1::jsonb, updated_at = now() WHERE id = $2",
                json.dumps(result), UUID(run_id),
            )
    except Exception as exc:
        log.exception("[internal_agents] %s failed for run %s", agent_id, run_id)
        async with db.acquire() as conn:
            await conn.execute(
                "UPDATE internal_agent_runs SET status = 'failed', error = $1, updated_at = now() WHERE id = $2",
                str(exc)[:2000], UUID(run_id),
            )


@router.get("/runs/{run_id}")
async def get_internal_agent_run(
    run_id: str,
    request: Request,
    user: dict = Depends(get_internal_user),
) -> dict:
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, agent_id, status, result, error, created_at, updated_at "
            "FROM internal_agent_runs WHERE id = $1",
            UUID(run_id),
        )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )

    result_raw = row["result"]
    if isinstance(result_raw, str):
        result_raw = json.loads(result_raw)

    return {
        "run_id": str(row["id"]),
        "agent_id": row["agent_id"],
        "status": row["status"],
        "result": result_raw,
        "error": row["error"],
    }
