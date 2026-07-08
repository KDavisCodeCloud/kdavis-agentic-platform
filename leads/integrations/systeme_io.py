"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

"""
systeme_io — thin wrapper around Systeme.io's REST API for contacts,
tags, and nurture sequences ("campaigns" in Systeme.io's terminology).

Endpoint paths and payload shapes below reflect Systeme.io's public API
docs (developer.systeme.io) as best-effort — verify against the current
docs before relying on this in production; every method is a single
`_request` call, so fixing a path is a one-line change. Tags follow the
naming convention from CLAUDE.md's Lead Capture section:
  product_{product_id}_interested / _trial_active / _trial_expired /
  _paid / _churned, plus email_only and visited_pricing.
"""

import os
from typing import Any, Optional

DEFAULT_BASE_URL = "https://api.systeme.io/api"


class SystemeIOError(RuntimeError):
    pass


class SystemeIOClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, client: Optional[Any] = None):
        self._api_key = api_key or os.environ["SYSTEME_API_KEY"]
        self._base_url = (base_url or os.getenv("SYSTEME_API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.Client(
                base_url=self._base_url,
                headers={"X-API-Key": self._api_key, "Content-Type": "application/json"},
                timeout=15.0,
            )
        return self._client

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = self._get_client().request(method, path, **kwargs)
        if response.status_code >= 400:
            raise SystemeIOError(f"Systeme.io {method} {path} failed [{response.status_code}]: {response.text}")
        return response.json() if response.content else {}

    def create_contact(self, email: str, tags: Optional[list[str]] = None, fields: Optional[dict] = None) -> dict:
        body: dict = {"email": email}
        if fields:
            body.update(fields)
        contact = self._request("POST", "/contacts", json=body)
        for tag in tags or []:
            self.add_tag(contact.get("id"), tag)
        return contact

    def add_tag(self, contact_id: Any, tag: str) -> dict:
        return self._request("POST", f"/contacts/{contact_id}/tags", json={"tag": tag})

    def enroll_sequence(self, contact_id: Any, sequence_id: Any) -> dict:
        return self._request("POST", f"/campaigns/{sequence_id}/subscribers", json={"contact_id": contact_id})

    def update_contact(self, contact_id: Any, fields: dict) -> dict:
        return self._request("PATCH", f"/contacts/{contact_id}", json=fields)

    def get_sequence_stats(self, sequence_id: Any) -> dict:
        return self._request("GET", f"/campaigns/{sequence_id}/stats")
