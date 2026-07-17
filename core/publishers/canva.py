"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
Canva Connect API client — Autofill only.

Fills existing Brand Templates with data (text/image fields) and polls
the resulting job until a finished design is ready. Does NOT generate
designs from scratch — Canva's Autofill API only works against a Brand
Template that already exists, built by hand in Canva's own editor with
named placeholder fields. That template must exist before any of this
is useful; see the OAuth connect flow's docstring in
api/routes/internal_marketing.py for the full manual prerequisite list.

Endpoint shapes verified against Canva's own Connect API docs
(canva.dev/docs/connect) 2026-07-17 — not guessed:
  POST /rest/v1/autofills                 create a design autofill job
  GET  /rest/v1/autofills/{jobId}          poll job status/result

COMPLIANCE BOUNDARY, same principle as core/publishers/linkedin.py: this
file only ever creates a design via the documented Autofill API. It does
not scrape templates, does not modify a user's other designs, and does
not do anything Canva's API doesn't explicitly support.
"""

import asyncio
import logging
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

_API_BASE = "https://api.canva.com/rest/v1"
_AUTOFILLS_URL = f"{_API_BASE}/autofills"


async def create_autofill_job(
    access_token: str,
    brand_template_id: str,
    data: dict[str, dict[str, Any]],
    title: Optional[str] = None,
) -> str:
    """
    Starts an autofill job against a Brand Template.

    Args:
        access_token:      OAuth 2.0 access token (asset:read/write + design:content:*)
        brand_template_id: ID of a Brand Template already built in Canva's editor
        data:               field name -> {"type": "text", "text": "..."} or
                            {"type": "image", "asset_id": "..."} per Canva's schema
        title:              optional title for the resulting design

    Returns: job_id, to be passed to poll_autofill_job()

    Raises: httpx.HTTPStatusError on API error (non-2xx)
    """
    payload: dict[str, Any] = {
        "brand_template_id": brand_template_id,
        "type": "create_from_brand_template",
        "data": data,
    }
    if title:
        payload["title"] = title

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            _AUTOFILLS_URL,
            json=payload,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        )
        response.raise_for_status()

    job = response.json()["job"]
    log.info("[Canva] Autofill job created — id=%s", job["id"])
    return job["id"]


async def get_autofill_job(access_token: str, job_id: str) -> dict:
    """
    Fetches the current status of an autofill job.

    Returns the raw `job` object: {"id", "status", "result"?, "error"?}
    where status is one of "in_progress" | "success" | "failed".
    """
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{_AUTOFILLS_URL}/{job_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()

    return response.json()["job"]


async def poll_autofill_job(
    access_token: str,
    job_id: str,
    max_wait_seconds: int = 60,
    poll_interval: int = 3,
) -> dict:
    """
    Polls get_autofill_job until status leaves "in_progress" or
    max_wait_seconds elapses.

    Returns: the finished job dict on "success" — design URL is at
    job["result"]["design"]["urls"]["edit_url"] / ["view_url"].

    Raises:
        RuntimeError: on status "failed" (includes job["error"] in the
          message) or on timeout — never returns a still-in-progress job
          silently, matching this repo's "no silent failures" rule.
    """
    elapsed = 0
    while elapsed < max_wait_seconds:
        job = await get_autofill_job(access_token, job_id)
        if job["status"] == "success":
            log.info("[Canva] Autofill job succeeded — id=%s", job_id)
            return job
        if job["status"] == "failed":
            raise RuntimeError(f"Canva autofill job {job_id} failed: {job.get('error')}")
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    raise RuntimeError(f"Canva autofill job {job_id} did not finish within {max_wait_seconds}s")
