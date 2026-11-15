"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

First-party funnel events (migration 060, gap-table #12/#13). See
core/funnel_events.py for the event model and privacy constraints.

POST /events                      public, rate-limited. Browser-sent
                                  CLIENT_EVENTS only; the server-recorded
                                  conversion steps are rejected here.
GET  /internal/funnel/summary     admin (Supabase session). Event counts
                                  for the last N days, overall and per
                                  utm_campaign.
GET  /internal/funnel/refs/{ref}  admin. Everything one outreach reference
                                  code led to: timeline, step counts, and
                                  the workspace it signed up as, if any.
                                  This is what the CEO dashboard's lead card
                                  reads (mse-api follow-up, GAPS.md).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from api.middleware.internal_auth import get_internal_user
from api.middleware.rate_limiter import limiter
from core.demo_sandbox import resolve_demo_session
from core.funnel_events import ALL_EVENTS, CLIENT_EVENTS, PRODUCT_ID, clean_ref, record_event

log = logging.getLogger(__name__)
router = APIRouter(tags=["funnel"])


class ClientEventRequest(BaseModel):
    event: str = Field(..., max_length=40)
    visitor_id: Optional[str] = Field(None, max_length=64)
    ref: Optional[str] = Field(None, max_length=64)
    utm_source: Optional[str] = Field(None, max_length=200)
    utm_medium: Optional[str] = Field(None, max_length=200)
    utm_campaign: Optional[str] = Field(None, max_length=200)
    path: Optional[str] = Field(None, max_length=500)
    properties: Optional[dict] = None


@router.post("/events", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("120/minute")
async def record_client_event(body: ClientEventRequest, request: Request) -> Response:
    if body.event not in CLIENT_EVENTS:
        # Conversion steps (approve, signup, checkout, subscribed) are only
        # ever written by the API itself -- a browser can't report them.
        raise HTTPException(status_code=422, detail=f"'{body.event}' is not a client-reportable event")

    db = request.app.state.db_pool

    # A demo token, if present, is resolved server-side. The client never
    # gets to name a demo_session_id directly.
    demo_session_id = None
    demo_token = request.headers.get("X-Demo-Session-Token")
    if demo_token:
        session = await resolve_demo_session(db, demo_token)
        if session:
            demo_session_id = session["demo_session_id"]

    async with db.acquire() as conn:
        await record_event(
            conn, body.event,
            visitor_id=body.visitor_id,
            ref=body.ref,
            utm_source=body.utm_source,
            utm_medium=body.utm_medium,
            utm_campaign=body.utm_campaign,
            path=body.path,
            demo_session_id=demo_session_id,
            properties=body.properties,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/internal/funnel/summary")
async def funnel_summary(
    request: Request,
    days: int = Query(30, ge=1, le=395),
    _user: dict = Depends(get_internal_user),
) -> dict:
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        totals = await conn.fetch(
            """
            SELECT event_name, COUNT(*) AS events,
                   COUNT(DISTINCT COALESCE(demo_session_id::text, workspace_id::text, visitor_id)) AS unique_subjects
            FROM cd_funnel_events
            WHERE product_id = $1 AND created_at >= NOW() - ($2 || ' days')::interval
            GROUP BY event_name
            """,
            PRODUCT_ID, str(days),
        )
        by_campaign = await conn.fetch(
            """
            SELECT COALESCE(utm_campaign, '(none)') AS campaign, event_name, COUNT(*) AS events
            FROM cd_funnel_events
            WHERE product_id = $1 AND created_at >= NOW() - ($2 || ' days')::interval
            GROUP BY 1, 2
            ORDER BY 1, 2
            """,
            PRODUCT_ID, str(days),
        )
    counts = {name: {"events": 0, "unique": 0} for name in sorted(ALL_EVENTS)}
    for row in totals:
        counts[row["event_name"]] = {"events": row["events"], "unique": row["unique_subjects"]}
    campaigns: dict[str, dict[str, int]] = {}
    for row in by_campaign:
        campaigns.setdefault(row["campaign"], {})[row["event_name"]] = row["events"]
    return {"days": days, "events": counts, "by_campaign": campaigns}


@router.get("/internal/funnel/refs/{ref}")
async def funnel_for_ref(
    ref: str,
    request: Request,
    _user: dict = Depends(get_internal_user),
) -> dict:
    if not clean_ref(ref):
        raise HTTPException(status_code=422, detail="ref must be 4-64 characters of A-Z, a-z, 0-9, _ or -")
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT event_name, path, properties, demo_session_id, workspace_id, created_at
            FROM cd_funnel_events
            WHERE product_id = $1 AND ref = $2
            ORDER BY created_at ASC
            LIMIT 500
            """,
            PRODUCT_ID, ref,
        )
        workspace = await conn.fetchrow(
            """
            SELECT id, company_name, product_tier, stripe_subscription_status, created_at
            FROM workspaces WHERE signup_ref = $1
            ORDER BY created_at ASC LIMIT 1
            """,
            ref,
        )
    steps = {name: 0 for name in sorted(ALL_EVENTS)}
    for row in rows:
        steps[row["event_name"]] = steps.get(row["event_name"], 0) + 1
    return {
        "ref": ref,
        "first_seen": rows[0]["created_at"].isoformat() if rows else None,
        "last_seen": rows[-1]["created_at"].isoformat() if rows else None,
        "steps": steps,
        "demo_sessions": len({r["demo_session_id"] for r in rows if r["demo_session_id"]}),
        "workspace": (
            {
                "id": str(workspace["id"]),
                "company_name": workspace["company_name"],
                "tier": workspace["product_tier"],
                "subscription_status": workspace["stripe_subscription_status"],
                "signed_up_at": workspace["created_at"].isoformat() if workspace["created_at"] else None,
            }
            if workspace else None
        ),
        "timeline": [
            {
                "event": r["event_name"],
                "path": r["path"],
                "properties": r["properties"] or {},
                "at": r["created_at"].isoformat(),
            }
            for r in rows
        ],
    }
