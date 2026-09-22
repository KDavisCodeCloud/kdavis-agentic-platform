"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Internal marketing integrations — owner-only. Completely separate from
api/routes/content.py's OAuth flow, which is a customer-facing Cloud Decoded
product feature (workspace_social_connections, gated by
api.middleware.auth.get_workspace / X-Workspace-Token). This file backs
Kelvin's own MKT-LI1 LinkedIn posting pipeline (agents/marketing/mkt_li1_*,
the linkedin_content_queue table) - a single owner identity, not a paying
customer's connected account. Stores tokens in internal_social_connections
(db/migrations/011), never workspace_social_connections. Do not merge these
two OAuth flows or have one call into the other - same isolation rule as
api/middleware/internal_auth.py's own docstring states for agent dispatch.

GET  /internal/marketing/connect/linkedin           - start LinkedIn OAuth
GET  /internal/marketing/connect/callback/linkedin   - LinkedIn OAuth callback
GET  /internal/marketing/connect/canva               - start Canva OAuth (PKCE)
GET  /internal/marketing/connect/callback/canva      - Canva OAuth callback
GET  /internal/marketing/connections                 - list connected platforms
PUT  /internal/marketing/canva/brand-templates        - record Brand Template IDs
POST /internal/marketing/publish/linkedin/{queue_id}  - publish an approved queue row
GET  /internal/marketing/linkedin-queue               - list queue rows (dashboard batch view)
PATCH /internal/marketing/linkedin-queue/{queue_id}   - approve/reject/reschedule one post
POST /internal/marketing/linkedin-queue/batch-approve - approve every pending post in a batch_month
GET  /internal/marketing/assets/{path}                 - serve an asset_library image (thumbnails)

Publish flow (added once linkedin_content_queue's HITL approval loop
needed an actual "make it go live" step — nothing called
core.publishers.canva or posted an image before this): reads one
APPROVED row from linkedin_content_queue, and if it carries an
image_brief AND a Canva Brand Template is configured for its post
format, renders the image via Canva (Autofill -> Export -> Download)
and posts image + text via core.publishers.linkedin.post_image().
Otherwise posts text only via post_text() — a deliberate fallback so
publishing isn't blocked entirely on Canva being fully set up yet.

The autofill data-field mapping (_CANVA_FIELD_MAP below) assumes a
specific set of named placeholder fields. It WILL be wrong until it's
reconciled against whatever field names Kelvin actually gives the real
Brand Template — confirm with core.publishers.canva.get_brand_template_dataset()
once that template exists, then update _CANVA_FIELD_MAP to match.

Canva prerequisites (all manual, external, Kelvin-only — cannot be done by
Claude Code): a Canva Developer account + "External Application" at
canva.com/developers with CANVA_CLIENT_ID/CANVA_CLIENT_SECRET generated,
this callback URL registered as the exact redirect URI, at least one Brand
Template built by hand in Canva's own editor with named autofill
placeholder fields (the Autofill API fills existing templates, it does
not generate designs from scratch), and a Canva plan tier that actually
includes Connect/Autofill API access. None of this can be verified until
those exist — see core/publishers/canva.py for the Autofill API client
this OAuth flow feeds tokens to.

Canva's OAuth flow (unlike LinkedIn's) requires PKCE — a code_verifier is
generated at the start of the flow and stored alongside the state entry,
then sent back (not the challenge) when exchanging the code for a token.

Auth note: the *callback* leg is a plain browser redirect from LinkedIn's
servers - it cannot carry a Bearer token, so get_internal_user cannot gate
it. The `state` parameter (bound to a short-lived in-memory entry at the
start of the flow) is what actually secures that leg, matching
content.py's existing pattern for the customer flow. The *start* leg
(/connect/linkedin) is currently gated by a shared ADMIN_BOOTSTRAP_KEY query
param rather than get_internal_user, because no ceo-dashboard UI trigger
exists yet to make an authenticated fetch() and hand the returned
authorization URL to the browser (a plain <a href> or curl can't attach a
Bearer header either). This is a deliberate, documented stopgap - replace
with a get_internal_user-gated JSON endpoint (returns {authUrl}, frontend
navigates) the moment a real "Connect LinkedIn" button exists on the
dashboard, and remove ADMIN_BOOTSTRAP_KEY at that point.
"""

import asyncio
import base64
import hashlib
import json
import logging
import mimetypes
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from api.middleware.internal_auth import get_internal_user
from api.routes.marketing import require_marketing_api_key

log = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/marketing", tags=["internal-marketing"])

_LI_CLIENT_ID = os.environ.get("LINKEDIN_CLIENT_ID", "")
_LI_CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
_LI_SCOPES = "openid profile w_member_social"
_API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8000")
_LI_REDIRECT = f"{_API_BASE}/api/v1/internal/marketing/connect/callback/linkedin"

_CANVA_CLIENT_ID = os.environ.get("CANVA_CLIENT_ID", "")
_CANVA_CLIENT_SECRET = os.environ.get("CANVA_CLIENT_SECRET", "")
_CANVA_SCOPES = "asset:read asset:write design:content:read design:content:write"
_CANVA_REDIRECT = f"{_API_BASE}/api/v1/internal/marketing/connect/callback/canva"
_CANVA_AUTHORIZE_URL = "https://www.canva.com/api/oauth/authorize"
_CANVA_TOKEN_URL = "https://api.canva.com/rest/v1/oauth/token"

# OAuth state store — migration 053, internal_oauth_state table. Was a
# plain in-memory dict until a real "expired oauth state" bug 2026-09-22
# (see that migration's comment): this service runs 4 uvicorn workers in
# production, and an in-memory dict on the worker that issued the state
# is invisible to whichever of the other 3 workers handles the callback.
# DB-backed so any worker can complete the flow. State entries expire
# after 10 minutes so a stale/abandoned flow can't be replayed later.
_STATE_TTL_SECONDS = 600


async def _store_oauth_state(conn, state: str, purpose: str, code_verifier: str | None = None) -> None:
    await conn.execute(
        "DELETE FROM internal_oauth_state WHERE issued_at < NOW() - ($1 || ' seconds')::interval",
        str(_STATE_TTL_SECONDS),
    )
    await conn.execute(
        "INSERT INTO internal_oauth_state (state, purpose, code_verifier) VALUES ($1, $2, $3)",
        state, purpose, code_verifier,
    )


async def _pop_oauth_state(conn, state: str, purpose: str) -> dict | None:
    """Atomically consumes a state entry (a replayed callback must fail the
    same way a genuinely unknown state does) and returns its issued_at /
    code_verifier, or None if the state doesn't exist for this purpose."""
    row = await conn.fetchrow(
        "DELETE FROM internal_oauth_state WHERE state = $1 AND purpose = $2 "
        "RETURNING issued_at, code_verifier",
        state, purpose,
    )
    return dict(row) if row else None


