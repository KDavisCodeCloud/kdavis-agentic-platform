"""
Coverage for the new /internal/marketing/publish/linkedin/{queue_id} and
/internal/marketing/canva/brand-templates endpoints — the piece that was
missing entirely before this pass: nothing previously chained an
approved linkedin_content_queue row through Canva rendering to an
actual LinkedIn post. Route handlers are called directly (no HTTP
TestClient/dependency-override harness exists anywhere in this repo yet)
with a fake request.app.state.db_pool exposing the same acquire()/fetchrow/
fetch/execute surface asyncpg's Pool does, mirroring tests/conftest.py's
mock_db fixture for the connection object itself.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from api.routes.internal_marketing import (
    BrandTemplateMap,
    _build_autofill_data,
    _fetch_asset_bytes,
    get_asset,
    publish_linkedin_post,
    set_brand_templates,
)


class _FakeAcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquireCtx(self._conn)


def _fake_request(conn):
    request = MagicMock()
    request.app.state.db_pool = _FakePool(conn)
    return request


def _connected_conn(queue_row, li_row, canva_row):
    """fetchrow is called 3x in publish_linkedin_post's happy path, in
    order: queue row, linkedin connection, canva connection."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[queue_row, li_row, canva_row])
    conn.execute = AsyncMock(return_value=None)
    return conn


QUEUE_ROW = {
    "id": "q-1", "post_copy": "The workflow nobody talks about\n\nMore body text here.",
    "image_brief": {"brief_type": "canva_infographic", "design_prompt": "x"},
    "format": "text_post", "status": "approved",
}
LI_ROW = {"encrypted_access_token": "ENC(li-token)", "author_urn": "urn:li:person:abc"}
CANVA_ROW = {"encrypted_access_token": "ENC(canva-token)", "brand_template_ids": {"linkedin_square": "BT-123"}}


def _patched_decrypt():
    return patch("api.routes.internal_marketing._decrypt", side_effect=lambda v: v.replace("ENC(", "").rstrip(")"))


# ── _build_autofill_data ─────────────────────────────────────────────

def test_build_autofill_data_uses_first_line_as_headline():
    data = _build_autofill_data("The workflow nobody talks about\n\nMore text.", {})
    assert data == {"headline": {"type": "text", "text": "The workflow nobody talks about"}}


def test_build_autofill_data_truncates_long_first_line_to_150_chars():
    long_line = "x" * 300
    data = _build_autofill_data(long_line, {})
    assert len(data["headline"]["text"]) == 150


# ── publish_linkedin_post ────────────────────────────────────────────

async def test_publish_uses_canva_image_path_when_brief_and_template_exist():
    conn = _connected_conn(QUEUE_ROW, LI_ROW, CANVA_ROW)
    request = _fake_request(conn)

    with _patched_decrypt(), \
         patch("core.publishers.canva.render_brand_template_to_image", new=AsyncMock(return_value=b"imgbytes")) as mock_render, \
         patch("core.publishers.linkedin.post_image", new=AsyncMock(return_value={"post_id": "urn:li:share:1", "url": "https://li/1"})) as mock_post_image, \
         patch("core.publishers.linkedin.post_text", new=AsyncMock()) as mock_post_text:
        result = await publish_linkedin_post("q-1", request, user={"sub": "kelvin"})

    mock_render.assert_awaited_once_with("canva-token", "BT-123", {"headline": {"type": "text", "text": "The workflow nobody talks about"}})
    mock_post_image.assert_awaited_once()
    mock_post_text.assert_not_awaited()
    assert result["used_image"] is True
    assert result["post_id"] == "urn:li:share:1"
    conn.execute.assert_awaited_once()
    assert "published" in conn.execute.call_args.args[0]


