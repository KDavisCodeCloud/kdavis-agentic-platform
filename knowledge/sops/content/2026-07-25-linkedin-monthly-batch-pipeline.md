# SOP: LinkedIn Monthly Batch Pipeline (MKT-LI1 + Gemini)
Date: 2026-07-25
Product: Kelvin's personal LinkedIn brand (not a monetized product)
Status: Live — first real end-to-end batch ran successfully 2026-07-23/24

---

## What this replaced

Previously tracked as "LinkedIn + Canva Pipeline," paused since 2026-07-14 on an OAuth click-through failure. That's resolved (see Bug section below) and the whole design changed: Canva is intentionally parked per Kelvin's directive ("only for generating our own ideas, which we aren't doing yet") — Gemini image generation replaced it entirely, and the cadence moved from a pooled weekly model to a fixed monthly batch.

---

## How to run a monthly batch

```bash
bash scripts/monthly_batch.sh --input path/to/request.json --batch-month YYYY-MM
```

`request.json` needs `research_report` (content angles), `idea_reservoir`, `kelvin_voice_profile`, and optionally `build_updates` — see `scripts/test_batch_input.json` for a real example. This calls `POST /marketing/linkedin-brand` (needs the FastAPI backend running — locally is fine, this is a manual once-a-month action, not something that needs to be always-on), which:

1. **MKT-LI1** (`agents/marketing/mkt_li1_linkedin_brand.py`) drafts ~12 posts, each with a real `scheduled_for` date (Tue/Wed/Thu, 9am ET, spread across the month), writes them to `linkedin_content_queue` with `status='pending_review'`.
2. **Step 1.5** — `assets_library/extract_image_briefs.py` pulls the per-post Gemini prompts out of the batch response, `assets_library/gemini_image_gen.py` generates one image per post (one Gemini API call per post — never batched into one call, which is what causes Gemini to default to multi-panel collages) and re-attaches it directly to that post's queue row by id.

Then: review and approve in ceo-dashboard's Marketing page. Approving is a one-time action (individually, or "Approve all pending" for the whole batch — never all-or-nothing, some posts can be approved, some rejected, some held with a note, independently). `scripts/dispatch_scheduled_posts.py` (GitHub Actions cron, every 15 min) publishes each approved post automatically when its own `scheduled_for` time arrives — this runs directly against Postgres and doesn't need the FastAPI backend at all.

---

## Dashboard review UI (ceo-dashboard → Marketing & Sales)

- Each post: topic, pillar, status badge, tier, one-line preview, scheduled time, image status
- **Review / Collapse** button — expands to the full untruncated post text, the image at full size (320px), and any hook variants the model drafted
- **Approve** / **Reject** / a datetime picker to reschedule
- **Append** — a note field (`hitl_notes`) independent of the approve/reject decision, e.g. "approve but flag the second sentence" or a rejection reason
- **Approve all pending** — approves every `pending_review` post in the selected `batch_month` in one action; already-decided posts are left untouched

Hook variants are alternate headline options the model drafts for reference — confirmed structurally impossible for them to end up in the actual published post: `publish_queue_row` (the one function both the manual publish button and the dispatch cron use) selects only `id, post_copy, image_brief, format, status` — `hook_variants` isn't even in that query.

---

## Model choice: Gemini image generation

`assets_library/gemini_image_gen.py` calls the REST API directly (`requests`, not the `google-genai` SDK — that SDK requires `httpx>=0.28`, which conflicts with `supabase==2.7.4`'s `httpx<0.28` pin; confirmed by installing it and watching the import chain break, reverted).

Model: `gemini-2.5-flash-image` ("Nano Banana") — chosen for reliable text rendering, which matters since every diagram is dense with labels. If legibility isn't good enough in practice, `gemini-3-pro-image-preview` ("Nano Banana Pro") is the documented upgrade path — swap the `MODEL` constant, no other code change needed.

**Real gotcha:** the first real batch hit `429 Quota exceeded... limit: 0` for the image-gen model specifically — not a rate limit, a hard zero-quota on that Google Cloud project (image generation needs billing enabled separately from plain text Gemini calls, even on what's nominally the "free tier"). Once Kelvin enabled billing, retrying the exact same saved batch file worked (idempotent — skips already-generated images by topic+date, so retrying never duplicates).

---

## Real bugs found getting the first batch to actually complete

None of this had ever been exercised against live data before 2026-07-23 (see [[lessons-learned/002-verify-against-live-data-not-mocks]] for the pattern this reveals). In the order they were hit:

1. **Migration 007 (`linkedin_content_queue`) had never been applied to the live database** — the table didn't exist at all. Applied it.
2. **Once applied, the very first insert failed anyway** — `run_li1_brand_agent` has always written `pillar`/`topic`/`hitl_tier`/`estimated_length`/`notes`/`pillar_name`, none of which migration 007 ever defined as columns. Added migration 014.
3. **`security/audit_log.py` wrote a column (`actor`) that doesn't exist** on the live `audit_log` table (real column is `agent_id`), and tried inserting plain strings (`"marketing"`/`"internal"`) into `uuid`-typed `product_id`/`tenant_id` columns. Had never once succeeded for any of the 5 marketing agents that call it — the 113 pre-existing rows in that table all came from a completely different code path with real UUIDs. Fixed to write the real columns; non-UUID callers now fall back into a `metadata` jsonb field instead of crashing.
4. **`audit_log_outcome_check` only allowed `'win'`/`'lose'`** (the MSE opportunity dashboard's vocabulary — the only caller that had ever actually written a row). Every other agent family uses its own independent vocabulary (`success`/`failure:...`, `passed`/`flagged:...`, `ok`/`error`, `hitl_approved`/`assertion_failed`) — a whitelist doesn't fit a column with this many uncoordinated vocabularies. Replaced with a simple non-empty check (migration 015).
5. **`_draft_post` never stripped Claude's ` ```json ` markdown fence** before `json.loads()` — every real call had always silently fallen back to raw-text mode (confirmed: the first live batch returned 10 fallback posts, topic literally equal to the pillar name). Also bumped `max_tokens` 1500→4000 (too small once `image_description` was added) and now tolerates literal unescaped newlines Claude sometimes emits inside JSON string values.
6. **`post_formatter.py`'s sentence-splitter treated a numbered list's "1." as a sentence-ending period**, splitting the number onto its own line from its own statement. Fixed with a 2-character lookbehind. First attempt at the regex compiled and passed review but didn't actually change behavior — Python evaluates multiple lookbehinds at the same position, so a single-char check was asking the wrong question. Caught by testing against the real failing text before calling it done.

---

## If this breaks again

- **Batch generation returns 0 posts:** check the raw API response body, not just `post_count` — `monthly_batch.sh` doesn't currently surface a FastAPI error detail if the whole call 500s (a known small gap, not yet fixed).
- **Images fail with a 429:** check whether it's `RESOURCE_EXHAUSTED` with `limit: 0` (billing/quota, needs a Google Cloud console fix) vs. a transient `503` (just retry — idempotent).
- **A post's number and its list statement print on separate lines:** that's the pre-2026-07-25 formatter bug — if it recurs, check `_SENTENCE_SPLIT_RE` in `assets_library/post_formatter.py` hasn't regressed.