def _generate_pkce_pair() -> tuple[str, str]:
    """Returns (code_verifier, code_challenge) per RFC 7636 S256."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def _fernet() -> Fernet:
    key = os.environ.get("ENCRYPTION_KEY", "")
    if not key:
        raise EnvironmentError("ENCRYPTION_KEY not set")
    return Fernet(key.encode() if isinstance(key, str) else key)


def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


@router.get("/connect/linkedin")
async def connect_linkedin(key: str, request: Request) -> RedirectResponse:
    """
    Start LinkedIn OAuth 2.0 flow for the internal (owner) identity.
    See module docstring - key= is a deliberate stopgap, not the long-term
    auth model for this leg.
    """
    admin_key = os.environ.get("ADMIN_BOOTSTRAP_KEY", "")
    if not admin_key or not secrets.compare_digest(key, admin_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid key")

    if not _LI_CLIENT_ID:
        raise HTTPException(status_code=503, detail="LINKEDIN_CLIENT_ID not configured")

    state = secrets.token_urlsafe(32)
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        await _store_oauth_state(conn, state, "linkedin")

    params = (
        f"response_type=code"
        f"&client_id={_LI_CLIENT_ID}"
        f"&redirect_uri={_LI_REDIRECT}"
        f"&scope={_LI_SCOPES.replace(' ', '%20')}"
        f"&state={state}"
    )
    return RedirectResponse(f"https://www.linkedin.com/oauth/v2/authorization?{params}")


@router.get("/connect/callback/linkedin")
async def linkedin_callback(code: str, state: str, request: Request) -> dict:
    """
    LinkedIn OAuth callback - exchanges code for an access token, stores it
    encrypted in internal_social_connections. Returns a plain JSON summary
    rather than redirecting into ceo-dashboard, since no post-connect UI
    page exists there yet for this flow.
    """
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        entry = await _pop_oauth_state(conn, state, "linkedin")
    if entry is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    if (datetime.now(timezone.utc) - entry["issued_at"]).total_seconds() > _STATE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="OAuth state expired - restart the connect flow")

    async with httpx.AsyncClient(timeout=30) as client:
        token_resp = await client.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _LI_REDIRECT,
                "client_id": _LI_CLIENT_ID,
                "client_secret": _LI_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()

    access_token = token_data["access_token"]
    expires_in = token_data.get("expires_in")
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        if expires_in is not None
        else None
    )
    if expires_at is None:
        log.warning(
            "[InternalMarketing] LinkedIn token exchange returned no expires_in -- "
            "expiry tracking will be blind for this connection until reconnected"
        )

    from core.publishers.linkedin import get_author_urn
    author_urn = await get_author_urn(access_token)

    async with httpx.AsyncClient(timeout=15) as client:
        profile_resp = await client.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}", "LinkedIn-Version": "202501"},
        )
        profile_resp.raise_for_status()
        profile = profile_resp.json()

    display_name = profile.get("name", "")
    platform_user_id = profile.get("sub", "")
    encrypted_token = _encrypt(access_token)

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO internal_social_connections
              (platform, platform_user_id, platform_display_name,
               encrypted_access_token, author_urn, expires_at, expiry_warned_at)
            VALUES ($1, $2, $3, $4, $5, $6, NULL)
            ON CONFLICT (platform)
            DO UPDATE SET
              platform_user_id = EXCLUDED.platform_user_id,
              platform_display_name = EXCLUDED.platform_display_name,
              encrypted_access_token = EXCLUDED.encrypted_access_token,
              author_urn = EXCLUDED.author_urn,
              expires_at = EXCLUDED.expires_at,
              expiry_warned_at = NULL,
              updated_at = NOW()
            """,
            "linkedin", platform_user_id, display_name, encrypted_token, author_urn, expires_at,
        )

    log.info("[InternalMarketing] LinkedIn connected — user=%s urn=%s", display_name, author_urn)
    return {
        "connected": True,
        "platform": "linkedin",
        "display_name": display_name,
        "author_urn": author_urn,
    }


