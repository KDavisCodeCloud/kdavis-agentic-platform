"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Customer-facing workspace membership routes -- Membership/SSO/RBAC/SCIM
plan, Phase A. Generalizes the Enterprise-only, admin-provisioned
mcp-invite pattern (api/routes/internal_workspaces.py) into a real,
self-serve product feature: any workspace can invite teammates with
their own Supabase Auth login, not just a shared X-Workspace-Token.

POST /workspace-members/invite  -- invite a teammate (bootstrap: token
                                    or an existing active admin member)
GET  /workspace-members         -- list the caller's workspace's members
POST /workspace-members/accept  -- invited user accepts, links their
                                    fresh Supabase session to their row

This table has ZERO role enforcement beyond "must be an active member to
list, must be admin (or hold the bootstrap token) to invite" -- Phase C
(RBAC) is where role-gated actions beyond invite get built. role today
is just 'admin' | 'member', stored for that future phase to read.
"""

import logging
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from api.middleware.auth import get_workspace_or_member

log = logging.getLogger(__name__)
router = APIRouter(prefix="/workspace-members", tags=["workspace-members"])

_VALID_ROLES = frozenset({"admin", "member"})

# Deliberately simple shape check, not full RFC 5322 -- matches
# api/routes/workspaces.py's own _EMAIL_RE convention: this codebase has
# no email-validator dependency (pydantic.EmailStr would need it), so
# reject obvious garbage without pulling in a new package for one field.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


# ── Request / response models ─────────────────────────────────────────────────

class InviteMemberRequest(BaseModel):
    email: str
    role: str = "member"

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        if not _EMAIL_RE.match(v):
            raise ValueError("not a valid email address")
        return v


class MemberResponse(BaseModel):
    id: str
    email: str
    role: str
    status: str
    invited_at: str | None = None
    joined_at: str | None = None


class AcceptInviteResponse(BaseModel):
    id: str
    workspace_id: str
    email: str
    role: str
    status: str


# ── Helpers ─────────────────────────────────────────────────────────────────

def _caller_is_authorized_to_invite(workspace: dict) -> bool:
    """
    True if this request authenticated via the shared workspace token
    (bootstrap path -- no members exist yet, or an integration/CI system
    holding the token) or via an active member session with role='admin'.
    A non-admin member session (member_role present and != 'admin') is
    rejected.
    """
    member_role = workspace.get("member_role")
    if member_role is None:
        return True  # token-authenticated -- bootstrap/integration path
    return member_role == "admin"


async def _get_member_row(conn, supabase_user_id) -> dict | None:
    row = await conn.fetchrow(
        "SELECT id, workspace_id, email, role, status FROM workspace_members "
        "WHERE supabase_user_id = $1",
        supabase_user_id,
    )
    return dict(row) if row else None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/invite", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def invite_member(
    body: InviteMemberRequest,
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
) -> MemberResponse:
    if body.role not in _VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"role must be one of {sorted(_VALID_ROLES)}",
        )
    if not _caller_is_authorized_to_invite(workspace):
        raise HTTPException(
            status_code=403,
            detail="Only a workspace admin can invite members",
        )

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM workspace_members WHERE workspace_id = $1 AND email = $2",
            workspace["id"], body.email,
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"{body.email} is already a member (or invited) at this workspace",
            )

        row = await conn.fetchrow(
            """
            INSERT INTO workspace_members (workspace_id, email, role, status)
            VALUES ($1, $2, $3, 'invited')
            RETURNING id, email, role, status, invited_at, joined_at
            """,
            workspace["id"], body.email, body.role,
        )

    # Lazy import -- matches this repo's convention (auth.py,
    # internal_workspaces.py) of never importing third-party clients at
    # module top level.
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not service_key:
        log.error("[WorkspaceMembers] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured")
        raise HTTPException(status_code=500, detail="Member invites are not configured on this server")

    client = create_client(url, service_key)
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    try:
        client.auth.admin.invite_user_by_email(
            body.email,
            {"redirect_to": f"{frontend_url}/accept-invite"},
        )
    except Exception as exc:
        # The workspace_members row already exists (status='invited') --
        # deliberately NOT rolled back: a resend can be built later
        # (re-call invite_user_by_email for an existing 'invited' row)
        # without losing the fact that this person was invited.
        log.error("[WorkspaceMembers] Supabase invite email failed for %s: %s", body.email, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Member record created but the invite email failed to send: {exc}",
        ) from exc

    log.info(
        "[WorkspaceMembers] Invited email=%s role=%s workspace=%s",
        body.email, body.role, workspace["id"],
        extra={"workspace_id": str(workspace["id"]), "invited_email": body.email, "invited_role": body.role},
    )

    return MemberResponse(
        id=str(row["id"]),
        email=row["email"],
        role=row["role"],
        status=row["status"],
        invited_at=row["invited_at"].isoformat() if row["invited_at"] else None,
        joined_at=row["joined_at"].isoformat() if row["joined_at"] else None,
    )


@router.get("", response_model=list[MemberResponse])
async def list_members(
    request: Request,
    workspace: dict = Depends(get_workspace_or_member),
) -> list[MemberResponse]:
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, email, role, status, invited_at, joined_at FROM workspace_members "
            "WHERE workspace_id = $1 ORDER BY created_at ASC",
            workspace["id"],
        )
    return [
        MemberResponse(
            id=str(r["id"]),
            email=r["email"],
            role=r["role"],
            status=r["status"],
            invited_at=r["invited_at"].isoformat() if r["invited_at"] else None,
            joined_at=r["joined_at"].isoformat() if r["joined_at"] else None,
        )
        for r in rows
    ]


@router.post("/accept", response_model=AcceptInviteResponse)
async def accept_invite(request: Request) -> AcceptInviteResponse:
    """
    The invited person calls this once, right after setting their
    password via Supabase's own invite-accept flow (client-side,
    triggered by the link Supabase emailed them) establishes a real
    Supabase session for them. Authenticated by that fresh session's
    Bearer token -- NOT by get_workspace_member(), since this row's
    supabase_user_id is still NULL at this point (that's exactly what
    this endpoint sets). The one place this table matches on email
    instead of supabase_user_id -- see migration 033's own comment.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization: Bearer <session token> required")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authorization: Bearer <session token> required")

    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not service_key:
        log.error("[WorkspaceMembers] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured")
        raise HTTPException(status_code=500, detail="Member auth is not configured on this server")

    client = create_client(url, service_key)
    try:
        user_resp = client.auth.get_user(token)
    except Exception:
        log.warning("[WorkspaceMembers] accept: session token verification failed")
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    user = getattr(user_resp, "user", None)
    if not user or not user.email:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, workspace_id, email, role, status FROM workspace_members "
            "WHERE email = $1 AND status = 'invited'",
            user.email,
        )
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"No pending invite found for {user.email}",
            )

        updated = await conn.fetchrow(
            """
            UPDATE workspace_members
            SET supabase_user_id = $1, status = 'active', joined_at = NOW()
            WHERE id = $2
            RETURNING id, workspace_id, email, role, status
            """,
            user.id, row["id"],
        )

    log.info(
        "[WorkspaceMembers] Invite accepted email=%s workspace=%s",
        user.email, updated["workspace_id"],
        extra={"workspace_id": str(updated["workspace_id"]), "member_email": user.email},
    )

    return AcceptInviteResponse(
        id=str(updated["id"]),
        workspace_id=str(updated["workspace_id"]),
        email=updated["email"],
        role=updated["role"],
        status=updated["status"],
    )
