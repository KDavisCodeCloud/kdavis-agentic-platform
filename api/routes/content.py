"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
Content pipeline routes.

POST /content/generate                    — start brief→draft→review pipeline
GET  /content/drafts                      — list drafts for workspace
GET  /content/drafts/{id}                 — get single draft with full pipeline output
POST /content/drafts/{id}/approve         — approve (optionally with edit), triggers publish
POST /content/drafts/{id}/reject          — reject with feedback
GET  /content/connect/linkedin            — start LinkedIn OAuth 2.0 flow
GET  /content/connect/callback/linkedin   — LinkedIn OAuth callback (stores token)
GET  /content/connect/x                  — start X OAuth 2.0 PKCE flow
GET  /content/connect/callback/x         — X OAuth callback (stores token)
GET  /content/connections                 — list connected social accounts

COMPLIANCE: All platform publish actions post through official OAuth APIs only.
Connection request automation, DM sending, auto-engagement, profile scraping,
browser session simulation, and credential storage are explicitly NOT implemented.
Any future change that would require these must be flagged and blocked.
"""

import json
import logging
import os
import secrets
import sys
from pathlib import Path
from typing import Optional
from uuid import UUID

import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from api.middleware.auth import get_workspace
from core.compliance import WorkspaceComplianceGuard, SubscriptionError
from core.security import shield
from db.content_models import (
    ContentDraftCreate,
    ContentDraftApprove,
    ContentDraftReject,
    DRAFT_GENERATING,
    DRAFT_PENDING,
    DRAFT_APPROVED,
    DRAFT_PUBLISHING,
    DRAFT_PUBLISHED,
    DRAFT_REJECTED,
    DRAFT_FAILED,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/content", tags=["content"])

# ── Agent path resolution ─────────────────────────────────────────────────────

_ROOT = Path(__file__).parent.parent.parent
_CONTENT_AGENTS = _ROOT / "agents" / "content"
sys.path.insert(0, str(_ROOT / ".llm"))


def _load_agent(name: str):
    """Dynamically import a content agent module by folder name."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        name, _CONTENT_AGENTS / name / "agent.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Encryption helpers ────────────────────────────────────────────────────────

def _fernet() -> Fernet:
    key = os.environ.get("ENCRYPTION_KEY", "")
    if not key:
        raise EnvironmentError("ENCRYPTION_KEY not set")
    return Fernet(key.encode() if isinstance(key, str) else key)


def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


# ── OAuth configuration ───────────────────────────────────────────────────────

_FRONTEND_URL  = os.environ.get("FRONTEND_URL", "http://localhost:3000")
_API_BASE      = os.environ.get("API_BASE_URL", "http://localhost:8000")

_LI_CLIENT_ID     = os.environ.get("LINKEDIN_CLIENT_ID", "")
_LI_CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
_LI_REDIRECT      = f"{_API_BASE}/api/v1/content/connect/callback/linkedin"
_LI_SCOPES        = "openid profile w_member_social"

_X_CLIENT_ID      = os.environ.get("X_CLIENT_ID", "")
_X_CLIENT_SECRET  = os.environ.get("X_CLIENT_SECRET", "")
_X_REDIRECT       = f"{_API_BASE}/api/v1/content/connect/callback/x"
_X_SCOPES         = "tweet.write users.read offline.access"

# In-memory PKCE/state store (process-local; fine for single-instance dev)
# In production: move to Redis with TTL
_oauth_state_store: dict[str, dict] = {}


# ── Impact scoring ────────────────────────────────────────────────────────────

