"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Webhook receivers — GitHub Actions and Azure DevOps.

Both endpoints:
1. Validate HMAC-SHA256 signature
2. Route to the correct agent based on event type
3. Return 202 Accepted immediately — agent runs async in background

Workspace identification: webhook URL includes workspace token

NOTE: this router is mounted with prefix="/api/v1" in api/main.py --
every path below must be read as /api/v1/webhooks/... in production.
Confirmed live 2026-09-15 after a real Azure Action Group test hit the
un-prefixed path and got a 404: /webhooks/... 404s, /api/v1/webhooks/...
reaches auth (403 on a bad token). OnboardingWizard.tsx already builds
the correct /api/v1-prefixed URL for GitHub/Azure DevOps -- this was a
docstring-only bug, not a customer-facing one, but it bit a manual setup
so every URL below is now written with the real prefix.
  POST /api/v1/webhooks/github?token=<workspace_token>
  POST /api/v1/webhooks/azure-devops?token=<workspace_token>
"""

import hashlib
import hmac
import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status

from api.middleware.rate_limiter import limiter, _webhook_tier_limit
from core.compliance import WorkspaceComplianceGuard, SubscriptionError
from core.error_tracking import capture_exception
from core.execution_semaphore import bounded_execution
from core.ingestion_log import log_alert_received, mark_alert_processed
from core.token_budget import BudgetExceededError
from security.encryption import decrypt

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _firing_alertmanager_alerts(payload: dict) -> list:
    """
    Entries from an Alertmanager-shaped payload's "alerts" array with
    status == "firing" — the same webhook shape Prometheus Alertmanager
    and Grafana's unified alerting webhook notifier both send (Grafana
    deliberately mirrors Alertmanager's webhook_config schema for
    compatibility; verified against both projects' own docs, 2026-09-14).
    Shared by aks_alert_webhook and resource_health_alert_webhook so this
    filter isn't copy-pasted a third time.
    """
    return [a for a in payload.get("alerts", []) if a.get("status") == "firing"]


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
            "SELECT id, stripe_subscription_status, product_tier, encrypted_llm_key, llm_provider, "
            "company_name, encrypted_github_webhook_secret, encrypted_azure_devops_webhook_secret "
            "FROM workspaces WHERE workspace_token = $1",
            token_hash,
        )
    return dict(row) if row else None


# ──────────────────────────────────────────────
# GitHub Actions webhook
# ──────────────────────────────────────────────

@router.post("/github")
@limiter.limit(_webhook_tier_limit)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    token: str,
) -> dict:
    """
    Receive GitHub Actions workflow_run events.
    Triggers Agent 01 (CI/CD Triage) on failure.

    Register in GitHub repository settings:
      URL: https://your-api.cloud-decoded.com/api/v1/webhooks/github?token=<workspace_token>
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

    # Validate HMAC signature using this workspace's own webhook secret
    # (minted by PATCH /workspace/credentials/github, core/workspace_credentials.py).
    # Fail closed: a workspace with no secret configured yet must reject
    # webhooks, not silently skip validation -- found live, a global env var
    # fallback meant an unset GITHUB_WEBHOOK_SECRET let ANY caller who knew a
    # workspace's token forge webhook events for it.
    encrypted_secret = workspace.get("encrypted_github_webhook_secret")
    if not encrypted_secret:
        log.warning("[Webhooks] No GitHub webhook secret configured for workspace %s", workspace["id"])
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Webhook not configured for this workspace")
    webhook_secret = decrypt(encrypted_secret)
    if not _verify_github_signature(payload_bytes, signature, webhook_secret):
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

        async with db.acquire() as conn:
            log_id = await log_alert_received(conn, workspace["id"], payload)
        background_tasks.add_task(_run_cicd_triage, request.app, workspace, payload, "github", ingestion_log_id=log_id)
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

        async with db.acquire() as conn:
            log_id = await log_alert_received(conn, workspace["id"], payload)
        background_tasks.add_task(_run_pr_review, request.app, workspace, payload, "github", ingestion_log_id=log_id)
        return {"status": "accepted", "message": "PR review initiated"}

    return {"status": "ignored", "reason": "unhandled event"}


