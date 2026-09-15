# SOP: LinkedIn Image Relevance Audit + Pipeline Sequencing Fix
Date: 2026-09-15
Product: Kelvin's personal LinkedIn brand (MKT-LI1) — `linkedin_content_queue`
Status: Live — backlog repaired, permanent pipeline rewired and tested

---

## What triggered this

Kelvin asked for two things: (1) audit every unpublished post with an image attached and fix any mismatch, (2) find where image generation was wired into the post-creation flow and fix the sequencing — images were being generated at draft time, before any human ever saw the post text, not after approval.

## Audit results (Task 1)

Scored all 22 unpublished `linkedin_content_queue` rows with an image (11 `pending_review`, 2 `approved`, 9 `rejected`) against their actual post text — not "is it a diagram," but "does this image depict what this specific post is about" (Kelvin's own correction mid-session: not every image needs people; Gemini decides the visual form from the parsed post content). The 24 already-published rows were explicitly left untouched — there's no way to swap an image on a post already live on LinkedIn, so editing our own DB record for one would just create a record that disagrees with what's actually posted.

Result: 10 MATCH, 2 PARTIAL, **10 MISMATCH**.

**Root cause of the 10 mismatches:** `assets_library/asset_selector.py`'s topic-word substring matching was loose enough that generic infra vocabulary (Kubernetes, LLM-agnostic, HITL, multi-tenant) in unrelated posts' topics matched an already-generated image's tags, and since every post in that batch run was drafted back-to-back with no publishes in between (`times_used=0` for all), the tie-break kept converging on the same earliest-generated file. Nine posts ended up sharing one "CI/CD Failure Path Map" diagram generated for a completely different post; one shared a "multi-agent marketing swarm" diagram. This is the same failure mode `scripts/fix_august_batch_images.py` patched once before, resurfacing in a later batch.

The 2 PARTIAL cases were real quality problems on otherwise-bespoke images: the garden/philosophy post's diagram had no trace of the garden metaphor that was the actual point of the post, and the "graceful failure handling" post's diagram had badly garbled text.

## Backlog fix

Built `assets_library/scene_image_gen.py` — a two-step, relevance-gated generator — and used it to regenerate all 12 flagged images via `scripts/fix_image_relevance_backlog.py` (hardcoded, documented list of the 12 queue IDs and their audit verdicts, same one-off-script pattern as `fix_august_batch_images.py`).

**Real bug found mid-run:** the first full pass used `gemini-2.5-flash-image` and got every subject right but garbled dense technical labels across nearly every image (`"Orchrestation"`, `"RepicaSets"`, `"Abstrcation Interface"`, `"Arthropic"`) — the relevance gate at that point only checked subject match, not legibility, so it passed all 12 anyway. Fixed two ways: upgraded to `gemini-3-pro-image-preview` (`assets_library/gemini_image_gen.py`'s `MODEL` — this was already the documented upgrade path in that file's own docstring), and extended the relevance gate's prompt to also reject garbled/misspelled visible text. The model swap then surfaced a second, unrelated bug: `gemini-3-pro-image-preview` returns JPEG bytes under the same `inlineData` field `gemini-2.5-flash-image` always returned PNG through, and Claude's vision API hard-rejects a mismatched declared media type — every one of the 12 relevance-gate calls failed with a 400 until `_generate_image` was fixed to always round-trip the response through Pillow and return genuine PNG bytes regardless of what the model actually sent.

Final backlog result: **11 images fixed and attached, 1 flagged for manual HITL review** (`4fa35503-f5be-49e5-aba2-b70072cda635`, the "scope discipline" post — already `status='rejected'` from before this session, so no live-queue risk; `hitl_notes` on that row explains the gate failure if Kelvin ever revisits it).

## Permanent pipeline fix (Task 2 + 3)

**Sequencing, before:** `agents/marketing/mkt_li1_linkedin_brand.py` drafted `image_description` (a rigid single-diagram Gemini prompt) in the *same* LLM call as `post_copy`, then `_select_image_for_post` matched/generated an image immediately at draft time — before any human ever reviewed the post. `monthly_batch.sh`'s Step 1.5 ran Gemini generation right after drafting, still before HITL.

**Sequencing, after:**
1. MKT-LI1 drafts `post_copy` only — `image_brief`/`image_description` are always null now, for every format, regardless of pillar or post type. `_select_image_for_post` and the `asset_selector.select_asset()` call are gone from this file entirely.
2. A human approves the post text in the dashboard (single-row PATCH `/linkedin-queue/{id}` or the batch-approve action).
3. **Only then**, `api/routes/internal_marketing.py`'s new `_generate_and_gate_image_for_approved_row` fires synchronously, inside that same approval request: reads the just-approved `post_copy`, calls `scene_image_gen.py`'s two-step pipeline (LLM extracts a scene description + classifies it CONTRAST/MOMENT/STORY/TECHNICAL, which shapes layout only — split panel, single scene, progression, or systems-diagram — never forcing people into the image), generates via Gemini, then gates the result (subject match + legibility) via Claude vision. One automatic regeneration on failure; still failing reverts the row to `pending_review` with `hitl_notes` explaining why, so `scripts/dispatch_scheduled_posts.py` can never publish a row that never got a real image decision.

`monthly_batch.sh` no longer has an image-generation step at all — approving a post (individually or in bulk) is what generates its image now.

**Known tradeoff, accepted for now:** a batch approval holds one pooled DB connection for the whole loop (N sequential Gemini + Claude calls, real minutes for a full monthly batch). Fine for an owner-only tool approving ~10-12 posts a month; noted in `batch_approve_linkedin_queue`'s docstring as the first thing to revisit if batch size or dashboard concurrency ever grows.

## Test coverage added/updated

- `tests/test_scene_image_gen.py` (new) — scene extraction/classification parsing, prompt composition, gate/regenerate-once/flag state machine.
- `tests/test_internal_marketing_approval_image_gen.py` (new) — approval-endpoint wiring: carousel skip, already-has-image skip, success/flagged/infra-failure outcomes, single-row and batch-approve call sites.
- `tests/test_mkt_li1_asset_vault_wiring.py` (rewritten) — the old file tested draft-time `asset_selector` wiring that no longer exists; now asserts `image_brief`/`image_description` are always null and `select_asset`/`_select_image_for_post` are gone from the module.
- `tests/test_mkt_li1_on_demand.py`, `tests/test_mkt_li1_stance_rotation.py` — removed now-dead `select_asset` mock patches.
- `tests/test_gemini_image_gen.py` — updated to feed `_generate_image` genuine decodable PNG bytes (it now round-trips every response through Pillow) instead of an opaque fake byte string.

90 tests passing across the affected suite.

---

## If this breaks again

- **A future post's image is topically wrong again:** check whether `assets_library/asset_selector.py` got reintroduced into the approval flow — it should never be called from `mkt_li1_linkedin_brand.py` or the approval endpoints again. The fix here was removing vault-matching from the LinkedIn flow entirely in favor of always-bespoke, scene-gated generation.
- **Images have garbled text again:** confirm `assets_library/gemini_image_gen.py`'s `MODEL` is still `gemini-3-pro-image-preview`, and that `scene_image_gen.py`'s `RELEVANCE_GATE_SYSTEM_PROMPT` still checks legibility, not just subject match.
- **A generated image request 400s against Claude's vision API:** almost certainly a mime-type mismatch again — confirm `_generate_image` is still round-tripping through Pillow (`image.convert("RGB").save(png_buffer, format="PNG")`) rather than returning whatever bytes/mime type the model happened to send.
- **A row sits `approved` with no image and isn't getting published:** check `hitl_notes` on that row first — `_generate_and_gate_image_for_approved_row` reverts to `pending_review` on any failure, it never leaves a silently broken `approved` row.
