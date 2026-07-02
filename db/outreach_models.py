"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
Outreach pipeline data models — Phase 3.

OutreachLead represents one prospect moving through the
qualify → assess → propose → draft-note → manual-send workflow.

This is decision-support only. The system never sends a connection
request, DM, or any communication on the user's behalf. The workflow
ends with the user copy-pasting a drafted note and clicking send
manually in their own LinkedIn browser session.

States:
  new           — lead entered, pipeline not yet run
  qualifying    — agents running in background
  qualified     — ICP score computed, connection note drafted, ready for review
  disqualified  — fit_score too low or recommended_action = reject
  ready_to_send — user reviewed and approved the note
  sent          — user manually marked as sent (pacing counter incremented)
  accepted      — connection accepted
  declined      — connection declined or withdrawn
  no_response   — no response after follow-up window
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


# ── Status constants ──────────────────────────────────────────────────────────

LEAD_NEW           = "new"
LEAD_QUALIFYING    = "qualifying"
LEAD_QUALIFIED     = "qualified"
LEAD_DISQUALIFIED  = "disqualified"
LEAD_READY         = "ready_to_send"
LEAD_SENT          = "sent"
LEAD_ACCEPTED      = "accepted"
LEAD_DECLINED      = "declined"
LEAD_NO_RESPONSE   = "no_response"

# Pacing thresholds — warn before hitting, loud message at limit
DAILY_WARN  = 20
DAILY_LIMIT = 30
WEEKLY_WARN  = 100
WEEKLY_LIMIT = 200
ACCEPTANCE_RATE_FLOOR = 0.20   # flag if below 20%


# ── Pydantic models ───────────────────────────────────────────────────────────

class OutreachLeadCreate(BaseModel):
    lead_name: str
    company: str
    role: str
    team_size: str
    cloud_provider: str
    pain_points: str
    how_they_found_us: str
    linkedin_url: str = ""
    additional_context: str = ""


class OutreachLeadStatusUpdate(BaseModel):
    status: str   # accepted | declined | no_response


class OutreachLead(BaseModel):
    id: UUID
    workspace_id: UUID

    lead_name: str
    company: str
    role: str
    team_size: str
    cloud_provider: str
    pain_points: str
    how_they_found_us: str
    linkedin_url: Optional[str]
    additional_context: Optional[str]

    qualify_output: Optional[dict] = None
    assessment_output: Optional[dict] = None
    proposal_output: Optional[dict] = None
    connection_note: Optional[str] = None    # ≤300 chars, ready to copy-paste

    status: str
    sent_at: Optional[datetime] = None
    status_updated_at: Optional[datetime] = None

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PacingStatus(BaseModel):
    daily_sent: int
    daily_warn: int
    daily_limit: int
    daily_pct: float            # 0.0–1.0
    daily_warning: bool
    daily_at_limit: bool

    weekly_sent: int
    weekly_warn: int
    weekly_limit: int
    weekly_pct: float
    weekly_warning: bool
    weekly_at_limit: bool

    total_sent: int
    total_accepted: int
    total_declined: int
    total_no_response: int
    acceptance_rate: Optional[float]         # None if not enough data
    acceptance_rate_warning: bool

    message: str                             # human-readable summary
