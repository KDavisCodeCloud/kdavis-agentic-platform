"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
run_post_batch.py — dry-run test harness for the asset vault + post
formatter pipeline (assets_library/). Takes a JSON batch file of test
post objects, runs each through asset_selector.select_asset() and
post_formatter.format_post(), and writes a preview file showing exactly
what would go live -- without ever calling LinkedIn's API.

This is a test harness, not the real MKT-LI1 pipeline -- the real
pipeline's wiring lives in agents/marketing/mkt_li1_linkedin_brand.py
(selection + formatting at draft time) and
api/routes/internal_marketing.py (publish time). This script exists to
exercise the asset vault + formatter in isolation against hand-written
test posts, without needing a real Claude draft or a real HITL queue
row.

Batch file schema (a JSON array of objects):
{
  "post_text": str,
  "topic": str,
  "pillar": str,
  "hitl_tier": str,
  "suggested_hashtags": [str, ...]
}

Usage: python run_post_batch.py test_batch.json --dry-run

--dry-run is required, not optional -- this script refuses to run
without it. There is no live-posting code path here at all; the flag
exists to make the safety guarantee explicit and self-documenting
rather than implicit in "this script just doesn't have a live mode."

Output: outputs/batch_preview_YYYY-MM-DD.json
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from assets_library.asset_selector import select_asset
from assets_library.post_formatter import format_post

REPO_ROOT = Path(__file__).parent
OUTPUTS_DIR = REPO_ROOT / "outputs"


def process_batch(batch: list[dict]) -> list[dict]:
    results = []
    for item in batch:
        topic = item["topic"]
        asset = select_asset(topic)
        has_image = asset["image_id"] is not None

        raw_text = item["post_text"].rstrip()
        hashtags = item.get("suggested_hashtags", [])
        if hashtags:
            raw_text = raw_text + "\n\n" + " ".join(hashtags)

        formatted_text, warnings = format_post(
            raw_text,
            credit_line=asset["credit_line"] if has_image else None,
            is_original=asset["is_original"] if has_image else False,
        )

        results.append({
            "topic": topic,
            "pillar": item.get("pillar"),
            "hitl_tier": item.get("hitl_tier"),
            "selected_image": asset,
            "formatted_post": formatted_text,
            "formatter_warnings": warnings,
            "would_post_live": False,
        })
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch_file")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run:
        print(
            "ERROR: run_post_batch.py only supports --dry-run right now -- "
            "there is no live-posting code path in this script at all. "
            "Refusing to run without the flag rather than silently no-op'ing.",
            file=sys.stderr,
        )
        sys.exit(1)

    batch = json.loads(Path(args.batch_file).read_text())
    results = process_batch(batch)

    OUTPUTS_DIR.mkdir(exist_ok=True)
    out_path = OUTPUTS_DIR / f"batch_preview_{date.today().isoformat()}.json"
    out_path.write_text(json.dumps(results, indent=2))

    print(f"Dry run complete. {len(results)} posts previewed. Written to {out_path}")


if __name__ == "__main__":
    main()