def _compute_impact(brand_score: Optional[int], align_score: Optional[int], platform: str) -> dict:
    """
    Directional impact estimate based on review-agent quality scores.
    Honest copy only — not a guarantee of actual reach.
    """
    if brand_score is None or align_score is None:
        return {"tier": "unknown", "label": "Not yet scored", "description": ""}

    combined = (brand_score + align_score) / 2

    reach_ranges = {
        "linkedin": {
            "strong": "500–2,000 impressions",
            "solid":  "150–500 impressions",
            "weak":   "under 150 impressions",
        },
        "x": {
            "strong": "300–1,500 impressions",
            "solid":  "50–300 impressions",
            "weak":   "under 50 impressions",
        },
        "video": {
            "strong": "1,000–5,000 views",
            "solid":  "200–1,000 views",
            "weak":   "under 200 views",
        },
    }

    ranges = reach_ranges.get(platform, reach_ranges["linkedin"])

    if combined >= 8:
        tier, label = "strong", "Strong"
        reach = ranges["strong"]
        desc = f"High-quality hook and brief alignment. Estimated organic reach: {reach}. Directional only."
    elif combined >= 6:
        tier, label = "solid", "Solid"
        reach = ranges["solid"]
        desc = f"Meets brand voice standards. Estimated organic reach: {reach}. Directional only."
    else:
        tier, label = "weak", "Needs work"
        reach = ranges["weak"]
        desc = f"Review flags present. Below-average reach likely: {reach}. Consider revising before posting."

    return {"tier": tier, "label": label, "description": desc, "combined_score": round(combined, 1)}


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _create_draft(db_pool, workspace_id: str, platform: str, raw_idea: str, goal: str,
                         target_audience: str, additional_constraints: str) -> str:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO content_drafts
              (workspace_id, platform, raw_idea, goal, target_audience,
               additional_constraints, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            UUID(workspace_id), platform, raw_idea, goal,
            target_audience, additional_constraints, DRAFT_GENERATING,
        )
    return str(row["id"])


async def _update_draft(db_pool, draft_id: str, **fields) -> None:
    if not fields:
        return
    sets, params = [], []
    i = 1
    for k, v in fields.items():
        sets.append(f"{k} = ${i}")
        params.append(json.dumps(v) if isinstance(v, dict) else v)
        i += 1
    sets.append("updated_at = NOW()")
    params.append(UUID(draft_id))
    sql = f"UPDATE content_drafts SET {', '.join(sets)} WHERE id = ${i}"
    async with db_pool.acquire() as conn:
        await conn.execute(sql, *params)


async def _get_draft(db_pool, draft_id: str, workspace_id: str) -> dict:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM content_drafts WHERE id = $1 AND workspace_id = $2",
            UUID(draft_id), UUID(workspace_id),
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    d = dict(row)
    for f in ("brief", "draft_output", "review_output", "publish_package"):
        if d.get(f) and isinstance(d[f], str):
            d[f] = json.loads(d[f])
    return d


async def _get_social_connection(db_pool, workspace_id: str, platform: str) -> Optional[dict]:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM workspace_social_connections WHERE workspace_id = $1 AND platform = $2",
            UUID(workspace_id), platform,
        )
    return dict(row) if row else None


# ── Pipeline background task ──────────────────────────────────────────────────

async def _run_pipeline(app, draft_id: str, workspace_id: str,
                         platform: str, raw_idea: str, goal: str,
                         target_audience: str, additional_constraints: str) -> None:
    """
    Runs brief → draft → review agents sequentially in the background.
    Updates content_drafts row at each step; sets status to pending_review on completion.
    """
    db = app.state.db_pool

    try:
        # Sanitize inputs before sending to LLM
        safe_idea = shield.sanitize(raw_idea, context="content_brief").sanitized_text
        safe_constraints = shield.sanitize(additional_constraints, context="content_brief").sanitized_text

        # ── Brief agent ──────────────────────────────────────────────────────
        brief_agent = _load_agent("brief-agent")
        brief = brief_agent.run(
            raw_idea=safe_idea,
            platform=platform,
            goal=goal,
            target_audience=target_audience,
            additional_constraints=safe_constraints,
        )
        await _update_draft(db, draft_id, brief=brief)
        log.info("[Content] Draft %s — brief complete", draft_id[:8])

        # ── Draft agent ──────────────────────────────────────────────────────
        draft_agent = _load_agent("draft-agent")
        draft_output = draft_agent.run(brief=brief)
        await _update_draft(db, draft_id, draft_output=draft_output)
        log.info("[Content] Draft %s — draft complete", draft_id[:8])

        # ── Review agent ─────────────────────────────────────────────────────
        review_agent = _load_agent("review-agent")
        draft_text = (draft_output.get("draft_a") or {}).get("text", "")
        review_output = review_agent.run(
            draft_text=draft_text,
            brief=brief,
            platform=platform,
        )

        brand_score = review_output.get("brand_voice_score")
        align_score = review_output.get("brief_alignment_score")

        await _update_draft(
            db, draft_id,
            review_output=review_output,
            status=DRAFT_PENDING,
            brand_voice_score=brand_score,
            brief_alignment_score=align_score,
        )
        log.info("[Content] Draft %s — review complete, status=pending_review", draft_id[:8])

    except Exception as exc:
        log.error("[Content] Pipeline failed for draft %s: %s", draft_id[:8], exc)
        await _update_draft(db, draft_id, status=DRAFT_FAILED)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/generate", status_code=202)
