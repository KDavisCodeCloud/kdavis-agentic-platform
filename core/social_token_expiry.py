"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

2026-09-22 incident fix -- root cause of "approved LinkedIn posts not
posting": api/routes/internal_marketing.py's linkedin_callback never
captured LinkedIn's `expires_in`, so nothing ever knew the access token
(60-day fixed lifetime, no refresh_token under this app's OAuth product
config -- that needs a separate LinkedIn Marketing Developer Platform
partner approval, not just a scope) was about to expire. It expired
silently around 2026-09-19; every scheduled post since failed closed with
a 401 from LinkedIn's Images API until Kelvin noticed three days later.

Same warn-then-escalate pattern as core/credential_expiry.py (which
covers workspace-facing Azure credentials via workspaces.contact_email)
adapted for internal_social_connections -- a single-row, owner-only table
with no workspace_id, so there's no HITLGate incident to create here;
OWNER_ALERT_EMAIL (same pattern as api/routes/internal_workspaces.py's
enterprise-tier alert) is the only channel.

Runs under its own advisory lock, same convention as db/migrate.py
(847_291_055), core/retention.py (592_014_773),
core/onboarding_sequence.py (401_887_226),
core/notification_retry.py (738_204_915 / 219_663_408),
core/credential_expiry.py (503_918_642).
"""

import logging
import os
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

_LOCK_ID = 361_558_204
_WARNING_WINDOW_DAYS = 14
_RECONNECT_PATH = "/api/v1/internal/marketing/connect/linkedin"


async def _send_alert(subject: str, body: str) -> None:
    from core.email import EmailError, send_email

    owner_email = os.environ.get("OWNER_ALERT_EMAIL", "kdav2k5@gmail.com")
    try:
        await send_email(owner_email, subject, body)
    except EmailError as exc:
        log.warning("[SocialTokenExpiry] Alert email failed: %s", exc)


async def run_social_token_expiry_check(pool) -> dict:
    """
    Called on a periodic loop from api/main.py. Returns
    {"warned": bool, "expired_alerted": bool} -- a no-lock pass (another
    worker already has it this cycle) returns both False, same shape
    convention as core/credential_expiry.py's run_credential_expiry_check.
    """
    summary = {"warned": False, "expired_alerted": False}

    async with pool.acquire() as conn:
        got_lock = await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)", _LOCK_ID)
        if not got_lock:
            return summary

        row = await conn.fetchrow(
            """
            SELECT expires_at, expiry_warned_at, platform_display_name
            FROM internal_social_connections
            WHERE platform = 'linkedin'
            """
        )
        if row is None or row["expires_at"] is None:
            return summary

        now = datetime.now(timezone.utc)
        expires_at = row["expires_at"]
        warning_cutoff = now + timedelta(days=_WARNING_WINDOW_DAYS)
        base_url = os.environ.get("API_BASE_URL", "https://api.theclouddecoded.com")
        admin_key = os.environ.get("ADMIN_BOOTSTRAP_KEY", "")
        reconnect_url = f"{base_url}{_RECONNECT_PATH}?key={admin_key}"

        if expires_at <= now:
            # Already expired. Re-alert at most once per day so this
            # doesn't spam every 15-minute cycle while Kelvin is away --
            # expiry_warned_at doubles as "last alerted at" once past
            # expiry, not just "warned before expiry" as in the
            # credential_expiry.py original.
            already_alerted_today = (
                row["expiry_warned_at"] is not None
                and (now - row["expiry_warned_at"]) < timedelta(days=1)
            )
            if not already_alerted_today:
                days_expired = (now - expires_at).days
                await _send_alert(
                    f"URGENT: LinkedIn posting token expired {days_expired} day"
                    f"{'s' if days_expired != 1 else ''} ago — scheduled posts are failing",
                    "Every approved LinkedIn post has been failing to publish "
                    f"since {expires_at.isoformat()} with a 401 from LinkedIn's API. "
                    f"Reconnect now: {reconnect_url}\n\n"
                    "This requires logging into LinkedIn as Kelvin Davis and "
                    "approving the connection again -- LinkedIn's OAuth tokens "
                    "under this app's product config are not auto-refreshable "
                    "(fixed ~60-day lifetime, no refresh_token).",
                )
                await conn.execute(
                    "UPDATE internal_social_connections SET expiry_warned_at = NOW() "
                    "WHERE platform = 'linkedin'"
                )
                summary["expired_alerted"] = True
        elif expires_at <= warning_cutoff and row["expiry_warned_at"] is None:
            days_left = max((expires_at - now).days, 0)
            await _send_alert(
                f"LinkedIn posting token expires in {days_left} day"
                f"{'s' if days_left != 1 else ''}",
                f"Your LinkedIn connection for scheduled posting expires "
                f"{expires_at.isoformat()}. Reconnect before then to avoid an "
                f"interruption to the monthly LinkedIn batch: {reconnect_url}",
            )
            await conn.execute(
                "UPDATE internal_social_connections SET expiry_warned_at = NOW() "
                "WHERE platform = 'linkedin'"
            )
            summary["warned"] = True

    return summary
