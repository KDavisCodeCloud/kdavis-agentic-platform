"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

GitHub App webhook events that change what Cloud Decoded knows (item 3).

installation
  - created, for an installation no workspace holds: recorded in
    github_app_unclaimed_installations, never linked. The payload carries no
    proof of which workspace started the install (Kelvin, 2026-11-17: "never
    auto-link"). Linking happens only via the signed Setup URL callback.
  - deleted: the workspace that held it is unlinked, so agents stop
    minting tokens for an installation GitHub has revoked.

pull_request closed
  - A merged Cloud Decoded fix PR (head branch from core/pr_branch.py) moves
    its incident from 'proposed' to 'fix_merged': "Fix merged — awaiting
    verification". Merging is not fixing. Nothing has been applied or
    re-checked yet; item 4's verification closes it as verified or
    verification_failed.
  - Closed without merging: recorded on the incident's audit trail; the
    incident stays 'proposed' (the operator can resolve it manually).
"""

import json
import logging
from typing import Optional
from uuid import UUID

from core.hitl import STATUS_FIX_MERGED, STATUS_PROPOSED
from core.pr_branch import incident_id_from_branch

log = logging.getLogger(__name__)


async def handle_installation_event(conn, payload: dict) -> dict:
    action = payload.get("action", "")
    installation = payload.get("installation") or {}
    installation_id = str(installation.get("id", ""))
    if not installation_id:
        return {"status": "ignored", "reason": "no installation.id in payload"}

    if action == "deleted":
        unlinked = await conn.fetch(
            "UPDATE workspaces SET github_app_installation_id = NULL, github_app_installed_at = NULL "
            "WHERE github_app_installation_id = $1 RETURNING id",
            installation_id,
        )
        await conn.execute(
            "DELETE FROM github_app_unclaimed_installations WHERE installation_id = $1", installation_id,
        )
        for row in unlinked:
            await _audit(conn, row["id"], None, None, "github_app_uninstalled", "unlinked",
                         {"installation_id": installation_id})
        log.info("[GitHubAppEvents] installation %s deleted; unlinked %d workspace(s)", installation_id, len(unlinked))
        return {"status": "accepted", "message": f"unlinked {len(unlinked)} workspace(s)"}

    if action != "created":
        return {"status": "ignored", "reason": f"installation action '{action}' not handled"}

    linked = await conn.fetchval(
        "SELECT id FROM workspaces WHERE github_app_installation_id = $1", installation_id,
    )
    if linked:
        return {"status": "ignored", "reason": "installation already linked"}

    account = installation.get("account") or {}
    await conn.execute(
        """
        INSERT INTO github_app_unclaimed_installations
            (installation_id, account_login, account_type, sender_login, repository_count)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (installation_id) DO UPDATE SET received_at = NOW()
        """,
        installation_id,
        account.get("login"),
        account.get("type"),
        (payload.get("sender") or {}).get("login"),
        len(payload.get("repositories") or []),
    )
    log.warning(
        "[GitHubAppEvents] installation %s (account=%s) created with no workspace claim -- recorded as "
        "unclaimed; the customer finishes linking from Settings → Integrations",
        installation_id, account.get("login"),
    )
    return {"status": "accepted", "message": "installation recorded as unclaimed; not linked"}


async def handle_fix_pr_closed(conn, workspace_id, payload: dict) -> dict:
    pr = payload.get("pull_request") or {}
    incident_id = incident_id_from_branch((pr.get("head") or {}).get("ref"))
    if not incident_id:
        return {"status": "ignored", "reason": "not a Cloud Decoded fix branch"}

    row = await conn.fetchrow(
        "SELECT id, agent_id, execution_status FROM incidents WHERE id = $1 AND workspace_id = $2",
        UUID(incident_id), workspace_id,
    )
    if not row:
        # A branch name alone is not proof: the incident must belong to the
        # workspace this installation is linked to.
        return {"status": "ignored", "reason": "fix branch names no incident in this workspace"}

    details = {
        "pr_url": pr.get("html_url"),
        "pr_number": pr.get("number"),
        "merge_commit_sha": pr.get("merge_commit_sha"),
        "merged_at": pr.get("merged_at"),
        "merged_by": (pr.get("merged_by") or {}).get("login"),
    }

    if not pr.get("merged"):
        await _audit(conn, workspace_id, row["id"], row["agent_id"], "fix_pr_closed_unmerged",
                     row["execution_status"], details)
        return {"status": "accepted", "message": "fix PR closed without merging; incident unchanged"}

    if row["execution_status"] != STATUS_PROPOSED:
        await _audit(conn, workspace_id, row["id"], row["agent_id"], "fix_pr_merged",
                     row["execution_status"], {**details, "status_unchanged": True})
        return {"status": "accepted",
                "message": f"fix PR merged; incident is '{row['execution_status']}', left unchanged"}

    await conn.execute(
        "UPDATE incidents SET execution_status = $1 WHERE id = $2 AND execution_status = $3",
        STATUS_FIX_MERGED, row["id"], STATUS_PROPOSED,
    )
    await _audit(conn, workspace_id, row["id"], row["agent_id"], "fix_pr_merged", STATUS_FIX_MERGED, details)
    log.info("[GitHubAppEvents] incident %s fix PR merged (%s) -> awaiting verification", incident_id,
             details["pr_url"])
    return {"status": "accepted", "message": "incident moved to fix_merged (awaiting verification)"}


async def _audit(conn, workspace_id, incident_id: Optional[UUID], agent_id: Optional[str],
                 action: str, status: str, metadata: dict) -> None:
    await conn.execute(
        """
        INSERT INTO audit_events (workspace_id, agent_id, incident_id, action, status, metadata)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        workspace_id, agent_id, incident_id, action, status, json.dumps(metadata),
    )
