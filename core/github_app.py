"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

GitHub App identity + installation-token minting (item 4 of the connectivity
build sequence, decided 2026-09-13). One App for the whole platform
(github_app_config, migration 023); each customer workspace holds only its
own installation_id (workspaces.github_app_installation_id).

Registration is the GitHub "manifest flow" -- the only part of App creation
that doesn't require manually filling out GitHub's web form:
  1. build_manifest() -- a JSON description of the App to create
  2. Kelvin visits https://github.com/settings/apps/new?state=<state>,
     POSTs the manifest (api/routes/github_app_admin.py's /register route
     hands back a ready form/link for this), clicks "Create GitHub App"
  3. GitHub redirects back to our callback with a one-time `code`
  4. exchange_manifest_code() trades that code for the App's real
     id/client_id/client_secret/webhook_secret/private_key -- this is the
     ONLY step that returns the private key; it is never shown again after.

Per-call installation tokens (core/workspace_credentials.py's
build_agent_credentials): mint_installation_token() signs a short RS256 JWT
with the App's own private key (proves "I am this App" to GitHub), then
exchanges that JWT for a ~1hr installation access token scoped to exactly
what that installation was granted. Nothing long-lived is ever stored orb
cached here -- mint fresh per call, same discipline as
core/workspace_credentials.py's AWS role assumption and Azure token minting.
"""

import hashlib
import hmac
import logging
import os
import time
from typing import Optional

import httpx
from jose import jwt

log = logging.getLogger(__name__)

_GH_API = "https://api.github.com"
_MAX_HTTP_TIMEOUT = 30

# Fine-grained, nothing broader than what agents 01/03/08 actually do today
# (read IaC, comment on PRs, open remediation PRs). Update this if a new
# GitHub call is added to any agent, same discipline as
# core/workspace_credentials.py's AWS _PERMISSIONS_POLICY_ACTIONS list.
_APP_PERMISSIONS = {
    "contents": "write",
    "pull_requests": "write",
    "metadata": "read",
}
_APP_WEBHOOK_EVENTS = ["pull_request", "workflow_run"]


class GitHubAppError(Exception):
    """Raised when App registration, manifest conversion, or installation
    token minting fails -- wraps GitHub's own error response."""


def build_manifest(app_name: str, homepage_url: str, callback_url: str, webhook_url: str) -> dict:
    """
    The manifest GitHub creates the App from. `state` (CSRF-style, ties the
    redirect back to this registration attempt) is passed separately as a
    query param on the /settings/apps/new URL, not part of the manifest body.
    """
    return {
        "name": app_name,
        "url": homepage_url,
        "redirect_url": callback_url,
        "hook_attributes": {"url": webhook_url},
        "public": False,
        "default_permissions": _APP_PERMISSIONS,
        "default_events": _APP_WEBHOOK_EVENTS,
    }


def build_registration_url(state: str) -> str:
    return f"https://github.com/settings/apps/new?state={state}"


async def exchange_manifest_code(code: str) -> dict:
    """
    Trades a one-time manifest-flow code for the App's real credentials.
    Returns {"app_id", "slug", "client_id", "client_secret", "webhook_secret",
    "pem"} -- store all of these (encrypted) in github_app_config, this is
    the only time webhook_secret/pem are ever returned by GitHub.
    """
    async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
        try:
            resp = await client.post(f"{_GH_API}/app-manifests/{code}/conversions")
        except httpx.RequestError as exc:
            raise GitHubAppError(f"Could not reach GitHub for manifest conversion: {exc}") from exc

    if resp.status_code != 201:
        raise GitHubAppError(f"Manifest conversion failed ({resp.status_code}): {resp.text[:300]}")

    body = resp.json()
    return {
        "app_id": str(body["id"]),
        "slug": body["slug"],
        "client_id": body["client_id"],
        "client_secret": body["client_secret"],
        "webhook_secret": body["webhook_secret"],
        "pem": body["pem"],
    }


_STATE_TTL_SECONDS = 900  # 15 minutes -- plenty for a customer to click through the install flow


def sign_workspace_state(workspace_id: str) -> str:
    """
    Ties a GitHub App install redirect back to the workspace that started
    it, without a DB round-trip. GitHub's install callback is a plain
    browser redirect with no auth header we control, so the `state` param
    itself has to carry (and prove) the workspace_id -- same role an OAuth
    `state` param normally plays.
    """
    key = os.environ.get("ENCRYPTION_KEY", "").encode()
    ts = str(int(time.time()))
    payload = f"{workspace_id}:{ts}"
    sig = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def verify_workspace_state(state: str) -> Optional[str]:
    """Returns the workspace_id if `state` is a valid, unexpired signature
    from sign_workspace_state(); None otherwise."""
    try:
        workspace_id, ts, sig = state.rsplit(":", 2)
    except ValueError:
        return None

    key = os.environ.get("ENCRYPTION_KEY", "").encode()
    expected = hmac.new(key, f"{workspace_id}:{ts}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None

    try:
        if int(time.time()) - int(ts) > _STATE_TTL_SECONDS:
            return None
    except ValueError:
        return None

    return workspace_id


def build_install_url(app_slug: str, state: str) -> str:
    """A customer clicks this to install the App on their org/repos. GitHub
    redirects back to the App's configured setup_url with `installation_id`
    and this same `state` (used to tie the installation back to a
    workspace_id)."""
    return f"https://github.com/apps/{app_slug}/installations/new?state={state}"


def _mint_app_jwt(app_id: str, private_key_pem: str) -> str:
    now = int(time.time())
    claims = {
        "iat": now - 60,  # allow for clock drift, per GitHub's own docs
        "exp": now + 540,  # max 10 minutes; keep well under it
        "iss": app_id,
    }
    return jwt.encode(claims, private_key_pem, algorithm="RS256")


async def mint_installation_token(app_id: str, private_key_pem: str, installation_id: str) -> str:
    """Fresh ~1hr installation access token, scoped to whatever that
    installation was granted. Never cached -- mint on every call, same
    discipline as assume_role_session()/get_azure_bearer_token()."""
    app_jwt = _mint_app_jwt(app_id, private_key_pem)

    async with httpx.AsyncClient(timeout=_MAX_HTTP_TIMEOUT) as client:
        try:
            resp = await client.post(
                f"{_GH_API}/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        except httpx.RequestError as exc:
            raise GitHubAppError(f"Could not reach GitHub to mint installation token: {exc}") from exc

    if resp.status_code != 201:
        raise GitHubAppError(f"Could not mint installation token ({resp.status_code}): {resp.text[:300]}")

    token = resp.json().get("token")
    if not token:
        raise GitHubAppError("Installation token response had no token")
    return token
