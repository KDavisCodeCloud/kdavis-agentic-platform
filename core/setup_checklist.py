"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

24-gap-closure build, Phase 6 -- the real 5-item setup completeness
signal computation, shared by api/routes/setup_checklist.py (the
customer-facing GET) and core/onboarding_sequence.py's day-2/day-5 email
gating (previously re-derived the same "connected anything" / "verified
alert source" signals from raw columns as a documented stand-in for this
exact field, per that module's own docstring -- this closes that
follow-up).

Takes a raw asyncpg connection + a workspace-shaped dict rather than a
FastAPI Request, so core/onboarding_sequence.py's periodic background
loop (which only ever has a bare pool connection, never a Request) can
call it directly without api/routes/* leaking into core/*.
"""

from typing import TypedDict


class SetupChecklist(TypedDict):
    cloud_connected: bool
    repo_connected: bool
    alert_source_verified: bool
    notification_channel_set: bool
    end_to_end_test_passed: bool
    completed_count: int


async def compute_setup_checklist(conn, workspace: dict) -> SetupChecklist:
    cloud_connected = bool(
        workspace.get("aws_role_verified_at")
        or workspace.get("azure_verified_at")
        or workspace.get("k8s_verified_at")
    )
    repo_connected = bool(
        workspace.get("github_app_installation_id")
        or workspace.get("github_pat_verified_at")
        or workspace.get("azure_devops_pat_verified_at")
    )

    alert_row = await conn.fetchrow(
        "SELECT 1 FROM alert_ingestion_log WHERE workspace_id = $1 LIMIT 1", workspace["id"],
    )
    channel_row = await conn.fetchrow(
        "SELECT 1 FROM workspace_notification_channels WHERE workspace_id = $1 AND enabled = true LIMIT 1",
        workspace["id"],
    )

    alert_source_verified = alert_row is not None
    notification_channel_set = channel_row is not None
    end_to_end_test_passed = bool(workspace.get("setup_test_passed_at"))

    return SetupChecklist(
        cloud_connected=cloud_connected,
        repo_connected=repo_connected,
        alert_source_verified=alert_source_verified,
        notification_channel_set=notification_channel_set,
        end_to_end_test_passed=end_to_end_test_passed,
        completed_count=sum((
            cloud_connected, repo_connected, alert_source_verified,
            notification_channel_set, end_to_end_test_passed,
        )),
    )
