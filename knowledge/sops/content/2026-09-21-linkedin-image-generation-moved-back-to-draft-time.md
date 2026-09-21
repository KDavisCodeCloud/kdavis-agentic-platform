# SOP: LinkedIn Image Generation Reverted to Draft Time (Before Approval)
Date: 2026-09-21
Product: Kelvin's personal LinkedIn brand (MKT-LI1) — `linkedin_content_queue`
Status: Live — reverts the 2026-09-15 sequencing change, tested, deployed

---

## What triggered this

Kelvin, after a dashboard screenshot showing every `pending_review` post with "no image":

> "I need to be able to approve the images and I was able to do so in previous deployments. that needs to continue to take place before approval, not after. Not sure where you got the idea that this was better. stick to what my instructions are and have been."

This directly reverses the 2026-09-15 sequencing fix ([[2026-09-15-linkedin-image-relevance-audit-and-pipeline-sequencing-fix]]), which moved image generation from draft time to post-approval time. That change was real work done the same day as a genuine image-relevance incident and was framed in that session's own SOP as fixing "images being generated at draft time, before any human ever saw the post text, not after approval" — but the interpretation of what Kelvin wanted was wrong. He wants to review and approve the image together with the caption, as one decision — not approve text blind and have an image appear afterward with no further review step.

## What was actually broken in the 2026-09-15 incident (re-examined)

Re-reading that day's own SOP: the root cause of 10/22 posts sharing the wrong image was `assets_library/asset_selector.py`'s loose topic-word substring matching converging multiple posts onto the same earliest-generated file — a vault-matching bug, not a timing bug. That same session already fixed the actual defect by replacing vault-matching entirely with `assets_library/scene_image_gen.py`'s bespoke, two-step (scene-extraction → Gemini generation) + relevance-and-legibility-gated pipeline. The additional decision to also move the trigger point from draft time to post-approval time was a second, separate change bundled into the same fix — and it's the one Kelvin is now correcting. The relevance fix stands; the timing change is reverted.

## Fix

Added `_attach_generated_image(post, anthropic_client=None)` to `agents/marketing/mkt_li1_linkedin_brand.py` — calls `scene_image_gen.generate_relevant_image()` and mutates the in-progress post dict with `image_brief`/`image_description` (or, on failure, leaves them null and appends a note — an image pipeline failure must never block drafting or queuing the post text). Wired into all five paths that produce a `text_post` row before it reaches `queue_for_review`:

1. `run_li1_brand_agent` (monthly evergreen batch)
2. `generate_on_demand_posts` ("Fire N posts" dashboard button)
3. `generate_builder_post` (session-notes-driven posts)
4. `generate_product_launch_post` (active-stage product launches)
5. `generate_product_content`'s warming-stage branch (product mention posts)

`document_carousel` format is unaffected — `_attach_generated_image` is a no-op for it, since carousels use `carousel_pdf_brief`, not a single generated image (see [[2026-09-21-document-carousel-publish-gap-fix]] for that format's separate, still-open publish gap).

`api/routes/internal_marketing.py`'s `_generate_and_gate_image_for_approved_row` (the 2026-09-15 post-approval hook) is **not removed** — it's now a fallback only, for the rare case a row reaches `pending_review` with no image (a draft-time generation failure). Its own `existing_brief` guard already makes it a no-op once an image exists, so leaving it wired into the approval endpoints costs nothing and preserves the "never leave an approved row with no image decision made" guarantee from that session for the edge case where draft-time generation didn't run or failed.

## Test coverage

- `tests/test_mkt_li1_asset_vault_wiring.py` — rewritten (previously asserted the opposite: image_brief always null at draft time). Now covers: real image attached on success, carousel format never calls generation, a generation failure leaves the brief null and notes it but still queues the post, a relevance-gate-flagged image still attaches (with a hitl_note) since Kelvin reviews it himself now.
- `tests/test_mkt_li1_on_demand.py`, `test_mkt_li1_new_post_types.py`, `test_mkt_li1_selling_stage_gate.py`, `test_mkt_li1_stance_rotation.py` — each gained an `autouse` fixture mocking `generate_relevant_image`, since these tests' fake Anthropic clients use finite `side_effect` lists sized to the number of draft calls; without the mock, `generate_relevant_image`'s own internal LLM calls (scene extraction + relevance check) would consume responses meant for the next draft.

Full suite: 1998 passed, 4 pre-existing failures unrelated to this change (`test_agent01_local.py`, three in `test_security.py`) — confirmed identical with and without this fix in the same session's earlier carousel-publish fix.

## If this breaks again

- **Images stop appearing at review time again:** check that `_attach_generated_image` is still called from all five drafting entry points listed above, before `queue_for_review` — not after. This is the one thing that must never regress again per Kelvin's explicit correction.
- **A future "let's move image generation after approval" idea comes up:** don't. That was tried 2026-09-15 and explicitly reverted 2026-09-21 because it took the image out of Kelvin's review step. If there's a real reason to revisit it, it needs Kelvin's explicit sign-off first, not a unilateral re-interpretation of an old incident.
- **Image relevance/quality regresses (wrong subject, garbled text):** that's a `scene_image_gen.py` problem, unrelated to this fix — see the 2026-09-15 SOP's own "If this breaks again" section.