@router.post("/azure-devops")
@limiter.limit(_webhook_tier_limit)
async def azure_devops_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    token: str,
) -> dict:
    """
    Receive Azure DevOps service hook events for failed pipeline runs.
    Triggers Agent 01 (CI/CD Triage) on failure.

    Register as a service hook in Azure DevOps:
      URL: https://your-api.cloud-decoded.com/api/v1/webhooks/azure-devops?token=<workspace_token>
      Trigger: Build completed (with filter: Status = Failed)
    """
    payload_bytes = await request.body()
    auth_header = request.headers.get("Authorization", "")

    db = request.app.state.db_pool
    workspace = await _get_workspace_from_token(db, token)

    if not workspace:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid workspace token")

    # Per-workspace secret (migration 024 + PATCH /workspace/credentials/azure-devops),
    # same fail-closed discipline as the GitHub path above: a workspace with
    # no secret configured yet must reject webhooks, not silently skip
    # validation. This used to validate against one global env var and skip
    # entirely if it was unset -- the exact gap GitHub's webhook had before
    # it was hardened.
    encrypted_secret = workspace.get("encrypted_azure_devops_webhook_secret")
    if not encrypted_secret:
        log.warning("[Webhooks] No Azure DevOps webhook secret configured for workspace %s", workspace["id"])
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Webhook not configured for this workspace")
    webhook_secret = decrypt(encrypted_secret)
    if not _verify_azure_signature(payload_bytes, auth_header, webhook_secret):
        log.warning("[Webhooks] Azure DevOps signature validation failed for workspace %s", workspace["id"])
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

    async with db.acquire() as conn:
        log_id = await log_alert_received(conn, workspace["id"], payload)

    background_tasks.add_task(
        _run_cicd_triage,
        request.app,
        workspace,
        payload,
        "azure_devops",
        ingestion_log_id=log_id,
    )

    return {"status": "accepted", "message": "Triage initiated"}


