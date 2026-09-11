"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Cloud audit findings submission + remediation plan review.

POST /audit/submit                — submit a kdavis-cloud-audit findings.json,
                                     runs the analysis agent synchronously
GET  /audit/{audit_id}/report     — retrieve a submission's plan
POST /audit/items/{item_id}/approve — mark an item approved (terminal, no execution)
POST /audit/items/{item_id}/dismiss — mark an item dismissed

Findings arrive already sanitized client-side (kdavis-cloud-audit's own
DataSanitizationShield) — this endpoint never re-sanitizes or assumes raw
secrets could be present in them, though every LLM call inside the analysis
agent still runs through core.security.shield as BaseAgent.call_llm always
does regardless of caller.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from agents.audit_analysis.workflow import AuditAnalysisAgent
from api.middleware.auth import get_workspace
from api.middleware.rate_limiter import limiter

log = logging.getLogger(__name__)
router = APIRouter(prefix="/audit", tags=["audit"])


# ── Request / response models ─────────────────────────────────────────────────

class FindingModel(BaseModel):
    finding_id: str
    provider: str
    category: str
    severity: str
    service: str
    resource_type: str
    resource_id: str
    title: str
    description: str
    remediation: str
    estimated_monthly_waste_usd: float = 0.0
    detected_at: str


class SummaryModel(BaseModel):
    total_findings: int
    high_severity: int
    medium_severity: int
    low_severity: int
    total_estimated_monthly_waste_usd: float
    total_estimated_annual_waste_usd: float


class AuditSubmitRequest(BaseModel):
    generated_at: str
    provider: str
    scan_duration_seconds: Optional[float] = None
    summary: SummaryModel
    findings: list[FindingModel] = Field(default_factory=list)


class RemediationItemResponse(BaseModel):
    id: str
    severity: str
    category: str
    title: str
    description: str
    remediation: str
    estimated_monthly_waste_usd: float
    priority_rank: int
    status: str


class AuditReportResponse(BaseModel):
    audit_id: str
    status: str
    provider: str
    total_findings: int
    total_estimated_monthly_waste_usd: float
    analysis_error: Optional[str] = None
    items: list[RemediationItemResponse]


class ItemActionResponse(BaseModel):
    id: str
    status: str


# ── Helpers ─────────────────────────────────────────────────────────────────

def _row_to_item(row) -> RemediationItemResponse:
    return RemediationItemResponse(
        id=str(row["id"]),
        severity=row["severity"],
        category=row["category"],
        title=row["title"],
        description=row["description"],
        remediation=row["remediation"],
        estimated_monthly_waste_usd=float(row["estimated_monthly_waste_usd"]),
        priority_rank=row["priority_rank"],
        status=row["status"],
    )


async def _load_report(conn, audit_id: str, workspace_id) -> AuditReportResponse:
    submission = await conn.fetchrow(
        "SELECT id, provider, total_findings, total_estimated_monthly_waste_usd, status, analysis_error "
        "FROM cloud_audit_submissions WHERE id = $1 AND workspace_id = $2",
        audit_id,
        workspace_id,
    )
    if not submission:
        raise HTTPException(status_code=404, detail="Audit submission not found")

    item_rows = await conn.fetch(
        "SELECT id, severity, category, title, description, remediation, "
        "estimated_monthly_waste_usd, priority_rank, status "
        "FROM cloud_audit_remediation_items WHERE submission_id = $1 ORDER BY priority_rank",
        audit_id,
    )

    return AuditReportResponse(
        audit_id=str(submission["id"]),
        status=submission["status"],
        provider=submission["provider"],
        total_findings=submission["total_findings"],
        total_estimated_monthly_waste_usd=float(submission["total_estimated_monthly_waste_usd"]),
        analysis_error=submission["analysis_error"],
        items=[_row_to_item(r) for r in item_rows],
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/submit", response_model=AuditReportResponse, status_code=201)
@limiter.limit("20/minute")
async def submit_audit(
    body: AuditSubmitRequest,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> AuditReportResponse:
    workspace_id = workspace["id"]
    findings = [f.model_dump() for f in body.findings]

    async with request.app.state.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO cloud_audit_submissions (
                workspace_id, provider, scan_duration_seconds,
                total_findings, total_estimated_monthly_waste_usd, raw_findings
            ) VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            workspace_id,
            body.provider,
            body.scan_duration_seconds,
            body.summary.total_findings,
            body.summary.total_estimated_monthly_waste_usd,
            findings,
        )
        submission_id = str(row["id"])

        agent = AuditAnalysisAgent(conn, str(workspace_id))
        await agent.run(payload={"submission_id": submission_id, "findings": findings})

        log.info("[Audit] Submission=%s workspace=%s findings=%d", submission_id, workspace_id, len(findings))

        return await _load_report(conn, submission_id, workspace_id)


@router.get("/{audit_id}/report", response_model=AuditReportResponse)
async def get_audit_report(
    audit_id: str,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> AuditReportResponse:
    async with request.app.state.db_pool.acquire() as conn:
        return await _load_report(conn, audit_id, workspace["id"])


@router.post("/items/{item_id}/approve", response_model=ItemActionResponse)
async def approve_item(
    item_id: str,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> ItemActionResponse:
    async with request.app.state.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE cloud_audit_remediation_items
            SET status = 'approved', actioned_at = $1
            WHERE id = $2 AND workspace_id = $3
            RETURNING id, status
            """,
            datetime.now(timezone.utc),
            item_id,
            workspace["id"],
        )
    if not row:
        raise HTTPException(status_code=404, detail="Remediation item not found")

    log.info("[Audit] Item=%s approved workspace=%s", item_id, workspace["id"])
    return ItemActionResponse(id=str(row["id"]), status=row["status"])


@router.post("/items/{item_id}/dismiss", response_model=ItemActionResponse)
async def dismiss_item(
    item_id: str,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> ItemActionResponse:
    async with request.app.state.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE cloud_audit_remediation_items
            SET status = 'dismissed', actioned_at = $1
            WHERE id = $2 AND workspace_id = $3
            RETURNING id, status
            """,
            datetime.now(timezone.utc),
            item_id,
            workspace["id"],
        )
    if not row:
        raise HTTPException(status_code=404, detail="Remediation item not found")

    log.info("[Audit] Item=%s dismissed workspace=%s", item_id, workspace["id"])
    return ItemActionResponse(id=str(row["id"]), status=row["status"])