async def test_publish_falls_back_to_text_when_no_canva_connection():
    row_no_image = {**QUEUE_ROW, "image_brief": None}
    conn = _connected_conn(row_no_image, LI_ROW, {"encrypted_access_token": None, "brand_template_ids": {}})
    # No canva row at all — connection query returns None
    conn.fetchrow = AsyncMock(side_effect=[row_no_image, LI_ROW, None])
    request = _fake_request(conn)

    with _patched_decrypt(), \
         patch("core.publishers.linkedin.post_text", new=AsyncMock(return_value={"post_id": "urn:li:share:2", "url": "https://li/2"})) as mock_post_text, \
         patch("core.publishers.canva.render_brand_template_to_image", new=AsyncMock()) as mock_render:
        result = await publish_linkedin_post("q-1", request, user={"sub": "kelvin"})

    mock_post_text.assert_awaited_once()
    mock_render.assert_not_awaited()
    assert result["used_image"] is False


async def test_publish_rejects_document_carousel_instead_of_silently_publishing_as_text():
    """Real bug found live 2026-09-21: document_carousel posts never had a
    real publish path -- carousel_slides/carousel_pdf_brief are drafted
    but nothing renders or posts them, so this function's image_brief
    check (carousels never populate image_brief) fell through to
    post_text(), silently publishing the caption alone with none of the
    carousel's actual content. Must now fail loud instead."""
    carousel_row = {**QUEUE_ROW, "format": "document_carousel", "image_brief": None}
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=carousel_row)
    request = _fake_request(conn)

    with patch("core.publishers.linkedin.post_text", new=AsyncMock()) as mock_post_text, \
         patch("core.publishers.linkedin.post_image", new=AsyncMock()) as mock_post_image:
        with pytest.raises(HTTPException) as exc_info:
            await publish_linkedin_post("q-1", request, user={"sub": "kelvin"})

    assert exc_info.value.status_code == 501
    mock_post_text.assert_not_awaited()
    mock_post_image.assert_not_awaited()
    conn.execute.assert_not_awaited()  # row must stay 'approved', never marked 'published'


async def test_publish_rejects_a_row_that_is_not_approved():
    pending_row = {**QUEUE_ROW, "status": "pending_review"}
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=pending_row)
    request = _fake_request(conn)

    with pytest.raises(HTTPException) as exc_info:
        await publish_linkedin_post("q-1", request, user={"sub": "kelvin"})

    assert exc_info.value.status_code == 409


async def test_publish_404s_when_queue_row_missing():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    request = _fake_request(conn)

    with pytest.raises(HTTPException) as exc_info:
        await publish_linkedin_post("missing-id", request, user={"sub": "kelvin"})

    assert exc_info.value.status_code == 404


async def test_publish_409s_when_linkedin_not_connected():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[QUEUE_ROW, None])
    request = _fake_request(conn)

    with pytest.raises(HTTPException) as exc_info:
        await publish_linkedin_post("q-1", request, user={"sub": "kelvin"})

    assert exc_info.value.status_code == 409
    assert "LinkedIn is not connected" in exc_info.value.detail


async def test_publish_does_not_mark_published_when_the_actual_post_fails():
    conn = _connected_conn(QUEUE_ROW, LI_ROW, CANVA_ROW)
    request = _fake_request(conn)

    with _patched_decrypt(), \
         patch("core.publishers.canva.render_brand_template_to_image", new=AsyncMock(side_effect=RuntimeError("canva exploded"))):
        with pytest.raises(HTTPException) as exc_info:
            await publish_linkedin_post("q-1", request, user={"sub": "kelvin"})

    assert exc_info.value.status_code == 502
    conn.execute.assert_not_awaited()  # status must stay 'approved', not flip to published


# ── set_brand_templates ──────────────────────────────────────────────

async def test_set_brand_templates_rejects_empty_body():
    request = _fake_request(AsyncMock())
    with pytest.raises(HTTPException) as exc_info:
        await set_brand_templates(BrandTemplateMap(), request, user={"sub": "kelvin"})
    assert exc_info.value.status_code == 400


async def test_set_brand_templates_409s_when_canva_not_connected():
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 0")
    request = _fake_request(conn)

    with pytest.raises(HTTPException) as exc_info:
        await set_brand_templates(BrandTemplateMap(linkedin_square="BT-999"), request, user={"sub": "kelvin"})

    assert exc_info.value.status_code == 409


