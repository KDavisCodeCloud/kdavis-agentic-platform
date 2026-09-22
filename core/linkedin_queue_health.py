"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

2026-09-22 incident fix. Kelvin's own framing after three sequential bugs
(LinkedIn token expiry with no alerting, an in-memory OAuth state store
broken under 4 production workers, an asset-fetch environment mismatch,
a double-JSON-encoding write bug) all surfaced as the same downstream
symptom -- "approved posts not posting" -- discovered three days late:
"I need this loop to be robust and not to break again."

The actual gap was never any one of those four bugs specifically. It was
that a `linkedin_content_queue` row can sit at status='approved' with
scheduled_for in the past and published_at still NULL indefinitely, for
*any* reason -- an expired token, a missing image, bad data, the
GitHub Actions cron silently disabled, a new bug nobody's found yet --
with zero signal to Kelvin until he happens to check LinkedIn itself.
This closes that gap generically: alert on the *symptom* (stuck due
posts), not each specific cause. Every future failure mode, including
ones nobody's hit yet, surfaces within hours instead of days.

Same hourly-loop + advisory-lock convention as core/social_token_expiry.py
(that module and this one are natural siblings, kept separate because
they check genuinely different things -- one credential, one queue).
Alert dedup via the generic system_health_alerts table (migration 055)
rather than a bespoke column, since "alert at most once a day" is a
pattern other checks will want too.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

_LOCK_ID = 719_442_183
_STALE_THRESHOLD_HOURS = 2
_ALERT_DEDUP_HOURS = 24
_ALERT_KEY = "linkedin_queue_stale_posts"


async def run_linkedin_queue_health_check(pool) -> dict:
    """
    Called on a periodic loop from api/main.py. Returns
    {"stale_count": n, "alerted": bool} -- a no-lock pass (another worker
    already has it this cycle) returns {"stale_count": 0, "alerted": False}.
    """
    summary = {"stale_count": 0, "alerted": False}

    async with pool.acquire() as conn:
        got_lock = await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)", _LOCK_ID)
        if not got_lock:
            return summary

        stale_rows = await conn.fetch(
            """
            SELECT id, scheduled_for FROM linkedin_content_queue
            WHERE status = 'approved'
              AND published_at IS NULL
              AND scheduled_for < NOW() - ($1 || ' hours')::interval
            ORDER BY scheduled_for
            """,
            str(_STALE_THRESHOLD_HOURS),
        )
        summary["stale_count"] = len(stale_rows)
        if not stale_rows:
            return summary

        alert_row = await conn.fetchrow(
            "SELECT last_alerted_at FROM system_health_alerts WHERE key = $1", _ALERT_KEY
        )
        now = datetime.now(timezone.utc)
        already_alerted_recently = (
            alert_row is not None
            and (now - alert_row["last_alerted_at"]) < timedelta(hours=_ALERT_DEDUP_HOURS)
        )
        if already_alerted_recently:
            return summary

        oldest = stale_rows[0]
        hours_stuck = (now - oldest["scheduled_for"]).total_seconds() / 3600
        await _send_alert(len(stale_rows), oldest["id"], hours_stuck)

        await conn.execute(
            """
            INSERT INTO system_health_alerts (key, last_alerted_at) VALUES ($1, NOW())
            ON CONFLICT (key) DO UPDATE SET last_alerted_at = NOW()
            """,
            _ALERT_KEY,
        )
        summary["alerted"] = True

    return summary


async def _send_alert(stale_count: int, oldest_id, hours_stuck: float) -> None:
    from core.email import EmailError, send_email

    owner_email = os.environ.get("OWNER_ALERT_EMAIL", "kdav2k5@gmail.com")
    try:
        await send_email(
            owner_email,
            f"{stale_count} LinkedIn post{'s' if stale_count != 1 else ''} stuck — "
            f"approved but not publishing",
            f"{stale_count} approved LinkedIn post(s) are past their scheduled time "
            f"and still haven't published. The oldest ({oldest_id}) has been stuck "
            f"{hours_stuck:.1f} hours. This means the scheduled dispatch isn't "
            "completing for these rows -- check the LinkedIn Scheduled Dispatch "
            "GitHub Actions workflow's recent runs for the actual error "
            "(github.com/KDavisCodeCloud/kdavis-agentic-platform/actions/workflows/"
            "linkedin-dispatch.yml). This alert re-fires at most once/day while "
            "any post stays stuck.",
        )
    except EmailError as exc:
        log.warning("[LinkedInQueueHealth] Alert email failed: %s", exc)
