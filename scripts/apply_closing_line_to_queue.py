"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

One-off backlog repair, 2026-09-15 closing-line directive.

Applies agents/marketing/mkt_li1_linkedin_brand.py's new
_apply_closing_line to every unpublished linkedin_content_queue row --
replacing the old "Comment [KEYWORD] if you want the full breakdown" /
"Drop a comment or DM me" / "Follow along if you want more" engagement
patterns, and appending the mandatory closing line for the post's
category: "Link in the comments." for Pillar 4, "If you or your team is
interested in working with me, link is in the description." for every
other pillar. Reuses the exact same function the live generation code
now calls, so the backlog and every future post get identical treatment.

Published rows are left untouched -- same "can't edit what's already
live" rule as every other backlog fix this session.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from supabase import create_client

from agents.marketing.mkt_li1_linkedin_brand import _apply_closing_line

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    rows = (
        client.table("linkedin_content_queue")
        .select("id,status,pillar,pillar_name,topic,post_copy")
        .neq("status", "published")
        .execute()
    ).data

    print(f"{len(rows)} unpublished rows to process")

    updated = 0
    unchanged = 0
    for row in rows:
        is_cta_post = row["pillar"] == 4
        new_copy = _apply_closing_line(row["post_copy"], is_cta_post=is_cta_post)

        if new_copy == row["post_copy"]:
            unchanged += 1
            continue

        print(f"\n--- {row['id'][:8]} | p{row['pillar']} | {row['status']:15s} | {row['topic'][:55]}")
        print(f"    OLD tail: ...{row['post_copy'][-100:]!r}")
        print(f"    NEW tail: ...{new_copy[-100:]!r}")

        if not dry_run:
            (
                client.table("linkedin_content_queue")
                .update({"post_copy": new_copy})
                .eq("id", row["id"])
                .eq("status", row["status"])  # never touch a row a human has since moved
                .execute()
            )
        updated += 1

    verb = "would be updated" if dry_run else "updated"
    print(f"\n{updated} rows {verb}, {unchanged} already compliant (no change needed).")


if __name__ == "__main__":
    main()