async def test_set_brand_templates_succeeds_and_merges_only_provided_keys():
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 1")
    request = _fake_request(conn)

    result = await set_brand_templates(BrandTemplateMap(linkedin_square="BT-999"), request, user={"sub": "kelvin"})

    assert result == {"updated": True, "brand_template_ids": {"linkedin_square": "BT-999"}}
    args = conn.execute.call_args.args
    assert json.loads(args[1]) == {"linkedin_square": "BT-999"}


async def test_fetch_asset_bytes_calls_the_assets_route_over_http(monkeypatch):
    """2026-09-22 fix: must fetch live, not read local disk -- the
    dispatch cron runs in GitHub Actions, which has no access to
    Railway's persistent volume where generated images actually live."""
    monkeypatch.setattr("api.routes.internal_marketing._API_BASE", "https://api.example.test")
    monkeypatch.setenv("MARKETING_API_KEY", "secret-key")

    mock_response = MagicMock()
    mock_response.content = b"\x89PNG..."
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await _fetch_asset_bytes("assets_library/ai_agents/foo.png")

    assert result == b"\x89PNG..."
    mock_client.get.assert_awaited_once_with(
        "https://api.example.test/api/v1/internal/marketing/assets/ai_agents/foo.png",
        headers={"X-API-Key": "secret-key"},
    )


# ── Double-JSON-encoded image_brief (2026-09-22 real bug) ──────────────

DOUBLE_ENCODED_IMAGE_BRIEF_ROW = {
    **QUEUE_ROW,
    "image_brief": json.dumps({"image_id": "img_002", "image_path": "assets_library/ai_agents/bar.png"}),
}


async def test_publish_recovers_from_a_double_json_encoded_image_brief():
    """One real row had image_brief stored as a JSON string instead of a
    JSON object -- asyncpg's jsonb codec decodes it once into a plain
    str, so this must decode a second time and proceed normally rather
    than raising on the first-pass str."""
    conn = _connected_conn(DOUBLE_ENCODED_IMAGE_BRIEF_ROW, LI_ROW, CANVA_ROW)
    request = _fake_request(conn)

    with _patched_decrypt(), \
         patch("api.routes.internal_marketing._fetch_asset_bytes", new=AsyncMock(return_value=b"\x89PNG...")), \
         patch("core.publishers.linkedin.post_image", new=AsyncMock(return_value={"post_id": "urn:li:share:2", "url": "https://li/2"})):
        result = await publish_linkedin_post("q-1", request, user={"sub": "kelvin"})

    assert result["used_image"] is True


async def test_publish_raises_clearly_for_image_brief_that_is_not_valid_json_at_all():
    row = {**QUEUE_ROW, "image_brief": "not json at all"}
    conn = _connected_conn(row, LI_ROW, CANVA_ROW)
    request = _fake_request(conn)

    with _patched_decrypt():
        with pytest.raises(HTTPException) as exc_info:
            await publish_linkedin_post("q-1", request, user={"sub": "kelvin"})

    assert exc_info.value.status_code == 500
    assert "malformed" in exc_info.value.detail
    conn.execute.assert_not_awaited()  # status must stay 'approved'


# ── Asset vault image path (2026-07-22) — takes priority over Canva ──

ASSET_VAULT_QUEUE_ROW = {
    **QUEUE_ROW,
    "image_brief": {
        "image_id": "img_001", "image_path": "assets_library/ai_agents/foo.png",
        "credit_line": "Visual credit: @aloksharan", "is_original": False,
        "selected_because": "topic match on: guardrails",
    },
}


