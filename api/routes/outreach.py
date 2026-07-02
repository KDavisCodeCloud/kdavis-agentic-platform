"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
Outreach pipeline routes — Phase 3.

POST /outreach/leads                    — create lead, run qualify→assess→propose pipeline
GET  /outreach/leads                    — list leads with ICP scores and pacing context
GET  /outreach/leads/{id}               — full lead detail
POST /outreach/leads/{id}/mark-sent     — operator marks they manually sent connection request
POST /outreach/leads/{id}/status        — update acceptance status
GET  /outreach/pacing                   — current daily/weekly counts + warnings

COMPLIANCE BOUNDARY — this system is decision support only:
  - No connection requests are sent on the user's behalf
  - No LinkedIn credentials or sessions are stored for this flow
  - No DM automation, auto-follow, auto-engagement, or profile scraping
  - The workflow ends at copy-paste + manual LinkedIn click in the user's own browser
  - The LinkedIn OAuth token stored for content publishing is NOT used here

If any future change would require sending a connection request via API or
simulating a browser session: STOP and flag it. Do not proceed.
"""

import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel

from api.middleware.auth import get_workspace
from core.compliance import WorkspaceComplianceGuard, SubscriptionError
from core.security import shield
from db.outreach_models import (
    OutreachLeadCreate,
    OutreachLeadStatusUpdate,
    PacingStatus,
    LEAD_NEW, LEAD_QUALIFYING, LEAD_QUALIFIED, LEAD_DISQUALIFIED,
    LEAD_READY, LEAD_SENT, LEAD_ACCEPTED, LEAD_DECLINED, LEAD_NO_RESPONSE,
    DAILY_WARN, DAILY_LIMIT, WEEKLY_WARN, WEEKLY_LIMIT, ACCEPTANCE_RATE_FLOOR,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/outreach", tags=["outreach"])

_ROOT = Path(__file__).parent.parent.parent
_SALES_AGENTS = _ROOT / "agents" / "sales"
sys.path.insert(0, str(_ROOT / ".llm"))


def _load_sales_agent(name: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        name, _SALES_AGENTS / name / "agent.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Connection note generator ─────────────────────────────────────────────────

def _draft_connection_note(qualify_output: dict, lead_name: str, company: str) -> str:
    """
    Draft a LinkedIn connection note (≤300 chars) from qualification data.
    Uses the LLM router directly — not a separate agent file.
    """
    from router import complete

    talk_track = qualify_output.get("talk_track", "")
    icp_matches = qualify_output.get("icp_matches", [])
    tier = qualify_output.get("tier_recommendation", "growth")

    pain_hint = icp_matches[0] if icp_matches else talk_track[:80] if talk_track else "DevOps challenges"

    prompt = f"""Draft a LinkedIn connection request note for a sales outreach.

Target: {lead_name} at {company}
Their situation: {pain_hint}
Tone: Direct, practitioner-first, no fluff. Written by Kelvin Davis (USAF veteran, Fortune 500 DevOps background).
Rules:
- Under 280 characters (hard limit — leave room for punctuation)
- Do NOT say "I noticed" or "I came across your profile" — too generic
- Reference their specific situation in one brief clause
- End with a low-friction reason to connect — NOT a pitch or meeting request
- No em dashes. No buzzwords.

Return ONLY the note text, nothing else. No quotes, no explanation."""

    try:
        note = complete(
            task_type="connection_note",
            messages=[{"role": "user", "content": prompt}],
            system_prompt="You write concise, credible LinkedIn connection notes for a DevOps SaaS founder.",
        ).strip().strip('"').strip("'")
        return note[:299]  # hard cap at 299 to stay under LinkedIn's 300 limit
    except Exception as exc:
        log.warning("[Outreach] Connection note generation failed: %s", exc)
        # Safe fallback
        first_name = lead_name.split()[0] if lead_name else "there"
        return f"Hi {first_name}, working on autonomous DevOps agents for teams dealing with {pain_hint[:80].lower()}. Thought it made sense to connect."[:299]


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _create_lead(db_pool, workspace_id: str, body: OutreachLeadCreate) -> str:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO outreach_leads
              (workspace_id, lead_name, company, role, team_size, cloud_provider,
               pain_points, how_they_found_us, linkedin_url, additional_context, status)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            RETURNING id
            """,
            UUID(workspace_id), body.lead_name, body.company, body.role,
            body.team_size, body.cloud_provider, body.pain_points,
            body.how_they_found_us, body.linkedin_url, body.additional_context,
            LEAD_QUALIFYING,
        )
    return str(row["id"])


