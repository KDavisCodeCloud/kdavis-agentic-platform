"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
Agent execution endpoints — manual trigger (not webhook-driven).

POST /agents/{agent_id}/run  — manually trigger an agent with a payload
GET  /agents                 — list available agents for this workspace's tier
"""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.middleware.auth import get_workspace
from api.middleware.rate_limiter import limiter, _tier_limit
from core.compliance import WorkspaceComplianceGuard, SubscriptionError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])


class AgentRunRequest(BaseModel):
    payload: dict
    cloud_provider: Optional[str] = "github"


class AgentRunResponse(BaseModel):
    incident_id: str
    agent_id: str
    status: str
    message: str


@router.post("/{agent_id}/run", response_model=AgentRunResponse)
@limiter.limit(_tier_limit)
async def run_agent(
    agent_id: str,
    body: AgentRunRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    workspace: dict = Depends(get_workspace),
) -> AgentRunResponse:
    """
    Manually trigger an agent with a custom payload.
    Returns incident_id immediately; poll GET /incidents/{id} for status.
    """
    workspace_id = str(workspace["id"])

    # Validate agent_id format
    valid_agents = {
        f"agent_{str(i).zfill(2)}_"
        for i in range(1, 11)
    }
    if not any(agent_id.startswith(p) for p in valid_agents):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown agent '{agent_id}'",
        )

    # Compliance check
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        compliance = WorkspaceComplianceGuard(conn)
        try:
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(
                workspace_id, agent_id, body.cloud_provider
            )
        except SubscriptionError as exc:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)
            )

    # Route to correct agent
    if agent_id == "agent_01_cicd_triage":
        from api.routes.webhooks import _run_cicd_triage
        background_tasks.add_task(
            _run_cicd_triage,
            request.app,
            workspace,
            body.payload,
            body.cloud_provider,
        )
        return AgentRunResponse(
            incident_id="pending",
            agent_id=agent_id,
            status="accepted",
            message="Triage started. Poll GET /incidents?status=pending_approval for result.",
        )

    if agent_id == "agent_02_k8s_alert":
        from api.routes.webhooks import _run_k8s_alert_triage
        background_tasks.add_task(
            _run_k8s_alert_triage,
            request.app,
            workspace,
            body.payload,
            body.cloud_provider,
        )
        return AgentRunResponse(
            incident_id="pending",
            agent_id=agent_id,
            status="accepted",
            message="K8s triage started. Poll GET /incidents?status=pending_approval for result.",
        )

    if agent_id == "agent_03_pr_review":
        from api.routes.webhooks import _run_pr_review
        background_tasks.add_task(
            _run_pr_review,
            request.app,
            workspace,
            body.payload,
            body.cloud_provider,
        )
        return AgentRunResponse(
            incident_id="pending",
            agent_id=agent_id,
            status="accepted",
            message="PR review started. Poll GET /incidents?status=pending_approval for result.",
        )

    if agent_id == "agent_04_migration":
        from api.routes.webhooks import _run_migration
        background_tasks.add_task(
            _run_migration,
            request.app,
            workspace,
            body.payload,
            body.cloud_provider,
        )
        return AgentRunResponse(
            incident_id="pending",
            agent_id=agent_id,
            status="accepted",
            message="Migration analysis started. Poll GET /incidents?status=pending_approval for result.",
        )

    if agent_id == "agent_05_iam_minimizer":
        from api.routes.webhooks import _run_iam_minimize
        background_tasks.add_task(
            _run_iam_minimize,
            request.app,
            workspace,
            body.payload,
            body.cloud_provider,
        )
        return AgentRunResponse(
            incident_id="pending",
            agent_id=agent_id,
            status="accepted",
            message="IAM minimization started. Poll GET /incidents?status=pending_approval for result.",
        )

    if agent_id == "agent_06_finops":
        from api.routes.webhooks import _run_finops
        background_tasks.add_task(
            _run_finops,
            request.app,
            workspace,
            body.payload,
            body.cloud_provider,
        )
        return AgentRunResponse(
            incident_id="pending",
            agent_id=agent_id,
            status="accepted",
            message="FinOps analysis started. Poll GET /incidents?status=pending_approval for result.",
        )

    if agent_id == "agent_07_runbook":
        from api.routes.webhooks import _run_runbook
        background_tasks.add_task(
            _run_runbook,
            request.app,
            workspace,
            body.payload,
            body.cloud_provider,
        )
        return AgentRunResponse(
            incident_id="pending",
            agent_id=agent_id,
            status="accepted",
            message="Runbook automation started. Poll GET /incidents?status=pending_approval for result.",
        )

    if agent_id == "agent_08_drift_detection":
        from api.routes.webhooks import _run_drift_detection
        background_tasks.add_task(
            _run_drift_detection,
            request.app,
            workspace,
            body.payload,
            body.cloud_provider,
        )
        return AgentRunResponse(
            incident_id="pending",
            agent_id=agent_id,
            status="accepted",
            message="Drift detection started. Poll GET /incidents?status=pending_approval for result.",
        )

    if agent_id == "agent_09_onboarding_buddy":
        from api.routes.webhooks import _run_onboarding_buddy
        background_tasks.add_task(
            _run_onboarding_buddy,
            request.app,
            workspace,
            body.payload,
            body.cloud_provider,
        )
        return AgentRunResponse(
            incident_id="pending",
            agent_id=agent_id,
            status="accepted",
            message="Knowledge brief started. Poll GET /incidents?status=pending_approval for result.",
        )

    if agent_id == "agent_10_dependency_patch":
        from api.routes.webhooks import _run_dependency_patch
        background_tasks.add_task(
            _run_dependency_patch,
            request.app,
            workspace,
            body.payload,
            body.cloud_provider,
        )
        return AgentRunResponse(
            incident_id="pending",
            agent_id=agent_id,
            status="accepted",
            message="Dependency scan started. Poll GET /incidents?status=pending_approval for result.",
        )

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Agent '{agent_id}' is not yet available. Phase 5 build coming soon.",
    )


@router.get("")
@limiter.limit(_tier_limit)
async def list_agents(
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> dict:
    """List agents available to this workspace based on product tier."""
    tier = workspace.get("product_tier", "starter")
    tier_limits = {
        "starter":    3,
        "growth":     10,
        "enterprise": 10,
    }
    max_agents = tier_limits.get(tier, 3)

    all_agents = [
        {"id": "agent_01_cicd_triage",     "name": "CI/CD Pipeline Failure Triage",           "status": "available"},
        {"id": "agent_02_k8s_alert",       "name": "Kubernetes Alert Fatigue & Remediation",   "status": "available"},
        {"id": "agent_03_pr_review",       "name": "PR Review for Architecture & Security",    "status": "available"},
        {"id": "agent_04_migration",       "name": "Legacy Code & Infrastructure Migration",   "status": "available"},
        {"id": "agent_05_iam_minimizer",   "name": "IAM Policy Minimization",                  "status": "available"},
        {"id": "agent_06_finops",          "name": "FinOps Cost Optimization",                 "status": "available"},
        {"id": "agent_07_runbook",         "name": "Interactive Runbook Automation",           "status": "available"},
        {"id": "agent_08_drift_detection", "name": "Drift Detection & Auto-Correction",        "status": "available"},
        {"id": "agent_09_onboarding_buddy","name": "Context-Aware Onboarding & On-Call Buddy", "status": "available"},
        {"id": "agent_10_dependency_patch","name": "Dependency & Vulnerability Patching",      "status": "available"},
    ]

    return {
        "tier": tier,
        "available_agents": all_agents[:max_agents],
        "locked_agents": all_agents[max_agents:],
        "upgrade_url": "https://cloud-decoded.com/pricing",
    }