async def generate_draft(
    body: ContentDraftCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    workspace: dict = Depends(get_workspace),
) -> dict:
    """
    Start the brief → draft → review pipeline for a new piece of content.

    Returns draft_id immediately — poll GET /content/drafts/{id} for status.
    Status moves from 'generating' → 'pending_review' when the pipeline completes.
    """
    workspace_id = str(workspace["id"])

    async with request.app.state.db_pool.acquire() as conn:
        compliance = WorkspaceComplianceGuard(conn)
        try:
            await compliance.assert_workspace_active(workspace_id)
        except SubscriptionError as exc:
            raise HTTPException(status_code=402, detail=str(exc))

    draft_id = await _create_draft(
        request.app.state.db_pool,
        workspace_id,
        body.platform,
        body.raw_idea,
        body.goal,
        body.target_audience,
        body.additional_constraints,
    )

    background_tasks.add_task(
        _run_pipeline,
        request.app,
        draft_id,
        workspace_id,
        body.platform,
        body.raw_idea,
        body.goal,
        body.target_audience,
        body.additional_constraints,
    )

    log.info("[Content] Draft %s queued — workspace=%s platform=%s", draft_id[:8], workspace_id[:8], body.platform)
    return {"draft_id": draft_id, "status": DRAFT_GENERATING, "message": "Pipeline started. Poll GET /content/drafts/{id} for status."}


@router.get("/drafts")
async def list_drafts(
    request: Request,
    status_filter: Optional[str] = None,
    workspace: dict = Depends(get_workspace),
) -> list:
    """List content drafts for this workspace, newest first."""
    workspace_id = str(workspace["id"])
    sql = "SELECT * FROM content_drafts WHERE workspace_id = $1"
    params = [UUID(workspace_id)]

    if status_filter:
        sql += " AND status = $2"
        params.append(status_filter)

    sql += " ORDER BY created_at DESC LIMIT 50"

    async with request.app.state.db_pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    results = []
    for row in rows:
        d = dict(row)
        brief = d.get("brief")
        if brief and isinstance(brief, str):
            brief = json.loads(brief)
        results.append({
            "id": str(d["id"]),
            "platform": d["platform"],
            "raw_idea": d["raw_idea"][:120] + "..." if len(d["raw_idea"]) > 120 else d["raw_idea"],
            "goal": d["goal"],
            "status": d["status"],
            "brand_voice_score": d.get("brand_voice_score"),
            "brief_alignment_score": d.get("brief_alignment_score"),
            "brief_title": (brief or {}).get("brief_title") if isinstance(brief, dict) else None,
            "impact": _compute_impact(d.get("brand_voice_score"), d.get("brief_alignment_score"), d["platform"]),
            "created_at": d["created_at"].isoformat(),
            "updated_at": d["updated_at"].isoformat(),
        })

    return results