@router.post("/github-app")
async def github_app_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    """
    Receives events for EVERY installation of the one Cloud Decoded GitHub
    App (item 4 migration) -- unlike /github's per-workspace query-string
    token, there is exactly one URL, signed with the App's own single
    webhook secret (github_app_config, migration 023). The payload's
    `installation.id` is how a workspace is identified instead.

    This is additive, not a replacement: /github (per-workspace token +
    per-workspace secret) keeps working for any workspace that connected
    via PAT before the App existed. New connections go through the App.
    """
    payload_bytes = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    event = request.headers.get("X-GitHub-Event", "")

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        app_row = await conn.fetchrow(
            "SELECT webhook_secret_encrypted FROM github_app_config WHERE id = 'singleton'"
        )
    if not app_row:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="GitHub App not registered")

    webhook_secret = decrypt(app_row["webhook_secret_encrypted"])
    if not _verify_github_signature(payload_bytes, signature, webhook_secret):
        log.warning("[Webhooks] GitHub App signature validation failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    installation_id = str(payload.get("installation", {}).get("id", ""))
    if not installation_id:
        return {"status": "ignored", "reason": "no installation.id in payload"}

    async with db.acquire() as conn:
        workspace = await conn.fetchrow(
            "SELECT id, stripe_subscription_status, product_tier, encrypted_llm_key, llm_provider, "
            "company_name, encrypted_github_webhook_secret FROM workspaces "
            "WHERE github_app_installation_id = $1",
            installation_id,
        )
    if not workspace:
        log.warning("[Webhooks] GitHub App event for unknown installation_id=%s", installation_id)
        return {"status": "ignored", "reason": "installation not linked to any workspace"}
    workspace = dict(workspace)

    action = payload.get("action", "")

    if event == "workflow_run":
        conclusion = payload.get("workflow_run", {}).get("conclusion", "")
        if action != "completed" or conclusion not in ("failure", "timed_out"):
            return {
                "status": "ignored",
                "reason": f"action={action} conclusion={conclusion} — only failure/timed_out triggers triage",
            }
        background_tasks.add_task(_run_cicd_triage, request.app, workspace, payload, "github")
        return {"status": "accepted", "message": "CI/CD triage initiated"}

    if event == "pull_request":
        if action not in ("opened", "synchronize", "reopened"):
            return {"status": "ignored", "reason": f"PR action='{action}' — only opened/synchronize/reopened triggers review"}
        background_tasks.add_task(_run_pr_review, request.app, workspace, payload, "github")
        return {"status": "accepted", "message": "PR review initiated"}

    return {"status": "ignored", "reason": f"event '{event}' not handled"}


@router.post("/aks-alert")
@limiter.limit(_webhook_tier_limit)
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
            - url: https://your-api.cloud-decoded.com/api/v1/webhooks/aks-alert?token=<ws_token>

    Or as an Azure Monitor Action Group webhook:
      URL: https://your-api.cloud-decoded.com/api/v1/webhooks/aks-alert?token=<ws_token>
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
        active_alerts = _firing_alertmanager_alerts(payload)
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

    async with db.acquire() as conn:
        log_id = await log_alert_received(conn, workspace["id"], payload)

    background_tasks.add_task(
        _run_k8s_alert_triage,
        request.app,
        workspace,
        payload,
        # Prometheus AlertManager can be watching any cluster (EKS included) --
        # only the Azure Monitor Common Alert Schema format is actually AKS-specific.
        "azure" if is_azure_monitor else "aws",
        ingestion_log_id=log_id,
    )

    return {"status": "accepted", "message": "K8s alert triage initiated"}


@router.post("/resource-health-alert")
@limiter.limit(_webhook_tier_limit)
async def resource_health_alert_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    token: str,
) -> dict:
    """
    Receive general cloud-resource health/security alerts for Agent 11
    (any resource, not just AKS pods -- see aks_alert_webhook above for
    the Kubernetes-specific equivalent). Supports four payload formats:
      - Azure Monitor Common Alert Schema (register as an Action Group
        webhook action, same URL shape as aks_alert_webhook)
      - AWS SNS (subscribe this URL to an SNS topic fed by CloudWatch
        Alarms) -- both SubscriptionConfirmation and Notification message
        types are handled; core.aws_sns verifies every Notification's
        signature before it's trusted, and confirms a
        SubscriptionConfirmation's SubscribeURL once
      - Prometheus Alertmanager (v4 webhook format) -- same detection as
        aks_alert_webhook
      - Grafana unified alerting (webhook contact point) -- payload shape
        deliberately mirrors Alertmanager's ("alerts" array, same
        per-alert "status" field), distinguished only by a Grafana-only
        top-level "orgId" field (verified against both projects' current
        docs, 2026-09-14; Prometheus's own webhook_config payload has no
        orgId)

    Register as an Azure Monitor Action Group webhook action, subscribe
    this URL to an AWS SNS topic, or use it as a Prometheus Alertmanager /
    Grafana webhook receiver:
      URL: https://your-api.cloud-decoded.com/api/v1/webhooks/resource-health-alert?token=<ws_token>
    """
    from core.aws_sns import confirm_subscription, verify_signature

    payload_bytes = await request.body()

    db = request.app.state.db_pool
    workspace = await _get_workspace_from_token(db, token)

    if not workspace:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid workspace token")

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    is_azure_monitor = "data" in payload and "essentials" in payload.get("data", {})
    is_sns = payload.get("Type") in ("SubscriptionConfirmation", "Notification", "UnsubscribeConfirmation")
    # Grafana's unified alerting webhook notifier deliberately mirrors
    # Alertmanager's payload shape (both send a top-level "alerts" array
    # with the same per-alert "status" field) -- "orgId" is the one
    # Grafana-only top-level field that reliably tells them apart, so it
    # must be checked first.
    is_grafana = "alerts" in payload and "orgId" in payload
    is_prometheus = "alerts" in payload and not is_grafana

    if is_grafana or is_prometheus:
        active_alerts = _firing_alertmanager_alerts(payload)
        if not active_alerts:
            return {"status": "ignored", "reason": "no firing alerts in payload"}

        alert_format = "grafana" if is_grafana else "prometheus"
        log.info("[Webhooks] Resource health alert received — workspace=%s format=%s", workspace["id"], alert_format)
        async with db.acquire() as conn:
            log_id = await log_alert_received(conn, workspace["id"], payload)
        background_tasks.add_task(
            # Prometheus/Grafana can be watching any cloud's resources --
            # unlike the Azure Monitor/SNS branches, this payload shape
            # carries no cloud-provider signal of its own, so "aws" is an
            # arbitrary default, same call aks_alert_webhook already makes
            # for its own Prometheus branch above.
            _run_resource_health_alert, request.app, workspace, payload, "aws", ingestion_log_id=log_id,
        )
        return {"status": "accepted", "message": "Resource health triage initiated"}

    if is_azure_monitor:
        condition = payload["data"]["essentials"].get("monitorCondition", "")
        if condition != "Fired":
            return {"status": "ignored", "reason": f"monitorCondition='{condition}' — only 'Fired' triggers triage"}

        log.info("[Webhooks] Resource health alert received — workspace=%s format=azure_monitor", workspace["id"])
        async with db.acquire() as conn:
            log_id = await log_alert_received(conn, workspace["id"], payload)
        background_tasks.add_task(
            _run_resource_health_alert, request.app, workspace, payload, "azure", ingestion_log_id=log_id,
        )
        return {"status": "accepted", "message": "Resource health triage initiated"}

    if is_sns:
        if not await verify_signature(payload):
            log.warning("[Webhooks] SNS message signature verification failed — workspace=%s", workspace["id"])
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid SNS signature")

        if payload["Type"] == "SubscriptionConfirmation":
            confirmed = await confirm_subscription(payload.get("SubscribeURL", ""))
            return {"status": "subscription_confirmed" if confirmed else "subscription_confirm_failed"}

        if payload["Type"] == "UnsubscribeConfirmation":
            return {"status": "acknowledged"}

        # Notification -- the actual CloudWatch Alarm JSON is inside "Message"
        try:
            alarm = json.loads(payload.get("Message", "{}"))
        except json.JSONDecodeError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SNS Message was not valid JSON")

        if alarm.get("NewStateValue") != "ALARM":
            return {"status": "ignored", "reason": f"NewStateValue='{alarm.get('NewStateValue')}' — only 'ALARM' triggers triage"}

        log.info("[Webhooks] Resource health alert received — workspace=%s format=aws_cloudwatch", workspace["id"])
        async with db.acquire() as conn:
            log_id = await log_alert_received(conn, workspace["id"], {"cloudwatch_alarm": alarm})
        background_tasks.add_task(
            _run_resource_health_alert, request.app, workspace, {"cloudwatch_alarm": alarm}, "aws",
            ingestion_log_id=log_id,
        )
        return {"status": "accepted", "message": "Resource health triage initiated"}

    log.warning("[Webhooks] Resource health alert received with unrecognized format from workspace %s", workspace["id"])
    return {"status": "ignored", "reason": "unrecognized alert payload format"}


