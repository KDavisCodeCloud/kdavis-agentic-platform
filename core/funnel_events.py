"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

First-party funnel events for Cloud Decoded (migration 060, gap-table
#12/#13). No third-party analytics and no cookies.

Two kinds of event, one table (cd_funnel_events):

  CLIENT_EVENTS  sent by the browser to POST /api/v1/events. Each carries a
                 random per-tab visitor_id (sessionStorage), so an anonymous
                 visitor is never followed across tabs or visits.
  SERVER_EVENTS  written only by the API itself, at the moment the real
                 thing happens (an approval, a signup, a checkout, a paid
                 subscription). A browser cannot send these, so the funnel's
                 conversion steps cannot be forged or inflated from outside.

ref is an opaque outreach reference code from a ?ref= link (generated per
lead by mse-api; disclosed on /privacy). It rides on demo_sessions and on
workspaces.signup_ref so server events inherit it.

Recording is best-effort by design: a failed analytics write must never
fail an approval, a signup, or a Stripe webhook. Failures are logged with
the event name (never swallowed silently) and the caller carries on.
"""

import logging
import re
from typing import Any, Optional
from uuid import UUID

log = logging.getLogger(__name__)

PRODUCT_ID = "cloud_decoded"

CLIENT_EVENTS = frozenset({"demo_opened", "incident_viewed", "signup_clicked", "booking_clicked"})
SERVER_EVENTS = frozenset({
    "fix_approved", "fix_resolved_manually", "fix_rejected",
    "signup_completed", "checkout_started", "subscribed",
})
ALL_EVENTS = CLIENT_EVENTS | SERVER_EVENTS

# Outreach ref codes and visitor ids: short, URL-safe, opaque. Anything else
# is dropped rather than stored, so a crafted link can't write arbitrary text.
_REF_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
_VISITOR_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_UTM_MAX = 100
_PATH_MAX = 255

# The only property keys ever stored, each a short scalar. No free text.
_ALLOWED_PROPERTIES = frozenset({"agent_id", "option_id", "cta", "tier"})
_PROPERTY_VALUE_MAX = 64


def clean_ref(value: Optional[str]) -> Optional[str]:
    if isinstance(value, str) and _REF_RE.match(value):
        return value
    return None


def clean_visitor_id(value: Optional[str]) -> Optional[str]:
    if isinstance(value, str) and _VISITOR_RE.match(value):
        return value
    return None


def clean_utm(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str) or not value:
        return None
    value = value.strip()[:_UTM_MAX]
    return value or None


def clean_path(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str) or not value.startswith("/"):
        return None
    # Path only: drop any query string so a ref/utm in the URL isn't
    # duplicated (or anything else smuggled) into this column.
    return value.split("?", 1)[0].split("#", 1)[0][:_PATH_MAX]


def clean_properties(props: Optional[dict]) -> dict:
    if not isinstance(props, dict) or not props:
        return {}
    out: dict[str, Any] = {}
    for key, value in props.items():
        if key not in _ALLOWED_PROPERTIES:
            continue
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            out[key] = value
        elif isinstance(value, str) and value:
            out[key] = value[:_PROPERTY_VALUE_MAX]
    return out


async def record_event(
    conn,
    event_name: str,
    *,
    visitor_id: Optional[str] = None,
    ref: Optional[str] = None,
    utm_source: Optional[str] = None,
    utm_medium: Optional[str] = None,
    utm_campaign: Optional[str] = None,
    path: Optional[str] = None,
    demo_session_id: Optional[UUID] = None,
    workspace_id: Optional[UUID] = None,
    properties: Optional[dict] = None,
) -> None:
    """Insert one validated event. Raises ValueError for an unknown event
    name (a programming error, not a runtime condition to tolerate)."""
    if event_name not in ALL_EVENTS:
        raise ValueError(f"Unknown funnel event '{event_name}'")
    await conn.execute(
        """
        INSERT INTO cd_funnel_events (
            product_id, event_name, visitor_id, ref, utm_source, utm_medium,
            utm_campaign, path, demo_session_id, workspace_id, properties
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """,
        PRODUCT_ID,
        event_name,
        clean_visitor_id(visitor_id),
        clean_ref(ref),
        clean_utm(utm_source),
        clean_utm(utm_medium),
        clean_utm(utm_campaign),
        clean_path(path),
        demo_session_id,
        UUID(str(workspace_id)) if workspace_id else None,
        # Native dict: the pool's jsonb codec (core/db.py register_jsonb_codec)
        # encodes it once. json.dumps here would double-encode.
        clean_properties(properties),
    )


async def record_demo_server_event(pool, event_name: str, demo_session_id, properties: Optional[dict] = None) -> None:
    """Server-side demo event (approve / resolve manually). Inherits the
    session's ref and UTM so the step is attributed to the outreach link
    that opened the demo. Best-effort: never raises."""
    try:
        async with pool.acquire() as conn:
            session = await conn.fetchrow(
                "SELECT ref, utm_source, utm_medium, utm_campaign FROM demo_sessions WHERE id = $1",
                demo_session_id,
            )
            await record_event(
                conn, event_name,
                ref=session["ref"] if session else None,
                utm_source=session["utm_source"] if session else None,
                utm_medium=session["utm_medium"] if session else None,
                utm_campaign=session["utm_campaign"] if session else None,
                path="/demo",
                demo_session_id=demo_session_id,
                properties=properties,
            )
    except Exception:
        log.exception("[FunnelEvents] Failed to record %s for demo session %s", event_name, demo_session_id)


async def record_workspace_server_event(
    pool, event_name: str, workspace_id, properties: Optional[dict] = None, *, once: bool = False,
) -> None:
    """Server-side workspace event (signup, checkout, subscribed). Inherits
    the workspace's signup attribution. once=True skips the write if this
    workspace already has this event (Stripe retries webhooks, so
    'subscribed' would otherwise double-count). Best-effort: never raises."""
    try:
        async with pool.acquire() as conn:
            if once and await conn.fetchval(
                "SELECT 1 FROM cd_funnel_events WHERE workspace_id = $1 AND event_name = $2 LIMIT 1",
                UUID(str(workspace_id)), event_name,
            ):
                return
            ws = await conn.fetchrow(
                """
                SELECT signup_ref, signup_utm_source, signup_utm_medium,
                       signup_utm_campaign, signup_visitor_id
                FROM workspaces WHERE id = $1
                """,
                UUID(str(workspace_id)),
            )
            await record_event(
                conn, event_name,
                visitor_id=ws["signup_visitor_id"] if ws else None,
                ref=ws["signup_ref"] if ws else None,
                utm_source=ws["signup_utm_source"] if ws else None,
                utm_medium=ws["signup_utm_medium"] if ws else None,
                utm_campaign=ws["signup_utm_campaign"] if ws else None,
                workspace_id=workspace_id,
                properties=properties,
            )
    except Exception:
        log.exception("[FunnelEvents] Failed to record %s for workspace %s", event_name, workspace_id)


# Disclosed on /privacy: funnel and reference-link records are deleted
# after 13 months (enough for a year-over-year comparison).
FUNNEL_RETENTION_DAYS = 395
# Distinct from every other advisory lock id in this codebase
# (core/retention.py 592_014_773, core/demo_sandbox.py 305_827_961,
# db/migrate.py 847_291_055).
_FUNNEL_PRUNE_LOCK_ID = 418_663_207


async def prune_funnel_events(pool) -> int:
    """Delete cd_funnel_events past FUNNEL_RETENTION_DAYS. Run daily from
    api/main.py's retention loop; guarded so only one of the 4 workers does
    it per cycle. Returns rows deleted (0 if another worker held the lock)."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            if not await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)", _FUNNEL_PRUNE_LOCK_ID):
                return 0
            result = await conn.execute(
                "DELETE FROM cd_funnel_events WHERE created_at < NOW() - ($1 || ' days')::interval",
                str(FUNNEL_RETENTION_DAYS),
            )
    deleted = int(result.split()[-1])
    log.info("[FunnelEvents] Retention pass deleted %d event(s) older than %d days", deleted, FUNNEL_RETENTION_DAYS)
    return deleted
