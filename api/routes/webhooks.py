"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 KDavis Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

"""
Webhook receivers — GitHub Actions and Azure DevOps.

Both endpoints:
1. Validate HMAC-SHA256 signature
2. Route to the correct agent based on event type
3. Return 202 Accepted immediately — agent runs async in background

Workspace identification: webhook URL includes workspace token
  POST /webhooks/github?token=<workspace_token>
  POST /webhooks/azure-devops?token=<workspace_token>
"""

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status

from core.compliance import WorkspaceComplianceGuard, SubscriptionError
from core.token_budget import BudgetExceededError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ──────────────────────────────────────────────
# Signature validation helpers
# ──────────────────────────────────────────────

def _verify_github_signature(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """
    Validate GitHub webhook HMAC-SHA256 signature.
    Ref: https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), payload_bytes, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _verify_azure_signature(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """
    Validate Azure DevOps service hook HMAC-SHA256 signature (Basic auth alternative).
    Azure DevOps uses HTTP Basic auth for service hooks — compare shared secret.
    """
    if not signature_header:
        return False
    import base64
    try:
        decoded = base64.b64decode(signature_header.split(" ")[-1]).decode()
        _, token = decoded.split(":", 1)
        return hmac.compare_digest(token, secret)
    except Exception:
        return False


# ──────────────────────────────────────────────
# Workspace lookup from query token
# ──────────────────────────────────────────────

async def _get_workspace_from_token(db_pool, token: str) -> Optional[dict]:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, stripe_subscription_status, product_tier, encrypted_llm_key, "
            "company_name FROM workspaces WHERE workspace_token = $1",
            token_hash,
        )
    return dict(row) if row else None


# ──────────────────────────────────────────────
# GitHub Actions webhook
# ──────────────────────────────────────────────

@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    token: str,
) -> dict:
    """
    Receive GitHub Actions workflow_run events.
    Triggers Agent 01 (CI/CD Triage) on failure.

    Register in GitHub repository settings:
      URL: https://your-api.cloud-decoded.com/webhooks/github?token=<workspace_token>
      Content type: application/json
      Events: Workflow runs
      Secret: <github_webhook_secret from workspace settings>
    """
    payload_bytes = await request.body()
    event = request.headers.get("X-GitHub-Event", "")
    signature = request.headers.get("X-Hub-Signature-256", "")

    db = request.app.state.db_pool
    workspace = await _get_workspace_from_token(db, token)

    if not workspace:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid workspace token")

    # Validate HMAC signature using workspace's github_webhook_secret
    # For now the secret comes from env — per-workspace secrets are Phase 4
    import os
    webhook_secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if webhook_secret and not _verify_github_signature(payload_bytes, signature, webhook_secret):
        log.warning("[Webhooks] GitHub signature validation failed for workspace %s", workspace["id"])
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    # Only process workflow_run events with conclusion=failure
    if event != "workflow_run":
        return {"status": "ignored", "reason": f"event '{event}' not handled"}

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    action = payload.get("action", "")
    conclusion = payload.get("workflow_run", {}).get("conclusion", "")

    if action != "completed" or conclusion not in ("failure", "timed_out"):
        return {
            "status": "ignored",
            "reason": f"action={action} conclusion={conclusion} — only failure/timed_out triggers triage",
        }

    log.info(
        "[Webhooks] GitHub failure received — workspace=%s run=%s",
        workspace["id"],
        payload.get("workflow_run", {}).get("id"),
    )

    # Fire agent in background — return 202 immediately
    background_tasks.add_task(
        _run_cicd_triage,
        request.app,
        workspace,
        payload,
        "github",
    )

    return {"status": "accepted", "message": "Triage initiated"}


@router.post("/azure-devops")
async def azure_devops_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    token: str,
) -> dict:
    """
    Receive Azure DevOps service hook events for failed pipeline runs.
    Triggers Agent 01 (CI/CD Triage) on failure.

    Register as a service hook in Azure DevOps:
      URL: https://your-api.cloud-decoded.com/webhooks/azure-devops?token=<workspace_token>
      Trigger: Build completed (with filter: Status = Failed)
    """
    payload_bytes = await request.body()
    auth_header = request.headers.get("Authorization", "")

    db = request.app.state.db_pool
    workspace = await _get_workspace_from_token(db, token)

    if not workspace:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid workspace token")

    import os
    webhook_secret = os.environ.get("AZURE_DEVOPS_WEBHOOK_SECRET", "")
    if webhook_secret and not _verify_azure_signature(payload_bytes, auth_header, webhook_secret):
        log.warning("[Webhooks] Azure DevOps signature validation failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    event_type = payload.get("eventType", "")
    if event_type not in ("build.complete", "ms.vss-release.release-abandoned-event"):
        return {"status": "ignored", "reason": f"event_type '{event_type}' not handled"}

    result = payload.get("resource", {}).get("result", "")
    if result not in ("failed", "partiallySucceeded"):
        return {"status": "ignored", "reason": f"result='{result}' — only failed triggers triage"}

    log.info(
        "[Webhooks] Azure DevOps failure received — workspace=%s build=%s",
        workspace["id"],
        payload.get("resource", {}).get("id"),
    )

    background_tasks.add_task(
        _run_cicd_triage,
        request.app,
        workspace,
        payload,
        "azure_devops",
    )

    return {"status": "accepted", "message": "Triage initiated"}


# ──────────────────────────────────────────────
# Background task — runs the agent
# ──────────────────────────────────────────────

async def _run_cicd_triage(app, workspace: dict, payload: dict, cloud_provider: str) -> None:
    """
    Background task: runs Agent 01 for the given webhook payload.
    Compliance and budget checks happen inside the agent workflow.
    """
    from agents.agent_01_cicd_triage.workflow import CICDTriageWorkflow

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            # Compliance check
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_01_cicd_triage", cloud_provider)

            # Run the agent
            agent = CICDTriageWorkflow(conn, workspace_id, checkpointer)
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 01 triage complete — workspace=%s incident=%s",
                workspace_id, incident_id
            )

    except SubscriptionError as exc:
        log.error("[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc)

    except BudgetExceededError as exc:
        log.error("[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc)
        # Update incident to budget_exceeded if it was created before the error
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 01 failed for workspace %s: %s", workspace_id, exc)