# ──────────────────────────────────────────────
# Background task — runs the agent
# ──────────────────────────────────────────────

@bounded_execution("agent_01_cicd_triage")
async def _run_cicd_triage(
    app, workspace: dict, payload: dict, cloud_provider: str, ingestion_log_id: Optional[str] = None,
) -> None:
    """
    Background task: runs Agent 01 for the given webhook payload.
    Compliance and budget checks happen inside the agent workflow.
    """
    from agents.agent_01_cicd_triage.workflow import CICDTriageWorkflow
    from core.workspace_credentials import build_agent_credentials

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            # Compliance check
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_01_cicd_triage", cloud_provider)

            # Run the agent
            creds = await build_agent_credentials(conn, workspace_id)
            agent = CICDTriageWorkflow(
                conn, workspace_id, checkpointer, **creds,
                llm_provider=workspace.get("llm_provider"), byok_encrypted_key=workspace.get("encrypted_llm_key"),
            )
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 01 triage complete — workspace=%s incident=%s",
                workspace_id, incident_id
            )

    except SubscriptionError as exc:
        log.error(
            "[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "block_reason": str(exc)},
        )

    except BudgetExceededError as exc:
        log.error(
            "[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "budget_error": str(exc)},
        )
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
        capture_exception(exc, workspace_id=workspace_id, agent_id="agent_01_cicd_triage")

    finally:
        # Runs whether the run above succeeded, hit a handled error, or
        # raised -- "processed" means the system took delivery to
        # completion, not "succeeded". Only a genuine process death
        # mid-execution skips this, which is exactly the recoverable
        # case core.ingestion_log.find_unprocessed_older_than() surfaces.
        if ingestion_log_id:
            async with app.state.db_pool.acquire() as conn:
                await mark_alert_processed(conn, ingestion_log_id)


