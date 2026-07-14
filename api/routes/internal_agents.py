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
import os
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
    "gap_detector_agent",
    "accounting_agent",
    "tax_agent",
    "wealth_agent",
    "finance_assistant_agent",
}

_NOT_WIRED_REASONS = {
    "portfolio_monitor": (
        "daily_digest() takes pre-built ProductMetricsSnapshot objects as "
        "input. The Stripe key gap is fixed (finance/integrations/"
        "stripe_revenue.py was reading a STRIPE_API_KEY env var that never "
        "existed — the real key is STRIPE_SECRET_KEY, same one "
        "stripe_billing.py already uses; corrected) and a live Stripe "
        "connection confirmed working, but Stripe currently has zero "
        "subscriptions/customers (pre-revenue, confirmed live) and "
        "config/products.yaml has no launched_at field and no populated "
        "stripe: product/price ID block (infra/stripe/setup.py was never "
        "run) — there's no real mapping from a Stripe product to an "
        "internal product_id yet, and no launch-date source to compute "
        "days-live for the kill-switch check. Building that mapping now "
        "would mean guessing product-name matches, not reading real data."
    ),
    "revenue_intelligence_agent": (
        "scan() needs Lead/VisitorSession/Product/RevenueEvent lists PLUS a "
        "products catalog dict and an aeo_cited signal — deeper than a "
        "simple schema mismatch. Re-checked directly against the live "
        "database (not migration files): leads, visitor_sessions, and "
        "revenue_events don't exist at all yet (db/migrations/005_leads.sql "
        "was never run), and nothing anywhere in this codebase currently "
        "writes trial-expiry, login-activity, or conversion-status events "
        "for any lead regardless of which schema is picked — the gap isn't "
        "which columns a table has, it's that the upstream lifecycle "
        "tracking this agent needs doesn't exist yet. Also: three different, "
        "mutually-inconsistent 'leads' schemas exist in this repo alone "
        "(CLAUDE.md's own spec, db/migrations/005_leads.sql, and this "
        "agent's Lead dataclass) — worth reconciling before building "
        "anything on top of any of them, not something to resolve as a "
        "side effect of wiring one agent's dispatch branch."
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

    # Captured for gap_detector_agent's AgentRunRecord signal (migration 009)
    # whenever a caller's payload names a product — most don't (these are
    # mostly product-agnostic internal tools), so NULL/'internal' is the
    # honest default, not every row needing one.
    product_id = body.payload.get("product_id")

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO internal_agent_runs
                (agent_id, requested_by, requested_by_email, payload, status, product_id)
            VALUES ($1, $2, $3, $4::jsonb, 'executing', $5)
            RETURNING id
            """,
            agent_id, user["id"], user["email"], json.dumps(body.payload), product_id,
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

        elif agent_id == "gap_detector_agent":
            from agents.internal.gap_detector_agent import (
                AgentRosterEntry,
                AgentRunRecord,
                ChatQuery,
                GapDetectorAgent,
                HITLCorrection,
            )

            days_back = int(payload.get("days_back", 30))
            if days_back < 1 or days_back > 365:
                raise ValueError("payload.days_back must be between 1 and 365")

            # AgentRunRecord — real internal_agent_runs rows (migration 009
            # added product_id/confidence_score to the table specifically
            # for this). status vocab differs from AgentRunRecord's own
            # ("completed"/"failed"/"paused"/"running" vs this table's
            # "executing"/"executed"/"failed") — mapped, not passed through
            # raw, so detect_low_confidence_pattern's status=="failed" check
            # actually lines up.
            _STATUS_MAP = {"executed": "completed", "executing": "running", "failed": "failed"}
            async with db.acquire() as conn:
                run_rows = await conn.fetch(
                    "SELECT agent_id, product_id, status, confidence_score, created_at "
                    "FROM internal_agent_runs WHERE created_at > now() - ($1 || ' days')::interval",
                    str(days_back),
                )
                correction_rows = await conn.fetch(
                    "SELECT agent_name, original_option, corrected_option, occurred_at "
                    "FROM hitl_corrections WHERE occurred_at > now() - ($1 || ' days')::interval",
                    str(days_back),
                )
                query_rows = await conn.fetch(
                    "SELECT query_text, routed_to_claude, occurred_at "
                    "FROM chat_queries WHERE occurred_at > now() - ($1 || ' days')::interval",
                    str(days_back),
                )

            runs = [
                AgentRunRecord(
                    agent_name=r["agent_id"],
                    product_id=r["product_id"] or "internal",
                    status=_STATUS_MAP.get(r["status"], r["status"]),
                    confidence_score=float(r["confidence_score"]) if r["confidence_score"] is not None else None,
                    started_at=r["created_at"].date(),
                )
                for r in run_rows
            ]
            corrections = [
                HITLCorrection(
                    agent_name=r["agent_name"], original_option=r["original_option"],
                    corrected_option=r["corrected_option"], occurred_at=r["occurred_at"].date(),
                )
                for r in correction_rows
            ]
            chat_queries = [
                ChatQuery(text=r["query_text"], routed_to_claude=r["routed_to_claude"], occurred_at=r["occurred_at"].date())
                for r in query_rows
            ]
            # AgentRosterEntry — deliberately NOT a DB table (see migration
            # 009's own comment): derived live from this module's own
            # _KNOWN_INTERNAL_AGENTS/_WIRABLE_AGENTS, which can never drift
            # out of sync with what's actually wired the way a separate
            # roster table could.
            roster = [
                AgentRosterEntry(
                    agent_name=name,
                    status="active" if name in _WIRABLE_AGENTS else "recommended",
                )
                for name in _KNOWN_INTERNAL_AGENTS
            ]

            recommendations = GapDetectorAgent().weekly_scan(
                runs=runs, corrections=corrections, chat_queries=chat_queries, roster=roster
            )
            result = {
                "days_back": days_back,
                "runs_analyzed": len(runs),
                "corrections_analyzed": len(corrections),
                "chat_queries_analyzed": len(chat_queries),
                "recommendations": [rec.to_row() for rec in recommendations],
            }

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

            # Real writer for gap_detector_agent's ChatQuery signal (see
            # migration 009) — every chat turn logged here, not just the
            # ones that fell through, so detect_claude_fallback_gap can
            # eventually be extended to consider handled-vs-fallback ratio,
            # not just raw fallback count.
            async with db.acquire() as conn:
                await conn.execute(
                    "INSERT INTO chat_queries (query_text, routed_to_claude) VALUES ($1, $2)",
                    query, result.get("routed_to") == "claude_think_tank",
                )

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

        elif agent_id == "accounting_agent":
            import datetime as _dt

            from finance.accounting.document_organizer import DocumentOrganizer
            from finance.accounting.invoice_tracker import InvoiceTracker
            from finance.accounting.receipt_processor import ReceiptProcessor, ReceiptSource
            from finance.accounting.revenue_ledger import RevenueLedger
            from finance.integrations.document_store import LocalFileSystemStore
            from agents.internal.accounting_agent import AccountingAgent

            action = payload.get("action")
            store_path = os.environ.get("FINANCE_DOCUMENT_STORE_PATH")
            if not store_path:
                raise ValueError("FINANCE_DOCUMENT_STORE_PATH not set — cannot file receipt documents")
            accounting = AccountingAgent(
                receipt_processor=ReceiptProcessor(),
                invoice_tracker=InvoiceTracker(),
                revenue_ledger=RevenueLedger(),
                document_organizer=DocumentOrganizer(LocalFileSystemStore(store_path)),
            )

            if action == "process_receipt":
                text = payload.get("text")
                if not text or not str(text).strip():
                    raise ValueError("payload.text is required for action=process_receipt")
                card = accounting.process_receipt(text, source=ReceiptSource.DASHBOARD_UPLOAD)
                rec = card["expense_record"]
                # accounting_agent holds this in an in-memory list that resets
                # every fire (constructed fresh per call, matching every other
                # agents/internal/* module's "no DB connection of its own"
                # design) — this dispatch layer owns turning that into real
                # persistence, same division of responsibility as
                # research_agent's result being persisted by the caller, not
                # the agent itself.
                async with db.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO expenses (product_id, amount, vendor, description, expense_date, "
                        "irs_category, receipt_url, receipt_ocr_text, tax_year, deductible, approved_by_cpa) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                        payload.get("product_id"), rec.get("amount"), rec["vendor"], rec.get("description"),
                        _dt.date.fromisoformat(rec["date"]) if rec.get("date") else None,
                        rec["irs_category"], rec.get("receipt_url"), rec.get("receipt_ocr_text"),
                        rec.get("tax_year"), rec.get("deductible", True), rec.get("approved_by_cpa", False),
                    )
                result = card

            elif action == "monthly_summary":
                year = payload.get("year")
                month = payload.get("month")
                if not year or not month:
                    raise ValueError("payload.year and payload.month are required for action=monthly_summary")
                # Hydrate the fresh AccountingAgent's in-memory _expenses from
                # the real table before summarizing — direct attribute set,
                # not a public API on this class (it wasn't designed to load
                # external state); documented here rather than changing
                # accounting_agent.py's own "no DB connection" contract.
                async with db.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT amount, vendor, description, expense_date, irs_category, "
                        "receipt_url, tax_year, deductible, approved_by_cpa FROM expenses WHERE tax_year = $1",
                        int(year),
                    )
                accounting._expenses = [
                    {
                        "amount": float(r["amount"]) if r["amount"] is not None else None,
                        "vendor": r["vendor"], "description": r["description"],
                        "date": r["expense_date"].isoformat() if r["expense_date"] else None,
                        "irs_category": r["irs_category"], "receipt_url": r["receipt_url"],
                        "tax_year": r["tax_year"], "deductible": r["deductible"], "approved_by_cpa": r["approved_by_cpa"],
                    }
                    for r in rows
                ]
                result = accounting.monthly_summary(int(year), int(month))

            else:
                raise ValueError(
                    "payload.action must be 'process_receipt' or 'monthly_summary' — "
                    "track_invoice/overdue_invoice_cards/sync_stripe_revenue/"
                    "export_monthly_stripe_csv need invoices/revenue_events tables "
                    "that don't exist yet, not wired in this pass"
                )

        elif agent_id == "tax_agent":
            import datetime as _dt

            from agents.internal.tax_agent import TaxAgent

            action = payload.get("action")
            tax = TaxAgent()

            if action == "track_deductions":
                tax_year = payload.get("tax_year")
                if not tax_year:
                    raise ValueError("payload.tax_year is required for action=track_deductions")
                # Real persisted expenses, not fabricated — same table
                # accounting_agent's monthly_summary reads.
                async with db.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT amount, vendor, description, expense_date, irs_category, tax_year "
                        "FROM expenses WHERE tax_year = $1", int(tax_year),
                    )
                expenses = [
                    {
                        "amount": float(r["amount"]) if r["amount"] is not None else None,
                        "vendor": r["vendor"], "description": r["description"],
                        "date": r["expense_date"].isoformat() if r["expense_date"] else None,
                        "irs_category": r["irs_category"], "tax_year": r["tax_year"],
                    }
                    for r in rows
                ]
                result = tax.track_deductions(
                    tax_year=int(tax_year),
                    expenses=expenses,
                    has_dedicated_workspace=bool(payload.get("has_dedicated_workspace", False)),
                    office_sqft=payload.get("office_sqft"),
                    business_miles=float(payload.get("business_miles", 0.0)),
                    health_insurance_premiums=float(payload.get("health_insurance_premiums", 0.0)),
                    retirement_contributions=float(payload.get("retirement_contributions", 0.0)),
                    net_se_income=payload.get("net_se_income"),
                    home_internet_monthly_bill=float(payload.get("home_internet_monthly_bill", 0.0)),
                    home_internet_business_use_percent=float(payload.get("home_internet_business_use_percent", 0.0)),
                )

            elif action == "quarterly_estimate_card":
                required = ["tax_year", "quarter", "ytd_net_income"]
                missing = [k for k in required if payload.get(k) is None]
                if missing:
                    raise ValueError(f"payload missing required fields for quarterly_estimate_card: {missing}")
                result = tax.quarterly_estimate_card(
                    tax_year=int(payload["tax_year"]), quarter=int(payload["quarter"]),
                    ytd_net_income=float(payload["ytd_net_income"]),
                    prior_year_tax=payload.get("prior_year_tax"), prior_year_agi=payload.get("prior_year_agi"),
                )

            else:
                raise ValueError(
                    "payload.action must be 'track_deductions' or 'quarterly_estimate_card' — "
                    "year_end_package needs a populated RevenueLedger/InvoiceTracker/quarterly_estimates "
                    "history that doesn't persist across fires yet, not wired in this pass"
                )

        elif agent_id == "wealth_agent":
            from agents.internal.wealth_agent import WealthAgent
            from finance.wealth.salary_advisor import EntityType

            action = payload.get("action")
            wealth = WealthAgent()

            if action == "monthly_cash_flow":
                required = ["year", "month", "revenue", "expenses", "annual_estimated_tax"]
                missing = [k for k in required if payload.get(k) is None]
                if missing:
                    raise ValueError(f"payload missing required fields for monthly_cash_flow: {missing}")
                result = wealth.monthly_cash_flow(
                    year=int(payload["year"]), month=int(payload["month"]),
                    revenue=float(payload["revenue"]), expenses=float(payload["expenses"]),
                    annual_estimated_tax=float(payload["annual_estimated_tax"]),
                )

            elif action == "surplus_opportunity_card":
                required = ["year", "month", "revenue", "expenses", "annual_estimated_tax"]
                missing = [k for k in required if payload.get(k) is None]
                if missing:
                    raise ValueError(f"payload missing required fields for surplus_opportunity_card: {missing}")
                card = wealth.surplus_opportunity_card(
                    year=int(payload["year"]), month=int(payload["month"]),
                    revenue=float(payload["revenue"]), expenses=float(payload["expenses"]),
                    annual_estimated_tax=float(payload["annual_estimated_tax"]),
                    emergency_fund_current=payload.get("emergency_fund_current"),
                    emergency_fund_avg_monthly_expenses=payload.get("emergency_fund_avg_monthly_expenses"),
                )
                result = card if card is not None else {"card": None, "message": "No surplus opportunity this period."}

            elif action == "salary_recommendation":
                required = ["entity_type", "business_net_income"]
                missing = [k for k in required if payload.get(k) is None]
                if missing:
                    raise ValueError(f"payload missing required fields for salary_recommendation: {missing}")
                try:
                    entity_type = EntityType(payload["entity_type"])
                except ValueError:
                    raise ValueError(
                        f"payload.entity_type must be one of {[e.value for e in EntityType]}"
                    )
                result = wealth.salary_recommendation(
                    entity_type=entity_type, business_net_income=float(payload["business_net_income"]),
                    prior_salary=payload.get("prior_salary"),
                )

            else:
                raise ValueError(
                    "payload.action must be 'monthly_cash_flow', 'surplus_opportunity_card', or "
                    "'salary_recommendation' — record_allocation/wealth_building_ratio need "
                    "investment_allocations persistence that doesn't exist yet, tax_writeoff_surface "
                    "needs tax_agent's deduction flags from the same fire (state doesn't cross calls), "
                    "none wired in this pass"
                )

        elif agent_id == "finance_assistant_agent":
            from finance.wealth.cash_flow_monitor import CashFlowMonitor

            action = payload.get("action")
            if action != "tax_reserve_status":
                raise ValueError(
                    "payload.action must be 'tax_reserve_status' — every other method on this agent "
                    "reads accounting_agent/tax_agent/invoice_tracker/revenue_ledger state that resets "
                    "every fire (fresh instances, no cross-call persistence for those), so answers would "
                    "always be empty/wrong; this is the one method that's pure math on payload inputs "
                    "with no dependency on that state, not wired further in this pass"
                )
            required = ["year", "month", "revenue", "expenses", "annual_estimated_tax"]
            missing = [k for k in required if payload.get(k) is None]
            if missing:
                raise ValueError(f"payload missing required fields for tax_reserve_status: {missing}")
            summary = CashFlowMonitor().monthly_summary(
                int(payload["year"]), int(payload["month"]),
                float(payload["revenue"]), float(payload["expenses"]), float(payload["annual_estimated_tax"]),
            )
            from finance import disclaim as _disclaim
            result = _disclaim({
                "answer": f"Recommended tax reserve for {payload['year']}-{int(payload['month']):02d}: ${summary.recommended_tax_reserve:,.2f}",
                "source": "cash_flow_monitor",
                "available_surplus": summary.available_surplus,
            })

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