async def test_publish_uses_asset_vault_image_in_preference_to_canva():
    """2026-09-22: asset vault images are now fetched live over HTTP from
    this backend's own /assets/{path} route (_fetch_asset_bytes), not read
    off local disk -- scripts/dispatch_scheduled_posts.py runs in GitHub
    Actions, which has no access to Railway's persistent volume where
    generated images actually live. See _fetch_asset_bytes's docstring."""
    conn = _connected_conn(ASSET_VAULT_QUEUE_ROW, LI_ROW, CANVA_ROW)  # Canva IS connected+configured too
    request = _fake_request(conn)

    with _patched_decrypt(), \
         patch("api.routes.internal_marketing._fetch_asset_bytes", new=AsyncMock(return_value=b"\x89PNG...")) as mock_fetch, \
         patch("core.publishers.canva.render_brand_template_to_image", new=AsyncMock()) as mock_render, \
         patch("core.publishers.linkedin.post_image", new=AsyncMock(return_value={"post_id": "urn:li:share:1", "url": "https://li/1"})) as mock_post_image, \
         patch("assets_library.asset_logger.log_usage") as mock_log_usage:
        result = await publish_linkedin_post("q-1", request, user={"sub": "kelvin"})

    mock_fetch.assert_awaited_once_with("assets_library/ai_agents/foo.png")
    mock_render.assert_not_awaited()  # Canva never touched -- asset vault took priority
    mock_post_image.assert_awaited_once()
    assert mock_post_image.call_args.args[3] == b"\x89PNG..."
    mock_log_usage.assert_called_once_with("img_001")
    assert result["used_image"] is True


async def test_publish_raises_clearly_when_asset_fetch_fails():
    conn = _connected_conn(ASSET_VAULT_QUEUE_ROW, LI_ROW, CANVA_ROW)
    request = _fake_request(conn)
    fetch_error = httpx.HTTPStatusError(
        "404", request=MagicMock(), response=MagicMock(status_code=404),
    )

    with _patched_decrypt(), \
         patch("api.routes.internal_marketing._fetch_asset_bytes", new=AsyncMock(side_effect=fetch_error)):
        with pytest.raises(HTTPException) as exc_info:
            await publish_linkedin_post("q-1", request, user={"sub": "kelvin"})

    assert exc_info.value.status_code == 502
    assert "Publish failed" in exc_info.value.detail
    conn.execute.assert_not_awaited()  # status must stay 'approved'


async def test_log_usage_not_called_for_the_canva_path():
    conn = _connected_conn(QUEUE_ROW, LI_ROW, CANVA_ROW)  # QUEUE_ROW's image_brief has no image_path -> Canva branch
    request = _fake_request(conn)

    with _patched_decrypt(), \
         patch("core.publishers.canva.render_brand_template_to_image", new=AsyncMock(return_value=b"imgbytes")), \
         patch("core.publishers.linkedin.post_image", new=AsyncMock(return_value={"post_id": "urn:li:share:1", "url": "https://li/1"})), \
         patch("assets_library.asset_logger.log_usage") as mock_log_usage:
        await publish_linkedin_post("q-1", request, user={"sub": "kelvin"})

    mock_log_usage.assert_not_called()


# ── get_asset (2026-07-24) — dashboard image thumbnails ──────────────────

async def test_get_asset_serves_a_real_file(tmp_path, monkeypatch):
    monkeypatch.setattr("api.routes.internal_marketing._REPO_ROOT", tmp_path)
    monkeypatch.setattr("api.routes.internal_marketing._ASSETS_LIBRARY_ROOT", (tmp_path / "assets_library").resolve())
    image_file = tmp_path / "assets_library" / "my_originals" / "foo.png"
    image_file.parent.mkdir(parents=True)
    image_file.write_bytes(b"\x89PNG...")

    response = await get_asset("my_originals/foo.png")

    assert str(response.path) == str(image_file)
    assert response.media_type == "image/png"


async def test_get_asset_404s_for_a_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("api.routes.internal_marketing._ASSETS_LIBRARY_ROOT", (tmp_path / "assets_library").resolve())

    with pytest.raises(HTTPException) as exc_info:
        await get_asset("my_originals/does-not-exist.png")

    assert exc_info.value.status_code == 404


async def test_get_asset_blocks_path_traversal_outside_the_vault(tmp_path, monkeypatch):
    assets_root = tmp_path / "assets_library"
    assets_root.mkdir()
    secret_file = tmp_path / ".env"
    secret_file.write_text("SECRET=do-not-serve-this")
    monkeypatch.setattr("api.routes.internal_marketing._ASSETS_LIBRARY_ROOT", assets_root.resolve())

    with pytest.raises(HTTPException) as exc_info:
        await get_asset("../.env")

    assert exc_info.value.status_code == 400