@bounded_execution("agent_02_k8s_alert")
async def _run_k8s_alert_triage(
    app, workspace: dict, payload: dict, cloud_provider: str, ingestion_log_id: Optional[str] = None,
) -> None:
    """
    Background task: runs Agent 02 for the given K8s alert payload.
    """
    from agents.agent_02_k8s_alert.workflow import K8sAlertWorkflow
    from core.workspace_credentials import build_agent_credentials, build_k8s_credentials

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_02_k8s_alert", cloud_provider)

            creds = await build_agent_credentials(conn, workspace_id)
            k8s_creds = await build_k8s_credentials(conn, workspace_id)
            agent = K8sAlertWorkflow(
                conn, workspace_id, checkpointer, **creds, **k8s_creds,
                llm_provider=workspace.get("llm_provider"), byok_encrypted_key=workspace.get("encrypted_llm_key"),
            )
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 02 triage complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error(
            "[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "block_reason": str(exc)},
        )

    except BudgetExceededError as exc:
        log.error(
            "[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "budget_error": str(exc)},
        )
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 02 failed for workspace %s: %s", workspace_id, exc)
        capture_exception(exc, workspace_id=workspace_id, agent_id="agent_02_k8s_alert")

    finally:
        if ingestion_log_id:
            async with app.state.db_pool.acquire() as conn:
                await mark_alert_processed(conn, ingestion_log_id)


@bounded_execution("agent_11_resource_health")
async def _run_resource_health_alert(
    app, workspace: dict, payload: dict, cloud_provider: str, ingestion_log_id: Optional[str] = None,
) -> None:
    """
    Background task: runs Agent 11 for the given resource-health alert.
    """
    from agents.agent_11_resource_health.workflow import ResourceHealthWorkflow
    from core.workspace_credentials import build_agent_credentials

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_11_resource_health", cloud_provider)

            creds = await build_agent_credentials(conn, workspace_id)
            agent = ResourceHealthWorkflow(
                conn, workspace_id, checkpointer, **creds,
                llm_provider=workspace.get("llm_provider"), byok_encrypted_key=workspace.get("encrypted_llm_key"),
            )
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 11 triage complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error(
            "[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "block_reason": str(exc)},
        )

    except BudgetExceededError as exc:
        log.error(
            "[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "budget_error": str(exc)},
        )
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 11 failed for workspace %s: %s", workspace_id, exc)
        capture_exception(exc, workspace_id=workspace_id, agent_id="agent_11_resource_health")

    finally:
        if ingestion_log_id:
            async with app.state.db_pool.acquire() as conn:
                await mark_alert_processed(conn, ingestion_log_id)


@bounded_execution("agent_03_pr_review")
async def _run_pr_review(
    app, workspace: dict, payload: dict, cloud_provider: str, ingestion_log_id: Optional[str] = None,
) -> None:
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

            agent = PRReviewWorkflow(
                conn, workspace_id, checkpointer,
                llm_provider=workspace.get("llm_provider"), byok_encrypted_key=workspace.get("encrypted_llm_key"),
            )
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 03 PR review complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error(
            "[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "block_reason": str(exc)},
        )

    except BudgetExceededError as exc:
        log.error(
            "[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "budget_error": str(exc)},
        )
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 03 failed for workspace %s: %s", workspace_id, exc)
        capture_exception(exc, workspace_id=workspace_id, agent_id="agent_03_pr_review")

    finally:
        if ingestion_log_id:
            async with app.state.db_pool.acquire() as conn:
                await mark_alert_processed(conn, ingestion_log_id)


