"""
One-off driver for a dedicated "Showing Signal week" -- 5 new LinkedIn
posts, one per weekday, Mon 2026-09-21 through Fri 2026-09-25. Chosen as
the first fully open week after the existing 2026-08 batch's last post
(2026-09-17) so this is purely additive -- no rescheduling of anything
already in front of Kelvin for review.

Each post covers a genuinely distinct facet of Showing Signal (not five
restatements of the same pitch), and per Kelvin's explicit instruction
after the 2026-08 batch shipped 12 of 16 posts sharing one recycled
vault image, every post here gets its own bespoke Gemini-generated
diagram from a distinct image_description -- never a shared stock photo,
even though all five posts share one subject.

Uses the same real pipeline as every other batch this session: MKT-LI1's
own _draft_post (voice prompt), MKT-10 compliance guard, MKT-09 HITL
queue writer, then assets_library/gemini_image_gen.py for the images
(not asset_selector's vault, which only has 8 photos total and caused
the duplicate problem in the first place).
"""
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.marketing._shared import get_anthropic_client, sanitize, write_audit_log, emit_event
from agents.marketing.mkt_09_hitl_queue_manager import queue_for_review
from agents.marketing.mkt_10_compliance_guard import run_compliance_guard
from agents.marketing.mkt_li1_linkedin_brand import AGENT_ID, MARKETING_PRODUCT_ID, PILLAR_NAMES, POST_HOUR_ET, _ET
from assets_library.gemini_image_gen import generate_batch
from assets_library.post_formatter import format_post

BATCH_MONTH = "2026-09"
WEEK_DATES = [date(2026, 9, d) for d in (21, 22, 23, 24, 25)]  # Mon-Fri

# Five distinct, real angles on Showing Signal -- no fabricated stats,
# no invented customer counts or revenue, only what's actually built and
# true about the product today.
SHOWING_SIGNAL_ANGLES = [
    (
        "Launch / core problem",
        "Showing Signal reads ShowingTime's own confirmation emails directly and writes "
        "structured showing data into a buyer's agent's CRM and email sequences "
        "automatically. There's no ShowingTime API for this -- it doesn't exist publicly. "
        "No Zapier integration exists for ShowingTime either. The product's whole reason "
        "to exist is that gap: agents were re-typing the same showing details into their "
        "CRM by hand after every single showing.",
    ),
    (
        "How it actually works",
        "The mechanism is an inbox connection, not an API integration: Gmail, Outlook, or "
        "any IMAP inbox with an app password. The parser reads the actual HTML structure "
        "of ShowingTime's real confirmation email -- confirmed field by field against a "
        "real captured email, not guessed -- and fires the CRM write and email sequence "
        "within seconds of the confirmation landing, not on a polling delay.",
    ),
    (
        "The integrity fix",
        "Found and pulled a discontinued CRM integration (LionDesk, shut down by its own "
        "vendor months earlier) that had still been offered as a live, working option on "
        "the checkout page and onboarding flow -- across ten files, not just one page of "
        "copy. Same week, closed a gap where campaign and referral attribution were never "
        "actually being captured at signup despite the backend supporting it since an "
        "earlier build phase. Fixing what's already live matters as much as shipping new.",
    ),
    (
        "Who it's built for",
        "Not a generic real estate tool. Built specifically for buyer's agents at "
        "independent teams -- the workflow logic, CRM field mapping, and sequence "
        "templates are all designed around buyer-side activity: showings booked, feedback "
        "collected, deals progressing. Three tiers -- Solo Agent, Independent Team, "
        "Brokerage -- and a 14-day money-back guarantee, no sales call required to start.",
    ),
    (
        "Building it like a real product, not a demo",
        "The unglamorous production work this month: real analytics wired in, a branded "
        "favicon and social preview image instead of a blank browser tab, first-touch "
        "campaign attribution actually captured at signup, a metadata bug fixed that was "
        "quietly breaking how the site previewed when shared. None of it is a feature. "
        "All of it is the difference between a live product and a demo that looks live.",
    ),
]


