"""
Repair for generate_showing_signal_week.py's real output bug: 4 of 5
source angles never explicitly named "Showing Signal" in the text fed to
the model, and MKT-LI1's own VOICE_SYSTEM_PROMPT's product roster
(Cloud Decoded / Micro SaaS Engine / DecodedSix / CEO Decoded) doesn't
list Showing Signal at all -- so the model filled the gap with whichever
named product it recognized. Result: two posts misnamed the product
outright ("Cloud Decoded", "Micro SaaS Engine"), a third named it
correctly everywhere except one closing line ("Cloud Decoded is in that
phase right now"), and a fourth never named it at all. Only post 1/5
(which did explicitly say "Showing Signal" in its source text) came back
clean.

Fix: rewrite the 4 affected angles so every one explicitly names
"Showing Signal" by name in the source text itself, then regenerate
those 4 posts in place (same queue_id, UPDATE not INSERT) so the
schedule/week structure from the original run is untouched.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.marketing._shared import get_anthropic_client, sanitize
from agents.marketing.mkt_09_hitl_queue_manager import queue_for_review  # noqa: F401 (not re-queuing, just importing for parity)
from agents.marketing.mkt_10_compliance_guard import run_compliance_guard
from agents.marketing.mkt_li1_linkedin_brand import _draft_post
from assets_library.gemini_image_gen import generate_batch
from assets_library.post_formatter import format_post
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

# Corrected, explicitly-named source angles for the 4 affected posts,
# keyed by their existing queue_id -- every angle now opens with or
# immediately states "Showing Signal" by name so there's no gap for the
# model to fill with a different product.
FIXES = {
    "585caf4e-e88c-41b1-9020-95b16578316b": (  # was "Cloud Decoded: ShowingTime inbox parser"
        "How it actually works",
        "Showing Signal's core mechanism is an inbox connection -- Gmail, Outlook, or any "
        "IMAP inbox with an app password. Not a vendor API (ShowingTime doesn't have a "
        "public one for this). The parser reads the actual HTML structure of ShowingTime's "
        "real confirmation email -- captured from a real email and mapped field by field, "
        "not guessed at. When that confirmation lands, Showing Signal fires the CRM write "
        "and the follow-up email sequence within seconds, not on a polling delay.",
    ),
    "4900e845-390f-459d-b141-0d395e35ae7d": (  # named correctly except once, worth tightening anyway
        "The integrity fix",
        "This week on Showing Signal: found a CRM integration (LionDesk, shut down by its "
        "own vendor months ago) still listed as a live, working option across ten files -- "
        "checkout, onboarding, help text. Also closed a gap where campaign and referral "
        "attribution had never actually been captured at signup despite the backend "
        "supporting it since an earlier build phase. Neither was on a roadmap. Both mattered "
        "more than shipping something new that week.",
    ),
    "8f824f48-4326-4e9e-a90a-cc1561a0b188": (  # was "Micro SaaS Engine" instead of naming the product
        "Who it's built for",
        "Showing Signal isn't a generic real estate tool retrofitted for buyer's agents -- "
        "it's built specifically for buyer's agents at independent teams from the ground up. "
        "The CRM field mapping, the sequence templates, the workflow logic -- all designed "
        "around buyer-side activity: showings booked, feedback collected, deals progressing. "
        "Three tiers: Solo Agent, Independent Team, Brokerage. 14-day money-back guarantee, "
        "no sales call required to start.",
    ),
    "b2c7d3db-6a04-4b71-ac89-c410225c4cde": (  # named correctly except the closing line ("Cloud Decoded is in that phase")
        "Building it like a real product, not a demo",
        "The unglamorous production work on Showing Signal this month: real analytics wired "
        "in, a branded favicon and social preview image instead of a blank browser tab, "
        "first-touch campaign attribution actually captured at signup, a metadata bug fixed "
        "that was quietly breaking how the site previewed when shared. None of it is a "
        "feature. All of it is the difference between Showing Signal being a live product "
        "and just looking like one.",
    ),
}


def main() -> None:
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    anthropic_client = get_anthropic_client()

    briefs = []
    for queue_id, (label, source) in FIXES.items():
        source_text = sanitize(source, context=f"mkt-li1-ss-week-fix:{label}")
        draft = _draft_post(anthropic_client, "pillar_4", source_text, voice_profile={})

        post_copy = draft.get("post_copy", "")
        compliance = run_compliance_guard(post_copy, platform="linkedin", product_id="marketing")
        if compliance["revised_content"]:
            post_copy = compliance["revised_content"]
        formatted_copy, warnings = format_post(post_copy, credit_line=None, is_original=True)

        if "Showing Signal" not in formatted_copy:
            print(f"WARNING: {queue_id} regenerated post still doesn't mention 'Showing Signal' by name -- needs a human look")

        update = {
            "topic": draft.get("topic", label),
            "post_copy": formatted_copy,
            "hook_variants": draft.get("hook_variants") or [],
            "image_description": draft.get("image_description"),
            "notes": (draft.get("notes", "") + " | Showing Signal launch week (renamed fix)").strip(" |"),
        }
        client.table("linkedin_content_queue").update(update).eq("id", queue_id).eq("status", "pending_review").execute()
        print(f"Fixed {queue_id} -> topic={update['topic'][:60]!r}")

        briefs.append({"post_topic": update["topic"], "pillar": "Product, Business, and CTA",
                        "image_description": update["image_description"], "queue_id": queue_id})

    print(f"\nRegenerating {len(briefs)} images for the corrected posts...")
    summary = generate_batch(briefs)
    print(summary)
    for f in summary["failures"]:
        print("FAILED:", f)


if __name__ == "__main__":
    main()
