"""
One-off repair for the 2026-08 LinkedIn batch (16 posts):

1. 12 of the 16 posts ended up sharing the same curated vault image
   (img_001). Root cause: assets_library/asset_selector.py's tie-break
   ("times_used ascending, then last_used_date ascending") only ever
   changes between REAL publishes, via asset_logger.py updating the
   index -- but this batch drafted all 16 posts back-to-back in one
   script run with no publishes in between, so every selection saw the
   exact same times_used=0/last_used_date=null vault state and kept
   converging on the same top match. This script replaces every post's
   image with a bespoke, real Gemini-generated diagram
   (assets_library/gemini_image_gen.py, already wired for exactly this)
   so no two posts share an image, even when several cover a related
   subject -- each post's own image_description is a distinct, specific
   diagram prompt, never a shared stock photo.

2. Two posts had real content-generation bugs surfaced by this same
   investigation, fixed here rather than left in front of Kelvin broken:
   - One post's _draft_post() call produced valid JSON that still hit
     the raw-text fallback path (parse failure for an unrelated reason)
     -- its post_copy field is a literal ```json {...} ``` dump instead
     of the actual post text. The real content is fully recoverable
     from inside that dump; this script re-parses it and fixes the row.
   - One post's model output never included an image_description,
     which meant asset_selector fell back to the weakest possible vault
     match (a topic-word hit on "work"). This script authors a real,
     on-topic image_description for it before generation, matching
     mkt_li1_linkedin_brand.py's own VOICE_SYSTEM_PROMPT format exactly.
"""

# ruff: noqa: E402  -- sys.path/env setup must run before these imports
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from supabase import create_client

from agents.marketing._shared import get_anthropic_client, sanitize
from agents.marketing.mkt_li1_linkedin_brand import _draft_post
from assets_library.gemini_image_gen import generate_batch

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
BATCH_MONTH = "2026-08"

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")

# Same source angle originally fed to the post that broke -- reused here
# to regenerate clean content from scratch rather than fight malformed
# JSON (the raw dump has an unescaped quote inside a string value that
# even strict=False parsing can't recover from).
_REGEN_SOURCE_TEXT = (
    "A downstream agent had a permanent ModuleNotFoundError for months, "
    "invisible the whole time because the orchestrator had a graceful "
    "'not yet built -- pending' fallback around the import. Graceful failure "
    "handling is exactly what let a real gap go unnoticed that long."
)

# Authored manually, matching VOICE_SYSTEM_PROMPT's exact required
# image_description format -- this is the one post whose model output
# never produced one, so it fell back to a weak generic vault match.
_MANUAL_IMAGE_DESCRIPTION = (
    "Single standalone diagram. One concept only. No panels, no grids, no collages. "
    "Full bleed 1080x1080px white background.\n\n"
    "A vertical stack titled 'Ship The Boring Fix First' in bold sans-serif at the top. "
    "Three stacked boxes connected top to bottom by downward arrows. "
    "Top box labeled 'Outreach Engine (built)' in blue (#5a96ff) outline with a small "
    "'sends real commercial email' subtext. "
    "Middle box labeled 'CAN-SPAM Compliance Guard' in amber (#F5A623) fill, larger than "
    "the others, with three bullet points inside: '- Suppression list checked pre-send', "
    "'- One-click unsubscribe token (HMAC)', '- Mailing address required, fails closed'. "
    "A small padlock icon sits at the left edge of this middle box. "
    "Bottom box labeled 'Safe To Turn On For Real Users' in green (#3fd17a) outline with a checkmark icon. "
    "A dashed horizontal line crosses behind the middle box labeled 'Ships before the interesting work resumes' "
    "in small italic gray text, running left to right. "
    "Arrows are directional with arrowheads. Layout is clean with generous whitespace. No shadows or gradients.\n\n"
    "Navy #0A0F1E primary elements, blue #5a96ff highlights, amber #F5A623 callouts and "
    "important labels. Clean sans-serif font. Real cloud provider logos where relevant. "
    "Small text \"Kelvin Davis\" bottom right corner. Professional LinkedIn infographic "
    "style similar to ByteByteGo. White background. No dark backgrounds."
)


def _repair_json_dump_row(client, row: dict) -> dict:
    """Row f10f786b: post_copy is a ```json {...}``` dump of what should
    have been the real parsed fields -- and the dump itself has a real
    syntax error (unescaped quote in a string value) that even
    strict=False can't recover from. Regenerate clean content from
    scratch against the same source angle rather than fight it."""
    try:
        raw = row["post_copy"]
        cleaned = _JSON_FENCE_RE.sub("", raw.strip()).strip()
        parsed = json.loads(cleaned, strict=False)
        update = {
            "topic": parsed.get("topic", row["topic"]),
            "post_copy": parsed.get("post_copy", ""),
            "hook_variants": parsed.get("hook_variants") or [],
            "image_description": parsed.get("image_description"),
            "notes": parsed.get("notes", row.get("notes") or ""),
        }
        print(f"Repaired JSON-dump content for {row['id']} -> topic={update['topic'][:60]!r}")
    except json.JSONDecodeError as exc:
        print(f"Dump unrecoverable ({exc}) -- regenerating {row['id']} from source angle")
        client_anthropic = get_anthropic_client()
        source_text = sanitize(_REGEN_SOURCE_TEXT, context="mkt-li1-fix:pillar_1")
        draft = _draft_post(client_anthropic, "pillar_1", source_text, voice_profile={})
        update = {
            "topic": draft.get("topic", row["topic"]),
            "post_copy": draft.get("post_copy", ""),
            "hook_variants": draft.get("hook_variants") or [],
            "image_description": draft.get("image_description"),
            "notes": draft.get("notes", ""),
        }

    client.table("linkedin_content_queue").update(update).eq("id", row["id"]).eq("status", "pending_review").execute()
    return {**row, **update}


def main() -> None:
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    rows = (
        client.table("linkedin_content_queue")
        .select("id,topic,pillar_name,image_description,post_copy,notes")
        .eq("batch_month", BATCH_MONTH)
        .eq("status", "pending_review")
        .execute()
    ).data

    print(f"{len(rows)} posts in batch_month={BATCH_MONTH}")

    fixed_rows = []
    for row in rows:
        if row["topic"] == "Cloud and AI Execution" and row["post_copy"].strip().startswith("```json"):
            row = _repair_json_dump_row(client, row)
        if not row.get("image_description"):
            row["image_description"] = _MANUAL_IMAGE_DESCRIPTION
            client.table("linkedin_content_queue").update(
                {"image_description": _MANUAL_IMAGE_DESCRIPTION}
            ).eq("id", row["id"]).eq("status", "pending_review").execute()
            print(f"Authored missing image_description for {row['id']} ({row['topic'][:50]!r})")
        fixed_rows.append(row)

    briefs = [
        {
            "post_topic": row["topic"],
            "pillar": row["pillar_name"],
            "image_description": row["image_description"],
            "queue_id": row["id"],
        }
        for row in fixed_rows
    ]

    print(f"\nGenerating {len(briefs)} bespoke Gemini images (one per post, all distinct prompts)...")
    summary = generate_batch(briefs)
    print(
        f"{summary['generated']} generated, {summary['skipped_existing']} already existed, "
        f"{summary['failed']} failed, {summary['reattached']} re-attached to queue rows."
    )
    for failure in summary["failures"]:
        print(f"  FAILED: {failure}")


if __name__ == "__main__":
    main()