@router.get("/connect/canva")
async def connect_canva(key: str, request: Request) -> RedirectResponse:
    """
    Start Canva's OAuth 2.0 + PKCE flow. Same key= stopgap as
    connect_linkedin above — see that function's note.
    """
    admin_key = os.environ.get("ADMIN_BOOTSTRAP_KEY", "")
    if not admin_key or not secrets.compare_digest(key, admin_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid key")

    if not _CANVA_CLIENT_ID:
        raise HTTPException(status_code=503, detail="CANVA_CLIENT_ID not configured")

    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = _generate_pkce_pair()
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        await _store_oauth_state(conn, state, "canva", code_verifier)

    params = (
        f"response_type=code"
        f"&client_id={_CANVA_CLIENT_ID}"
        f"&redirect_uri={_CANVA_REDIRECT}"
        f"&scope={_CANVA_SCOPES.replace(' ', '%20')}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
        f"&state={state}"
    )
    return RedirectResponse(f"{_CANVA_AUTHORIZE_URL}?{params}")


@router.get("/connect/callback/canva")
async def canva_callback(code: str, state: str, request: Request) -> dict:
    """
    Canva OAuth callback — exchanges code + code_verifier for an access
    token (PKCE, no client_secret needed in the body per Canva's spec,
    but Canva's token endpoint additionally requires Basic auth with
    client_id:client_secret), stores it encrypted in
    internal_canva_connection.
    """
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        entry = await _pop_oauth_state(conn, state, "canva")
    if entry is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    code_verifier = entry["code_verifier"]
    if (datetime.now(timezone.utc) - entry["issued_at"]).total_seconds() > _STATE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="OAuth state expired - restart the connect flow")

    basic_auth = base64.b64encode(f"{_CANVA_CLIENT_ID}:{_CANVA_CLIENT_SECRET}".encode()).decode()

    async with httpx.AsyncClient(timeout=30) as client:
        token_resp = await client.post(
            _CANVA_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _CANVA_REDIRECT,
                "code_verifier": code_verifier,
            },
            headers={
                "Authorization": f"Basic {basic_auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()

    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in")

    encrypted_access_token = _encrypt(access_token)
    encrypted_refresh_token = _encrypt(refresh_token) if refresh_token else None

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO internal_canva_connection
              (platform, platform_user_id, platform_display_name,
               encrypted_access_token, encrypted_refresh_token, token_expires_at)
            VALUES ('canva', $1, $2, $3, $4, CASE WHEN $5::int IS NULL THEN NULL ELSE now() + ($5 || ' seconds')::interval END)
            ON CONFLICT (platform)
            DO UPDATE SET
              encrypted_access_token = EXCLUDED.encrypted_access_token,
              encrypted_refresh_token = EXCLUDED.encrypted_refresh_token,
              token_expires_at = EXCLUDED.token_expires_at,
              updated_at = NOW()
            """,
            "canva-owner", "Canva (owner)", encrypted_access_token, encrypted_refresh_token, expires_in,
        )

    log.info("[InternalMarketing] Canva connected")
    return {"connected": True, "platform": "canva"}


@router.get("/connections")
async def list_connections(
    request: Request,
    user: dict = Depends(get_internal_user),
) -> dict:
    """List connected platforms (no tokens returned). Admin-only, real auth."""
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        social_rows = await conn.fetch(
            "SELECT platform, platform_display_name, author_urn, connected_at, updated_at "
            "FROM internal_social_connections ORDER BY platform"
        )
        canva_rows = await conn.fetch(
            "SELECT platform_display_name, connected_at, updated_at, token_expires_at "
            "FROM internal_canva_connection"
        )
    connections = [dict(r) for r in social_rows]
    connections += [{"platform": "canva", **dict(r)} for r in canva_rows]
    return {"connections": connections}


# ── Brand Template registration ───────────────────────────────────────────

class BrandTemplateMap(BaseModel):
    linkedin_square: str | None = None
    linkedin_header: str | None = None


@router.put("/canva/brand-templates")
async def set_brand_templates(
    body: BrandTemplateMap,
    request: Request,
    user: dict = Depends(get_internal_user),
) -> dict:
    """
    Records which Canva Brand Template ID to use for each post format —
    keys match agents/marketing/mkt_cn1_image_brief.py's DIMENSIONS dict
    ("linkedin_square" / "linkedin_header"). Call once after building each
    template by hand in Canva's editor. Requires Canva to already be
    connected (/connect/canva) — this only updates the existing row.
    """
    template_ids = {k: v for k, v in body.model_dump().items() if v}
    if not template_ids:
        raise HTTPException(status_code=400, detail="Provide at least one template ID")

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE internal_canva_connection
            SET brand_template_ids = brand_template_ids || $1::jsonb, updated_at = NOW()
            WHERE platform = 'canva'
            """,
            template_ids,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=409, detail="Canva is not connected yet — run /connect/canva first")

    log.info("[InternalMarketing] Brand templates registered: %s", list(template_ids.keys()))
    return {"updated": True, "brand_template_ids": template_ids}


# ── Publish ────────────────────────────────────────────────────────────────

