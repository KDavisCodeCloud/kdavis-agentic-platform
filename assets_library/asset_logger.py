"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
LinkedIn Asset Vault — asset_logger.py

# INTEGRATION: MKT-LI1 calls asset_selector.py after generating post text,
# passing the post topic as --topic. The returned image_path is attached to
# the LinkedIn post payload. After successful post, MKT-LI1 calls
# asset_logger.py with --id to update usage tracking.
# credit_line from asset_selector output is appended as the last line
# of every post that uses a curated image (is_original: false).

Run after every successful LinkedIn post that used a curated image.
"""

import argparse
import json
import os
from datetime import date
from pathlib import Path

ASSETS_ROOT = Path(__file__).parent
INDEX_PATH = ASSETS_ROOT / "index.json"


def _load_index() -> list[dict]:
    text = INDEX_PATH.read_text().strip()
    return json.loads(text) if text else []


def _write_index_atomic(entries: list[dict]) -> None:
    tmp_path = INDEX_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(entries, indent=2))
    os.replace(tmp_path, INDEX_PATH)


def log_usage(image_id: str, used_date: str | None = None) -> dict:
    used_date = used_date or date.today().isoformat()
    entries = _load_index()

    for entry in entries:
        if entry["id"] == image_id:
            entry["last_used_date"] = used_date
            entry["times_used"] = entry.get("times_used", 0) + 1
            _write_index_atomic(entries)
            return entry

    raise ValueError(f"No entry found in index.json with id '{image_id}'")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True)
    parser.add_argument("--date", default=None)
    args = parser.parse_args()

    entry = log_usage(args.id, args.date)
    print(f"Logged: {args.id} used on {entry['last_used_date']}. Total uses: {entry['times_used']}")


if __name__ == "__main__":
    main()