async def _update_lead(db_pool, lead_id: str, **fields) -> None:
    if not fields:
        return
    sets, params = [], []
    i = 1
    for k, v in fields.items():
        sets.append(f"{k} = ${i}")
        params.append(json.dumps(v) if isinstance(v, dict) else v)
        i += 1
    sets.append("updated_at = NOW()")
    params.append(UUID(lead_id))
    sql = f"UPDATE outreach_leads SET {', '.join(sets)} WHERE id = ${i}"
    async with db_pool.acquire() as conn:
        await conn.execute(sql, *params)


async def _get_lead(db_pool, lead_id: str, workspace_id: str) -> dict:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM outreach_leads WHERE id = $1 AND workspace_id = $2",
            UUID(lead_id), UUID(workspace_id),
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
    d = dict(row)
    for f in ("qualify_output", "assessment_output", "proposal_output"):
        if d.get(f) and isinstance(d[f], str):
            d[f] = json.loads(d[f])
    return d


# ── Pacing helper ─────────────────────────────────────────────────────────────

async def _compute_pacing(db_pool, workspace_id: str) -> PacingStatus:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start  = today_start - timedelta(days=now.weekday())

    async with db_pool.acquire() as conn:
        daily_sent  = await conn.fetchval(
            "SELECT COUNT(*) FROM outreach_leads WHERE workspace_id=$1 AND sent_at >= $2",
            UUID(workspace_id), today_start,
        ) or 0
        weekly_sent = await conn.fetchval(
            "SELECT COUNT(*) FROM outreach_leads WHERE workspace_id=$1 AND sent_at >= $2",
            UUID(workspace_id), week_start,
        ) or 0
        total_sent  = await conn.fetchval(
            "SELECT COUNT(*) FROM outreach_leads WHERE workspace_id=$1 AND sent_at IS NOT NULL",
            UUID(workspace_id),
        ) or 0
        total_accepted = await conn.fetchval(
            "SELECT COUNT(*) FROM outreach_leads WHERE workspace_id=$1 AND status=$2",
            UUID(workspace_id), LEAD_ACCEPTED,
        ) or 0
        total_declined = await conn.fetchval(
            "SELECT COUNT(*) FROM outreach_leads WHERE workspace_id=$1 AND status=$2",
            UUID(workspace_id), LEAD_DECLINED,
        ) or 0
        total_no_resp  = await conn.fetchval(
            "SELECT COUNT(*) FROM outreach_leads WHERE workspace_id=$1 AND status=$2",
            UUID(workspace_id), LEAD_NO_RESPONSE,
        ) or 0

    responded = total_accepted + total_declined + total_no_resp
    acceptance_rate = (total_accepted / responded) if responded >= 5 else None

    daily_pct  = min(daily_sent / DAILY_LIMIT, 1.0)
    weekly_pct = min(weekly_sent / WEEKLY_LIMIT, 1.0)

    daily_warning   = daily_sent >= DAILY_WARN
    daily_at_limit  = daily_sent >= DAILY_LIMIT
    weekly_warning  = weekly_sent >= WEEKLY_WARN
    weekly_at_limit = weekly_sent >= WEEKLY_LIMIT
    rate_warning    = acceptance_rate is not None and acceptance_rate < ACCEPTANCE_RATE_FLOOR

    # Build message
    if daily_at_limit:
        message = f"Daily limit reached ({daily_sent}/{DAILY_LIMIT}). Stop sending today — resume tomorrow."
    elif weekly_at_limit:
        message = f"Weekly limit reached ({weekly_sent}/{WEEKLY_LIMIT}). Resume next Monday."
    elif rate_warning:
        pct = round(acceptance_rate * 100)
        message = f"Acceptance rate is {pct}% — below the 20% floor. Review your targeting and note quality before sending more."
    elif daily_warning:
        remaining = DAILY_LIMIT - daily_sent
        message = f"Approaching daily limit — {remaining} sends left today before threshold."
    elif weekly_warning:
        remaining = WEEKLY_LIMIT - weekly_sent
        message = f"Approaching weekly limit — {remaining} sends left this week."
    else:
        message = f"Pacing is healthy. {daily_sent} sent today, {weekly_sent} this week."

    return PacingStatus(
        daily_sent=daily_sent,
        daily_warn=DAILY_WARN,
        daily_limit=DAILY_LIMIT,
        daily_pct=daily_pct,
        daily_warning=daily_warning,
        daily_at_limit=daily_at_limit,
        weekly_sent=weekly_sent,
        weekly_warn=WEEKLY_WARN,
        weekly_limit=WEEKLY_LIMIT,
        weekly_pct=weekly_pct,
        weekly_warning=weekly_warning,
        weekly_at_limit=weekly_at_limit,
        total_sent=total_sent,
        total_accepted=total_accepted,
        total_declined=total_declined,
        total_no_response=total_no_resp,
        acceptance_rate=acceptance_rate,
        acceptance_rate_warning=rate_warning,
        message=message,
    )


