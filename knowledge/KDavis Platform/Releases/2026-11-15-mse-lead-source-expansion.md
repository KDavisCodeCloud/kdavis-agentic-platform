# 2026-11-15: MSE lead-source expansion and buyer resolver

**Engine (kdavis-microsaas-engine, main):** 99e94fc, 3a3c327, 5d79556, 60e8edf, fbb7dc2, bb2ee16,
10bd622, 04e0b4c, a2cd2f9, e0f180f, 6fc7a99. Each went to staging first, then prod, by SHA.
**Platform (master):** db50971, the CEO dashboard's Find the Buyer suggestion and signal chips.
**Migrations:** 072 (`ats_slugs` view + Recruitee), 073 (HN candidates), 074 (SEC Form D),
075 (resolver + targeting columns). Each was proven on staging first.
**Full report:** `kdavis-microsaas-engine/docs/lead-sources/REPORT.md`.

## What shipped
- **ATS slugs grew from 643 to 964.**
  - Scouts read every slug, in parallel per provider, instead of 200 at a time.
  - Recruitee was added.
  - A weekly Brave slug discovery found 314 new slugs from 36 queries.
- **HN:** each post is parsed into roles, location, remote flag and emails. A founder or CTO
  poster is recorded as a candidate buyer. The read runs on the first weekday after the
  thread is posted.
- **SEC Form D:** official EDGAR only, at most 5 requests a second.
  - A matched lead gets its funding date and amount, and the filing's officers as
    candidates.
  - Consulting leads get +0.10 intent for funding within 180 days.
- **Wellfound:** Brave result titles only; the site is never fetched. The first run found
  7 new verified slugs.
- **Buyer resolver** (daily, 14:00 UTC): tries Form D, team pages, GitHub, the HN poster and
  (behind a flag) search snippets.
  - A verified email with a buyer title creates the contact. A name without one pre-fills
    the card.
- **Targeting:** roles open 30+ days rank higher. Cloud Decoded prefers 20–150 people.
  Cards show source and signals.
- **Measurement:** per-source yield against a weekly target of 40 companies / 15 named
  buyers / 10 verified emails, in the summary API and on the Loop Map Step 1 card.

## Gate results
- **Resolver on the 15 Find the Buyer cards:** 0 auto-resolved, 2 pre-filled (Multiply Labs,
  CentralReach), 13 manual.
- **Form D seed:** 0 of 80 tech filers resolved to an ATS board.

## Stopped or not applied
- **SmartRecruiters:** its robots.txt disallows us, so it was not added.
- **EDGAR `/cgi-bin`:** disallowed by robots.txt, so it is not used.
- **The live n8n 8am node:** not edited. Kelvin pastes 6 lines; see REPORT §5.

## If this fails next time
- **Slugs:** check `select provider, count(*) from ats_slugs group by 1`. A scout's
  `funnel_stats.board_tokens_from_cache` should be the full pollable count.
- **Discovery didn't run:** check `mse_scheduled_job_runs where job_key='slug_discovery'`.
  The scouts fall back to their own discovery when it is missing.
- **Brave:** check `brave_budget.usage_by_source(db)`. A refusal names the source and its
  allocation.
- **Rollback (mse-api prod):** 66dba6c4 → 15274d2d → eb1acb54 → c7d578cb → 9d1856ea (pre-build).
