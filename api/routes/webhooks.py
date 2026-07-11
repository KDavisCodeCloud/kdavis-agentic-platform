"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

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

    # Route based on event type
    if event not in ("workflow_run", "pull_request"):
        return {"status": "ignored", "reason": f"event '{event}' not handled"}

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    action = payload.get("action", "")

    # ── workflow_run failures → Agent 01 (CI/CD Triage) ──
    if event == "workflow_run":
        conclusion = payload.get("workflow_run", {}).get("conclusion", "")
        if action != "completed" or conclusion not in ("failure", "timed_out"):
            return {
                "status": "ignored",
                "reason": f"action={action} conclusion={conclusion} — only failure/timed_out triggers triage",
            }

        log.info(
            "[Webhooks] GitHub workflow failure — workspace=%s run=%s",
            workspace["id"],
            payload.get("workflow_run", {}).get("id"),
        )

        background_tasks.add_task(_run_cicd_triage, request.app, workspace, payload, "github")
        return {"status": "accepted", "message": "CI/CD triage initiated"}

    # ── pull_request opened/updated → Agent 03 (PR Review) ──
    if event == "pull_request":
        if action not in ("opened", "synchronize", "reopened"):
            return {"status": "ignored", "reason": f"PR action='{action}' — only opened/synchronize/reopened triggers review"}

        pr_number = payload.get("pull_request", {}).get("number")
        log.info(
            "[Webhooks] GitHub PR received — workspace=%s PR#%s action=%s",
            workspace["id"], pr_number, action,
        )

        background_tasks.add_task(_run_pr_review, request.app, workspace, payload, "github")
        return {"status": "accepted", "message": "PR review initiated"}

    return {"status": "ignored", "reason": "unhandled event"}


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


@router.post("/aks-alert")
async def aks_alert_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    token: str,
) -> dict:
    """
    Receive Kubernetes pod failure alerts.
    Supports two payload formats:
      - Prometheus AlertManager (v4 webhook format)
      - Azure Monitor Common Alert Schema (from AKS action groups)

    Register in Prometheus alertmanager.yml:
      receivers:
        - name: cloud-decoded
          webhook_configs:
            - url: https://your-api.cloud-decoded.com/webhooks/aks-alert?token=<ws_token>

    Or as an Azure Monitor Action Group webhook:
      URL: https://your-api.cloud-decoded.com/webhooks/aks-alert?token=<ws_token>
    """
    payload_bytes = await request.body()

    db = request.app.state.db_pool
    workspace = await _get_workspace_from_token(db, token)

    if not workspace:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid workspace token")

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    # Determine alert source and check it's a firing/active alert
    is_prometheus = "alerts" in payload
    is_azure_monitor = "data" in payload and "essentials" in payload.get("data", {})

    if is_prometheus:
        active_alerts = [a for a in payload.get("alerts", []) if a.get("status") == "firing"]
        if not active_alerts:
            return {"status": "ignored", "reason": "no firing alerts in payload"}

    elif is_azure_monitor:
        condition = payload["data"]["essentials"].get("monitorCondition", "")
        if condition != "Fired":
            return {"status": "ignored", "reason": f"monitorCondition='{condition}' — only 'Fired' triggers triage"}

    else:
        log.warning("[Webhooks] AKS alert received with unrecognized format from workspace %s", workspace["id"])
        return {"status": "ignored", "reason": "unrecognized alert payload format"}

    log.info(
        "[Webhooks] K8s alert received — workspace=%s format=%s",
        workspace["id"],
        "prometheus" if is_prometheus else "azure_monitor",
    )

    background_tasks.add_task(
        _run_k8s_alert_triage,
        request.app,
        workspace,
        payload,
        "azure" if is_azure_monitor else "azure",
    )

    return {"status": "accepted", "message": "K8s alert triage initiated"}


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