# ── Pipeline background task ──────────────────────────────────────────────────

async def _run_lead_pipeline(app, lead_id: str, workspace_id: str,
                              lead_name: str, company: str, role: str,
                              team_size: str, cloud_provider: str,
                              pain_points: str, how_they_found_us: str,
                              additional_context: str) -> None:
    """
    Runs qualify → assess → propose → draft connection note in background.
    Updates outreach_leads row progressively; sets status to qualified/disqualified.
    """
    db = app.state.db_pool

    try:
        safe_pain = shield.sanitize(pain_points, context="lead_qualify").sanitized_text
        safe_ctx  = shield.sanitize(additional_context, context="lead_qualify").sanitized_text

        # ── Qualify ──────────────────────────────────────────────────────────
        qualify_agent = _load_sales_agent("qualify-agent")
        qualify_output = qualify_agent.run(
            lead_name=lead_name,
            company=company,
            role=role,
            team_size=team_size,
            cloud_provider=cloud_provider,
            pain_points=safe_pain,
            how_they_found_us=how_they_found_us,
            additional_context=safe_ctx,
        )
        await _update_lead(db, lead_id, qualify_output=qualify_output)
        log.info("[Outreach] Lead %s — qualify complete (score=%s)", lead_id[:8], qualify_output.get("fit_score"))

        # Disqualify early if poor fit
        if qualify_output.get("recommended_action") == "reject" or qualify_output.get("fit_score", 0) <= 3:
            await _update_lead(db, lead_id, status=LEAD_DISQUALIFIED)
            log.info("[Outreach] Lead %s disqualified", lead_id[:8])
            return

        # ── Assessment ───────────────────────────────────────────────────────
        assess_agent = _load_sales_agent("assessment-agent")
        assessment_output = assess_agent.run(
            company=company,
            cloud_provider=cloud_provider,
            tech_stack={"described": cloud_provider},
            team_size=int("".join(filter(str.isdigit, team_size)) or "10"),
            pain_points=safe_pain,
            additional_context=safe_ctx,
        )
        await _update_lead(db, lead_id, assessment_output=assessment_output)
        log.info("[Outreach] Lead %s — assessment complete", lead_id[:8])

        # ── Proposal ─────────────────────────────────────────────────────────
        proposal_agent = _load_sales_agent("proposal-agent")
        proposal_output = proposal_agent.run(
            company=company,
            contact_name=lead_name,
            contact_role=role,
            assessment_result=assessment_output,
            qualification_result=qualify_output,
        )
        await _update_lead(db, lead_id, proposal_output=proposal_output)
        log.info("[Outreach] Lead %s — proposal complete", lead_id[:8])

        # ── Connection note ───────────────────────────────────────────────────
        connection_note = _draft_connection_note(qualify_output, lead_name, company)
        await _update_lead(
            db, lead_id,
            connection_note=connection_note,
            status=LEAD_QUALIFIED,
        )
        log.info("[Outreach] Lead %s — pipeline complete, status=qualified", lead_id[:8])

    except Exception as exc:
        log.error("[Outreach] Pipeline failed for lead %s: %s", lead_id[:8], exc)
        await _update_lead(db, lead_id, status=LEAD_NEW)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/leads", status_code=202)
