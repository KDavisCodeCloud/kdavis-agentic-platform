"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Workspace creation + BYOK LLM key storage.

POST /workspaces          — create a workspace, returns a workspace token once
POST /workspaces/llm-key  — store a BYOK LLM API key for the caller's workspace

Security rules:
  - Raw workspace token is returned ONCE on creation and never stored —
    only its SHA-256 hash is persisted, using the same hash function
    api.middleware.auth.get_workspace uses to look it back up.
  - Raw LLM API key is never stored or echoed back — only its Fernet
    ciphertext is persisted, via security/encryption.py.
  - POST /workspaces has no auth (a workspace can't authenticate before it
    exists) — rate limited by IP instead.
"""

import logging
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from api.middleware.auth import _hash_token, get_workspace
from api.middleware.rate_limiter import limiter
from security.encryption import encrypt

log = logging.getLogger(__name__)
router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_TOKEN_PREFIX = "cd_ws_"
_VALID_PROVIDERS = frozenset({"anthropic", "openai"})
# Deliberately simple shape check, not full RFC 5322 -- this is the only
# contact address Cloud Decoded's own code has for a customer (no
# email-validator dependency in this codebase), so reject obvious garbage
# without rejecting a real address on an edge case the regex misses.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _generate_raw_token() -> str:
    return f"{_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


# ── Request / response models ─────────────────────────────────────────────────

class CreateWorkspaceRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=255)
    contact_email: str = Field(..., min_length=3, max_length=255)

    @field_validator("contact_email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("contact_email is not a valid email address")
        return v


class CreateWorkspaceResponse(BaseModel):
    id: str
    workspace_token: str  # ONLY time the raw token is shown — store it now
    warning: str = "Save this token now — it will not be shown again."


class SaveLlmKeyRequest(BaseModel):
    provider: str = Field(..., min_length=1, max_length=20)
    api_key: str = Field(..., min_length=1)


class SaveLlmKeyResponse(BaseModel):
    status: str = "ok"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", response_model=CreateWorkspaceResponse, status_code=201)
@limiter.limit("5/minute")
async def create_workspace(
    body: CreateWorkspaceRequest,
    request: Request,
) -> CreateWorkspaceResponse:
    raw_token = _generate_raw_token()
    token_hash = _hash_token(raw_token)

    async with request.app.state.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO workspaces (company_name, workspace_token, contact_email)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            body.company_name,
            token_hash,
            body.contact_email,
        )

    log.info(
        "[Workspaces] Created workspace=%s company=%s contact=%s",
        row["id"], body.company_name, body.contact_email,
    )

    return CreateWorkspaceResponse(id=str(row["id"]), workspace_token=raw_token)


@router.post("/llm-key", response_model=SaveLlmKeyResponse)
@limiter.limit("30/minute")  # _tier_limit is broken under the pinned slowapi==0.1.9 — see GAPS.md
async def save_llm_key(
    body: SaveLlmKeyRequest,
    request: Request,
    workspace: dict = Depends(get_workspace),
) -> SaveLlmKeyResponse:
    if body.provider not in _VALID_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider '{body.provider}' — must be one of: {', '.join(sorted(_VALID_PROVIDERS))}",
        )

    workspace_id = workspace["id"]
    encrypted_key = encrypt(body.api_key)

    async with request.app.state.db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE workspaces
            SET encrypted_llm_key = $1, llm_provider = $2
            WHERE id = $3
            """,
            encrypted_key,
            body.provider,
            workspace_id,
        )

    log.info("[Workspaces] Stored BYOK key workspace=%s provider=%s", workspace_id, body.provider)

    return SaveLlmKeyResponse()
