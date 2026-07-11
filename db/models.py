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

class RemediationOption(BaseModel):
    id: str                      # "opt_1", "opt_2", "opt_3", "hold"
    title: str
    description: str
    impact: str                  # "low" | "medium" | "high"
    docs_url: str


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


class ApprovalResponse(BaseModel):
    incident_id: str
    status: str
    selected_option_id: str
    message: str