async def create_lead(
    body: OutreachLeadCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    workspace: dict = Depends(get_workspace),
) -> dict:
    """
    Add a new lead and kick off the qualify → assess → propose pipeline.
    Returns lead_id immediately — poll GET /outreach/leads/{id} for status.
    """
    workspace_id = str(workspace["id"])

    async with request.app.state.db_pool.acquire() as conn:
        compliance = WorkspaceComplianceGuard(conn)
        try:
            await compliance.assert_workspace_active(workspace_id)
        except SubscriptionError as exc:
            raise HTTPException(status_code=402, detail=str(exc))

    lead_id = await _create_lead(request.app.state.db_pool, workspace_id, body)

    background_tasks.add_task(
        _run_lead_pipeline,
        request.app,
        lead_id,
        workspace_id,
        body.lead_name,
        body.company,
        body.role,
        body.team_size,
        body.cloud_provider,
        body.pain_points,
        body.how_they_found_us,
        body.additional_context,
    )

    return {
        "lead_id": lead_id,
        "status": LEAD_QUALIFYING,
        "message": "Pipeline started. Poll GET /outreach/leads/{lead_id} for status.",
    }


@router.get("/leads")
async def list_leads(
    request: Request,
    status_filter: Optional[str] = None,
    workspace: dict = Depends(get_workspace),
) -> list:
    """List leads for this workspace, newest first."""
    workspace_id = str(workspace["id"])
    sql = "SELECT * FROM outreach_leads WHERE workspace_id = $1"
    params = [UUID(workspace_id)]

    if status_filter:
        sql += " AND status = $2"
        params.append(status_filter)

    sql += " ORDER BY created_at DESC LIMIT 100"

    async with request.app.state.db_pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    results = []
    for row in rows:
        d = dict(row)
        qualify = d.get("qualify_output")
        if qualify and isinstance(qualify, str):
            qualify = json.loads(qualify)

        results.append({
            "id": str(d["id"]),
            "lead_name": d["lead_name"],
            "company": d["company"],
            "role": d["role"],
            "status": d["status"],
            "fit_score": (qualify or {}).get("fit_score") if qualify else None,
            "recommended_action": (qualify or {}).get("recommended_action") if qualify else None,
            "tier_recommendation": (qualify or {}).get("tier_recommendation") if qualify else None,
            "connection_note": d.get("connection_note"),
            "linkedin_url": d.get("linkedin_url", ""),
            "sent_at": d["sent_at"].isoformat() if d.get("sent_at") else None,
            "created_at": d["created_at"].isoformat(),
            "updated_at": d["updated_at"].isoformat(),
        })

    return results