async def _run_k8s_alert_triage(app, workspace: dict, payload: dict, cloud_provider: str) -> None:
    """
    Background task: runs Agent 02 for the given K8s alert payload.
    """
    from agents.agent_02_k8s_alert.workflow import K8sAlertWorkflow

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_02_k8s_alert", cloud_provider)

            agent = K8sAlertWorkflow(conn, workspace_id, checkpointer)
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 02 triage complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error("[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc)

    except BudgetExceededError as exc:
        log.error("[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc)
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 02 failed for workspace %s: %s", workspace_id, exc)


async def _run_pr_review(app, workspace: dict, payload: dict, cloud_provider: str) -> None:
    """
    Background task: runs Agent 03 for the given GitHub pull_request payload.
    """
    from agents.agent_03_pr_review.workflow import PRReviewWorkflow

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_03_pr_review", cloud_provider)

            agent = PRReviewWorkflow(conn, workspace_id, checkpointer)
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 03 PR review complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error("[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc)

    except BudgetExceededError as exc:
        log.error("[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc)
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 03 failed for workspace %s: %s", workspace_id, exc)


async def _run_migration(app, workspace: dict, payload: dict, cloud_provider: str) -> None:
    """
    Background task: runs Agent 04 for the given migration payload.
    Agent 04 is always manually triggered — no webhook calls this directly.
    """
    from agents.agent_04_migration.workflow import MigrationWorkflow

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_04_migration", cloud_provider)

            agent = MigrationWorkflow(conn, workspace_id, checkpointer)
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 04 migration analysis complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error("[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc)

    except BudgetExceededError as exc:
        log.error("[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc)
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 04 failed for workspace %s: %s", workspace_id, exc)


async def _run_iam_minimize(app, workspace: dict, payload: dict, cloud_provider: str) -> None:
    """
    Background task: runs Agent 05 for the given IAM principal payload.
    Agent 05 is always manually triggered — no webhook calls this directly.
    """
    from agents.agent_05_iam_minimizer.workflow import IAMMinimizeWorkflow

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_05_iam_minimizer", cloud_provider)

            agent = IAMMinimizeWorkflow(conn, workspace_id, checkpointer)
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 05 IAM minimization complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error("[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc)

    except BudgetExceededError as exc:
        log.error("[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc)
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 05 failed for workspace %s: %s", workspace_id, exc)


async def _run_finops(app, workspace: dict, payload: dict, cloud_provider: str) -> None:
    """
    Background task: runs Agent 06 for the given billing data payload.
    Agent 06 is always manually triggered — no webhook calls this directly.
    """
    from agents.agent_06_finops.workflow import FinOpsWorkflow

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_06_finops", cloud_provider)

            agent = FinOpsWorkflow(conn, workspace_id, checkpointer)
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 06 FinOps analysis complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error("[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc)

    except BudgetExceededError as exc:
        log.error("[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc)
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 06 failed for workspace %s: %s", workspace_id, exc)


async def _run_runbook(app, workspace: dict, payload: dict, cloud_provider: str) -> None:
    """
    Background task: runs Agent 07 for the given runbook payload.
    Agent 07 is always manually triggered — no webhook calls this directly.
    """
    from agents.agent_07_runbook.workflow import RunbookWorkflow

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_07_runbook", cloud_provider)

            agent = RunbookWorkflow(conn, workspace_id, checkpointer)
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 07 runbook automation complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error("[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc)

    except BudgetExceededError as exc:
        log.error("[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc)
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 07 failed for workspace %s: %s", workspace_id, exc)


async def _run_drift_detection(app, workspace: dict, payload: dict, cloud_provider: str) -> None:
    """
    Background task: runs Agent 08 for the given drift detection payload.
    Agent 08 is always manually triggered or CI-scheduled — no inbound webhook calls this directly.
    """
    from agents.agent_08_drift_detection.workflow import DriftWorkflow

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_08_drift_detection", cloud_provider)

            agent = DriftWorkflow(conn, workspace_id, checkpointer)
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 08 drift detection complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error("[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc)

    except BudgetExceededError as exc:
        log.error("[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc)
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 08 failed for workspace %s: %s", workspace_id, exc)


async def _run_onboarding_buddy(app, workspace: dict, payload: dict, cloud_provider: str) -> None:
    """
    Background task: runs Agent 09 for the given onboarding or on-call question.
    Accepts both manual API triggers and alertmanager/PagerDuty webhook mappings.
    """
    from agents.agent_09_onboarding_buddy.workflow import OnboardingWorkflow

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_09_onboarding_buddy", cloud_provider)

            agent = OnboardingWorkflow(conn, workspace_id, checkpointer)
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 09 onboarding buddy complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error("[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc)

    except BudgetExceededError as exc:
        log.error("[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc)
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 09 failed for workspace %s: %s", workspace_id, exc)


async def _run_dependency_patch(app, workspace: dict, payload: dict, cloud_provider: str) -> None:
    """
    Background task: runs Agent 10 for the given dependency manifest scan.
    Supports npm, pip, go, maven, ruby, cargo ecosystems.
    """
    from agents.agent_10_dependency_patch.workflow import DependencyPatchWorkflow

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_10_dependency_patch", cloud_provider)

            agent = DependencyPatchWorkflow(conn, workspace_id, checkpointer)
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 10 dependency patch complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error("[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc)

    except BudgetExceededError as exc:
        log.error("[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc)
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 10 failed for workspace %s: %s", workspace_id, exc)
