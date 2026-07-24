"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
Canva Connect API client — Autofill + Export only.

Fills existing Brand Templates with data (text/image fields), polls the
resulting job until a finished design is ready, then exports that design
to a downloadable image file. Does NOT generate designs from scratch —
Canva's Autofill API only works against a Brand Template that already
exists, built by hand in Canva's own editor with named placeholder
fields. That template must exist before any of this is useful; see the
OAuth connect flow's docstring in api/routes/internal_marketing.py for
the full manual prerequisite list.

Autofill alone does not produce a downloadable file — it produces an
editable Canva *design* (edit_url/view_url, meant for a human to open
in Canva's editor). Getting an actual image file requires the separate
Export API below, run against the design_id the autofill job produced.
This was a real gap: only Autofill existed here until this pass added
Export — nothing in this repo called either one until the internal
marketing publish path was wired up.

Endpoint shapes verified against Canva's own Connect API docs
(canva.dev/docs/connect):
  POST /rest/v1/autofills                 create a design autofill job    (2026-07-17)
  GET  /rest/v1/autofills/{jobId}          poll autofill job status/result (2026-07-17)
  POST /rest/v1/exports                   create a design export job      (added this pass)
  GET  /rest/v1/exports/{exportId}        poll export job status/result   (added this pass)

Existing OAuth scopes already requested in api/routes/internal_marketing.py
(_CANVA_SCOPES) include design:content:read, which is what Export
requires — no new consent/reconnect needed for this addition.

COMPLIANCE BOUNDARY, same principle as core/publishers/linkedin.py: this
file only ever creates a design via the documented Autofill API and
exports it via the documented Export API. It does not scrape templates,
does not modify a user's other designs, and does not do anything
Canva's API doesn't explicitly support.
"""

import asyncio
import logging
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)

_API_BASE = "https://api.canva.com/rest/v1"
_AUTOFILLS_URL = f"{_API_BASE}/autofills"
_EXPORTS_URL = f"{_API_BASE}/exports"


async def get_brand_template_dataset(access_token: str, brand_template_id: str) -> dict:
    """
    Fetches the field schema for a Brand Template — the named placeholder
    fields Kelvin defines by hand when building the template in Canva's
    editor, e.g. {"headline": {"type": "text"}, "hero_image": {"type": "image"}}.

    This exists so the internal marketing publish path can build its
    autofill `data` payload from the template's REAL field names instead
    of guessing them — MKT-CN1 (agents/marketing/mkt_cn1_image_brief.py)
    only produces a prose design_prompt today, not a field-keyed dict, so
    there is no way to know the right keys without either this call or
    Kelvin telling us directly. Call this once after the template exists
    and hardcode the confirmed field names in the caller — no need to
    call it on every publish.

    Returns: {field_name: {"type": "text" | "image"}, ...}
    """
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{_API_BASE}/brand-templates/{brand_template_id}/dataset",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()

    return response.json().get("dataset", {})


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


async def create_export_job(
    access_token: str,
    design_id: str,
    file_format: str = "png",
) -> str:
    """
    Starts an export job for a design (e.g. the one produced by a
    finished autofill job — job["result"]["design"]["id"]).

    Args:
        access_token: OAuth 2.0 access token with design:content:read scope
        design_id:    ID of the design to export
        file_format:  "png" | "jpg" | "pdf" | "pptx" | "gif" | "mp4" —
                      "png" is the default since LinkedIn image posts
                      accept PNG/JPEG and PNG preserves text/diagram
                      sharpness better than JPEG for the infographic-style
                      images this pipeline produces.

    Returns: job_id, to be passed to poll_export_job()

    Raises: httpx.HTTPStatusError on API error (non-2xx)
    """
    payload = {"design_id": design_id, "format": {"type": file_format}}

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            _EXPORTS_URL,
            json=payload,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        )
        response.raise_for_status()

    job = response.json()["job"]
    log.info("[Canva] Export job created — id=%s", job["id"])
    return job["id"]


async def get_export_job(access_token: str, job_id: str) -> dict:
    """
    Fetches the current status of an export job.

    Returns the raw `job` object: {"id", "status", "urls"?, "error"?}
    where status is one of "in_progress" | "success" | "failed", and
    "urls" (present on success) is a list of downloadable file URLs —
    a list because some design types export as multiple files/pages;
    single-image Brand Template exports produce exactly one URL.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{_EXPORTS_URL}/{job_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()

    return response.json()["job"]


async def poll_export_job(
    access_token: str,
    job_id: str,
    max_wait_seconds: int = 60,
    poll_interval: int = 3,
) -> list[str]:
    """
    Polls get_export_job until status leaves "in_progress" or
    max_wait_seconds elapses.

    Returns: the list of downloadable file URLs on "success".

    Raises:
        RuntimeError: on status "failed" (includes job["error"] in the
          message) or on timeout — never returns a still-in-progress job
          silently, matching this repo's "no silent failures" rule.
    """
    elapsed = 0
    while elapsed < max_wait_seconds:
        job = await get_export_job(access_token, job_id)
        if job["status"] == "success":
            log.info("[Canva] Export job succeeded — id=%s", job_id)
            return job["urls"]
        if job["status"] == "failed":
            raise RuntimeError(f"Canva export job {job_id} failed: {job.get('error')}")
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    raise RuntimeError(f"Canva export job {job_id} did not finish within {max_wait_seconds}s")


async def download_export(url: str) -> bytes:
    """
    Downloads a finished export file from one of the URLs poll_export_job()
    returns. These URLs are pre-signed and require no auth header, per
    Canva's Export API docs.
    """
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(url)
        response.raise_for_status()
    log.info("[Canva] Downloaded export (%d bytes)", len(response.content))
    return response.content


async def render_brand_template_to_image(
    access_token: str,
    brand_template_id: str,
    data: dict[str, dict[str, Any]],
    title: Optional[str] = None,
    file_format: str = "png",
) -> bytes:
    """
    Convenience wrapper chaining the full Autofill -> Export -> Download
    flow — this is the one function the internal marketing publish path
    actually calls; the individual steps above stay available for
    testing and for callers that need to inspect an intermediate job.

    Returns: raw image bytes, ready to pass to
    core.publishers.linkedin.post_image()'s image_bytes argument.
    """
    autofill_job_id = await create_autofill_job(access_token, brand_template_id, data, title)
    autofill_job = await poll_autofill_job(access_token, autofill_job_id)
    design_id = autofill_job["result"]["design"]["id"]

    export_job_id = await create_export_job(access_token, design_id, file_format)
    urls = await poll_export_job(access_token, export_job_id)
    if not urls:
        raise RuntimeError(f"Canva export job {export_job_id} succeeded but returned no URLs")

    return await download_export(urls[0])