# Placeholder mapping from a linkedin_content_queue row's fields to the
# Brand Template's named autofill fields. MUST be reconciled against the
# real template once Kelvin builds it (see module docstring) — these
# names are a reasonable starting guess (a single headline text field
# plus an optional hero image field), not a confirmed schema.
_CANVA_HEADLINE_FIELD = "headline"
_CANVA_IMAGE_FIELD = "hero_image"


def _build_autofill_data(post_copy: str, image_brief: dict) -> dict:
    """
    Builds the {field_name: {"type": ..., ...}} payload create_autofill_job()
    needs, from the queue row's own text. Only fills the headline field for
    now — image_brief's design_prompt/reference_style are informational for
    a human building the template by hand, not machine-consumable inputs to
    autofill (autofill only ever inserts text/existing-asset-image into
    fields that already exist in the template, it doesn't generate new
    graphics from a prompt).
    """
    headline = post_copy.strip().split("\n")[0][:150]
    return {_CANVA_HEADLINE_FIELD: {"type": "text", "text": headline}}


async def _get_linkedin_connection(conn) -> tuple[str, str]:
    row = await conn.fetchrow(
        "SELECT encrypted_access_token, author_urn FROM internal_social_connections WHERE platform = 'linkedin'"
    )
    if row is None:
        raise HTTPException(status_code=409, detail="LinkedIn is not connected — run /connect/linkedin first")
    return _decrypt(row["encrypted_access_token"]), row["author_urn"]


async def _get_canva_connection(conn) -> tuple[str, dict]:
    row = await conn.fetchrow(
        "SELECT encrypted_access_token, brand_template_ids FROM internal_canva_connection WHERE platform = 'canva'"
    )
    if row is None:
        return "", {}
    return _decrypt(row["encrypted_access_token"]), dict(row["brand_template_ids"] or {})


_REPO_ROOT = Path(__file__).resolve().parents[2]  # api/routes/internal_marketing.py -> repo root


async def _fetch_asset_bytes(image_path: str) -> bytes:
    """
    Fetches an assets_library image live over HTTP from this backend's own
    /assets/{path} route (get_asset above) rather than reading local disk.

    Real bug found live 2026-09-22, same class as get_asset's own 2026-09-21
    one: publish_queue_row used to read `_REPO_ROOT / image_path` directly,
    which only works for the caller that IS this Railway app (the
    dashboard's manual publish button, in-process). scripts/dispatch_scheduled_posts.py
    runs in GitHub Actions -- a different machine entirely, with no access
    to Railway's persistent volume where generated images actually live --
    so every image-bearing post published via the 15-min dispatch cron
    failed "Asset vault image not found on disk," non-obviously, since text
    posts and the dashboard's own manual publish both worked fine. Fetching
    over HTTP unifies both callers on one path that works from anywhere,
    matching the same fix direction ceo-dashboard's asset proxy already took
    (see get_asset's docstring) rather than branching in-process-vs-remote.
    """
    relative = image_path.removeprefix("assets_library/")
    api_key = os.environ.get("MARKETING_API_KEY", "")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{_API_BASE}/api/v1/internal/marketing/assets/{relative}",
            headers={"X-API-Key": api_key},
        )
        resp.raise_for_status()
        return resp.content


