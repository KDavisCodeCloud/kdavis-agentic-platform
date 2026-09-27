"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Admin visibility build (2026-09-27) -- when a PAYING workspace sits
below 5/5 on the setup checklist with no item flipping for 72+ hours,
email the platform owner. Same OWNER_ALERT_EMAIL / send_email /
EmailError pattern as api/routes/internal_workspaces.py's
_send_enterprise_alert. Runs hourly as an in-process background task
(api/main.py's lifespan) -- same reasoning as every other periodic scan
in this codebase: this platform runs as Railway web-service workers
only, no separate worker/cron service exists to host a scheduled job
elsewhere.

Re-alert discipline: workspaces.setup_stall_alert_sent_at (migration
058) records the last alert sent for this workspace. A later check only
re-alerts once there has been NEW checklist activity (a later
last_activity_at) since that recorded alert, followed by another full
72h of silence after that new activity -- so a workspace that never
touches its setup again after the first alert does not get re-emailed
every hourly cycle forever, but one that makes partial progress and
then stalls again for another 72h does get a fresh alert.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from core.email import EmailError, send_email, stalled_setup_alert_html
from core.setup_checklist import compute_setup_checklist_detail_bulk

log = logging.getLogger(__name__)

STALL_ALERT_INTERVAL_SECONDS = 60 * 60
STALL_THRESHOLD = timedelta(hours=72)

# Order matters only for the email's missing-items list -- readable,
# not load-bearing.
_ITEM_LABELS = {
    "cloud_connected": "Cloud connected",
    "repo_connected": "Repo connected",
    "alert_source_verified": "Alert source verified",
    "notification_channel_set": "Notification channel set",
    "end_to_end_test_passed": "End-to-end test passed",
}

_CHECKLIST_COLUMNS = (
    "id, company_name, contact_email, created_at, "
    "aws_role_verified_at, azure_verified_at, k8s_verified_at, "
    "github_app_installed_at, github_pat_verified_at, azure_devops_pat_verified_at, "
    "setup_test_passed_at, setup_stall_alert_sent_at"
)


async def run_stalled_setup_check(pool) -> dict:
    """
    One pass: finds every active (paying) workspace stalled below 5/5
    for 72h+ that hasn't already been alerted for this exact stall
    episode, emails the owner, and records the alert. Returns
    {"checked": N, "alerted": [workspace_id, ...]} for logging/tests --
    never raises; a single workspace's email failure is logged and
    skipped, not allowed to abort the rest of the pass.
    """
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT {_CHECKLIST_COLUMNS} FROM workspaces WHERE stripe_subscription_status = 'active'"
        )
        workspaces = [dict(r) for r in rows]
        details = await compute_setup_checklist_detail_bulk(conn, workspaces)

    alerted: list[str] = []
    for workspace in workspaces:
        detail = details.get(workspace["id"])
        if not detail or detail["completed_count"] >= 5:
            continue

        baseline = detail["last_activity_at"] or workspace["created_at"]
        if now - baseline < STALL_THRESHOLD:
            continue

        already_alerted_at = workspace.get("setup_stall_alert_sent_at")
        if already_alerted_at is not None and already_alerted_at >= baseline:
            continue  # already alerted for this exact stall episode -- no new activity since

        missing_items = [_ITEM_LABELS[key] for key in _ITEM_LABELS if not detail[key]["done"]]
        last_activity_label = (
            f"Last checklist activity: {detail['last_activity_at'].isoformat()}."
            if detail["last_activity_at"]
            else f"No checklist item has ever been completed (workspace created {workspace['created_at'].isoformat()})."
        )

        try:
            await send_email(
                to=os.environ.get("OWNER_ALERT_EMAIL", "kdav2k5@gmail.com"),
                subject=f"Setup stalled: {workspace['company_name']}",
                html=stalled_setup_alert_html(
                    workspace["company_name"], str(workspace["id"]), workspace.get("contact_email"),
                    missing_items, last_activity_label,
                ),
            )
        except EmailError as exc:
            log.warning("[SetupChecklistStallAlert] Email failed for workspace=%s: %s", workspace["id"], exc)
            continue

        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE workspaces SET setup_stall_alert_sent_at = $1 WHERE id = $2", now, workspace["id"],
            )
        alerted.append(str(workspace["id"]))

    log.info("[SetupChecklistStallAlert] Checked %d active workspaces, alerted %d", len(workspaces), len(alerted))
    return {"checked": len(workspaces), "alerted": alerted}
