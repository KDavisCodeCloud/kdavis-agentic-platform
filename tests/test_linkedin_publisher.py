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

import core.publishers.linkedin as linkedin
from core.publishers.linkedin import (
    get_author_urn,
    post_image,
    post_text,
    register_image_upload,
    upload_image_binary,
)


@pytest.fixture(autouse=True)
def _reset_working_version():
    # _working_version is a module-level cache set by a successful call --
    # reset it around every test so one test's success doesn't change which
    # version candidate a later test tries first.
    linkedin._working_version = None
    yield
    linkedin._working_version = None


def _fake_response(json_data=None, headers=None, status_ok=True, status_code=200, text=""):
    resp = MagicMock()
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    resp.status_code = status_code
    resp.text = text
    if status_ok:
        resp.raise_for_status.return_value = None
    else:
        resp.raise_for_status.side_effect = Exception("HTTP error")
    return resp


def _nonexistent_version_response(version: str):
    return _fake_response(
        status_ok=False,
        status_code=426,
        text=f'{{"status":426,"code":"NONEXISTENT_VERSION","message":"Requested version {version}01 is not active"}}',
    )


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


# Real bug found and fixed 2026-08-04: a hardcoded LinkedIn-Version string
# ("202507", itself an off-by-one-year mistake made 2026-07-21) went stale
# and killed every scheduled post with 426 NONEXISTENT_VERSION. Fixed by
# trying a computed range of recent versions and retrying automatically
# on that specific error -- these tests cover the retry itself so this
# class of bug can't silently regress the same way again.

@pytest.mark.asyncio
async def test_post_text_retries_on_nonexistent_version_and_succeeds():
    bad = _nonexistent_version_response("202608")
    good = _fake_response(headers={"x-restli-id": "urn:li:share:123"})
    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=[bad, good])) as mock_post:
        result = await post_text("token", "urn:li:person:abc", "hello world")

    assert mock_post.await_count == 2
    assert result["post_id"] == "urn:li:share:123"
    # the version that actually worked is cached for the next call
    assert linkedin._working_version is not None


@pytest.mark.asyncio
async def test_post_text_does_not_retry_on_non_version_error():
    # A real auth/rate-limit/payload error must raise immediately, never
    # be mistaken for a stale-version problem and retried.
    real_error = _fake_response(status_ok=False, status_code=401, text='{"message":"invalid token"}')
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=real_error)) as mock_post:
        with pytest.raises(Exception, match="HTTP error"):
            await post_text("token", "urn:li:person:abc", "hello world")

    mock_post.assert_awaited_once()


@pytest.mark.asyncio
async def test_working_version_is_reused_on_next_call_skipping_dead_versions():
    linkedin._working_version = "202607"
    good = _fake_response(headers={"x-restli-id": "urn:li:share:456"})
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=good)) as mock_post:
        await post_text("token", "urn:li:person:abc", "hello again")

    # only one call was needed -- the cached working version was tried first
    mock_post.assert_awaited_once()
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["LinkedIn-Version"] == "202607"


@pytest.mark.asyncio
async def test_raises_clearly_when_every_candidate_version_is_dead():
    all_dead = AsyncMock(side_effect=lambda *a, **kw: _nonexistent_version_response(kw["headers"]["LinkedIn-Version"]))
    with patch("httpx.AsyncClient.post", new=all_dead):
        with pytest.raises(Exception, match="HTTP error"):
            await post_text("token", "urn:li:person:abc", "hello world")
