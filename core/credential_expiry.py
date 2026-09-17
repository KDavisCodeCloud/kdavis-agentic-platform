"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

24-gap-closure build, Phase 5 -- daily check for Azure Service Principal
client secrets and Azure DevOps PATs expiring within 14 days (email to
workspaces.contact_email; the ConnectionsPanel banner reads the same
*_expires_at columns this module writes nothing new for) or already
expired (a real critical incident via core/hitl.py's HITLGate, which
already fans out to whatever notification channels the workspace has
configured -- Slack/PagerDuty/ticketing/email, Phase 3 -- so nothing
extra is needed here for the "critical incident" requirement itself).

AWS roles are deliberately N/A: an IAM role's AssumeRole trust
relationship has no expiring secret the way an SP client secret or a
PAT does, so there is nothing to check for AWS here (see migration
045's own comment).

Runs under a distinct advisory lock (pg_try_advisory_xact_lock) so only
one of this app's --workers processes does the check on a given pass --
same convention as db/migrate.py (847_291_055), core/retention.py
(592_014_773), core/onboarding_sequence.py (401_887_226),
core/notification_retry.py (738_204_915 / 219_663_408).
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

log = logging.getLogger(__name__)

_LOCK_ID = 503_918_642
_WARNING_WINDOW_DAYS = 14

# Deterministic per-workspace-per-credential incident id. A repeated
# daily check for a credential that's already expired naturally no-ops
# via HITLGate.create_incident's own ON CONFLICT (id) DO NOTHING once
# the incident exists, instead of needing a separate "already flagged"
# column -- same trick migration 042's incident_id passthrough already
# relies on for LangGraph resume idempotency.
_INCIDENT_NAMESPACE = uuid5(NAMESPACE_URL, "theclouddecoded.com/credential-expiry")

_CREDENTIALS = (
    {
        "column_expires": "azure_client_secret_expires_at",
        "column_warned": "azure_client_secret_expiry_warned_at",
        "label": "Azure Service Principal client secret",
        "slug": "azure_sp_secret",
    },
    {
        "column_expires": "azure_devops_pat_expires_at",
        "column_warned": "azure_devops_pat_expiry_warned_at",
        "label": "Azure DevOps personal access token",
        "slug": "azure_devops_pat",
    },
)


def _incident_id_for(workspace_id, slug: str) -> str:
    return str(uuid5(_INCIDENT_NAMESPACE, f"{workspace_id}:{slug}"))


async def _send_expiry_warning(conn, row, cred: dict, expires_at, now) -> None:
    from core.email import EmailError, send_email

    if row["contact_email"]:
        days_left = max((expires_at - now).days, 0)
        try:
            await send_email(
                row["contact_email"],
                f"Cloud Decoded — {cred['label']} expires in {days_left} "
                f"day{'s' if days_left != 1 else ''}",
                f"Your {cred['label']} for {row['company_name']} expires "
                f"{expires_at.isoformat()}. Reconnect it in the Connections tab "
                f"before then to avoid an interruption.",
            )
        except EmailError as exc:
            log.warning("[CredentialExpiry] Email send failed workspace=%s: %s", row["id"], exc)
    else:
        log.warning("[CredentialExpiry] No contact_email for workspace=%s -- warning not sent", row["id"])

    await conn.execute(
        f"UPDATE workspaces SET {cred['column_warned']} = NOW() WHERE id = $1",
        row["id"],
    )


async def _create_expired_incident(conn, row, cred: dict) -> None:
    from core.hitl import HITLGate

    gate = HITLGate(conn)
    await gate.create_incident(
        workspace_id=str(row["id"]),
        agent_id="system_credential_lifecycle",
        raw_log=f"{cred['label']} expired for workspace {row['id']}",
        parsed_error=f"{cred['label']} has expired and must be reconnected",
        remediation_options=[
            {
                "id": "reconnect",
                "title": "Reconnect credential",
                "description": f"Go to Connections and reconnect the {cred['label']}.",
            },
        ],
        incident_id=_incident_id_for(row["id"], cred["slug"]),
        severity="critical",
    )


async def run_credential_expiry_check(pool) -> dict:
    """
    Called on a periodic loop from api/main.py. Returns
    {"warned": n, "critical_incidents": n} -- a no-lock pass (another
    worker already has it this cycle) returns both as 0, same shape as
    core/notification_retry.py's run_pending_retries.
    """
    summary = {"warned": 0, "critical_incidents": 0}

    async with pool.acquire() as conn:
        got_lock = await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)", _LOCK_ID)
        if not got_lock:
            return summary

        now = datetime.now(timezone.utc)
        warning_cutoff = now + timedelta(days=_WARNING_WINDOW_DAYS)

        for cred in _CREDENTIALS:
            rows = await conn.fetch(
                f"""
                SELECT id, company_name, contact_email,
                       {cred['column_expires']} AS expires_at,
                       {cred['column_warned']} AS warned_at
                FROM workspaces
                WHERE {cred['column_expires']} IS NOT NULL
                  AND {cred['column_expires']} <= $1
                """,
                warning_cutoff,
            )
            for row in rows:
                expires_at = row["expires_at"]
                if expires_at <= now:
                    await _create_expired_incident(conn, row, cred)
                    summary["critical_incidents"] += 1
                elif row["warned_at"] is None:
                    await _send_expiry_warning(conn, row, cred, expires_at, now)
                    summary["warned"] += 1

    return summary
