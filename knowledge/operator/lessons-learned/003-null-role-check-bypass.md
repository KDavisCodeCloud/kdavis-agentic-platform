# Lesson — A Role Check Written as a Bare Comparison Silently Passes for an Anonymous Caller

**Date:** 2026-09-07
**Phase:** DIST Phase 8 — closing the `mse_leads` pipeline loop

## What Was Found

While building `update_lead_stage()`/`log_lead_activity()` (new Postgres functions, same `SECURITY DEFINER` + `auth.jwt() -> 'app_metadata' ->> 'role'` role-check shape as the existing `decide_hitl_item()`), testing the new functions with the public **anon key** — not a real admin/hitl session — should have produced a role-rejection error. It didn't at first, for the exact same reason `decide_hitl_item()` didn't either, once it was checked the same way:

```sql
if v_role <> 'admin' then raise exception ...       -- WRONG
if v_role not in ('admin', 'hitl') then raise ...   -- WRONG
```

When `v_role` is `NULL` (an anon-key-only caller has no `app_metadata.role` claim at all — a completely realistic case, since the anon key is public), both `NULL <> 'admin'` and `NULL NOT IN (...)` evaluate to SQL's three-valued `NULL` (unknown), not `true`. plpgsql's `IF` treats `NULL` as `false` and does not raise — so the check silently no-ops and the caller falls through as if already authorized.

`decide_hitl_item()` had shipped to `microsaas-prod` with this exact bug (migration `20260831000036`). An anonymous caller who knew or guessed a pending `mse_hitl_items` id could approve/reject it — including a `mse_positioning`-sourced item, bypassing the admin-only positioning-approval gate this codebase documents in multiple places as a hard, three-layer invariant.

## Why It Matters

- This is not a hypothetical: the anon key is meant to be public (shipped to every browser), so "a caller with no role claim" isn't an edge case, it's the *default* unauthenticated request shape.
- A passing test with a real admin or hitl JWT proves the happy path works. It proves nothing about whether the check actually rejects everyone else — only a test that deliberately sends no role claim (or the anon key specifically) does that.
- The bug is easy to reintroduce because it reads correctly at a glance — `<>` and `NOT IN` look like they obviously reject anything that isn't the allowed value. The three-valued-logic gap only shows up when you know to look for it.

## Fix

Wrap the comparison so a missing role can never produce `NULL`:

```sql
if coalesce(v_role, '') <> 'admin' then ...
if coalesce(v_role, '') not in ('admin', 'hitl') then ...
```

Fixed in `decide_hitl_item()` via migration `20260907000043_fix_decide_hitl_item_null_role_bypass.sql`; `update_lead_stage()`/`log_lead_activity()` shipped with the fix from the start.

## What to Watch For Next Time

- Any `SECURITY DEFINER` function in this codebase that checks `auth.jwt() -> 'app_metadata' ->> 'role'` (there will be more of these as the unified HITL queue grows) needs an explicit test that calls it with the **anon key**, not just a real role's JWT, before it's considered done.
- Same three-valued-logic trap applies anywhere else a NULL-able column or claim is compared with a bare `<>`/`=`/`NOT IN`/`IN` inside an `IF` — not unique to role checks. `coalesce(...)` (or `IS DISTINCT FROM`) is the fix whenever the left-hand side can legitimately be NULL.
