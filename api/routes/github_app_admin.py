"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

One-time platform bootstrap for the item 4 GitHub App migration -- there is
exactly one Cloud Decoded GitHub App for the whole platform (github_app_config,
migration 023), registered once via GitHub's "manifest flow":

  1. POST /internal/github-app/register (admin-gated) -- returns the manifest
     + a URL for Kelvin to open in his own browser.
  2. Kelvin opens that URL, GitHub shows the manifest, he clicks
     "Create GitHub App" -- the ONE step nobody but him can do.
  3. GitHub redirects to GET /internal/github-app/callback with a one-time
     `code`. This route is NOT admin-gated (GitHub's redirect carries no
     auth header we control) -- it's protected instead by only ever
     succeeding once: if github_app_config already has a row, it refuses.
"""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request

from api.middleware.internal_auth import get_internal_user
from core.github_app import GitHubAppError, build_manifest, build_registration_url, exchange_manifest_code
from security.encryption import encrypt

log = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/github-app", tags=["internal-github-app"])


@router.post("/register")
async def register_github_app(request: Request, admin: dict = Depends(get_internal_user)) -> dict:
    async with request.app.state.db_pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT id FROM github_app_config WHERE id = 'singleton'")
    if existing:
        raise HTTPException(status_code=409, detail="GitHub App already registered on this platform")

    base_url = os.environ.get("API_BASE_URL", "http://localhost:8000")
    manifest = build_manifest(
        app_name="Cloud Decoded",
        homepage_url="https://theclouddecoded.com",
        callback_url=f"{base_url}/api/v1/internal/github-app/callback",
        webhook_url=f"{base_url}/api/v1/webhooks/github-app",
    )
    return {
        "manifest": manifest,
        "registration_url": build_registration_url(state="bootstrap"),
        "instructions": (
            "Open registration_url in your own browser, review the manifest GitHub shows you, "
            "and click 'Create GitHub App'. You'll be redirected back automatically -- nothing "
            "further to do here."
        ),
    }


@router.get("/callback")
async def github_app_manifest_callback(request: Request, code: str) -> dict:
    async with request.app.state.db_pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT id FROM github_app_config WHERE id = 'singleton'")
        if existing:
            raise HTTPException(status_code=409, detail="GitHub App already registered on this platform")

        try:
            app_creds = await exchange_manifest_code(code)
        except GitHubAppError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        await conn.execute(
            """
            INSERT INTO github_app_config
                (id, app_id, app_slug, client_id, client_secret_encrypted,
                 webhook_secret_encrypted, private_key_encrypted)
            VALUES ('singleton', $1, $2, $3, $4, $5, $6)
            """,
            app_creds["app_id"],
            app_creds["slug"],
            app_creds["client_id"],
            encrypt(app_creds["client_secret"]),
            encrypt(app_creds["webhook_secret"]),
            encrypt(app_creds["pem"]),
        )

    log.info("[GitHubAppAdmin] GitHub App registered: id=%s slug=%s", app_creds["app_id"], app_creds["slug"])
    return {"status": "registered", "app_id": app_creds["app_id"], "app_slug": app_creds["slug"]}
