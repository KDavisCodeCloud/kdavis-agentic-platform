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

GET /internal/marketing/connect/linkedin           - start LinkedIn OAuth
GET /internal/marketing/connect/callback/linkedin   - LinkedIn OAuth callback
GET /internal/marketing/connect/canva               - start Canva OAuth (PKCE)
GET /internal/marketing/connect/callback/canva      - Canva OAuth callback
GET /internal/marketing/connections                 - list connected platforms

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
import logging
import os
import secrets
import time

import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

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
