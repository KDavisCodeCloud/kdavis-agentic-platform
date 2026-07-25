# Lesson — Mocked Tests Can Hide That Code Has Never Actually Run

**Date:** 2026-07-25
**Phase:** LinkedIn Monthly Batch Pipeline — first real end-to-end run

## What Was Found

Getting the first real LinkedIn batch to complete (see [[sops/content/2026-07-25-linkedin-monthly-batch-pipeline]]) surfaced five independent, previously-invisible bugs, all with the same shape: code that looked correct, had test coverage, and had been reviewed — but had **never once been exercised against the real database or a real LLM response**:

- `linkedin_content_queue`'s own migration had never been applied to the live database at all
- Once applied, the insert itself failed — the code has always written columns the migration never defined
- `security/audit_log.py` had a real column-name mismatch (`actor` vs. the live table's `agent_id`) that would break on the very first real write, for every one of 5 agents that call it
- A CHECK constraint scoped to one caller's vocabulary silently blocked every other caller
- The JSON-parsing fallback in `_draft_post` had been "working" for months because every real Claude response gets wrapped in a markdown fence that the parser never stripped — meaning it had always silently produced garbage, and the fallback path itself was the only thing that had ever actually run

Every one of these had unit tests. The tests passed. They tested the code's logic correctly — they just never touched the real schema or a real model response, so a whole category of "does this actually work against reality" bug had zero coverage.

## Why It Matters

- A green test suite is not the same claim as "this has run successfully against production data." Mocking the DB/LLM call is the right choice for testing logic in isolation, but it means schema drift and real-response-format quirks are structurally invisible until the first live run.
- These bugs compounded — migration 007 not being applied blocked everything else from ever being discovered, so bugs 2-5 had been sitting there, undetected, for as long as the code existed.
- The actual fix each time was small (a migration, a column rename, a regex). The expensive part was that nothing surfaced any of this until someone actually tried to use the feature for real.

## Proof

Real audit_log table had 113 pre-existing rows, all from a completely different code path with real UUIDs — none from `security/audit_log.py`'s own `AuditLog.append()`, which would have hit the exact same `actor`-column error every time it was ever called. Confirmed by checking `information_schema.columns` directly against the live table before touching the code, rather than trusting what the class's own docstring claimed about how it worked.

## What to Watch For Next Time

- Before trusting "this is built and tested" for anything that writes to a shared table: check the table actually has the columns the code assumes, against the live schema, not the migration file (a migration file existing doesn't mean it was ever run).
- When a fallback/error path exists in code, treat "does the primary path actually get hit in practice" as an open question, not an assumption — the primary JSON-parsing path here had a 100% failure rate for months and nobody knew because the fallback quietly produced *something*.
- The fix for a too-narrow CHECK constraint isn't always "add the missing value" — if a second and third distinct value show up on retry, stop patching one at a time and check what the *actual* full range of real usage looks like across every caller first.
- A regex or logic fix that "should" work isn't done until it's tested against the real failing input specifically — a fix that compiles, passes existing tests, and looks correct on inspection can still silently do nothing (found here: a lookbehind that checked the wrong character entirely, twice, before landing on the right one).