@router.get("/leads/{lead_id}")
async def get_lead(
    lead_id: str,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> dict:
    """Get full lead detail including pipeline outputs."""
    workspace_id = str(workspace["id"])
    d = await _get_lead(request.app.state.db_pool, lead_id, workspace_id)

    qualify = d.get("qualify_output") or {}
    assess  = d.get("assessment_output") or {}

    return {
        "id": str(d["id"]),
        "lead_name": d["lead_name"],
        "company": d["company"],
        "role": d["role"],
        "team_size": d["team_size"],
        "cloud_provider": d["cloud_provider"],
        "pain_points": d["pain_points"],
        "how_they_found_us": d["how_they_found_us"],
        "linkedin_url": d.get("linkedin_url", ""),
        "status": d["status"],
        "fit_score": qualify.get("fit_score"),
        "talk_track": qualify.get("talk_track"),
        "recommended_action": qualify.get("recommended_action"),
        "tier_recommendation": qualify.get("tier_recommendation"),
        "icp_matches": qualify.get("icp_matches", []),
        "disqualifiers": qualify.get("disqualifiers", []),
        "risk_areas": assess.get("risk_areas", []),
        "recommended_agents": assess.get("recommended_agents", []),
        "estimated_monthly_hours_saved": assess.get("estimated_monthly_hours_saved"),
        "estimated_monthly_value_usd": assess.get("estimated_monthly_value_usd"),
        "connection_note": d.get("connection_note"),
        "qualify_output": d.get("qualify_output"),
        "assessment_output": d.get("assessment_output"),
        "proposal_output": d.get("proposal_output"),
        "sent_at": d["sent_at"].isoformat() if d.get("sent_at") else None,
        "status_updated_at": d["status_updated_at"].isoformat() if d.get("status_updated_at") else None,
        "created_at": d["created_at"].isoformat(),
        "updated_at": d["updated_at"].isoformat(),
        # Convenience: LinkedIn search URL — opens in user's browser, no automation
        "linkedin_search_url": (
            d.get("linkedin_url")
            or f"https://www.linkedin.com/search/results/people/?keywords={d['lead_name'].replace(' ', '+')}+{d['company'].replace(' ', '+')}"
        ),
    }


@router.post("/leads/{lead_id}/mark-sent")
async def mark_sent(
    lead_id: str,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> dict:
    """
    Mark that the operator has manually sent a connection request for this lead.

    This is the only pacing counter increment in the system.
    The actual connection request is ALWAYS sent manually by the operator
    in their own LinkedIn browser session — never by this API.
    """
    workspace_id = str(workspace["id"])
    db = request.app.state.db_pool
    d = await _get_lead(db, lead_id, workspace_id)

    if d["status"] not in (LEAD_QUALIFIED, LEAD_READY):
        raise HTTPException(
            status_code=409,
            detail=f"Lead is '{d['status']}' — only qualified or ready_to_send leads can be marked sent",
        )

    if d.get("sent_at"):
        raise HTTPException(status_code=409, detail="Lead already marked as sent")

    now = datetime.now(timezone.utc)
    await _update_lead(db, lead_id, status=LEAD_SENT, sent_at=now)

    # Return updated pacing so dashboard can refresh immediately
    pacing = await _compute_pacing(db, workspace_id)
    log.info("[Outreach] Lead %s marked sent — daily=%s weekly=%s",
             lead_id[:8], pacing.daily_sent, pacing.weekly_sent)

    return {
        "lead_id": lead_id,
        "status": LEAD_SENT,
        "pacing": pacing.model_dump(),
    }


@router.post("/leads/{lead_id}/status")
async def update_lead_status(
    lead_id: str,
    body: OutreachLeadStatusUpdate,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> dict:
    """
    Update acceptance status after manually sending a connection request.
    Valid transitions: sent → accepted | declined | no_response
    """
    valid = {LEAD_ACCEPTED, LEAD_DECLINED, LEAD_NO_RESPONSE}
    if body.status not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{body.status}'. Must be: {', '.join(valid)}",
        )

    workspace_id = str(workspace["id"])
    db = request.app.state.db_pool
    d = await _get_lead(db, lead_id, workspace_id)

    if d["status"] != LEAD_SENT:
        raise HTTPException(
            status_code=409,
            detail=f"Lead is '{d['status']}' — only 'sent' leads can have acceptance status updated",
        )

    now = datetime.now(timezone.utc)
    await _update_lead(db, lead_id, status=body.status, status_updated_at=now)

    return {"lead_id": lead_id, "status": body.status}


@router.get("/pacing", response_model=PacingStatus)
async def get_pacing(
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> PacingStatus:
    """
    Current pacing status — daily/weekly send counts, warnings, acceptance rate.
    Poll this after every mark-sent action to keep the dashboard current.
    """
    workspace_id = str(workspace["id"])
    return await _compute_pacing(request.app.state.db_pool, workspace_id)
