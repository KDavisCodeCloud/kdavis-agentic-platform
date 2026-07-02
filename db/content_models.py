"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
Content pipeline data models.

ContentDraft represents one piece of content moving through the
brief → draft → review → human-approval → publish pipeline.

States:
  generating     — LLM pipeline is running (brief/draft/review agents)
  pending_review — pipeline complete, waiting for human approval
  approved       — human approved, ready to post
  publishing     — API call to LinkedIn/X in flight
  published      — successfully posted; platform post ID recorded
  rejected       — human rejected; rejection_feedback stored for re-run
  failed         — pipeline or publish error

This extends the HITL concept from core/hitl.py without duplicating its
infrastructure — content drafts have different fields (no remediation_options,
no cloud_provider) so they live in their own table.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


# ── State constants — keep in sync with content_drafts table CHECK constraint ─

DRAFT_GENERATING    = "generating"
DRAFT_PENDING       = "pending_review"
DRAFT_APPROVED      = "approved"
DRAFT_PUBLISHING    = "publishing"
DRAFT_PUBLISHED     = "published"
DRAFT_REJECTED      = "rejected"
DRAFT_FAILED        = "failed"


# ── Pydantic models ───────────────────────────────────────────────────────────

class ContentDraftCreate(BaseModel):
    workspace_id: UUID
    platform: str           # "linkedin" | "x" | "video"
    raw_idea: str
    goal: str               # "awareness" | "education" | "credibility" | "lead_gen"
    target_audience: str = "Engineering Managers and DevOps leads"
    additional_constraints: str = ""


class ContentDraftApprove(BaseModel):
    selected_draft: str     # "draft_a" | "draft_b"
    operator_edit: Optional[str] = None   # if non-None, use this text instead of selected draft


class ContentDraftReject(BaseModel):
    feedback: str           # returned to draft-agent on re-run


class ContentDraft(BaseModel):
    id: UUID
    workspace_id: UUID
    platform: str
    raw_idea: str
    goal: str
    status: str

    # Pipeline outputs — populated progressively as agents run
    brief: Optional[dict] = None
    draft_output: Optional[dict] = None        # full draft-agent output (has draft_a, draft_b)
    review_output: Optional[dict] = None       # full review-agent output
    publish_package: Optional[dict] = None     # publish-agent output

    # Human decision
    selected_draft: Optional[str] = None       # "draft_a" or "draft_b"
    operator_edit: Optional[str] = None        # override text if human edited
    rejection_feedback: Optional[str] = None

    # Published result
    linkedin_post_id: Optional[str] = None
    x_post_id: Optional[str] = None

    # Impact scoring (from review-agent scores)
    brand_voice_score: Optional[int] = None
    brief_alignment_score: Optional[int] = None

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ContentDraftResponse(BaseModel):
    """Slimmed response shape for list endpoints."""
    id: str
    platform: str
    raw_idea: str
    goal: str
    status: str
    brand_voice_score: Optional[int]
    brief_alignment_score: Optional[int]
    brief_title: Optional[str]   # from brief.brief_title
    created_at: datetime
    updated_at: datetime


class SocialConnection(BaseModel):
    """OAuth connection record for LinkedIn or X."""
    id: UUID
    workspace_id: UUID
    platform: str                  # "linkedin" | "x"
    platform_user_id: str
    platform_display_name: Optional[str]
    encrypted_access_token: str
    encrypted_token_secret: Optional[str] = None   # X OAuth 1.0a only
    author_urn: Optional[str] = None               # LinkedIn author URN for posting
    connected_at: datetime

    class Config:
        from_attributes = True