@router.get("/drafts/{draft_id}")
async def get_draft(
    draft_id: str,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> dict:
    """Get a single content draft with full pipeline output."""
    workspace_id = str(workspace["id"])
    d = await _get_draft(request.app.state.db_pool, draft_id, workspace_id)

    return {
        "id": str(d["id"]),
        "platform": d["platform"],
        "raw_idea": d["raw_idea"],
        "goal": d["goal"],
        "status": d["status"],
        "brief": d.get("brief"),
        "draft_output": d.get("draft_output"),
        "review_output": d.get("review_output"),
        "publish_package": d.get("publish_package"),
        "selected_draft": d.get("selected_draft"),
        "operator_edit": d.get("operator_edit"),
        "rejection_feedback": d.get("rejection_feedback"),
        "brand_voice_score": d.get("brand_voice_score"),
        "brief_alignment_score": d.get("brief_alignment_score"),
        "impact": _compute_impact(d.get("brand_voice_score"), d.get("brief_alignment_score"), d["platform"]),
        "linkedin_post_id": d.get("linkedin_post_id"),
        "x_post_id": d.get("x_post_id"),
        "created_at": d["created_at"].isoformat(),
        "updated_at": d["updated_at"].isoformat(),
    }


@router.post("/drafts/{draft_id}/approve")
async def approve_draft(
    draft_id: str,
    body: ContentDraftApprove,
    request: Request,
    background_tasks: BackgroundTasks,
    workspace: dict = Depends(get_workspace),
) -> dict:
    """
    Approve a content draft and trigger publishing.

    selected_draft: "draft_a" or "draft_b" — which variation to post
    operator_edit:  optional override text — if provided, posts this text instead

    The publish step calls the official LinkedIn or X API with the stored OAuth token.
    If no OAuth token is connected for the platform, returns 424 with instructions.
    """
    workspace_id = str(workspace["id"])
    db = request.app.state.db_pool
    d = await _get_draft(db, draft_id, workspace_id)

    if d["status"] != DRAFT_PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Draft is in '{d['status']}' state — only 'pending_review' drafts can be approved",
        )

    # Determine final text to post
    draft_output = d.get("draft_output") or {}
    if body.operator_edit:
        final_text = body.operator_edit
    else:
        variant = draft_output.get(body.selected_draft, {})
        final_text = variant.get("text", "") if isinstance(variant, dict) else ""

    if not final_text:
        raise HTTPException(status_code=400, detail="No text found for selected draft variant")

    # Run publish-agent to prepare the package
    publish_agent = _load_agent("publish-agent")
    brief = d.get("brief") or {}
    publish_package = publish_agent.run(
        approved_draft=final_text,
        platform=d["platform"],
        brief=brief,
    )

    await _update_draft(
        db, draft_id,
        status=DRAFT_APPROVED,
        selected_draft=body.selected_draft,
        operator_edit=body.operator_edit,
        publish_package=publish_package,
    )

    # Check for social connection
    connection = await _get_social_connection(db, workspace_id, d["platform"])
    if not connection:
        return {
            "draft_id": draft_id,
            "status": DRAFT_APPROVED,
            "message": (
                f"Draft approved. No {d['platform']} account connected. "
                f"Connect at GET /content/connect/{d['platform']} then re-approve."
            ),
            "publish_package": publish_package,
        }

    # Trigger publish in background
    background_tasks.add_task(
        _publish_draft,
        request.app,
        draft_id,
        workspace_id,
        d["platform"],
        final_text,
        connection,
    )

    return {
        "draft_id": draft_id,
        "status": DRAFT_PUBLISHING,
        "message": f"Publishing to {d['platform']}. Poll GET /content/drafts/{draft_id} for result.",
    }