@bounded_execution("agent_04_migration")
async def _run_migration(app, workspace: dict, payload: dict, cloud_provider: str) -> None:
    """
    Background task: runs Agent 04 for the given migration payload.
    Agent 04 is always manually triggered — no webhook calls this directly.
    """
    from agents.agent_04_migration.workflow import MigrationWorkflow
    from core.workspace_credentials import build_agent_credentials

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_04_migration", cloud_provider)

            creds = await build_agent_credentials(conn, workspace_id)
            agent = MigrationWorkflow(
                conn, workspace_id, checkpointer, **creds,
                llm_provider=workspace.get("llm_provider"), byok_encrypted_key=workspace.get("encrypted_llm_key"),
            )
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 04 migration analysis complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error(
            "[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "block_reason": str(exc)},
        )

    except BudgetExceededError as exc:
        log.error(
            "[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "budget_error": str(exc)},
        )
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 04 failed for workspace %s: %s", workspace_id, exc)
        capture_exception(exc, workspace_id=workspace_id, agent_id="agent_04_migration")


@bounded_execution("agent_05_iam_minimizer")
async def _run_iam_minimize(app, workspace: dict, payload: dict, cloud_provider: str) -> None:
    """
    Background task: runs Agent 05 for the given IAM principal payload.
    Agent 05 is always manually triggered — no webhook calls this directly.
    """
    from agents.agent_05_iam_minimizer.workflow import IAMMinimizeWorkflow
    from core.workspace_credentials import build_agent_credentials

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_05_iam_minimizer", cloud_provider)

            creds = await build_agent_credentials(conn, workspace_id)
            agent = IAMMinimizeWorkflow(
                conn, workspace_id, checkpointer, **creds,
                llm_provider=workspace.get("llm_provider"), byok_encrypted_key=workspace.get("encrypted_llm_key"),
            )
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 05 IAM minimization complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error(
            "[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "block_reason": str(exc)},
        )

    except BudgetExceededError as exc:
        log.error(
            "[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "budget_error": str(exc)},
        )
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 05 failed for workspace %s: %s", workspace_id, exc)
        capture_exception(exc, workspace_id=workspace_id, agent_id="agent_05_iam_minimizer")


@bounded_execution("agent_06_finops")
async def _run_finops(app, workspace: dict, payload: dict, cloud_provider: str) -> None:
    """
    Background task: runs Agent 06 for the given billing data payload.
    Agent 06 is always manually triggered — no webhook calls this directly.
    """
    from agents.agent_06_finops.workflow import FinOpsWorkflow
    from core.workspace_credentials import build_agent_credentials

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_06_finops", cloud_provider)

            creds = await build_agent_credentials(conn, workspace_id)
            agent = FinOpsWorkflow(
                conn, workspace_id, checkpointer, **creds,
                llm_provider=workspace.get("llm_provider"), byok_encrypted_key=workspace.get("encrypted_llm_key"),
            )
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 06 FinOps analysis complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error(
            "[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "block_reason": str(exc)},
        )

    except BudgetExceededError as exc:
        log.error(
            "[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "budget_error": str(exc)},
        )
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 06 failed for workspace %s: %s", workspace_id, exc)
        capture_exception(exc, workspace_id=workspace_id, agent_id="agent_06_finops")


@bounded_execution("agent_07_runbook")
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

            agent = RunbookWorkflow(
                conn, workspace_id, checkpointer,
                llm_provider=workspace.get("llm_provider"), byok_encrypted_key=workspace.get("encrypted_llm_key"),
            )
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 07 runbook automation complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error(
            "[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "block_reason": str(exc)},
        )

    except BudgetExceededError as exc:
        log.error(
            "[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "budget_error": str(exc)},
        )
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 07 failed for workspace %s: %s", workspace_id, exc)
        capture_exception(exc, workspace_id=workspace_id, agent_id="agent_07_runbook")