class PublishError(Exception):
    """Raised by publish_queue_row for any failure that should map to an
    HTTP error when called from the route — kept as a plain exception
    (not HTTPException) so scripts/dispatch_scheduled_posts.py, which has
    no HTTP context, can catch and log it without an HTTPException import."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def publish_queue_row(conn, queue_id: str) -> dict:
    """
    Publishes one APPROVED linkedin_content_queue row to LinkedIn.

    Extracted from the /publish/linkedin/{queue_id} route (2026-07-23) so
    scripts/dispatch_scheduled_posts.py's cron dispatcher can call the
    exact same logic directly with its own asyncpg connection — the
    dispatcher runs unattended (GitHub Actions cron, no human present),
    so it cannot hold a live admin Supabase session JWT the way
    get_internal_user requires; going through the HTTP route was never
    viable for it. `conn` is any asyncpg connection/pool-acquired
    connection; this function has no FastAPI/Request dependency.

    Image source priority:
    1. Asset vault (assets_library/) — MKT-LI1 already selected and
       attached this image at draft time (agents/marketing/
       mkt_li1_linkedin_brand.py), so image_brief here holds
       asset_selector's own payload (image_path/credit_line/image_id).
       This is the active path — Canva is parked (Kelvin, 2026-07-22:
       "will only be used when generating our own ideas which we aren't
       doing yet"). post_copy was already formatted by post_formatter at
       queue time, so it's used verbatim here, never reformatted.
    2. Canva Autofill — dormant, not deleted, for when Canva comes back
       into use. Only triggers if brand_template_ids ever gets populated
       again (nothing currently calls /canva/brand-templates while
       parked), so this branch is naturally inactive rather than
       disabled by removing code.
    3. Text only — no image selected or matched.

    Sets status to 'published' and published_at on success, logs the
    asset vault image as used (asset_selector.log_usage) only on a
    confirmed successful post — never at draft/HITL time, since a
    rejected post must not count against an image's usage tracking.
    Never silently swallows a failure — an error at any step raises
    PublishError, the row's status is left as 'approved' so it can be
    retried, matching this repo's no-silent-failures rule.
    """
    row = await conn.fetchrow(
        "SELECT id, post_copy, image_brief, format, status FROM linkedin_content_queue WHERE id = $1",
        queue_id,
    )
    if row is None:
        raise PublishError(404, "Queue row not found")
    if row["status"] != "approved":
        raise PublishError(409, f"Queue row status is '{row['status']}' — must be 'approved' before publishing")

    # Real bug found live 2026-09-21: document_carousel posts have NEVER
    # had a real publish path. carousel_slides/carousel_pdf_brief are
    # only ever drafted (agents/marketing/mkt_li1_linkedin_brand.py,
    # mkt_v1_content_multiplier.py, scripts/generate_showing_signal_week.py)
    # -- nothing anywhere in this codebase renders them into an actual PDF/
    # image set, and core/publishers/linkedin.py has no document-post
    # function (only post_text/post_image exist). This function's own
    # image_brief check below (carousels never populate image_brief --
    # they use the separate carousel_pdf_brief field) fell through to the
    # else branch and silently published the caption alone via post_text,
    # used_image=False, with no error -- a carousel post going out with
    # none of its slides/visual content, and no signal anywhere that
    # anything was wrong. dispatch_scheduled_posts.py's cron reported
    # every one of these as a success.
    #
    # Fail loud instead, matching this function's own "never silently
    # swallows a failure" contract -- row stays 'approved' so it can be
    # retried once real document/carousel publishing exists (see GAPS.md).
    if row["format"] == "document_carousel":
        raise PublishError(
            501,
            "document_carousel publishing is not implemented — no code path renders "
            "carousel_slides/carousel_pdf_brief into a postable artifact, and "
            "core/publishers/linkedin.py has no document-post function. Re-approve as "
            "text_post with a generated image, or build real carousel publishing first.",
        )

    li_access_token, author_urn = await _get_linkedin_connection(conn)
    if not author_urn:
        raise PublishError(409, "LinkedIn connection has no author_urn — reconnect")

    canva_access_token, brand_template_ids = await _get_canva_connection(conn)

    image_brief = row["image_brief"]
    # Real bug found live 2026-09-22, same "fail loud, never silently
    # degrade" contract as the document_carousel fix above: one queue
    # row's image_brief was stored double-JSON-encoded (a JSON string
    # where a JSON object belongs -- asyncpg's jsonb codec then decodes
    # it once into a plain str, and image_brief.get(...) below raised an
    # opaque "'str' object has no attribute 'get'"). Try one more decode
    # pass; if it's still not a dict, raise a clear, specific error
    # instead of either that cryptic AttributeError or silently treating
    # a real image-bearing post as text-only.
    if isinstance(image_brief, str):
        try:
            image_brief = json.loads(image_brief)
        except (json.JSONDecodeError, TypeError):
            pass
    if image_brief is not None and not isinstance(image_brief, dict):
        raise PublishError(
            500,
            f"image_brief for queue row {queue_id} is malformed (expected a JSON "
            f"object, got {type(image_brief).__name__} even after one decode pass "
            "-- likely double-JSON-encoded at write time). Fix the row's image_brief "
            "directly or re-approve it without an image.",
        )
    post_type = "linkedin_header" if row["format"] == "document_carousel" else "linkedin_square"
    brand_template_id = brand_template_ids.get(post_type)

    from core.publishers.linkedin import post_image, post_text

    used_image_id = None
    try:
        if image_brief and image_brief.get("image_path"):
            image_bytes = await _fetch_asset_bytes(image_brief["image_path"])
            result = await post_image(li_access_token, author_urn, row["post_copy"], image_bytes)
            used_image = True
            used_image_id = image_brief.get("image_id")
        elif image_brief and canva_access_token and brand_template_id:
            from core.publishers.canva import render_brand_template_to_image

            data = _build_autofill_data(row["post_copy"], image_brief)
            image_bytes = await render_brand_template_to_image(canva_access_token, brand_template_id, data)
            result = await post_image(li_access_token, author_urn, row["post_copy"], image_bytes)
            used_image = True
        else:
            result = await post_text(li_access_token, author_urn, row["post_copy"])
            used_image = False
    except Exception as exc:
        log.error("[InternalMarketing] Publish failed for queue row %s: %s", queue_id, exc)
        raise PublishError(502, f"Publish failed: {exc}") from exc

    await conn.execute(
        "UPDATE linkedin_content_queue SET status = 'published', published_at = now() WHERE id = $1",
        queue_id,
    )

    if used_image_id:
        from assets_library.asset_logger import log_usage
        log_usage(used_image_id)

    log.info("[InternalMarketing] Published queue row %s — post_id=%s image=%s", queue_id, result["post_id"], used_image)
    return {
        "published": True,
        "queue_id": queue_id,
        "post_id": result["post_id"],
        "url": result["url"],
        "used_image": used_image,
    }


@router.post("/publish/linkedin/{queue_id}")
async def publish_linkedin_post(
    queue_id: str,
    request: Request,
    user: dict = Depends(get_internal_user),
) -> dict:
    """Thin HTTP wrapper — see publish_queue_row for the actual logic."""
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        try:
            return await publish_queue_row(conn, queue_id)
        except PublishError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


# ── Batch review, scheduling, and bulk approval (dashboard) ────────────────
#
# FALLBACK ONLY as of 2026-09-21 (v2.7 of agents/marketing/
# mkt_li1_linkedin_brand.py): the primary image generation point moved
# back to draft/queue time — mkt_li1_linkedin_brand.py's
# _attach_generated_image now runs before a row ever reaches
# pending_review, using this same assets_library/scene_image_gen.py
# pipeline, so Kelvin reviews and approves the image together with the
# post text (his explicit correction of the 2026-09-15 change below,
# which had moved generation to fire only after approval — he was
# approving text blind and never got to review or reject the image).
#
# This function is left wired into the approval endpoints below purely
# as a safety net: if a row somehow reaches pending_review with no
# image (a draft-time generation failure, or a legacy row), approving
# it will still fill one in rather than leaving a permanently-blank
# row. Its own `existing_brief` guard makes it a no-op whenever an
# image already exists, which is the normal case now.
#
# Original 2026-09-15 rationale (kept for history — the sequencing part
# is superseded, the relevance-gating part is not): an image now only
# ever gets generated from real post text via assets_library/
# scene_image_gen.py's two-step scene-extraction pipeline (never from
# the old asset_selector.py vault-matching), and that same module gates
# the result (subject match + text legibility) before it's ever
# attached, regenerating once on a failure and, if still failing,
# reverting the row to 'pending_review' with hitl_notes explaining why
# rather than leaving 'approved' status pointing at a bad or missing
# image that scripts/dispatch_scheduled_posts.py could otherwise
# publish as-is.
#
# Runs inside the same request that flips status to 'approved' (not a
# background job) specifically so there is no window where a row is
# 'approved' with no image decision made yet — dispatch_scheduled_posts.py
# only ever sees a row that is 'approved' AND already has (or explicitly
# doesn't need) an image.


async def _generate_and_gate_image_for_approved_row(conn, queue_id: str) -> None:
    row = await conn.fetchrow(
        "SELECT post_copy, pillar_name, topic, format, image_brief, notes FROM linkedin_content_queue WHERE id = $1",
        queue_id,
    )
    if row is None:
        return  # row vanished between the approval UPDATE and here -- nothing to attach to

    # document_carousel posts use carousel_pdf_brief, not a single generated
    # image (unchanged from the old flow) -- nothing to generate here.
    if row["format"] != "text_post":
        return

    existing_brief = row["image_brief"]
    if isinstance(existing_brief, str):
        existing_brief = json.loads(existing_brief)
    if existing_brief and existing_brief.get("image_path"):
        return  # already has a real image (e.g. re-approving after a prior successful run) -- don't spend another Gemini call

    from assets_library.gemini_image_gen import ASSETS_ROOT
    from assets_library.scene_image_gen import generate_relevant_image

    try:
        result = await asyncio.to_thread(
            generate_relevant_image,
            post_text=row["post_copy"],
            pillar=row["pillar_name"],
            post_topic=row["topic"],
        )
    except Exception as exc:  # noqa: BLE001 -- an infra failure must revert to pending_review, never leave 'approved' with no image decision made
        log.error("[InternalMarketing] Image generation failed for queue row %s: %s", queue_id, exc)
        note = f"IMAGE GENERATION FAILED: {exc}"
        existing_notes = row["notes"] or ""
        await conn.execute(
            """
            UPDATE linkedin_content_queue
            SET status = 'pending_review', hitl_notes = $1, notes = $2
            WHERE id = $3 AND status = 'approved'
            """,
            note, (existing_notes + " | " if existing_notes else "") + note, queue_id,
        )
        return

    image_brief = {
        "image_id": None,
        "image_path": f"assets_library/{result['image_path'].relative_to(ASSETS_ROOT)}",
        "credit_line": None,
        "is_original": True,
        "selected_because": f"scene-gated generation, {result['scene_type'].lower()}, post-approval fallback",
        "generation_available": True,
    }

    if result["flagged_for_review"]:
        note = f"IMAGE RELEVANCE GATE FAILED after regeneration: {result['reason']}"
        existing_notes = row["notes"] or ""
        await conn.execute(
            """
            UPDATE linkedin_content_queue
            SET status = 'pending_review', hitl_notes = $1, notes = $2,
                image_brief = $3, image_description = $4
            WHERE id = $5 AND status = 'approved'
            """,
            note, (existing_notes + " | " if existing_notes else "") + note,
            image_brief, result["scene_description"], queue_id,
        )
        log.warning("[InternalMarketing] Queue row %s reverted to pending_review — %s", queue_id, note)
    else:
        await conn.execute(
            """
            UPDATE linkedin_content_queue
            SET image_brief = $1, image_description = $2
            WHERE id = $3 AND status = 'approved'
            """,
            image_brief, result["scene_description"], queue_id,
        )
        log.info("[InternalMarketing] Queue row %s: image generated and attached (%s)", queue_id, result["scene_type"])


async def _generate_images_in_background(db_pool, queue_ids: list[str]) -> None:
    """Sequential, one row at a time -- same accepted tradeoff as
    batch_approve_linkedin_queue's own loop (avoids concurrent Gemini rate-
    limit issues; this is a low-volume owner tool, not a high-throughput
    service). One row's failure never stops the rest."""
    for queue_id in queue_ids:
        try:
            async with db_pool.acquire() as conn:
                await _generate_and_gate_image_for_approved_row(conn, queue_id)
        except Exception as exc:  # noqa: BLE001 -- one row's failure must never stop the rest
            log.error("[InternalMarketing] Background image generation failed for %s: %s", queue_id, exc)


