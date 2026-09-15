"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

SCIM 2.0 user provisioning -- Membership/SSO/RBAC/SCIM plan, Phase E.

An IdP already wired to this workspace's SSO connection (Phase D) can
push user lifecycle events here instead of an admin manually managing
workspace_members: hire -> POST creates an active member, deprovision ->
PATCH/DELETE deactivates one. Maps directly onto Phase A's
workspace_members table -- no new data model.

GET    /scim/v2/Users          -- list, supports ?filter=userName eq "x"
                                   (the one filter shape Okta/Azure AD
                                   actually send in practice, for a
                                   pre-create dedup check)
POST   /scim/v2/Users          -- create (role defaults to 'viewer' --
                                   least-privilege; promote via the
                                   existing invite/member endpoints)
GET    /scim/v2/Users/{id}
PUT    /scim/v2/Users/{id}     -- full replace of email/displayName/active
PATCH  /scim/v2/Users/{id}     -- the standard Okta/Azure AD deprovision
                                   op: {"Operations":[{"op":"replace",
                                   "path":"active","value":false}]}
DELETE /scim/v2/Users/{id}     -- deactivates, does NOT hard-delete --
                                   matches this codebase's existing
                                   "archival, not hard deletion" model
                                   (docs/customer/dpa-outline.md)

Authenticated by get_workspace_by_scim_token (api/middleware/auth.py) --
NOT the shared workspace token, NOT a Supabase member session. A SCIM
connector is provisioned its own bearer token via POST /internal/
workspaces/{id}/sso-config/scim-token.

SCIM 2.0 core schema (RFC 7643/7644) -- a deliberately pragmatic subset
covering what real IdP connectors actually send, not the full spec
(no Groups resource, no ServiceProviderConfig/Schemas/ResourceTypes
discovery endpoints, no complex filter grammar beyond the one shape
above). Extend if a real IdP integration hits something this doesn't
cover.
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.middleware.auth import get_workspace_by_scim_token

log = logging.getLogger(__name__)
router = APIRouter(prefix="/scim/v2", tags=["scim"])

_SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
_SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"


class ScimCreateUserRequest(BaseModel):
    userName: str  # SCIM convention -- the email address
    displayName: str | None = None
    active: bool = True


class ScimPatchOperation(BaseModel):
    op: str
    path: str | None = None
    value: Any = None


class ScimPatchRequest(BaseModel):
    Operations: list[ScimPatchOperation]


def _member_to_scim(member: dict) -> dict:
    return {
        "schemas": [_SCIM_USER_SCHEMA],
        "id": str(member["id"]),
        "userName": member["email"],
        "displayName": member["email"],
        "active": member["status"] != "deactivated",
        "emails": [{"value": member["email"], "primary": True}],
        "meta": {
            "resourceType": "User",
            "created": member["created_at"].isoformat() if member.get("created_at") else None,
            "lastModified": member["updated_at"].isoformat() if member.get("updated_at") else None,
        },
    }


def _scim_error(detail: str, status_code: int) -> HTTPException:
    """SCIM error responses have their own schema (RFC 7644 §3.12) --
    IdP connectors parse `detail`/`status`, not a generic FastAPI
    {"detail": ...} body."""
    return HTTPException(
        status_code=status_code,
        detail={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
            "detail": detail,
            "status": str(status_code),
        },
    )


@router.get("/Users")
async def list_users(
    request: Request,
    filter: str | None = None,
    startIndex: int = 1,
    count: int = 100,
    scim_auth: dict = Depends(get_workspace_by_scim_token),
) -> dict:
    db = request.app.state.db_pool
    workspace_id = scim_auth["workspace_id"]

    email_filter = None
    if filter:
        # The one real-world shape: userName eq "person@company.com"
        parts = filter.split(" eq ", 1)
        if len(parts) == 2 and parts[0].strip() == "userName":
            email_filter = parts[1].strip().strip('"')

    async with db.acquire() as conn:
        if email_filter:
            rows = await conn.fetch(
                "SELECT id, email, role, status, created_at, updated_at FROM workspace_members "
                "WHERE workspace_id = $1 AND email = $2",
                workspace_id, email_filter,
            )
        else:
            rows = await conn.fetch(
                "SELECT id, email, role, status, created_at, updated_at FROM workspace_members "
                "WHERE workspace_id = $1 ORDER BY created_at ASC OFFSET $2 LIMIT $3",
                workspace_id, max(startIndex - 1, 0), count,
            )

    resources = [_member_to_scim(dict(r)) for r in rows]
    return {
        "schemas": [_SCIM_LIST_SCHEMA],
        "totalResults": len(resources),
        "startIndex": startIndex,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


@router.post("/Users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: ScimCreateUserRequest,
    request: Request,
    scim_auth: dict = Depends(get_workspace_by_scim_token),
) -> dict:
    db = request.app.state.db_pool
    workspace_id = scim_auth["workspace_id"]

    async with db.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM workspace_members WHERE workspace_id = $1 AND email = $2",
            workspace_id, body.userName,
        )
        if existing:
            raise _scim_error(f"{body.userName} already exists", status.HTTP_409_CONFLICT)

        # SCIM provisioning implies the IdP already verified this
        # person's identity -- unlike the self-serve invite flow
        # (workspace_members.py), there's no email round trip: the
        # member lands 'active' immediately if active=true, matching
        # what a real IdP connector expects (no pending state it has to
        # poll for). role defaults to the least-privileged 'viewer' --
        # an admin promotes via the existing member-management endpoints.
        row = await conn.fetchrow(
            """
            INSERT INTO workspace_members (workspace_id, email, role, status, joined_at)
            VALUES ($1, $2, 'viewer', $3, CASE WHEN $3 = 'active' THEN NOW() ELSE NULL END)
            RETURNING id, email, role, status, created_at, updated_at
            """,
            workspace_id, body.userName, "active" if body.active else "deactivated",
        )

    log.info(
        "[SCIM] User created email=%s workspace=%s active=%s",
        body.userName, workspace_id, body.active,
        extra={"workspace_id": workspace_id, "scim_email": body.userName},
    )
    return _member_to_scim(dict(row))