@bounded_execution("agent_08_drift_detection")
async def _run_drift_detection(app, workspace: dict, payload: dict, cloud_provider: str) -> None:
    """
    Background task: runs Agent 08 for the given drift detection payload.
    Agent 08 is always manually triggered or CI-scheduled — no inbound webhook calls this directly.
    """
    from agents.agent_08_drift_detection.workflow import DriftWorkflow
    from core.workspace_credentials import build_agent_credentials, build_k8s_credentials, resolve_k8s_context

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_08_drift_detection", cloud_provider)

            creds = await build_agent_credentials(conn, workspace_id)
            k8s_creds = await build_k8s_credentials(conn, workspace_id)
            # Real per-workspace cluster credentials (k8s_creds) take
            # priority inside DriftTools itself when present; k8s_context
            # stays the fallback for a workspace that hasn't connected its
            # own cluster yet (resolve_k8s_context's global KUBECONFIG_YAML
            # stopgap).
            k8s_context = resolve_k8s_context(cloud_provider)
            agent = DriftWorkflow(
                conn, workspace_id, checkpointer, **creds, **k8s_creds, k8s_context=k8s_context,
                llm_provider=workspace.get("llm_provider"), byok_encrypted_key=workspace.get("encrypted_llm_key"),
            )
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 08 drift detection complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error(
            "[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "block_reason": str(exc)},
        )

    except BudgetExceededError as exc:
        log.error(
            "[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "budget_error": str(exc)},
        )
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 08 failed for workspace %s: %s", workspace_id, exc)
        capture_exception(exc, workspace_id=workspace_id, agent_id="agent_08_drift_detection")


@bounded_execution("agent_09_onboarding_buddy")
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

            agent = OnboardingWorkflow(
                conn, workspace_id, checkpointer,
                llm_provider=workspace.get("llm_provider"), byok_encrypted_key=workspace.get("encrypted_llm_key"),
            )
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 09 onboarding buddy complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error(
            "[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "block_reason": str(exc)},
        )

    except BudgetExceededError as exc:
        log.error(
            "[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "budget_error": str(exc)},
        )
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 09 failed for workspace %s: %s", workspace_id, exc)
        capture_exception(exc, workspace_id=workspace_id, agent_id="agent_09_onboarding_buddy")


@bounded_execution("agent_10_dependency_patch")
async def _run_dependency_patch(app, workspace: dict, payload: dict, cloud_provider: str) -> None:
    """
    Background task: runs Agent 10 for the given dependency manifest scan.
    Supports npm, pip, go, maven, ruby, cargo ecosystems.
    """
    from agents.agent_10_dependency_patch.workflow import DependencyPatchWorkflow
    from core.workspace_credentials import build_agent_credentials

    workspace_id = str(workspace["id"])
    checkpointer = app.state.checkpointer

    try:
        async with app.state.db_pool.acquire() as conn:
            compliance = WorkspaceComplianceGuard(conn)
            await compliance.assert_workspace_active(workspace_id)
            await compliance.assert_agent_permitted(workspace_id, "agent_10_dependency_patch", cloud_provider)

            creds = await build_agent_credentials(conn, workspace_id)
            agent = DependencyPatchWorkflow(
                conn, workspace_id, checkpointer, **creds,
                llm_provider=workspace.get("llm_provider"), byok_encrypted_key=workspace.get("encrypted_llm_key"),
            )
            incident_id = await agent.run(payload, cloud_provider=cloud_provider)
            log.info(
                "[Webhooks] Agent 10 dependency patch complete — workspace=%s incident=%s",
                workspace_id, incident_id,
            )

    except SubscriptionError as exc:
        log.error(
            "[Webhooks] Subscription blocked for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "block_reason": str(exc)},
        )

    except BudgetExceededError as exc:
        log.error(
            "[Webhooks] Budget exceeded for workspace %s: %s", workspace_id, exc,
            extra={"workspace_id": workspace_id, "budget_error": str(exc)},
        )
        async with app.state.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE incidents SET execution_status = 'budget_exceeded' "
                "WHERE workspace_id = $1 AND execution_status = 'pending_approval' "
                "ORDER BY created_at DESC LIMIT 1",
                __import__("uuid").UUID(workspace_id),
            )

    except Exception as exc:
        log.exception("[Webhooks] Agent 10 failed for workspace %s: %s", workspace_id, exc)
        capture_exception(exc, workspace_id=workspace_id, agent_id="agent_10_dependency_patch")