class GenerateImagesRequest(BaseModel):
    queue_ids: list[str]


@router.post("/linkedin-queue/generate-images")
async def generate_linkedin_queue_images(
    body: GenerateImagesRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_marketing_api_key),
) -> dict:
    """
    Fired by ceo-dashboard's own Next.js API routes (app/api/linkedin-queue/
    [id]/route.ts and .../batch-approve/route.ts) immediately after THEY flip
    a row's status to 'approved' via a direct Supabase write.

    Found 2026-09-16: those Next.js routes talk to Supabase directly and
    never call this router's own PATCH /linkedin-queue/{id} or POST
    /linkedin-queue/batch-approve at all (a 2026-07-24 comment in that
    Next.js code explains why: this backend was not yet deployed anywhere
    reachable at the time those routes were written). This backend IS live
    on Railway now, but the dashboard's approve buttons still never call it
    -- meaning _generate_and_gate_image_for_approved_row, wired into this
    same file's PATCH/batch-approve endpoints earlier the same day, was
    dead code in production the whole time. This endpoint is the fix: a
    narrow, server-to-server bridge the Next.js routes call right after
    their own Supabase write, gated by the shared X-API-Key
    (MARKETING_API_KEY) this repo already uses for exactly this kind of
    Next.js-to-FastAPI call (see api/routes/marketing.py's linkedin-on-demand
    route for the precedent), not get_internal_user (no Supabase session JWT
    exists in that server-to-server context).

    Runs every row as a background task and returns immediately --
    scheduling a 12-post batch's worth of sequential Gemini+Claude calls
    inline here would block the Next.js caller (and risk a serverless
    function timeout) for minutes. The dashboard shows each row as
    'approved' right away (that already happened, via Supabase, before this
    endpoint was even called); the image lands a short time later, or the
    row reverts to 'pending_review' with hitl_notes if the relevance gate
    fails twice -- same as the synchronous PATCH/batch-approve path.

    Does not itself flip anything to 'approved' -- assumes the caller
    already did that. _generate_and_gate_image_for_approved_row's own WHERE
    status = 'approved' guards are what make this safe to call for a row
    that isn't (or is no longer) actually approved: it's simply a no-op for
    that row rather than an error.
    """
    if not body.queue_ids:
        raise HTTPException(status_code=400, detail="queue_ids must be a non-empty list")
    db = request.app.state.db_pool
    background_tasks.add_task(_generate_images_in_background, db, body.queue_ids)
    return {"queued": len(body.queue_ids)}


