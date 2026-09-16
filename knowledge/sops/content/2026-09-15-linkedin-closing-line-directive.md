# SOP: LinkedIn Closing Line Directive — "Link in the comments" / "Working with me"
Date: 2026-09-15
Product: Kelvin's personal LinkedIn brand (MKT-LI1) — `linkedin_content_queue`
Status: Live — code shipped, all 29 unpublished queue posts edited, tests passing

---

## What Kelvin asked for

All CTA posts need a closing line of "link in the comments," with the old "type DECODED"-style comment-keyword language removed. Every other post should close with "if you or your team is interested in working with me, link is in the description," so every post always carries a way to reach a link. Applies to the existing queue and to every future post.

Clarified with Kelvin before touching anything (both concrete conflicts the queue data surfaced):
1. "Comment [KEYWORD]" patterns existed on both Pillar 1 (technical, e.g. "Comment HITL", "Comment BLUEPRINT") and Pillar 4 (product) posts. Scope decided: **CTA posts = Pillar 4 + Product Launch Posts only.** Every Pillar 1 post's "Comment X" line gets replaced with the "working with me" line, not "Link in the comments."
2. Product Launch Posts required the URL written verbatim in the body ("THE DOOR"). Decided: **switch to "Link in the comments."** too — the URL moves out of the post body into `notes`, for Kelvin to paste as the first comment at publish time.

## What changed

`agents/marketing/mkt_li1_linkedin_brand.py` (v2.6):
- New `CTA_CLOSING_LINE` ("Link in the comments.") and `WORKING_WITH_ME_CLOSING_LINE` ("If you or your team is interested in working with me, link is in the description.") constants.
- New `_apply_closing_line(post_copy, is_cta_post)`: strips any lingering "Comment [KEYWORD]"/"Drop a comment or DM me"/"Follow along if you want" pattern via regex, then appends the correct line if not already present. Code-enforced, not just prompt instruction — same pattern this file already uses for Product Launch Post's URL requirement.
- Wired into all five generation paths: `run_li1_brand_agent` and `generate_on_demand_posts` (is_cta_post = pillar==4), `generate_builder_post` and the mention-only branch of `generate_product_content` (always False), `generate_product_launch_post` (always True — and its "THE DOOR" URL-in-body requirement removed; the URL now goes into `notes` instead).
- `VOICE_SYSTEM_PROMPT`'s old CTA ROTATION section replaced with a CLOSING LINE section instructing the model not to write its own closing at all — the system appends it.
- `HITL_TIER_RULES` clarified: the new `WORKING_WITH_ME_CLOSING_LINE` is a structural constant applied to every non-Pillar-4 post now, so it does **not** by itself escalate a post to Tier 3 the way an actual product CTA does — otherwise every single post would become Tier 3 and the wife/Kelvin two-tier review split would collapse.

`agents/marketing/mkt_10_compliance_guard.py`: removed `"link in comments"` from `PLATFORM_PROHIBITED_PHRASES["linkedin"]` — it was banned as generic engagement bait before this directive made it the mandatory closing line on every CTA post. Left banned: "tag a friend", "dm me for details", and the rest of the generic-engagement list, which are unrelated to this directive.

## Backlog

`scripts/apply_closing_line_to_queue.py` (new, `--dry-run` supported) applied `_apply_closing_line` to all 29 unpublished `linkedin_content_queue` rows, reusing the exact same function live generation now calls. Previewed the diff for every row before running for real — all 29 transformed cleanly, no artifacts. Verified idempotent: a second dry-run afterward reported 0 changes needed. Published rows untouched, same rule as every other backlog fix this session.

## Test coverage added/updated

- `tests/test_mkt_li1_closing_line.py` (new) — `_apply_closing_line`'s stripping and appending logic, both closing lines, idempotency.
- `tests/test_mkt_10_compliance_guard.py` (new — no prior test file existed for this agent) — confirms "link in comments" no longer flags, other banned phrases and financial claims still do.
- `tests/test_mkt_li1_new_post_types.py`, `tests/test_mkt_li1_selling_stage_gate.py`, `tests/test_mkt_li1_asset_vault_wiring.py` — updated assertions that previously expected the URL in Product Launch Post's body / no closing line on a Builder Post's soft question.

88 tests passing across the affected suite.

---

## If this breaks again

- **A post is missing its closing line, or has two:** `_apply_closing_line` checks `closing not in text` before appending — if a future model output phrases the line slightly differently (not verbatim), it'll get double-appended. Keep the two closing-line strings exact constants, never let the model paraphrase them.
- **A Pillar 1 post ends up Tier 3 when it shouldn't:** check `HITL_TIER_RULES` in the code — only `WORKING_WITH_ME_CLOSING_LINE` on its own must never escalate a post; only an actual product mention should.
- **"Comment [KEYWORD]" language resurfaces:** the model was told directly not to write one in every relevant system prompt, and `_OLD_CTA_CLAUSE_RE` should strip it as defense-in-depth — check that regex still matches the actual pattern the model produced (it only expects "comment WORD" fairly literally).
- **A Product Launch Post's real URL goes missing entirely:** it's in `notes` now, not `post_copy` — check the queued row's notes field, not the post body.
