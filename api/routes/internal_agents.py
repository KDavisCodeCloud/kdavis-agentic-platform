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

import asyncio
import dataclasses
import datetime
import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.middleware.internal_auth import get_internal_user

_REPO_ROOT = Path(__file__).resolve().parents[2]  # api/routes/ -> api -> repo root


def _json_safe(obj):
    """Recursively converts dataclasses/date/datetime into plain
    JSON-serializable values. Agent return types are frequently
    dataclasses (ReleaseNote, CodeQualityReport, ...) with date fields —
    json.dumps can't handle either on its own."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _json_safe(dataclasses.asdict(obj))
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _run_coro_sync(coro):
    """Bridges an async call into a sync callback contract (e.g.
    ChatRouterAgent's claude_fn) from inside code that's already running
    on an event loop (this module's background tasks are async). Runs the
    coroutine in a fresh thread with its own event loop rather than
    asyncio.run() directly, which would raise on "loop already running"."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()


def _llm_call_sync(prompt: str) -> str:
    """Sync single-prompt LLM callback for agents whose llm_call contract is
    Callable[[str], str] (content_agent, email_sequence_agent) — distinct
    from ChatRouterAgent's claude_fn(query, context) shape, so not shared
    with that closure. Same providers.router bridge as chat_router_agent's
    branch below."""
    import providers.router as llm_router

    completion = _run_coro_sync(llm_router.complete(prompt, task_type="content_draft"))
    return completion.text

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
#
# DATABASE_URL is now a real, live connection (microsaas-prod, pooler mode)
# — every agent below actually executes end-to-end against Postgres, not
# just against a mocked db_pool. Verified directly: GET / returns 200, pool
# connects, LangGraph checkpointer initializes.
_WIRABLE_AGENTS = {
    "research_agent",
    "chat_router_agent",
    "code_quality_agent",
    "release_notes_agent",
    "visitor_capture_agent",
    "onboarding_agent",
    "content_agent",
    "email_sequence_agent",
    "sop_agent",
}

_NOT_WIRED_REASONS = {
    "portfolio_monitor": (
        "daily_digest() takes pre-built ProductMetricsSnapshot objects as "
        "input. finance/integrations/stripe_revenue.py exists but "
        "STRIPE_API_KEY is unset in this environment, and there's no "
        "aggregation layer anywhere that turns raw Stripe charges + the "
        "products table into the snapshot shape this method actually needs "
        "(new_subscriptions, trial_to_paid_conversions, agent_run_count, "
        "etc. aren't derivable from stripe_revenue.py's RevenueEvent alone)."
    ),
    "gap_detector_agent": (
        "weekly_scan() needs four separate structured inputs (agent runs, "
        "HITL corrections, chat queries, agent roster). Only one has a "
        "matching live table shape at all — infra/supabase/migrations's "
        "product-scoped agent_runs table lines up with AgentRunRecord's "
        "fields — but that table belongs to the customer-facing commercial "
        "agent_01-10 path, not these internal business-OS runs; mapping "
        "internal_agent_runs rows onto AgentRunRecord would mean fabricating "
        "a product_id and confidence_score that table doesn't have. "
        "hitl_corrections/chat_queries/roster have no backing table at all."
    ),
    "revenue_intelligence_agent": (
        "scan() needs Lead/VisitorSession/Product/RevenueEvent lists. "
        "VisitorSession and the revenue-event shape line up with the real "
        "visitor_sessions/revenue_events tables reasonably well, but the "
        "Lead dataclass (signup_type, trial_expired, trial_end_date, "
        "last_login, converted_to_paid, cancelled, months_active, "
        "hit_usage_limit, company_size, role) does not match the live "
        "leads table at all (db/migrations/005_leads.sql only has "
        "product_id/email/name/source/stage/metadata) — wiring this would "
        "mean fabricating most of Lead's fields rather than reading them, "
        "so it stays unwired. This is a genuine schema mismatch bug, same "
        "category as the ceo-dashboard hitl_queue mismatch found earlier "
        "this session — worth its own fix, not papered over here."
    ),
    "accounting_agent": (
        "Constructible (InvoiceTracker/RevenueLedger are in-memory, no "
        "external deps), but every fire creates a fresh instance with empty "
        "state — no Supabase-backed persistence wires finance/accounting's "
        "in-memory trackers to the expenses/revenue_events/invoices tables "
        "CLAUDE.md's own finance-system spec calls for. Firing it would "
        "silently no-op (report zero everything) every single time, which "
        "isn't real functionality — it's an unwired placeholder wearing a "
        "constructible face."
    ),
    "finance_assistant_agent": (
        "Same root cause as accounting_agent — it wraps AccountingAgent/"
        "TaxAgent/InvoiceTracker/RevenueLedger, none of which persist "
        "across calls without a real DB-backed store that doesn't exist yet."
    ),
    "tax_agent": (
        "DeductionTracker/YearEndPackager are stateless in-memory classes "
        "with no persistence layer — same gap as accounting_agent, deferred "
        "for the same reason."
    ),
    "wealth_agent": (
        "CashFlowMonitor/InvestmentTracker are stateless in-memory classes "
        "with no persistence layer — same gap as accounting_agent, deferred "
        "for the same reason."
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

        elif agent_id in ("content_agent", "email_sequence_agent"):
            # Both chain off a completed research_agent run rather than
            # taking a raw research payload directly — research is
            # expensive (scraping + LLM synthesis) and HITL-gated, so
            # re-running it implicitly on every content/email fire would be
            # wrong. payload.research_run_id must point at an
            # internal_agent_runs row with agent_id='research_agent' and
            # status='executed'; its result is {"research": {...}, "hitl_card":
            # {...}} (ResearchAgent.run()'s own return shape) — unwrap
            # ["research"], not the row itself.
            research_run_id = payload.get("research_run_id")
            product_id = payload.get("product_id")
            if not research_run_id:
                raise ValueError(
                    "payload.research_run_id (a completed research_agent run id) "
                    f"is required to run {agent_id}"
                )
            if not product_id or not str(product_id).strip():
                raise ValueError(f"payload.product_id is required to run {agent_id}")

            async with db.acquire() as conn:
                research_row = await conn.fetchrow(
                    "SELECT status, result FROM internal_agent_runs "
                    "WHERE id = $1 AND agent_id = 'research_agent'",
                    UUID(str(research_run_id)),
                )
            if not research_row:
                raise ValueError(f"research_run_id '{research_run_id}' not found")
            if research_row["status"] != "executed":
                raise ValueError(
                    f"research_run_id '{research_run_id}' has status "
                    f"'{research_row['status']}', not 'executed' — {agent_id} "
                    "needs a completed research_agent run to chain from"
                )
            research_result = research_row["result"]
            if isinstance(research_result, str):
                research_result = json.loads(research_result)
            research = research_result.get("research")
            if not research:
                raise ValueError(
                    f"research_run_id '{research_run_id}''s result has no "
                    "'research' key — not a genuine research_agent output"
                )

            if agent_id == "content_agent":
                from agents.internal.content_agent import ContentAgent

                result = ContentAgent(llm_call=_llm_call_sync).build_package(
                    research=research, product_id=product_id
                )
            else:
                from agents.internal.email_sequence_agent import EmailSequenceAgent

                result = EmailSequenceAgent(llm_call=_llm_call_sync).draft_all_sequences(
                    research=research, product_id=product_id
                )

        elif agent_id == "sop_agent":
            from agents.internal.sop_agent import SOPAgent

            required = ["agent_name", "task_summary"]
            missing = [k for k in required if not payload.get(k)]
            if missing:
                raise ValueError(
                    f"payload missing required fields for sop_agent: {missing}"
                )
            # SOPAgent.run() takes a free-form agent_run dict (agent_name +
            # task_summary required, everything else optional with .get()
            # defaults per sop_agent.py itself) — genuinely fireable from a
            # bare payload, not tied to any DB table shape. The old "not
            # something a bare fire-button payload has on hand" reasoning
            # was overcautious; correcting it here rather than leaving it
            # unwired.
            file_path = SOPAgent().run(agent_run=payload)
            result = {"file_path": file_path}

        elif agent_id == "chat_router_agent":
            from agents.internal.chat_router_agent import ChatRouterAgent

            query = payload.get("query")
            if not query or not str(query).strip():
                raise ValueError("payload.query is required to run chat_router_agent")

            def _claude_fn(q: str, context) -> str:
                # providers.router.complete is async and this callback must
                # be sync (ChatRouterAgent's own contract) — bridge via
                # _run_coro_sync rather than importing anthropic/deepseek
                # directly, per CLAUDE.md rule 1.
                import providers.router as llm_router

                completion = _run_coro_sync(
                    llm_router.complete(q, task_type="chat_think_tank")
                )
                return completion.text

            handlers = {}  # research_agent/portfolio_monitor/content_agent/
            # gap_detector_agent aren't wired as chat handlers yet — routing
            # to them returns "handler_not_available" rather than erroring,
            # same deferred pattern as their own direct dispatch above.
            router_agent = ChatRouterAgent(handlers=handlers, claude_fn=_claude_fn)
            result = router_agent.handle(query)

        elif agent_id == "code_quality_agent":
            from agents.internal.code_quality_agent import CodeQualityAgent

            raw_paths = payload.get("paths")
            if not raw_paths:
                raise ValueError(
                    "payload.paths (list of repo-relative .py file paths) is "
                    "required to run code_quality_agent"
                )
            resolved: list[Path] = []
            for p in raw_paths:
                candidate = (_REPO_ROOT / p).resolve()
                if _REPO_ROOT not in candidate.parents:
                    raise ValueError(f"path '{p}' escapes the repo root — refusing")
                if not candidate.is_file():
                    raise ValueError(f"path '{p}' does not exist or is not a file")
                resolved.append(candidate)
            report = CodeQualityAgent().review(resolved)
            result = {
                "files_reviewed": report.files_reviewed,
                "issues": [issue.to_row() for issue in report.issues],
                "clean_files": report.clean_files,
            }

        elif agent_id == "release_notes_agent":
            from agents.internal.release_notes_agent import DeploySummary, ReleaseNotesAgent

            commit_count = int(payload.get("commit_count", 10))
            if commit_count < 1 or commit_count > 200:
                raise ValueError("payload.commit_count must be between 1 and 200")

            log_proc = subprocess.run(
                ["git", "log", f"-{commit_count}", "--pretty=format:%s", "--name-only"],
                cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
            )
            version_proc = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
            )
            commit_messages: list[str] = []
            changed_files: set[str] = set()
            for block in log_proc.stdout.strip().split("\n\n"):
                lines = [ln for ln in block.splitlines() if ln.strip()]
                if not lines:
                    continue
                commit_messages.append(lines[0])
                changed_files.update(lines[1:])

            summary = DeploySummary(
                version=version_proc.stdout.strip(),
                deployed_at=datetime.date.today(),
                changed_files=sorted(changed_files),
                commit_messages=commit_messages,
            )
            note = ReleaseNotesAgent().build(summary)
            result = note.to_row()

        elif agent_id == "visitor_capture_agent":
            from agents.internal.visitor_capture_agent import IncomingLead, VisitorCaptureAgent

            required = ["product_id", "email", "signup_type", "utm_source"]
            missing = [k for k in required if not payload.get(k)]
            if missing:
                raise ValueError(
                    f"payload missing required fields for visitor_capture_agent: {missing}"
                )
            lead = IncomingLead(
                product_id=payload["product_id"],
                email=payload["email"],
                signup_type=payload["signup_type"],
                utm_source=payload["utm_source"],
                name=payload.get("name"),
                company=payload.get("company"),
                role=payload.get("role"),
                pages_viewed=int(payload.get("pages_viewed", 0)),
            )
            # enrich_fn/tag_fn intentionally omitted (None) — no company-size
            # enrichment or Systeme.io tagging integration is wired here yet;
            # real, honest partial functionality (scoring + decision card),
            # not a fake enrichment result.
            result = VisitorCaptureAgent().process_incoming_lead(lead)

        elif agent_id == "onboarding_agent":
            from agents.internal.onboarding_agent import OnboardingAgent, TeamMemberInvite

            required = ["email", "name", "role"]
            missing = [k for k in required if not payload.get(k)]
            if missing:
                raise ValueError(
                    f"payload missing required fields for onboarding_agent: {missing}"
                )
            invite = TeamMemberInvite(
                email=payload["email"], name=payload["name"], role=payload["role"],
            )
            card = OnboardingAgent().prepare_invite(invite)
            result = {
                "email": card.email,
                "name": card.name,
                "role": card.role,
                "message": card.message,
                "note": (
                    "prepare_invite only — execute_invite is still genuinely "
                    "blocked, no personal-folder template exists in this repo "
                    "yet (see onboarding_agent.py's own FileNotFoundError)."
                ),
            }

        else:
            # Unreachable: run_internal_agent already gates on _WIRABLE_AGENTS.
            raise ValueError(f"No execution branch wired for '{agent_id}'")

        async with db.acquire() as conn:
            await conn.execute(
                "UPDATE internal_agent_runs SET status = 'executed', result = $1::jsonb, updated_at = now() WHERE id = $2",
                json.dumps(_json_safe(result)), UUID(run_id),
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