@router.post("/drafts/{draft_id}/reject")
async def reject_draft(
    draft_id: str,
    body: ContentDraftReject,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> dict:
    """
    Reject a draft with feedback. Optionally re-run the draft agent with the feedback.
    """
    workspace_id = str(workspace["id"])
    db = request.app.state.db_pool
    d = await _get_draft(db, draft_id, workspace_id)

    if d["status"] not in (DRAFT_PENDING, DRAFT_APPROVED):
        raise HTTPException(
            status_code=409,
            detail=f"Draft is in '{d['status']}' state — cannot reject",
        )

    await _update_draft(db, draft_id, status=DRAFT_REJECTED, rejection_feedback=body.feedback)
    log.info("[Content] Draft %s rejected — feedback recorded", draft_id[:8])

    return {
        "draft_id": draft_id,
        "status": DRAFT_REJECTED,
        "message": "Draft rejected. Create a new draft via POST /content/generate with updated constraints.",
    }


# ── Publish background task ───────────────────────────────────────────────────

async def _publish_draft(app, draft_id: str, workspace_id: str,
                          platform: str, text: str, connection: dict) -> None:
    """Post to LinkedIn or X using the stored OAuth token."""
    db = app.state.db_pool

    try:
        await _update_draft(db, draft_id, status=DRAFT_PUBLISHING)
        access_token = _decrypt(connection["encrypted_access_token"])

        if platform == "linkedin":
            from core.publishers.linkedin import post_text
            author_urn = connection.get("author_urn", "")
            if not author_urn:
                raise ValueError("LinkedIn author URN not stored — reconnect your LinkedIn account")
            result = await post_text(access_token, author_urn, text)
            await _update_draft(db, draft_id, status=DRAFT_PUBLISHED, linkedin_post_id=result["post_id"])

        elif platform == "x":
            from core.publishers.x import post_tweet
            result = await post_tweet(access_token, text)
            await _update_draft(db, draft_id, status=DRAFT_PUBLISHED, x_post_id=result["post_id"])

        else:
            raise ValueError(f"Unsupported platform for API publishing: {platform}")

        log.info("[Content] Draft %s published to %s — post_id=%s",
                 draft_id[:8], platform, result.get("post_id", "?"))

    except Exception as exc:
        log.error("[Content] Publish failed for draft %s: %s", draft_id[:8], exc)
        await _update_draft(db, draft_id, status=DRAFT_FAILED)


# ── OAuth — LinkedIn ──────────────────────────────────────────────────────────

@router.get("/connect/linkedin")
async def connect_linkedin(
    workspace: dict = Depends(get_workspace),
) -> RedirectResponse:
    """
    Start LinkedIn OAuth 2.0 flow. Redirects user to LinkedIn authorization page.
    Required scopes: openid profile w_member_social
    """
    if not _LI_CLIENT_ID:
        raise HTTPException(status_code=503, detail="LINKEDIN_CLIENT_ID not configured")

    state = secrets.token_urlsafe(32)
    workspace_id = str(workspace["id"])
    _oauth_state_store[state] = {"workspace_id": workspace_id, "platform": "linkedin"}

    params = (
        f"response_type=code"
        f"&client_id={_LI_CLIENT_ID}"
        f"&redirect_uri={_LI_REDIRECT}"
        f"&scope={_LI_SCOPES.replace(' ', '%20')}"
        f"&state={state}"
    )
    return RedirectResponse(f"https://www.linkedin.com/oauth/v2/authorization?{params}")


@router.get("/connect/callback/linkedin")
async def linkedin_callback(
    code: str,
    state: str,
    request: Request,
) -> RedirectResponse:
    """LinkedIn OAuth callback — exchanges code for token and stores encrypted."""
    stored = _oauth_state_store.pop(state, None)
    if not stored:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    workspace_id = stored["workspace_id"]

    # Exchange code for access token
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

    # Get author URN
    from core.publishers.linkedin import get_author_urn
    author_urn = await get_author_urn(access_token)

    # Get display name
    async with httpx.AsyncClient(timeout=15) as client:
        profile_resp = await client.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}", "LinkedIn-Version": "202501"},
        )
        profile = profile_resp.json()

    display_name = profile.get("name", "")
    platform_user_id = profile.get("sub", "")

    encrypted_token = _encrypt(access_token)

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO workspace_social_connections
              (workspace_id, platform, platform_user_id, platform_display_name,
               encrypted_access_token, author_urn)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (workspace_id, platform)
            DO UPDATE SET
              platform_user_id = EXCLUDED.platform_user_id,
              platform_display_name = EXCLUDED.platform_display_name,
              encrypted_access_token = EXCLUDED.encrypted_access_token,
              author_urn = EXCLUDED.author_urn,
              connected_at = NOW()
            """,
            UUID(workspace_id), "linkedin", platform_user_id,
            display_name, encrypted_token, author_urn,
        )

    log.info("[Content] LinkedIn connected — workspace=%s user=%s", workspace_id[:8], display_name)
    return RedirectResponse(f"{_FRONTEND_URL}/dashboard?connected=linkedin")


# ── OAuth — X ─────────────────────────────────────────────────────────────────

@router.get("/connect/x")
async def connect_x(
    workspace: dict = Depends(get_workspace),
) -> RedirectResponse:
    """
    Start X OAuth 2.0 PKCE flow. Redirects user to X authorization page.
    Required scopes: tweet.write users.read offline.access
    """
    if not _X_CLIENT_ID:
        raise HTTPException(status_code=503, detail="X_CLIENT_ID not configured")

    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)

    import hashlib, base64
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()

    workspace_id = str(workspace["id"])
    _oauth_state_store[state] = {
        "workspace_id": workspace_id,
        "platform": "x",
        "code_verifier": code_verifier,
    }

    params = (
        f"response_type=code"
        f"&client_id={_X_CLIENT_ID}"
        f"&redirect_uri={_X_REDIRECT}"
        f"&scope={_X_SCOPES.replace(' ', '%20')}"
        f"&state={state}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )
    return RedirectResponse(f"https://twitter.com/i/oauth2/authorize?{params}")


@router.get("/connect/callback/x")
async def x_callback(
    code: str,
    state: str,
    request: Request,
) -> RedirectResponse:
    """X OAuth callback — exchanges code for token and stores encrypted."""
    stored = _oauth_state_store.pop(state, None)
    if not stored:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    workspace_id = stored["workspace_id"]
    code_verifier = stored["code_verifier"]

    async with httpx.AsyncClient(timeout=30) as client:
        token_resp = await client.post(
            "https://api.twitter.com/2/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _X_REDIRECT,
                "code_verifier": code_verifier,
                "client_id": _X_CLIENT_ID,
            },
            auth=(_X_CLIENT_ID, _X_CLIENT_SECRET),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()

    access_token = token_data["access_token"]

    # Get user info
    async with httpx.AsyncClient(timeout=15) as client:
        user_resp = await client.get(
            "https://api.twitter.com/2/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_data = user_resp.json().get("data", {})

    platform_user_id = user_data.get("id", "")
    display_name = user_data.get("username", "")

    encrypted_token = _encrypt(access_token)

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO workspace_social_connections
              (workspace_id, platform, platform_user_id, platform_display_name,
               encrypted_access_token)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (workspace_id, platform)
            DO UPDATE SET
              platform_user_id = EXCLUDED.platform_user_id,
              platform_display_name = EXCLUDED.platform_display_name,
              encrypted_access_token = EXCLUDED.encrypted_access_token,
              connected_at = NOW()
            """,
            UUID(workspace_id), "x", platform_user_id,
            display_name, encrypted_token,
        )

    log.info("[Content] X connected — workspace=%s user=@%s", workspace_id[:8], display_name)
    return RedirectResponse(f"{_FRONTEND_URL}/dashboard?connected=x")


@router.get("/connections")
async def list_connections(
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> list:
    """List connected social accounts (tokens not exposed)."""
    workspace_id = str(workspace["id"])
    async with request.app.state.db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT platform, platform_display_name, platform_user_id, connected_at "
            "FROM workspace_social_connections WHERE workspace_id = $1",
            UUID(workspace_id),
        )
    return [
        {
            "platform": r["platform"],
            "display_name": r["platform_display_name"],
            "user_id": r["platform_user_id"],
            "connected_at": r["connected_at"].isoformat(),
        }
        for r in rows
    ]
