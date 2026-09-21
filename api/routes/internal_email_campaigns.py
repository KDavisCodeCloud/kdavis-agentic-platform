"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Internal Email Campaign HITL API (migration 051) -- owner-only, backing
the CEO Decoded dashboard's Email Campaign queue (a separate build/repo
directory, ceo-dashboard/). Contract documented in
docs/internal/email-approval-api.md -- keep field names stable, the
dashboard's proxy routes depend on this exact shape.

Auth: Depends(get_internal_user) -- same Supabase-session-JWT admin check
every other /internal/* route in this file uses (api/middleware/
internal_auth.py). NOTE: that dependency only recognizes role=='admin' --
there is no 'hitl' role in this backend's auth model yet. Kelvin's plan
for his wife to approve templates under a 'hitl' role needs that role
added to get_internal_user's check first; not done in this build to avoid
changing a shared auth dependency's semantics without being asked (see
GAPS.md). Every endpoint below is admin-only for now.

GET  /internal/email-templates                 - list (filter by status/sequence_key)
GET  /internal/email-templates/{key}           - one template, rendered preview
PUT  /internal/email-templates/{key}           - edit (resets to pending_approval)
POST /internal/email-templates/{key}/approve
POST /internal/email-templates/{key}/retire
POST /internal/email-sequences/{key}/activate  - refuses if any step lacks an approved template
POST /internal/email-sequences/{key}/deactivate
GET  /internal/email-metrics                   - per-sequence sends/clicks/unsubs/conversions/revenue
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.middleware.internal_auth import get_internal_user
from core.marketing_email import compliance_footer_html, compliance_footer_text

log = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/email", tags=["internal-email-campaigns"])

_PRODUCT = "cloud-decoded"

# Static tier pricing for the metrics endpoint's revenue estimate --
# matches CLAUDE.md's published Cloud Decoded pricing. Not read from
# Stripe live, since a workspace's *current* price could differ from list
# price (promo codes, grandfathering) -- this is a directional estimate,
# documented as such in the response, not a billing-accurate figure.
_TIER_PRICE_USD = {"starter": 299, "growth": 699, "enterprise": 2499}


class TemplateOut(BaseModel):
    template_key: str
    sequence_key: str
    step_number: int
    delay_days: int
    subject: str
    preheader: Optional[str]
    status: str
    origin: str
    source_script: Optional[str]
    cta_url: Optional[str]
    skip_if: Optional[str]
    approved_at: Optional[str]
    approved_by: Optional[str]
    product: str = _PRODUCT


class TemplatePreviewOut(TemplateOut):
    body_html: str
    body_text: str
    rendered_html: str
    rendered_text: str


class TemplateEditRequest(BaseModel):
    subject: Optional[str] = None
    preheader: Optional[str] = None
    body_html: Optional[str] = None
    body_text: Optional[str] = None
    cta_url: Optional[str] = None


class SequenceActionOut(BaseModel):
    sequence_key: str
    active: bool
    detail: str


def _row_to_template_out(row: dict) -> TemplateOut:
    return TemplateOut(
        template_key=row["key"],
        sequence_key=row["sequence_key"],
        step_number=row["step_number"],
        delay_days=row["delay_days"],
        subject=row["subject"],
        preheader=row.get("preheader"),
        status=row["status"],
        origin=row["origin"],
        source_script=row.get("source_script"),
        cta_url=row.get("cta_url"),
        skip_if=row.get("skip_if"),
        approved_at=row["approved_at"].isoformat() if row.get("approved_at") else None,
        approved_by=row.get("approved_by"),
    )


@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(
    request: Request,
    status_filter: Optional[str] = None,
    sequence_key: Optional[str] = None,
    admin: dict = Depends(get_internal_user),
) -> list[TemplateOut]:
    clauses, params = [], []
    if status_filter:
        params.append(status_filter)
        clauses.append(f"status = ${len(params)}")
    if sequence_key:
        params.append(sequence_key)
        clauses.append(f"sequence_key = ${len(params)}")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    async with request.app.state.db_pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT key, sequence_key, step_number, delay_days, subject, preheader,
                   status, origin, source_script, cta_url, skip_if, approved_at, approved_by
            FROM cd_email_templates
            {where}
            ORDER BY sequence_key, step_number
            """,
            *params,
        )
    return [_row_to_template_out(dict(r)) for r in rows]


async def _fetch_template_or_404(conn, key: str) -> dict:
    row = await conn.fetchrow("SELECT * FROM cd_email_templates WHERE key = $1", key)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {key!r} not found")
    return dict(row)


@router.get("/templates/{key}", response_model=TemplatePreviewOut)
async def get_template(key: str, request: Request, admin: dict = Depends(get_internal_user)) -> TemplatePreviewOut:
    async with request.app.state.db_pool.acquire() as conn:
        row = await _fetch_template_or_404(conn, key)

    base = _row_to_template_out(row)
    # Preview includes the exact compliance footer a real send would get,
    # using a placeholder recipient -- the reviewer sees what the
    # recipient will actually see, unsubscribe link included.
    placeholder = "preview@theclouddecoded.com"
    return TemplatePreviewOut(
        **base.model_dump(),
        body_html=row["body_html"],
        body_text=row["body_text"],
        rendered_html=row["body_html"] + compliance_footer_html(placeholder),
        rendered_text=row["body_text"] + compliance_footer_text(placeholder),
    )


@router.put("/templates/{key}", response_model=TemplateOut)
async def edit_template(
    key: str, body: TemplateEditRequest, request: Request, admin: dict = Depends(get_internal_user),
) -> TemplateOut:
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    sets, params = [], []
    for field_name, value in fields.items():
        params.append(value)
        sets.append(f"{field_name} = ${len(params)}")
    # Any edit resets review state -- an edited template must be re-approved.
    sets += ["status = 'pending_approval'", "approved_at = NULL", "approved_by = NULL"]
    params.append(key)

    async with request.app.state.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE cd_email_templates SET {', '.join(sets)} WHERE key = ${len(params)} RETURNING *",
            *params,
        )
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {key!r} not found")

    log.info("[EmailCampaigns] Template %s edited by %s -- reset to pending_approval", key, admin["email"])
    return _row_to_template_out(dict(row))


@router.post("/templates/{key}/approve", response_model=TemplateOut)
async def approve_template(key: str, request: Request, admin: dict = Depends(get_internal_user)) -> TemplateOut:
    async with request.app.state.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE cd_email_templates
            SET status = 'approved', approved_at = NOW(), approved_by = $2
            WHERE key = $1
            RETURNING *
            """,
            key, admin["email"],
        )
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {key!r} not found")

    log.info("[EmailCampaigns] Template %s approved by %s", key, admin["email"])
    return _row_to_template_out(dict(row))


@router.post("/templates/{key}/retire", response_model=TemplateOut)
async def retire_template(key: str, request: Request, admin: dict = Depends(get_internal_user)) -> TemplateOut:
    async with request.app.state.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE cd_email_templates SET status = 'retired' WHERE key = $1 RETURNING *", key,
        )
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {key!r} not found")

    log.info("[EmailCampaigns] Template %s retired by %s", key, admin["email"])
    return _row_to_template_out(dict(row))


@router.post("/sequences/{key}/activate", response_model=SequenceActionOut)
async def activate_sequence(key: str, request: Request, admin: dict = Depends(get_internal_user)) -> SequenceActionOut:
    async with request.app.state.db_pool.acquire() as conn:
        seq = await conn.fetchrow("SELECT key FROM cd_email_sequences WHERE key = $1", key)
        if not seq:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Sequence {key!r} not found")

        steps = await conn.fetch(
            """
            SELECT step_number,
                   bool_or(status = 'approved') AS has_approved
            FROM cd_email_templates WHERE sequence_key = $1
            GROUP BY step_number
            """,
            key,
        )
        missing = sorted(s["step_number"] for s in steps if not s["has_approved"])
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot activate {key!r} -- steps without an approved template: {missing}",
            )

        await conn.execute("UPDATE cd_email_sequences SET active = true WHERE key = $1", key)

    log.info("[EmailCampaigns] Sequence %s activated by %s", key, admin["email"])
    return SequenceActionOut(sequence_key=key, active=True, detail="Activated -- enrollments will now advance.")


@router.post("/sequences/{key}/deactivate", response_model=SequenceActionOut)
async def deactivate_sequence(key: str, request: Request, admin: dict = Depends(get_internal_user)) -> SequenceActionOut:
    async with request.app.state.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE cd_email_sequences SET active = false WHERE key = $1 RETURNING key", key,
        )
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Sequence {key!r} not found")

    log.info("[EmailCampaigns] Sequence %s deactivated by %s", key, admin["email"])
    return SequenceActionOut(sequence_key=key, active=False, detail="Deactivated -- no further sends will go out.")


class MetricsRow(BaseModel):
    sequence_key: str
    sends: int
    clicks: int
    unsubscribes: int
    conversions: int
    revenue_usd_estimate: int
    product: str = _PRODUCT


@router.get("/metrics", response_model=list[MetricsRow])
async def email_metrics(
    request: Request, sequence_key: Optional[str] = None, admin: dict = Depends(get_internal_user),
) -> list[MetricsRow]:
    async with request.app.state.db_pool.acquire() as conn:
        seq_filter = "WHERE t.sequence_key = $1" if sequence_key else ""
        params = [sequence_key] if sequence_key else []

        send_rows = await conn.fetch(
            f"""
            SELECT t.sequence_key,
                   COUNT(*) FILTER (WHERE s.status = 'sent') AS sends,
                   COUNT(DISTINCT c.id) AS clicks
            FROM cd_email_sends s
            JOIN cd_email_templates t ON t.key = s.template_key
            LEFT JOIN cd_email_clicks c ON c.send_id = s.id
            {seq_filter}
            GROUP BY t.sequence_key
            """,
            *params,
        )

        # Global unsubscribe count -- suppression isn't sequence-scoped
        # (one email can be enrolled in several sequences), so this is a
        # platform-wide figure attached to every row, not summed per row.
        unsub_count = await conn.fetchval(
            "SELECT COUNT(*) FROM cd_email_suppressions WHERE reason = 'unsubscribe'"
        )

        conversions = await conn.fetch(
            """
            SELECT last_touch_template, product_tier
            FROM workspaces
            WHERE last_touch_template IS NOT NULL AND stripe_subscription_status IN ('active', 'past_due')
            """,
        )

    template_to_sequence: dict[str, str] = {}
    if conversions:
        async with request.app.state.db_pool.acquire() as conn:
            template_rows = await conn.fetch("SELECT key, sequence_key FROM cd_email_templates")
        template_to_sequence = {r["key"]: r["sequence_key"] for r in template_rows}

    conv_by_sequence: dict[str, list[int]] = {}
    for c in conversions:
        seq = template_to_sequence.get(c["last_touch_template"])
        if seq:
            conv_by_sequence.setdefault(seq, []).append(_TIER_PRICE_USD.get(c["product_tier"], 0))

    results = []
    for r in send_rows:
        seq = r["sequence_key"]
        conv_prices = conv_by_sequence.get(seq, [])
        results.append(MetricsRow(
            sequence_key=seq,
            sends=r["sends"],
            clicks=r["clicks"],
            unsubscribes=unsub_count,
            conversions=len(conv_prices),
            revenue_usd_estimate=sum(conv_prices),
        ))
    return results
