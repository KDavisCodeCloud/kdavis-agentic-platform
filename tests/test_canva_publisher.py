"""
Unit coverage for core/publishers/canva.py's Autofill + Export flow.

Autofill alone was the only thing built here before this pass — it
produces an editable Canva design, not a downloadable file. These tests
cover the Export addition (create/poll/download) and the
render_brand_template_to_image() convenience wrapper that chains the
whole Autofill -> Export -> Download flow into the one call the
internal marketing publish path actually uses.

httpx.AsyncClient is patched directly (no respx/pytest-httpx dependency
in this repo), matching tests/test_linkedin_publisher.py's approach.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.publishers.canva import (
    create_export_job,
    download_export,
    get_brand_template_dataset,
    get_export_job,
    poll_export_job,
    render_brand_template_to_image,
)


def _fake_response(json_data=None, content=b"", status_ok=True):
    resp = MagicMock()
    resp.json.return_value = json_data or {}
    resp.content = content
    if status_ok:
        resp.raise_for_status.return_value = None
    else:
        resp.raise_for_status.side_effect = Exception("HTTP error")
    return resp


async def test_get_brand_template_dataset_returns_field_schema():
    fake_resp = _fake_response(json_data={"dataset": {"headline": {"type": "text"}, "hero_image": {"type": "image"}}})
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_resp)):
        dataset = await get_brand_template_dataset("token", "bt-123")

    assert dataset == {"headline": {"type": "text"}, "hero_image": {"type": "image"}}


async def test_get_brand_template_dataset_defaults_to_empty_dict_when_absent():
    fake_resp = _fake_response(json_data={})
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_resp)):
        dataset = await get_brand_template_dataset("token", "bt-123")

    assert dataset == {}


async def test_create_export_job_sends_design_id_and_format_returns_job_id():
    fake_resp = _fake_response(json_data={"job": {"id": "export-1", "status": "in_progress"}})
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_resp)) as mock_post:
        job_id = await create_export_job("token", "design-123", "png")

    assert job_id == "export-1"
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"design_id": "design-123", "format": {"type": "png"}}


async def test_get_export_job_returns_raw_job_dict():
    fake_resp = _fake_response(json_data={"job": {"id": "export-1", "status": "success", "urls": ["https://x/y.png"]}})
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_resp)):
        job = await get_export_job("token", "export-1")

    assert job["status"] == "success"
    assert job["urls"] == ["https://x/y.png"]


async def test_poll_export_job_returns_urls_on_success():
    fake_resp = _fake_response(json_data={"job": {"id": "export-1", "status": "success", "urls": ["https://x/y.png"]}})
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_resp)):
        urls = await poll_export_job("token", "export-1")

    assert urls == ["https://x/y.png"]


async def test_poll_export_job_raises_on_failed_status():
    fake_resp = _fake_response(json_data={"job": {"id": "export-1", "status": "failed", "error": {"message": "bad design"}}})
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_resp)):
        with pytest.raises(RuntimeError, match="bad design"):
            await poll_export_job("token", "export-1")


async def test_poll_export_job_raises_on_timeout_not_silently_returning_in_progress():
    fake_resp = _fake_response(json_data={"job": {"id": "export-1", "status": "in_progress"}})
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_resp)), \
         patch("asyncio.sleep", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="did not finish"):
            await poll_export_job("token", "export-1", max_wait_seconds=5, poll_interval=3)


async def test_download_export_returns_raw_bytes_no_auth_header():
    fake_resp = _fake_response(content=b"\x89PNG...")
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_resp)) as mock_get:
        data = await download_export("https://x/y.png")

    assert data == b"\x89PNG..."
    _, kwargs = mock_get.call_args
    assert "headers" not in kwargs or not kwargs.get("headers")


async def test_render_brand_template_to_image_chains_all_four_steps():
    autofill_create_resp = _fake_response(json_data={"job": {"id": "af-1", "status": "in_progress"}})
    autofill_poll_resp = _fake_response(json_data={
        "job": {
            "id": "af-1", "status": "success",
            "result": {"design": {"id": "design-123", "urls": {"edit_url": "https://canva/edit", "view_url": "https://canva/view"}}},
        }
    })
    export_create_resp = _fake_response(json_data={"job": {"id": "export-1", "status": "in_progress"}})
    export_poll_resp = _fake_response(json_data={"job": {"id": "export-1", "status": "success", "urls": ["https://x/final.png"]}})
    download_resp = _fake_response(content=b"finalbytes")

    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=[autofill_create_resp, export_create_resp])), \
         patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=[autofill_poll_resp, export_poll_resp, download_resp])):
        result = await render_brand_template_to_image(
            "token", "brand-template-1", {"headline": {"type": "text", "text": "hello"}}
        )

    assert result == b"finalbytes"


async def test_render_brand_template_to_image_raises_when_export_returns_no_urls():
    autofill_create_resp = _fake_response(json_data={"job": {"id": "af-1", "status": "in_progress"}})
    autofill_poll_resp = _fake_response(json_data={
        "job": {"id": "af-1", "status": "success", "result": {"design": {"id": "design-123"}}}
    })
    export_create_resp = _fake_response(json_data={"job": {"id": "export-1", "status": "in_progress"}})
    export_poll_resp = _fake_response(json_data={"job": {"id": "export-1", "status": "success", "urls": []}})

    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=[autofill_create_resp, export_create_resp])), \
         patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=[autofill_poll_resp, export_poll_resp])):
        with pytest.raises(RuntimeError, match="no URLs"):
            await render_brand_template_to_image("token", "brand-template-1", {})