class QueueRowUpdate(BaseModel):
    status: str | None = None
    hitl_notes: str | None = None
    scheduled_for: str | None = None


class BatchApproveRequest(BaseModel):
    batch_month: str


_VALID_STATUSES = {"pending_review", "approved", "rejected", "published"}


@router.get("/linkedin-queue")
async def list_linkedin_queue(
    request: Request,
    batch_month: str | None = None,
    status: str | None = None,
    user: dict = Depends(get_internal_user),
) -> dict:
    """Lists linkedin_content_queue rows for the dashboard's batch review
    view — optionally filtered to one batch_month and/or one status."""
    db = request.app.state.db_pool
    conditions = []
    params: list = []
    if batch_month:
        params.append(batch_month)
        conditions.append(f"batch_month = ${len(params)}")
    if status:
        params.append(status)
        conditions.append(f"status = ${len(params)}")
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with db.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, pillar, pillar_name, topic, post_copy, hook_variants,
                   format, image_brief, hitl_tier, status, hitl_notes,
                   batch_month, scheduled_for, published_at, created_at
            FROM linkedin_content_queue
            {where_clause}
            ORDER BY scheduled_for NULLS LAST, created_at
            """,
            *params,
        )
    return {"posts": [dict(r) for r in rows]}


@router.patch("/linkedin-queue/{queue_id}")
async def update_linkedin_queue_row(
    queue_id: str,
    body: QueueRowUpdate,
    request: Request,
    user: dict = Depends(get_internal_user),
) -> dict:
    """Approve/reject a single post, adjust its scheduled_for date, or add
    a reviewer note — the per-row review action in the dashboard's batch
    view. Never touches status='published' rows (a decision already
    executed isn't reversible through this endpoint)."""
    if body.status is not None and body.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(_VALID_STATUSES)}")

    fields: list[str] = []
    params: list = []

    def _set(column: str, value) -> None:
        params.append(value)
        fields.append(f"{column} = ${len(params)}")

    if body.status is not None:
        _set("status", body.status)
        fields.append("hitl_reviewed_at = now()")  # not a bound param — a literal SQL call, not a value
    if body.hitl_notes is not None:
        _set("hitl_notes", body.hitl_notes)
    if body.scheduled_for is not None:
        _set("scheduled_for", body.scheduled_for)

    if not fields:
        raise HTTPException(status_code=400, detail="Provide at least one of status/hitl_notes/scheduled_for")

    approving = body.status == "approved"

    db = request.app.state.db_pool
    params.append(queue_id)
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE linkedin_content_queue
            SET {', '.join(fields)}
            WHERE id = ${len(params)} AND status != 'published'
            RETURNING id, status, hitl_notes, scheduled_for
            """,
            *params,
        )
        if row is None:
            raise HTTPException(status_code=409, detail="Row not found, or already published (immutable)")

        if approving and row["status"] == "approved":
            await _generate_and_gate_image_for_approved_row(conn, queue_id)
            row = await conn.fetchrow(
                "SELECT id, status, hitl_notes, scheduled_for, image_brief FROM linkedin_content_queue WHERE id = $1",
                queue_id,
            )

    log.info("[InternalMarketing] Queue row %s updated: %s", queue_id, dict(row))
    return dict(row)


@router.post("/linkedin-queue/batch-approve")
async def batch_approve_linkedin_queue(
    body: BatchApproveRequest,
    request: Request,
    user: dict = Depends(get_internal_user),
) -> dict:
    """
    Approves every pending_review row in one batch_month in a single
    action — the "review once, it runs itself the rest of the month"
    step. This does NOT publish anything; it only flips status to
    'approved' so scripts/dispatch_scheduled_posts.py's cron can fire
    each row on its own scheduled_for date. Rejected/already-approved
    rows in the batch are left untouched.

    Runs image generation (see _generate_and_gate_image_for_approved_row)
    for every row this call approves, one at a time, before returning --
    a batch approval of N posts means N sequential Gemini + Claude calls
    in this one request, same "never publish an approved row with no
    image decision made" guarantee as the single-row PATCH endpoint. A
    row the gate flags is reverted to pending_review inside that helper
    and is reported separately below, not counted as approved.

    Known tradeoff, accepted for this owner-only, ~10-12-post-a-month
    tool: one pooled DB connection stays checked out for the whole loop
    (a monthly batch can take minutes of real external API time), which
    would be a real concern under concurrent traffic. If batch sizes or
    dashboard concurrency ever grow enough for this to matter, the fix
    is releasing/reacquiring the connection per row (or moving this to a
    background job the dashboard polls) rather than holding it — not
    something to build ahead of an actual need here.
    """
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            UPDATE linkedin_content_queue
            SET status = 'approved'
            WHERE batch_month = $1 AND status = 'pending_review'
            RETURNING id
            """,
            body.batch_month,
        )
        candidate_ids = [r["id"] for r in rows]

        for queue_id in candidate_ids:
            await _generate_and_gate_image_for_approved_row(conn, queue_id)

        final_rows = await conn.fetch(
            "SELECT id, status FROM linkedin_content_queue WHERE id = ANY($1::uuid[])",
            candidate_ids,
        )

    approved_ids = [r["id"] for r in final_rows if r["status"] == "approved"]
    reverted_ids = [r["id"] for r in final_rows if r["status"] != "approved"]
    log.info(
        "[InternalMarketing] Batch-approved %s posts for %s (%s reverted to pending_review by the image gate)",
        len(approved_ids), body.batch_month, len(reverted_ids),
    )
    return {
        "batch_month": body.batch_month,
        "approved_count": len(approved_ids),
        "approved_ids": approved_ids,
        "reverted_to_review_ids": reverted_ids,
    }


