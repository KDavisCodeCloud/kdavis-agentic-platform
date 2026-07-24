"""
Unit coverage for core/publishers/linkedin.py.

Real bug found and fixed this session: post_text(), get_author_urn(),
and the equivalent call in x.py's post_tweet() all called
client.post()/client.get() on an httpx.AsyncClient WITHOUT awaiting it
— response was an un-awaited coroutine, so response.raise_for_status()
would have raised AttributeError on every real call, including during
the OAuth callback itself (get_author_urn). This explains "click-
through not confirmed working yet" independent of any redirect_uri
issue. These tests assert the awaited call actually happens and the
response is used correctly, so this class of bug can't silently
regress.

httpx.AsyncClient is patched directly (no respx/pytest-httpx dependency
in this repo) — each test replaces the relevant method with an
AsyncMock returning a fake response object.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.publishers.linkedin import (
    get_author_urn,
    post_image,
    post_text,
    register_image_upload,
    upload_image_binary,
)


def _fake_response(json_data=None, headers=None, status_ok=True):
    resp = MagicMock()
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    if status_ok:
        resp.raise_for_status.return_value = None
    else:
        resp.raise_for_status.side_effect = Exception("HTTP error")
    return resp


@pytest.mark.asyncio
async def test_post_text_awaits_the_client_call_and_returns_post_id():
    fake_resp = _fake_response(headers={"x-restli-id": "urn:li:share:123"})
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_resp)) as mock_post:
        result = await post_text("token", "urn:li:person:abc", "hello world")

    mock_post.assert_awaited_once()
    assert result == {
        "post_id": "urn:li:share:123",
        "url": "https://www.linkedin.com/feed/update/urn:li:share:123",
    }


async def test_post_text_rejects_text_over_3000_chars():
    with pytest.raises(ValueError):
        await post_text("token", "urn:li:person:abc", "x" * 3001)


@pytest.mark.asyncio
async def test_get_author_urn_awaits_the_client_call_and_parses_sub():
    fake_resp = _fake_response(json_data={"sub": "abc123"})
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_resp)) as mock_get:
        urn = await get_author_urn("token")

    mock_get.assert_awaited_once()
    assert urn == "urn:li:person:abc123"


@pytest.mark.asyncio
async def test_get_author_urn_raises_when_sub_missing():
    fake_resp = _fake_response(json_data={})
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_resp)):
        with pytest.raises(ValueError):
            await get_author_urn("token")


@pytest.mark.asyncio
async def test_register_image_upload_returns_upload_url_and_urn():
    fake_resp = _fake_response(json_data={
        "value": {"uploadUrl": "https://upload.example/xyz", "image": "urn:li:image:abc"}
    })
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_resp)):
        upload_url, image_urn = await register_image_upload("token", "urn:li:person:abc")

    assert upload_url == "https://upload.example/xyz"
    assert image_urn == "urn:li:image:abc"


@pytest.mark.asyncio
async def test_upload_image_binary_puts_raw_bytes_no_auth_header():
    fake_resp = _fake_response()
    with patch("httpx.AsyncClient.put", new=AsyncMock(return_value=fake_resp)) as mock_put:
        await upload_image_binary("https://upload.example/xyz", b"\x89PNG...")

    mock_put.assert_awaited_once()
    _, kwargs = mock_put.call_args
    assert kwargs["content"] == b"\x89PNG..."


@pytest.mark.asyncio
async def test_post_image_runs_all_three_steps_and_references_image_urn_in_content():
    register_resp = _fake_response(json_data={
        "value": {"uploadUrl": "https://upload.example/xyz", "image": "urn:li:image:abc"}
    })
    upload_resp = _fake_response()
    post_resp = _fake_response(headers={"x-restli-id": "urn:li:share:999"})

    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=[register_resp, post_resp])) as mock_post, \
         patch("httpx.AsyncClient.put", new=AsyncMock(return_value=upload_resp)) as mock_put:
        result = await post_image("token", "urn:li:person:abc", "check this out", b"imgbytes", alt_text="a diagram")

    assert mock_post.await_count == 2   # register upload, then create post
    mock_put.assert_awaited_once()      # binary upload
    assert result["post_id"] == "urn:li:share:999"

    # second post() call is the actual post creation — assert it referenced the image urn
    post_call_kwargs = mock_post.call_args_list[1].kwargs
    assert post_call_kwargs["json"]["content"]["media"]["id"] == "urn:li:image:abc"
    assert post_call_kwargs["json"]["content"]["media"]["title"] == "a diagram"


@pytest.mark.asyncio
async def test_post_image_omits_title_when_no_alt_text_given():
    register_resp = _fake_response(json_data={
        "value": {"uploadUrl": "https://upload.example/xyz", "image": "urn:li:image:abc"}
    })
    upload_resp = _fake_response()
    post_resp = _fake_response(headers={"x-restli-id": "urn:li:share:999"})

    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=[register_resp, post_resp])) as mock_post, \
         patch("httpx.AsyncClient.put", new=AsyncMock(return_value=upload_resp)):
        await post_image("token", "urn:li:person:abc", "no alt text here", b"imgbytes")

    post_call_kwargs = mock_post.call_args_list[1].kwargs
    assert post_call_kwargs["json"]["content"]["media"] == {"id": "urn:li:image:abc"}


async def test_post_image_rejects_text_over_3000_chars():
    with pytest.raises(ValueError):
        await post_image("token", "urn:li:person:abc", "x" * 3001, b"imgbytes")
