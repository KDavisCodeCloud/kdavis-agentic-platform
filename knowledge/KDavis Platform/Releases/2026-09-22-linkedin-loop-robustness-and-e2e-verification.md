# Release: LinkedIn Posting Loop — Root Cause, Robustness, E2E Verified
Date: 2026-09-22
Migrations: 052-055

## What Kelvin asked for
After the token-expiry and OAuth-state fixes earlier the same day: "I
need an end to end test of my linkedin posting from ceo dashboard to
the posts ending on linkedin, and I need this loop to be robust and
not to break again. Its a simple loop, yet there's too many fixes
happening for something that does work."

Fair pushback. The real problem was never any single bug — it was that
the pipeline had zero integration coverage and zero symptom-level
monitoring, so unrelated bugs kept surfacing as the same "posts aren't
going out" complaint, discovered late each time.

## The actual root cause of the "too many fixes" pattern
Traced the dashboard's real approve action (`ceo-dashboard/app/api/
linkedin-queue/[id]/route.ts` — writes straight to Supabase, then calls
a separate bridge, `lib/trigger-image-generation.ts`, to reach the
FastAPI backend's image-gen endpoint) through to
`_generate_and_gate_image_for_approved_row` in
`api/routes/internal_marketing.py`. Found the true source bug: that
function bound `json.dumps(image_brief)` as a query parameter on a
connection where `api/main.py`'s pool already has
`core/db.py`'s `register_jsonb_codec` applied (encoder=`json.dumps`) —
double-encoding **every** auto-generated `image_brief` into a JSON
string instead of a JSON object, silently, since the function was
written. Not a one-off bad row. Fixed at the source (pass the native
dict); the earlier defensive recovery stays as a safety net for
historical rows only.

Two existing unit tests had been asserting the *buggy* behavior as
correct (`json.loads(params[0])`, expecting a string) — they mocked
`conn.execute` and checked the code's self-consistency, never real
Postgres. This is structural: `tests/conftest.py` stubs `asyncpg`
entirely, so no test in this 2000+-test suite can catch a real
codec-serialization bug. Fixed both assertions. Verified the fix two
ways beyond mocks: a live round-trip against the real database (a
native dict now comes back as a dict, confirmed), and a new static
guard test (`tests/test_no_double_json_encoding.py`) that fails CI if
this exact pattern reappears in this file.

**Found the identical anti-pattern in ~10+ other files** (`core/hitl.py`,
`core/notification_retry.py`, `api/routes/incidents.py`, others) —
deliberately not audited or fixed this session (a static match can't
tell a real bug from a legitimate `text` column; guessing wrong risks a
new bug). Logged as GAPS.md #33 for a dedicated pass.

## Robustness: symptom-based monitoring, not cause-based
`core/linkedin_queue_health.py` (new, hourly, migration 055): alerts
if any `linkedin_content_queue` row sits `approved` past its
`scheduled_for` with no `published_at` for 2+ hours, re-alerting at
most once/day while stuck. This catches *any* future failure mode —
including ones nobody's hit yet — within hours instead of the 3 days
this incident took to notice. Confirmed firing for real in production
within minutes of deploy (the one known-bad legacy row, see below,
triggered it immediately).

Full list of what closes the loop from today:
1. `core/social_token_expiry.py` — LinkedIn token expiry, 14-day warning + daily re-alert once expired.
2. `core/linkedin_queue_health.py` — stuck-post symptom monitor, this entry.
3. Migrations 053/054 — OAuth state moved from broken per-worker memory to Postgres (both the owner-only and customer-facing flows).
4. This entry's fix — image_brief written correctly at the source.
5. `tests/test_no_double_json_encoding.py` — regression guard for the specific bug class.

## End-to-end verification (real, not simulated)
Approved a real pending draft (`27430104-de78-43c2-bde6-b4e66cb3704e`)
via the exact write the dashboard's PATCH route performs (direct
Supabase update, `status='approved'`), then called the exact same
image-generation bridge endpoint the dashboard calls
(`POST /internal/marketing/linkedin-queue/generate-images`, same
`X-API-Key` auth). Watched real Gemini generation complete, confirmed
the resulting image was actually fetchable live from the backend (catching
one more real issue proactively: this row's *original* July image had
been lost pre-persistent-volume-fix, exactly like the still-open row
below — cleared it and let generation run fresh rather than reusing a
known-bad reference). Triggered the real dispatch workflow. Result:

**Published live: https://www.linkedin.com/feed/update/urn:li:share:7508243032345853952**

Confirms the full real path end-to-end: dashboard-equivalent approval →
real image generation → image served live → LinkedIn publish → queue
row marked published.

## Still open — needs Kelvin's decision, not a code fix
`5c4d8d01-67d3-462d-85f3-f975727e0a0f` — a pre-persistent-volume-fix
row whose image was lost the same way the test row's was, but this one
hasn't been cleared/regenerated. Options: clear its `image_brief` (same
fix as above, lets real generation run) or re-approve as text-only.
The new stale-post monitor is correctly alerting on it right now — that
alert should stop once this row is resolved.

## Outcome
Full suite 2160 passed, same 4 pre-existing unrelated failures, zero
regressions. All migrations (052-055) confirmed applied via direct
query. Two real LinkedIn posts published today as a direct result of
this fix (the E2E test row, plus the earlier asset-fetch-fix
verification row).

## If this fails next time
- Check for a "stuck posts" email from `core/linkedin_queue_health.py`
  first — it now fires within hours of any failure, not days.
- If it's an image-generation/serving issue specifically, check
  whether the referenced image predates the persistent-volume fix
  (`knowledge/sops/` — search "persistent-volume") before assuming a
  new bug; several older rows still reference now-lost pre-fix images.
- GAPS.md #33 has the list of other files carrying the same
  double-encoding risk pattern, for whenever that dedicated audit
  happens.
