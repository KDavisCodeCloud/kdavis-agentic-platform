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

from datetime import datetime
from typing import Optional, TypedDict


class SetupChecklist(TypedDict):
    cloud_connected: bool
    repo_connected: bool
    alert_source_verified: bool
    notification_channel_set: bool
    end_to_end_test_passed: bool
    completed_count: int


class SetupChecklistItemDetail(TypedDict):
    done: bool
    completed_at: Optional[datetime]


class SetupChecklistDetail(TypedDict):
    cloud_connected: SetupChecklistItemDetail
    repo_connected: SetupChecklistItemDetail
    alert_source_verified: SetupChecklistItemDetail
    notification_channel_set: SetupChecklistItemDetail
    end_to_end_test_passed: SetupChecklistItemDetail
    completed_count: int
    # The most recent of the 5 items' completed_at values -- "nothing has
    # changed since" for admin stall detection (core/setup_checklist_
    # stall_alert.py) and the "Azure connected Tuesday, nothing since"
    # narrative on the admin detail view. None only when zero items are
    # done yet.
    last_activity_at: Optional[datetime]


def _item(timestamps: list) -> SetupChecklistItemDetail:
    """`timestamps` is every non-null source column/row for one item (an
    OR of several possible signals, e.g. aws/azure/k8s verified_at) --
    the item "flipped" true at whichever of those came first."""
    present = [t for t in timestamps if t is not None]
    completed_at = min(present) if present else None
    return SetupChecklistItemDetail(done=completed_at is not None, completed_at=completed_at)


def _assemble_detail(
    cloud: SetupChecklistItemDetail,
    repo: SetupChecklistItemDetail,
    alert: SetupChecklistItemDetail,
    channel: SetupChecklistItemDetail,
    e2e: SetupChecklistItemDetail,
) -> SetupChecklistDetail:
    items = (cloud, repo, alert, channel, e2e)
    completed_ats = [i["completed_at"] for i in items if i["completed_at"] is not None]
    return SetupChecklistDetail(
        cloud_connected=cloud,
        repo_connected=repo,
        alert_source_verified=alert,
        notification_channel_set=channel,
        end_to_end_test_passed=e2e,
        completed_count=sum(1 for i in items if i["done"]),
        last_activity_at=max(completed_ats) if completed_ats else None,
    )


async def compute_setup_checklist_detail(conn, workspace: dict) -> SetupChecklistDetail:
    """
    Admin-facing companion to compute_setup_checklist below -- same 5
    signals, but with a per-item completed_at timestamp instead of a
    bare bool, so a stalled workspace shows as "Azure connected Tuesday,
    nothing since" rather than just "3/5". Deliberately a SEPARATE
    function with its own queries (SELECT MIN(...) instead of SELECT 1)
    rather than a refactor of compute_setup_checklist -- that function is
    on the customer-facing GET /workspace/setup-checklist path and
    core/onboarding_sequence.py's email gating; this file's own tests
    pin its exact query shape, so it stays untouched rather than risk a
    regression on a live customer path for the sake of an admin feature.
    """
    cloud = _item([
        workspace.get("aws_role_verified_at"),
        workspace.get("azure_verified_at"),
        workspace.get("k8s_verified_at"),
    ])
    repo = _item([
        workspace.get("github_app_installed_at"),
        workspace.get("github_pat_verified_at"),
        workspace.get("azure_devops_pat_verified_at"),
    ])

    alert_row = await conn.fetchrow(
        "SELECT MIN(received_at) AS first_at FROM alert_ingestion_log WHERE workspace_id = $1",
        workspace["id"],
    )
    channel_row = await conn.fetchrow(
        "SELECT MIN(created_at) AS first_at FROM workspace_notification_channels "
        "WHERE workspace_id = $1 AND enabled = true",
        workspace["id"],
    )
    alert = _item([alert_row["first_at"] if alert_row else None])
    channel = _item([channel_row["first_at"] if channel_row else None])
    e2e = _item([workspace.get("setup_test_passed_at")])

    return _assemble_detail(cloud, repo, alert, channel, e2e)


async def compute_setup_checklist_detail_bulk(conn, workspaces: list[dict]) -> dict[str, SetupChecklistDetail]:
    """
    Same signals as compute_setup_checklist_detail, batched for a
    workspace LIST view (api/routes/internal_workspaces.py's
    list_workspaces) -- two GROUP BY queries total instead of 2*N, so a
    200-row admin list doesn't fire 400 round trips. `workspaces` must
    already carry every raw column compute_setup_checklist_detail reads
    (aws_role_verified_at, azure_verified_at, k8s_verified_at,
    github_app_installed_at, github_pat_verified_at,
    azure_devops_pat_verified_at, setup_test_passed_at, id).
    """
    ids = [w["id"] for w in workspaces]
    if not ids:
        return {}

    alert_rows = await conn.fetch(
        "SELECT workspace_id, MIN(received_at) AS first_at FROM alert_ingestion_log "
        "WHERE workspace_id = ANY($1::uuid[]) GROUP BY workspace_id",
        ids,
    )
    channel_rows = await conn.fetch(
        "SELECT workspace_id, MIN(created_at) AS first_at FROM workspace_notification_channels "
        "WHERE workspace_id = ANY($1::uuid[]) AND enabled = true GROUP BY workspace_id",
        ids,
    )
    first_alert_by_workspace = {r["workspace_id"]: r["first_at"] for r in alert_rows}
    first_channel_by_workspace = {r["workspace_id"]: r["first_at"] for r in channel_rows}

    result: dict[str, SetupChecklistDetail] = {}
    for w in workspaces:
        cloud = _item([w.get("aws_role_verified_at"), w.get("azure_verified_at"), w.get("k8s_verified_at")])
        repo = _item([w.get("github_app_installed_at"), w.get("github_pat_verified_at"), w.get("azure_devops_pat_verified_at")])
        alert = _item([first_alert_by_workspace.get(w["id"])])
        channel = _item([first_channel_by_workspace.get(w["id"])])
        e2e = _item([w.get("setup_test_passed_at")])
        result[w["id"]] = _assemble_detail(cloud, repo, alert, channel, e2e)

    return result


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
