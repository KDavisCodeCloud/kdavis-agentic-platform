"""
Coverage for the 2026-09-15 image-pipeline sequencing fix in
api/routes/internal_marketing.py: image generation now fires
synchronously, once, the moment a linkedin_content_queue row's status
flips to 'approved' -- never before, per Kelvin's directive that a
generated image must only ever be built from post text a human has
already approved.

Also covers the 2026-09-16 follow-up fix: ceo-dashboard's actual Next.js
API routes (app/api/linkedin-queue/[id]/route.ts and .../batch-approve/
route.ts) never call this router's PATCH/batch-approve endpoints at all
-- they write straight to Supabase -- which meant everything above was
dead code in production. generate_linkedin_queue_images is the bridge
those Next.js routes now call directly, server-to-server, after their own
Supabase write.

Route handlers are called directly (no HTTP TestClient harness exists
in this repo yet) against a fake request.app.state.db_pool, same
pattern as tests/test_internal_marketing_publish.py.
generate_relevant_image (assets_library/scene_image_gen.py) is mocked
throughout -- this covers the wiring/state-machine logic (when it's
called, what happens to `status` on each outcome), not real model
output; that module has its own tests.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from api.routes.internal_marketing import (
    BatchApproveRequest,
    GenerateImagesRequest,
    QueueRowUpdate,
    _generate_and_gate_image_for_approved_row,
    _generate_images_in_background,
    batch_approve_linkedin_queue,
    generate_linkedin_queue_images,
    update_linkedin_queue_row,
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


def _generation_result(tmp_path, relevant=True, flagged=False, scene_type="TECHNICAL"):
    image_path = tmp_path / "cloud-and-ai-execution" / "some-post_20260915.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"fake")
    return {
        "image_path": image_path,
        "sidecar_path": image_path.with_suffix(".json"),
        "scene_description": "A test scene.",
        "scene_type": scene_type,
        "attempts": 1,
        "relevant": relevant,
        "reason": "YES. Matches." if relevant else "NO. Wrong subject.",
        "flagged_for_review": flagged,
    }


# ── _generate_and_gate_image_for_approved_row ───────────────────────────

@pytest.mark.asyncio
async def test_skips_document_carousel_posts():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "post_copy": "x", "pillar_name": "p", "topic": "t", "format": "document_carousel",
        "image_brief": None, "notes": None,
    })
    with patch("assets_library.scene_image_gen.generate_relevant_image") as mock_gen:
        await _generate_and_gate_image_for_approved_row(conn, "q-1")

    mock_gen.assert_not_called()
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_skips_when_row_already_has_a_real_image():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "post_copy": "x", "pillar_name": "p", "topic": "t", "format": "text_post",
        "image_brief": json.dumps({"image_path": "assets_library/my_originals/x.png"}),
        "notes": None,
    })
    with patch("assets_library.scene_image_gen.generate_relevant_image") as mock_gen:
        await _generate_and_gate_image_for_approved_row(conn, "q-1")

    mock_gen.assert_not_called()
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_successful_generation_attaches_image_and_leaves_status_alone(tmp_path):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "post_copy": "approved post text", "pillar_name": "Cloud and AI Execution", "topic": "Some Topic",
        "format": "text_post", "image_brief": None, "notes": None,
    })
    result = _generation_result(tmp_path, relevant=True, flagged=False)

    with patch("assets_library.scene_image_gen.generate_relevant_image", return_value=result), \
         patch("assets_library.gemini_image_gen.ASSETS_ROOT", tmp_path):
        await _generate_and_gate_image_for_approved_row(conn, "q-1")

    conn.execute.assert_called_once()
    sql, *params = conn.execute.call_args.args
    assert "SET status" not in sql  # never touches status here -- only the WHERE guard checks it's still 'approved'
    assert "image_brief" in sql and "image_description" in sql
    image_brief = json.loads(params[0])
    assert image_brief["image_path"] == "assets_library/cloud-and-ai-execution/some-post_20260915.png"
    assert params[1] == "A test scene."


@pytest.mark.asyncio
async def test_flagged_generation_reverts_to_pending_review_with_notes(tmp_path):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "post_copy": "approved post text", "pillar_name": "Cloud and AI Execution", "topic": "Some Topic",
        "format": "text_post", "image_brief": None, "notes": "existing note",
    })
    result = _generation_result(tmp_path, relevant=False, flagged=True)

    with patch("assets_library.scene_image_gen.generate_relevant_image", return_value=result), \
         patch("assets_library.gemini_image_gen.ASSETS_ROOT", tmp_path):
        await _generate_and_gate_image_for_approved_row(conn, "q-1")

    conn.execute.assert_called_once()
    sql, *params = conn.execute.call_args.args
    assert "status = 'pending_review'" in sql
    assert "IMAGE RELEVANCE GATE FAILED" in params[0]
    assert params[1].startswith("existing note | ")


@pytest.mark.asyncio
async def test_infra_failure_reverts_to_pending_review_without_attaching_anything():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "post_copy": "approved post text", "pillar_name": "Cloud and AI Execution", "topic": "Some Topic",
        "format": "text_post", "image_brief": None, "notes": None,
    })
    with patch("assets_library.scene_image_gen.generate_relevant_image", side_effect=RuntimeError("Gemini down")):
        await _generate_and_gate_image_for_approved_row(conn, "q-1")

    conn.execute.assert_called_once()
    sql, *params = conn.execute.call_args.args
    assert "status = 'pending_review'" in sql
    assert "IMAGE GENERATION FAILED" in params[0]


# ── update_linkedin_queue_row wiring ─────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_single_row_triggers_image_gen_and_returns_refreshed_row():
    approved_row = {"id": "q-1", "status": "approved", "hitl_notes": None, "scheduled_for": None}
    final_row = {**approved_row, "image_brief": {"image_path": "x.png"}}
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[approved_row, final_row])

    with patch("api.routes.internal_marketing._generate_and_gate_image_for_approved_row", new=AsyncMock()) as mock_helper:
        result = await update_linkedin_queue_row(
            "q-1", QueueRowUpdate(status="approved"), _fake_request(conn),
        )

    mock_helper.assert_called_once_with(conn, "q-1")
    assert result["image_brief"] == {"image_path": "x.png"}


@pytest.mark.asyncio
async def test_reject_does_not_trigger_image_gen():
    rejected_row = {"id": "q-1", "status": "rejected", "hitl_notes": None, "scheduled_for": None}
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=rejected_row)

    with patch("api.routes.internal_marketing._generate_and_gate_image_for_approved_row", new=AsyncMock()) as mock_helper:
        await update_linkedin_queue_row("q-1", QueueRowUpdate(status="rejected"), _fake_request(conn))

    mock_helper.assert_not_called()


# ── batch_approve_linkedin_queue wiring ──────────────────────────────────

@pytest.mark.asyncio
async def test_batch_approve_runs_image_gen_per_row_and_splits_reverted_from_approved():
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[
        [{"id": "q-1"}, {"id": "q-2"}],  # the UPDATE ... RETURNING id
        [{"id": "q-1", "status": "approved"}, {"id": "q-2", "status": "pending_review"}],  # final re-fetch
    ])

    with patch("api.routes.internal_marketing._generate_and_gate_image_for_approved_row", new=AsyncMock()) as mock_helper:
        result = await batch_approve_linkedin_queue(
            BatchApproveRequest(batch_month="2026-09"), _fake_request(conn),
        )

    assert mock_helper.call_count == 2
    assert result["approved_ids"] == ["q-1"]
    assert result["reverted_to_review_ids"] == ["q-2"]


# ── _generate_images_in_background ───────────────────────────────────────

@pytest.mark.asyncio
async def test_background_helper_processes_each_id_sequentially():
    conn = AsyncMock()
    pool = _FakePool(conn)

    with patch("api.routes.internal_marketing._generate_and_gate_image_for_approved_row", new=AsyncMock()) as mock_helper:
        await _generate_images_in_background(pool, ["q-1", "q-2", "q-3"])

    assert mock_helper.call_count == 3
    called_ids = [call.args[1] for call in mock_helper.await_args_list]
    assert called_ids == ["q-1", "q-2", "q-3"]


@pytest.mark.asyncio
async def test_background_helper_one_failure_does_not_stop_the_rest():
    conn = AsyncMock()
    pool = _FakePool(conn)

    with patch(
        "api.routes.internal_marketing._generate_and_gate_image_for_approved_row",
        new=AsyncMock(side_effect=[RuntimeError("boom"), None]),
    ) as mock_helper:
        await _generate_images_in_background(pool, ["q-bad", "q-ok"])

    assert mock_helper.call_count == 2


# ── generate_linkedin_queue_images endpoint (the Next.js bridge) ─────────

@pytest.mark.asyncio
async def test_generate_images_endpoint_schedules_background_task_and_returns_immediately():
    conn = AsyncMock()
    request = _fake_request(conn)
    background_tasks = MagicMock(spec=BackgroundTasks)

    result = await generate_linkedin_queue_images(
        GenerateImagesRequest(queue_ids=["q-1", "q-2"]), request, background_tasks,
    )

    assert result == {"queued": 2}
    background_tasks.add_task.assert_called_once()
    task_fn, task_pool, task_ids = background_tasks.add_task.call_args.args
    assert task_fn is _generate_images_in_background
    assert task_ids == ["q-1", "q-2"]


@pytest.mark.asyncio
async def test_generate_images_endpoint_rejects_empty_list():
    conn = AsyncMock()
    request = _fake_request(conn)
    background_tasks = MagicMock(spec=BackgroundTasks)

    with pytest.raises(HTTPException) as exc:
        await generate_linkedin_queue_images(GenerateImagesRequest(queue_ids=[]), request, background_tasks)

    assert exc.value.status_code == 400
    background_tasks.add_task.assert_not_called()
