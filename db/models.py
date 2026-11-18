"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────
# Remediation option embedded in incident JSONB
# ──────────────────────────────────────────────

class BlastRadius(BaseModel):
    """What an option touches if approved (gap-table #8). Plain words, shown
    as a badge next to the option, so an approver can weigh scope before
    approving -- not a computed risk score."""
    scope: str                   # "1 deployment, 3 pods"
    change_surface: str          # "Kubernetes API" | "pull request" | "AWS IAM" ...
    reversible: bool


class RemediationOption(BaseModel):
    id: str                      # "opt_1", "opt_2", "opt_3", "hold"
    title: str
    description: str
    impact: str                  # "low" | "medium" | "high"
    docs_url: str
    # Gap-table #7-#9, all optional so every agent's existing options stay
    # valid unchanged: the exact change as a unified diff, what it touches,
    # and the execution steps this option will stream when approved.
    diff: Optional[str] = None
    blast_radius: Optional[BlastRadius] = None
    execution_log: Optional[list[str]] = None


class EvidenceBlock(BaseModel):
    """One piece of root-cause evidence (migration 061, gap-table #6)."""
    kind: str                    # "log" | "kubectl" | "metrics" | "terraform" | "cli"
    title: str
    lines: list[str]


# ──────────────────────────────────────────────
# Workspace
# ──────────────────────────────────────────────

class WorkspaceBase(BaseModel):
    company_name: str
    product_tier: str = "starter"
    max_repos: int = 3
    cloud_providers: list[str] = Field(default_factory=list)
    monthly_token_budget_usd: float = 50.00


class WorkspaceCreate(WorkspaceBase):
    workspace_token: str
    stripe_customer_id: Optional[str] = None


class Workspace(WorkspaceBase):
    id: UUID
    workspace_token: str
    stripe_customer_id: Optional[str] = None
    stripe_subscription_status: str = "trialing"
    encrypted_llm_key: Optional[str] = None
    current_month_spend_usd: float = 0.00
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
# Incident
# ──────────────────────────────────────────────

class IncidentCreate(BaseModel):
    workspace_id: UUID
    agent_id: str
    cloud_provider: Optional[str] = None
    raw_log_hash: Optional[str] = None
    parsed_error: str
    remediation_options: list[RemediationOption]
    tokens_used: int = 0
    estimated_duration_seconds: Optional[int] = None


class IncidentApproveRequest(BaseModel):
    selected_option_id: str          # "opt_1" | "opt_2" | "opt_3" | "hold" | "custom"
    custom_solution_input: Optional[str] = None


class IncidentResolveManuallyRequest(BaseModel):
    """
    "I'll handle this myself" on the HITL card. Not a custom execution
    path -- resolution_note is a record of what the operator already did
    outside the platform, never an instruction the platform acts on.
    """
    resolution_note: Optional[str] = Field(default=None, max_length=4000)


class ManualResolutionResponse(BaseModel):
    incident_id: str
    status: str
    resolution_note: Optional[str] = None
    resolved_at: datetime


class Incident(BaseModel):
    id: UUID
    workspace_id: UUID
    agent_id: str
    cloud_provider: Optional[str] = None
    raw_log_hash: Optional[str] = None
    parsed_error: str
    remediation_options: list[RemediationOption]
    selected_option_id: Optional[str] = None
    custom_solution_input: Optional[str] = None
    execution_status: str = "pending_approval"
    estimated_duration_seconds: Optional[int] = None
    tokens_used: int = 0
    created_at: datetime
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
# Internal Agent Task
# ──────────────────────────────────────────────

class InternalAgentTaskCreate(BaseModel):
    source_agent: str
    target_agent: Optional[str] = None
    task_type: str
    payload: dict
    operator_approval_required: bool = True


class InternalAgentTask(InternalAgentTaskCreate):
    id: UUID
    operator_approved: bool = False
    execution_state: str = "queued"
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
# Token Usage
# ──────────────────────────────────────────────

class TokenUsageRecord(BaseModel):
    id: UUID
    workspace_id: UUID
    incident_id: Optional[UUID] = None
    agent_id: Optional[str] = None
    tokens_used: int
    cost_usd: float
    billing_month: str     # "YYYY-MM"
    created_at: datetime

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
# API response shapes
# ──────────────────────────────────────────────

class IncidentResponse(BaseModel):
    incident_id: str
    status: str
    parsed_error: str
    options: list[RemediationOption]
    estimated_duration_seconds: Optional[int] = None
    severity: Optional[str] = None  # critical|high|medium|low -- migration 042
    # Migration 061: root-cause evidence blocks, None when an agent produced none.
    evidence: Optional[list[EvidenceBlock]] = None
    # 24-gap-closure Phase 2. agent_id/created_at were referenced throughout
    # the frontend (PipelineTracker.tsx, RemediationCard.tsx) but never
    # actually returned by get_incident/list_incidents -- a real pre-existing
    # gap found while adding the search/filter API, not introduced here.
    agent_id: Optional[str] = None
    resource_id: Optional[str] = None
    resource_name: Optional[str] = None
    # Settings → Policies, Step 3 -- so the frontend can map an incident to
    # its workspace connection mode (aws_connection_mode/azure_connection_mode)
    # without a second lookup. Was tracked on the incidents row all along
    # (core/hitl.py's create_incident) but never actually returned here.
    cloud_provider: Optional[str] = None
    created_at: Optional[str] = None
    assigned_to: Optional[str] = None
    assigned_to_email: Optional[str] = None
    # migration 050 -- graceful permission-failure surfacing (Settings →
    # Policies, Step 4). Both None for every incident that never reached
    # execution, or that failed for a reason other than execution.
    failure_reason: Optional[str] = None
    failure_kind: Optional[str] = None  # 'permission_denied' | 'execution_error' | None
    # migration 064 (G4) -- the last post-fix verification check:
    # {outcome: fixed|not_fixed|unknown|unverifiable, detail, checked_at, attempt}
    verification_result: Optional[dict] = None
    # migration 065 (G2): the earlier incident with the same regression_key, and
    # whether that one was fixed (or said it was) -- i.e. this is a regression.
    previous_incident_id: Optional[str] = None
    is_regression: bool = False
    # migration 056 / G3: when the alert source itself reported the condition cleared.
    source_resolved_at: Optional[datetime] = None


class IncidentAssignRequest(BaseModel):
    member_id: Optional[str] = None  # None unassigns


class IncidentCommentCreateRequest(BaseModel):
    # Bounded so no caller (the public demo included) can store an
    # arbitrarily large comment; 4,000 chars is well beyond any real note.
    body: str = Field(..., max_length=4000)


class IncidentCommentResponse(BaseModel):
    id: str
    incident_id: str
    member_id: Optional[str] = None
    member_email: Optional[str] = None  # None for a token-authenticated caller
    body: str
    created_at: str


class BulkIncidentActionRequest(BaseModel):
    incident_ids: list[str]
    action: str  # "dismiss" | "resolve_manually"
    reason: Optional[str] = None            # dismiss
    resolution_note: Optional[str] = None   # resolve_manually


class BulkIncidentActionResult(BaseModel):
    incident_id: str
    outcome: str  # "applied" | "not_found" | "not_pending" (status the action doesn't apply to)


class BulkIncidentActionResponse(BaseModel):
    action: str
    results: list[BulkIncidentActionResult]


class ApprovalResponse(BaseModel):
    incident_id: str
    status: str
    selected_option_id: str
    message: str