def _compute_week_schedule() -> list[datetime]:
    return [datetime(d.year, d.month, d.day, POST_HOUR_ET, 0, tzinfo=_ET) for d in WEEK_DATES]


def main() -> None:
    from agents.marketing.mkt_li1_linkedin_brand import _draft_post

    client = get_anthropic_client()
    schedule = _compute_week_schedule()

    print(f"Generating {len(SHOWING_SIGNAL_ANGLES)} Showing Signal posts for "
          f"{schedule[0].date()} .. {schedule[-1].date()}")

    posts = []
    for i, (label, source) in enumerate(SHOWING_SIGNAL_ANGLES):
        source_text = sanitize(source, context=f"mkt-li1-ss-week:{label}")
        draft = _draft_post(client, "pillar_4", source_text, voice_profile={})

        scheduled_for = schedule[i]
        post = {
            "pillar": 4,
            "pillar_name": PILLAR_NAMES["pillar_4"],
            "topic": draft.get("topic", label),
            "hitl_tier": 3,  # pillar_4 always Tier 3 -- product mention + CTA
            "estimated_length": draft.get("estimated_length", "medium"),
            "post_copy": draft.get("post_copy", ""),
            "hook_variants": draft.get("hook_variants", []) or [],
            "batch_month": BATCH_MONTH,
            "scheduled_for": scheduled_for.isoformat(),
            "suggested_post_time": scheduled_for.strftime("%A %-I%p ET"),
            "format": draft.get("format", "text_post"),
            "image_brief": None,  # filled by Gemini generation below, not the vault
            "image_description": draft.get("image_description"),
            "carousel_slides": draft.get("carousel_slides"),
            "carousel_pdf_brief": draft.get("carousel_pdf_brief"),
            "notes": (draft.get("notes", "") + " | Showing Signal launch week").strip(" |"),
        }

        compliance = run_compliance_guard(post["post_copy"], platform="linkedin", product_id=MARKETING_PRODUCT_ID)
        if compliance["revised_content"]:
            post["post_copy"] = compliance["revised_content"]

        formatted_copy, format_warnings = format_post(post["post_copy"], credit_line=None, is_original=True)
        post["post_copy"] = formatted_copy
        if format_warnings:
            post["notes"] = (post["notes"] + " | " if post["notes"] else "") + "post_formatter: " + "; ".join(format_warnings)

        content_item = {**post, "agent_id": AGENT_ID}
        hitl_tier = 3
        if compliance["flags"]:
            content_item["hitl_notes"] = "MKT-10: " + "; ".join(compliance["flags"])

        queued = queue_for_review(content_item, tier=hitl_tier, product_id=MARKETING_PRODUCT_ID)
        post["id"] = queued.get("id")
        posts.append(post)
        print(f"  [{i+1}/5] {label} -> {scheduled_for.strftime('%a %m-%d')} id={post['id']} "
              f"topic={post['topic'][:60]!r}")

    briefs = [
        {"post_topic": p["topic"], "pillar": p["pillar_name"], "image_description": p["image_description"], "queue_id": p["id"]}
        for p in posts if p["image_description"]
    ]
    print(f"\nGenerating {len(briefs)} bespoke Gemini images for the Showing Signal week...")
    summary = generate_batch(briefs)
    print(f"{summary['generated']} generated, {summary['failed']} failed, {summary['reattached']} re-attached.")
    for failure in summary["failures"]:
        print(f"  FAILED: {failure}")

    write_audit_log(AGENT_ID, "showing_signal_week_generated",
                     resource=f"{len(posts)} posts, week={WEEK_DATES[0]}..{WEEK_DATES[-1]}", outcome="success")
    emit_event(AGENT_ID, "showing_signal_week_generated", {"post_count": len(posts)})
    print(f"\nDone. {len(posts)} Showing Signal posts queued, status=pending_review.")


if __name__ == "__main__":
    main()
