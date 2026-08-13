"""
One-off driver for the 2026-08 LinkedIn batch (16 posts instead of the
usual 12) — run directly, not imported. Uses the real MKT-LI1 pipeline
(voice prompt, MKT-10 compliance guard, asset selection, post formatter,
MKT-09 HITL queue writer) exactly as agents/marketing/mkt_li1_linkedin_brand.py
does, but with two deliberate overrides for this batch only:

1. 16 posts instead of POSTS_PER_BATCH=12 (Kelvin's request this session).
2. 4 of those 16 are guaranteed Pillar 4 (Product/Business/CTA) slots
   built from this week's real build_updates milestones (CAN-SPAM
   compliance guard, MKT-V1, Showing Signal integrity/attribution work,
   Showing Signal's core value prop) — the normal 40/30/20/10 ratio only
   yields ~2 Pillar 4 slots at n=16, not the 4 Kelvin explicitly asked
   for, so those 4 are carved out first and the remaining 12 are
   apportioned across Pillars 1-3 only.

Schedule starts from the next available Tue/Wed/Thu after today
(2026-08-12) rather than from the 1st of the month, since day 1 already
passed — spills into early September if 16 posts don't fit the
remaining Tue/Wed/Thu slots in August, same "never drops a post"
principle _compute_schedule already documents.

No fabricated pillar_3 (Philosophy/Faith/Gardening) material is
supplied — this script has no real source text for that pillar, and
the existing _build_slots() fallback (empty pillar -> falls back to
pillar_1, matching the agent's own "never fabricate a milestone/pillar"
principle) handles it exactly as it already does in the real agent.
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.marketing._shared import apportion, get_anthropic_client, sanitize, write_audit_log, emit_event
from agents.marketing.mkt_09_hitl_queue_manager import queue_for_review
from agents.marketing.mkt_10_compliance_guard import run_compliance_guard
from agents.marketing.mkt_li1_linkedin_brand import (
    AGENT_ID, MARKETING_PRODUCT_ID, PILLAR_NAMES, POST_HOUR_ET, POST_WEEKDAYS,
    _draft_post, _select_image_for_post, _ET,
)
from assets_library.post_formatter import format_post

BATCH_MONTH = "2026-08"
TOTAL_POSTS = 16
PILLAR_4_GUARANTEED = 4
SCHEDULE_START = date(2026, 8, 13)  # next day after today (2026-08-12)

# ---- Pillar 1: Cloud and AI Execution -- real technical work from this session ----
PILLAR_1_ANGLES = [
    "Built a CAN-SPAM compliance guard for an agent that sends real commercial "
    "email: HMAC-signed one-click unsubscribe tokens (no DB lookup needed to "
    "generate one, only to redeem it), a suppression list checked before every "
    "send, and a mailing-address requirement that fails closed -- raises an "
    "exception rather than silently sending without one, because a missing "
    "physical address is a real legal violation, not a degraded-but-OK state.",
    "A downstream agent had a permanent ModuleNotFoundError for months, "
    "invisible the whole time because the orchestrator had a graceful "
    "'not yet built -- pending' fallback around the import. Graceful failure "
    "handling is exactly what let a real gap go unnoticed that long.",
    "Spent a session pinging two live third-party APIs directly with curl "
    "instead of trusting either the docs or my own assumptions. One API key "
    "was valid but sitting on a Free tier with zero API access -- 403 on "
    "every call. The other key was valid and working, but the exact endpoint "
    "the integration needed simply doesn't exist on the live API yet. Neither "
    "was a code bug. Both would have stayed invisible without the direct check.",
    "Found an internal automation instance that had been down for 2.75+ days. "
    "Its health check endpoint was returning 200 the entire time. The database "
    "backing it was completely healthy -- a direct connection resolved in "
    "under a second. The app's own connection pool was just stuck. A plain "
    "redeploy fixed it in under two minutes. The lesson isn't the fix, it's "
    "that a green health check told us nothing for three days.",
    "Fail-closed is a compliance decision as much as an engineering one. "
    "The easy version of an unsubscribe-footer function degrades gracefully "
    "when a config value is missing. The correct version raises, because a "
    "commercial email going out without a real mailing address is the thing "
    "you're trying to prevent, not an edge case to paper over.",
]

# ---- Pillar 2: Builder's Journey -- this week's build-in-public narrative ----
PILLAR_2_IDEAS = [
    "A prior audit of a codebase turned out to be almost entirely wrong -- "
    "not from bad intent, just from a review that never actually exercised "
    "the live system. The fix wasn't better tooling, it was slower: re-verify "
    "every claim against curl/psql/dig output before writing a single line "
    "of the actual fix.",
    "Shipped the boring, legally-required fix before touching any of the "
    "more interesting agent work queued up behind it. A working one-click "
    "unsubscribe link isn't exciting to build. It's also the thing that "
    "keeps a real outreach engine from being a liability the day it starts "
    "sending for real.",
    "Went in to fix a stale code comment. Found instead that the comment was "
    "pointing at a CRM integration that had been fully discontinued by its "
    "own vendor months earlier -- and it was still being offered, live, as a "
    "working choice on a paying product's checkout and onboarding screens.",
    "Chose to remove a broken integration entirely rather than leave a "
    "half-working version of it in place. It touched ten files, including "
    "live product UI, not just marketing copy -- the easy version would have "
    "been a copy edit on one page and calling it done.",
]

# ---- Pillar 4: Product/Business/CTA -- this week's real milestones ----
BUILD_UPDATES = [
    {
        "milestone": True,
        "text": (
            "Shipped a CAN-SPAM compliance guard for the outreach engine behind "
            "the Micro SaaS Engine's marketing factory: a suppression list, a "
            "working one-click unsubscribe endpoint, and a hard requirement for "
            "a real mailing address on every commercial email before it can "
            "send. It was the most serious real gap sitting in that system, so "
            "it went first, ahead of anything else queued behind it."
        ),
    },
    {
        "milestone": True,
        "text": (
            "Closed a permanent gap in the marketing factory: the content "
            "multiplier agent that turns product research into genuine, "
            "non-salesy Reddit and Facebook community posts had never "
            "actually been built, despite being wired into the pipeline for "
            "months. It's live now, drafting from the same real research "
            "every other content agent in the system uses -- never a "
            "fabricated post."
        ),
    },
    {
        "milestone": True,
        "text": (
            "Pulled a discontinued CRM integration off Showing Signal entirely "
            "-- it had been offered as a live, working option on the checkout "
            "page, the onboarding flow, and in marketing copy for months after "
            "the vendor shut the product down. Also closed a real gap where "
            "referral and campaign attribution were never actually being "
            "captured at signup despite the backend supporting it since a "
            "much earlier phase."
        ),
    },
    {
        "milestone": True,
        "text": (
            "Showing Signal is live: it reads ShowingTime's own confirmation "
            "emails directly and writes structured showing data into a buyer's "
            "agent's CRM and email sequences automatically -- no ShowingTime "
            "API key required (there isn't a public one for this use case), "
            "no Zapier, no manual data entry after every showing."
        ),
    },
]


def _compute_schedule_from(start: date, count: int) -> list[datetime]:
    candidates: list[date] = []
    d = start
    while len(candidates) < count:
        if d.weekday() in POST_WEEKDAYS:
            candidates.append(d)
        d += timedelta(days=1)
    return [datetime(c.year, c.month, c.day, POST_HOUR_ET, 0, tzinfo=_ET) for c in candidates]


def _build_pillar4_slots() -> list[dict]:
    assert len(BUILD_UPDATES) == PILLAR_4_GUARANTEED, "expected exactly 4 real milestones for this batch"
    return [{"pillar_key": "pillar_4", "source": {"text": u["text"], "source": "build_updates"}} for u in BUILD_UPDATES]


def _build_pillar123_slots(remaining: int) -> list[dict]:
    pool = {
        "pillar_1": [{"text": t, "source": "session_notes"} for t in PILLAR_1_ANGLES],
        "pillar_2": [{"text": t, "source": "session_notes"} for t in PILLAR_2_IDEAS],
        "pillar_3": [],  # no real source material this batch -- never fabricated
    }
    # Renormalize the 40/30/20 (pillar 1-3) weights to sum to 1.0 over `remaining` slots.
    ratios = {"pillar_1": 0.4 / 0.9, "pillar_2": 0.3 / 0.9, "pillar_3": 0.2 / 0.9}
    quota = apportion(ratios, remaining)

    slots: list[dict] = []
    for pillar_key, count in quota.items():
        for _ in range(count):
            key = pillar_key
            if not pool[key]:
                key = "pillar_1" if pool["pillar_1"] else "pillar_2"
            if not pool[key]:
                continue
            # cycle through the pool rather than popping it dry -- 4-5 real
            # angles need to stretch across more slots than they have items
            item = pool[key].pop(0)
            pool[key].append(item)
            slots.append({"pillar_key": key, "source": item})
    return slots


def main() -> None:
    client = get_anthropic_client()
    slots = _build_pillar4_slots() + _build_pillar123_slots(TOTAL_POSTS - PILLAR_4_GUARANTEED)
    schedule = _compute_schedule_from(SCHEDULE_START, len(slots))

    print(f"Generating {len(slots)} posts, batch_month={BATCH_MONTH}, "
          f"schedule {schedule[0].date()} .. {schedule[-1].date()}")

    posts = []
    for i, slot in enumerate(slots):
        pillar_key = slot["pillar_key"]
        source_text = sanitize(slot["source"]["text"], context=f"mkt-li1-batch:{pillar_key}")

        draft = _draft_post(client, pillar_key, source_text, voice_profile={})
        hitl_tier = 3 if pillar_key == "pillar_4" else int(draft.get("hitl_tier", 2))

        scheduled_for = schedule[i]
        post = {
            "pillar": draft.get("pillar", int(pillar_key.split("_")[1])),
            "pillar_name": PILLAR_NAMES.get(pillar_key, pillar_key),
            "topic": draft.get("topic", ""),
            "hitl_tier": hitl_tier,
            "estimated_length": draft.get("estimated_length", "medium"),
            "post_copy": draft.get("post_copy", ""),
            "hook_variants": draft.get("hook_variants", []) or [],
            "batch_month": BATCH_MONTH,
            "scheduled_for": scheduled_for.isoformat(),
            "suggested_post_time": scheduled_for.strftime("%A %-I%p ET"),
            "format": draft.get("format", "text_post"),
            "image_brief": draft.get("image_brief"),
            "image_description": draft.get("image_description"),
            "carousel_slides": draft.get("carousel_slides"),
            "carousel_pdf_brief": draft.get("carousel_pdf_brief"),
            "notes": draft.get("notes", ""),
        }

        compliance = run_compliance_guard(post["post_copy"], platform="linkedin", product_id=MARKETING_PRODUCT_ID)
        if compliance["revised_content"]:
            post["post_copy"] = compliance["revised_content"]

        if post["format"] == "text_post":
            asset = _select_image_for_post(post["topic"], image_description=post["image_description"])
            post["image_brief"] = asset
            formatted_copy, format_warnings = format_post(
                post["post_copy"],
                credit_line=asset["credit_line"] if asset else None,
                is_original=asset["is_original"] if asset else False,
            )
            post["post_copy"] = formatted_copy
            if format_warnings:
                post["notes"] = (post["notes"] + " | " if post["notes"] else "") + "post_formatter: " + "; ".join(format_warnings)

        content_item = {**post, "agent_id": AGENT_ID}
        if compliance["flags"]:
            content_item["hitl_notes"] = "MKT-10: " + "; ".join(compliance["flags"])
            hitl_tier = 3

        queued = queue_for_review(content_item, tier=hitl_tier, product_id=MARKETING_PRODUCT_ID)
        post["id"] = queued.get("id")
        posts.append(post)
        print(f"  [{i+1}/{len(slots)}] {pillar_key} tier={hitl_tier} "
              f"{scheduled_for.strftime('%a %m-%d')} -> id={post['id']} topic={post['topic'][:60]!r}")

    write_audit_log(AGENT_ID, "monthly_batch_generated",
                     resource=f"{len(posts)} posts, batch_month={BATCH_MONTH} (16-post override)", outcome="success")
    emit_event(AGENT_ID, "monthly_batch_generated", {"post_count": len(posts), "batch_month": BATCH_MONTH})
    print(f"\nDone. {len(posts)} posts queued to linkedin_content_queue, status=pending_review.")


if __name__ == "__main__":
    main()