# ── Asset thumbnails (dashboard image preview) ─────────────────────────────

_ASSETS_LIBRARY_ROOT = (_REPO_ROOT / "assets_library").resolve()


@router.get("/assets/{asset_path:path}")
async def get_asset(asset_path: str, _: None = Depends(require_marketing_api_key)) -> FileResponse:
    """
    Serves one file from assets_library/ live off this backend's own
    filesystem, for the dashboard's image thumbnails — image_brief.
    image_path is stored as "assets_library/my_originals/foo.png"; the
    frontend strips the "assets_library/" prefix before requesting
    {asset_path} here.

    Real bug found live 2026-09-21: ceo-dashboard's own app/api/asset/
    [...path]/route.ts used to serve these from a git-committed snapshot
    bundled into its Vercel deployment at build time (outputFileTracingIncludes),
    a 2026-07-24 workaround from when this backend "had never been
    deployed anywhere reachable." It has been live on Railway since
    before 2026-09-16 (see generate_linkedin_queue_images's docstring
    below), making that workaround both obsolete and actively broken —
    any image generated after ceo-dashboard's last Vercel build (which is
    every image from a live run, since nothing auto-commits generated
    PNGs to git) 404'd as "image failed to load" in the review queue.
    ceo-dashboard's route.ts now proxies here server-to-server instead.

    Gated by require_marketing_api_key (same shared secret as this
    file's other server-to-server bridge, generate_linkedin_queue_images)
    rather than get_internal_user — the caller is now always
    ceo-dashboard's own Next.js route handler (which does its own session
    check via requireRole before proxying), never a browser request
    carrying a Supabase session token directly.

    Path traversal is blocked by resolving the requested path and
    confirming it's still inside _ASSETS_LIBRARY_ROOT before serving —
    asset_path comes straight from the URL, so "../../.env" must not
    resolve outside the vault.
    """
    requested = (_ASSETS_LIBRARY_ROOT / asset_path).resolve()
    if not requested.is_relative_to(_ASSETS_LIBRARY_ROOT):
        raise HTTPException(status_code=400, detail="Invalid asset path")
    if not requested.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")

    media_type = mimetypes.guess_type(str(requested))[0] or "application/octet-stream"
    return FileResponse(requested, media_type=media_type)