@router.get("/Users/{user_id}")
async def get_user(
    user_id: str,
    request: Request,
    scim_auth: dict = Depends(get_workspace_by_scim_token),
) -> dict:
    member = await _get_member_or_404(request, scim_auth["workspace_id"], user_id)
    return _member_to_scim(member)


@router.put("/Users/{user_id}")
async def replace_user(
    user_id: str,
    body: ScimCreateUserRequest,
    request: Request,
    scim_auth: dict = Depends(get_workspace_by_scim_token),
) -> dict:
    workspace_id = scim_auth["workspace_id"]
    await _get_member_or_404(request, workspace_id, user_id)

    db = request.app.state.db_pool
    new_status = "active" if body.active else "deactivated"
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE workspace_members
            SET email = $1, status = $2, updated_at = NOW()
            WHERE id = $3 AND workspace_id = $4
            RETURNING id, email, role, status, created_at, updated_at
            """,
            body.userName, new_status, UUID(user_id), workspace_id,
        )

    log.info("[SCIM] User replaced id=%s workspace=%s", user_id, workspace_id)
    return _member_to_scim(dict(row))


@router.patch("/Users/{user_id}")
async def patch_user(
    user_id: str,
    body: ScimPatchRequest,
    request: Request,
    scim_auth: dict = Depends(get_workspace_by_scim_token),
) -> dict:
    workspace_id = scim_auth["workspace_id"]
    await _get_member_or_404(request, workspace_id, user_id)

    new_active: bool | None = None
    for operation in body.Operations:
        if operation.path == "active":
            new_active = bool(operation.value)
        elif operation.path is None and isinstance(operation.value, dict) and "active" in operation.value:
            # Some connectors send {"op":"replace","value":{"active":false}}
            # instead of a "path" -- both are valid per RFC 7644 §3.5.2.
            new_active = bool(operation.value["active"])

    if new_active is None:
        raise _scim_error("Only the 'active' attribute can be patched", status.HTTP_400_BAD_REQUEST)

    db = request.app.state.db_pool
    new_status = "active" if new_active else "deactivated"
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE workspace_members SET status = $1, updated_at = NOW()
            WHERE id = $2 AND workspace_id = $3
            RETURNING id, email, role, status, created_at, updated_at
            """,
            new_status, UUID(user_id), workspace_id,
        )

    log.info(
        "[SCIM] User %s workspace=%s -- active=%s",
        "deprovisioned" if not new_active else "reactivated", workspace_id, new_active,
        extra={"workspace_id": workspace_id, "scim_member_id": user_id},
    )
    return _member_to_scim(dict(row))


@router.delete("/Users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    request: Request,
    scim_auth: dict = Depends(get_workspace_by_scim_token),
) -> None:
    workspace_id = scim_auth["workspace_id"]
    await _get_member_or_404(request, workspace_id, user_id)

    # Deactivates, does not hard-delete -- matches docs/customer/
    # dpa-outline.md's existing "archival, not hard deletion" model
    # (same reasoning as internal_workspaces.py's purge-data endpoint,
    # which nulls credentials but keeps the row for audit-trail integrity).
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE workspace_members SET status = 'deactivated', updated_at = NOW() "
            "WHERE id = $1 AND workspace_id = $2",
            UUID(user_id), workspace_id,
        )

    log.info("[SCIM] User deprovisioned (DELETE) id=%s workspace=%s", user_id, workspace_id)


async def _get_member_or_404(request: Request, workspace_id: str, user_id: str) -> dict:
    try:
        member_uuid = UUID(user_id)
    except ValueError:
        raise _scim_error(f"'{user_id}' is not a valid user id", status.HTTP_400_BAD_REQUEST)

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, role, status, created_at, updated_at FROM workspace_members "
            "WHERE id = $1 AND workspace_id = $2",
            member_uuid, workspace_id,
        )

    if not row:
        raise _scim_error(f"User {user_id} not found", status.HTTP_404_NOT_FOUND)
    return dict(row)
