# SOP: document_carousel LinkedIn Posts Silently Publishing Without Images
Date: 2026-09-21
Product: Kelvin's personal LinkedIn brand (MKT) — `linkedin_content_queue`
Status: Live — root cause fixed, regression test added, tested against full suite

---

## What triggered this

Kelvin: "Linkedin content created without images. Need to find the root cause to why and make sure it doesn't happen again and that bug is fixed also."

## Investigation

This looked at first like it could be the same failure class as the 2026-09-15 image-relevance incident ([[2026-09-15-linkedin-image-relevance-audit-and-pipeline-sequencing-fix]]) — a mismatched or missing image on an otherwise-normal post. It wasn't. Ruled out in order:

1. **Format-value hypothesis** — checked `db/migrations/007_marketing_queues.sql`'s CHECK constraint: `format text CHECK (format IN ('text_post', 'document_carousel'))`. Only two legal formats exist; no typo/unexpected value possible.
2. **Race condition on the post-approval image gate** — `_generate_and_gate_image_for_approved_row` (the 2026-09-15 fix) reverts to `pending_review` on any failure and never leaves a row silently `approved` with no image. Considered, not the cause here.
3. **A second write path bypassing approval** — checked `agents/marketing/mkt_09_hitl_queue_manager.py` and `api/routes/marketing.py` for any other place that could flip a row to `approved` or call a publish function directly. Nothing found; `publish_queue_row` in `api/routes/internal_marketing.py` is the only publish path.

**Actual root cause**, found by reading `publish_queue_row` directly: it has no handling at all for `format == "document_carousel"`. Carousel content (`carousel_slides`, `carousel_pdf_brief`) is drafted in three places — `agents/marketing/mkt_li1_linkedin_brand.py`, `agents/marketing/mkt_v1_content_multiplier.py`, `scripts/generate_showing_signal_week.py` — but read nowhere. `core/publishers/linkedin.py` only ever had `post_text` and `post_image`; there has never been a document/carousel-post function in this codebase. Carousels also never populate `image_brief` (they use the separate `carousel_pdf_brief` field), so `publish_queue_row`'s own image-brief check fell through to its `else` branch and quietly published the caption alone via `post_text`, with `used_image=False` and no error. `scripts/dispatch_scheduled_posts.py`'s cron reported every one of these as a success — there was never a signal anywhere that a carousel post had gone out with none of its actual visual content.

## Fix

`api/routes/internal_marketing.py`'s `publish_queue_row`: added an explicit check for `format == "document_carousel"` immediately after the `status != 'approved'` guard, before any credential/token lookup. It raises `PublishError(501, ...)` naming exactly what's missing (no renderer for `carousel_slides`/`carousel_pdf_brief`, no document-post function in `core/publishers/linkedin.py`) instead of falling through to the text-only path. The row stays `approved` so it can be retried once real carousel publishing exists, rather than being marked `published` against reality.

This matches the function's own existing contract — every other failure path in `publish_queue_row` already raises with a descriptive message rather than degrading silently; this was the one gap.

## Test coverage added

`tests/test_internal_marketing_publish.py::test_publish_rejects_document_carousel_instead_of_silently_publishing_as_text` — builds a `document_carousel` row with `image_brief=None` (the real shape every carousel row has), asserts `publish_linkedin_post` raises `HTTPException(501)`, and asserts `post_text`/`post_image` are never awaited and `conn.execute` is never awaited (row must never be marked `published`).

Full suite run: 1997 passed, 4 pre-existing failures unrelated to this change (`test_agent01_local.py::test_diagnose_node_returns_three_options`, three in `test_security.py` around AWS/Azure secret redaction) — confirmed identical with and without this fix via `git stash`.

## Follow-up not built here (see GAPS.md #30)

Two options, deferred for Kelvin's decision, not built this session per this repo's "surface gaps, don't build mid-session" rule:
1. Build real carousel publishing — LinkedIn's Documents API, rendering `carousel_slides`/`carousel_pdf_brief` into an actual postable PDF/image set.
2. Retire `document_carousel` as a choosable format entirely if it's not worth building.

Until one of those happens, any existing `approved` carousel rows will now fail loudly (501) instead of quietly going out wrong — check the dashboard/logs for 501s on publish if Kelvin has carousel content queued.

## If this breaks again

- **A carousel post publishes with no images again:** confirm the `format == "document_carousel"` check is still the first thing checked in `publish_queue_row`, before the image_brief branch.
- **A different format silently loses its visual content:** check whether that format also lacks a real writer for whatever field it uses to carry visual content — the underlying lesson here is that `publish_queue_row`'s fallback-to-text-only branch is not a safe default for any format that isn't a plain text/single-image post.
