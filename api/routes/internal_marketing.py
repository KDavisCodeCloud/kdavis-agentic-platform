"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
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

import base64
import hashlib
import json
import logging
import mimetypes
import os
import secrets
import time
from pathlib import Path

import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from api.middleware.internal_auth import get_internal_user

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

# In-memory OAuth state store, same pattern + same caveat as content.py's
# _oauth_state_store: fine for a single-process, single-owner manual connect
# flow; does not survive a process restart mid-flow. State entries expire
# after 10 minutes so a stale/abandoned flow can't be replayed later.
_oauth_state_store: dict[str, float] = {}
_STATE_TTL_SECONDS = 600

# Separate store because Canva's PKCE flow needs the code_verifier back at
# the callback leg too, not just the state — keeping it alongside a plain
# timestamp (like _oauth_state_store) would conflate the two purposes.
_canva_pkce_store: dict[str, tuple[str, float]] = {}  # state -> (code_verifier, issued_at)


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
async def connect_linkedin(key: str) -> RedirectResponse:
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

    now = time.time()
    for s, ts in list(_oauth_state_store.items()):
        if now - ts > _STATE_TTL_SECONDS:
            _oauth_state_store.pop(s, None)

    state = secrets.token_urlsafe(32)
    _oauth_state_store[state] = now

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
    issued_at = _oauth_state_store.pop(state, None)
    if issued_at is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    if time.time() - issued_at > _STATE_TTL_SECONDS:
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
               encrypted_access_token, author_urn)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (platform)
            DO UPDATE SET
              platform_user_id = EXCLUDED.platform_user_id,
              platform_display_name = EXCLUDED.platform_display_name,
              encrypted_access_token = EXCLUDED.encrypted_access_token,
              author_urn = EXCLUDED.author_urn,
              updated_at = NOW()
            """,
            "linkedin", platform_user_id, display_name, encrypted_token, author_urn,
        )

    log.info("[InternalMarketing] LinkedIn connected — user=%s urn=%s", display_name, author_urn)
    return {
        "connected": True,
        "platform": "linkedin",
        "display_name": display_name,
        "author_urn": author_urn,
    }


@router.get("/connect/canva")
async def connect_canva(key: str) -> RedirectResponse:
    """
    Start Canva's OAuth 2.0 + PKCE flow. Same key= stopgap as
    connect_linkedin above — see that function's note.
    """
    admin_key = os.environ.get("ADMIN_BOOTSTRAP_KEY", "")
    if not admin_key or not secrets.compare_digest(key, admin_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid key")

    if not _CANVA_CLIENT_ID:
        raise HTTPException(status_code=503, detail="CANVA_CLIENT_ID not configured")

    now = time.time()
    for s, (_, ts) in list(_canva_pkce_store.items()):
        if now - ts > _STATE_TTL_SECONDS:
            _canva_pkce_store.pop(s, None)

    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = _generate_pkce_pair()
    _canva_pkce_store[state] = (code_verifier, now)

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
    entry = _canva_pkce_store.pop(state, None)
    if entry is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    code_verifier, issued_at = entry
    if time.time() - issued_at > _STATE_TTL_SECONDS:
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
            json.dumps(template_ids),
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

    li_access_token, author_urn = await _get_linkedin_connection(conn)
    if not author_urn:
        raise PublishError(409, "LinkedIn connection has no author_urn — reconnect")

    canva_access_token, brand_template_ids = await _get_canva_connection(conn)

    image_brief = row["image_brief"]
    post_type = "linkedin_header" if row["format"] == "document_carousel" else "linkedin_square"
    brand_template_id = brand_template_ids.get(post_type)

    from core.publishers.linkedin import post_image, post_text

    used_image_id = None
    try:
        if image_brief and image_brief.get("image_path"):
            image_path = _REPO_ROOT / image_brief["image_path"]
            if not image_path.exists():
                raise FileNotFoundError(f"Asset vault image not found on disk: {image_path}")
            image_bytes = image_path.read_bytes()
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
    approved_ids = [r["id"] for r in rows]
    log.info("[InternalMarketing] Batch-approved %s posts for %s", len(approved_ids), body.batch_month)
    return {"batch_month": body.batch_month, "approved_count": len(approved_ids), "approved_ids": approved_ids}


# ── Asset thumbnails (dashboard image preview) ─────────────────────────────

_ASSETS_LIBRARY_ROOT = (_REPO_ROOT / "assets_library").resolve()


@router.get("/assets/{asset_path:path}")
async def get_asset(asset_path: str, user: dict = Depends(get_internal_user)) -> FileResponse:
    """
    Serves one file from assets_library/ for the dashboard's image
    thumbnails — image_brief.image_path is stored as
    "assets_library/my_originals/foo.png"; the frontend strips the
    "assets_library/" prefix before requesting {asset_path} here.

    Gated by get_internal_user, same as every other route in this file —
    a plain <img src="..."> can't carry a Bearer token, so the frontend
    fetches this authenticated and renders the bytes as a blob URL rather
    than this endpoint being left open (these are pre-publish marketing
    images, low sensitivity, but there's no reason to be the one
    unauthenticated hole in this router when the fetch-and-blob pattern
    costs only a few more lines client-side).

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
