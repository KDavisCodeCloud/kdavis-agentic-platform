"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
LinkedIn Asset Vault — asset_selector.py

# INTEGRATION: MKT-LI1 calls asset_selector.py after generating post text,
# passing the post topic as --topic. The returned image_path is attached to
# the LinkedIn post payload. After successful post, MKT-LI1 calls
# asset_logger.py with --id to update usage tracking.
# credit_line from asset_selector output is appended as the last line
# of every post that uses a curated image (is_original: false).

Selection priority, applied in order:
  1. topic match — any word in --topic appears (case-insensitive, partial)
     in topic_tags or compatible_post_topics, or vice versa
  2. exclude anything used within the last 60 days
  3. exclude any id passed via --exclude
  4. among what's left, prefer is_original: true
  5. sort by times_used ascending, then last_used_date ascending
     (null = never used, always sorts first)

generation_available (added 2026-07-23): true when image_description was
passed in and is non-empty, regardless of whether a vault match was also
found — signals to the caller (MKT-LI1) that
assets_library/gemini_image_gen.py can still produce an image for this
post even when no existing vault image matches yet. Purely a pass-through
flag based on the caller's own input, not something this function derives
from the vault itself.
"""

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path

ASSETS_ROOT = Path(__file__).parent
INDEX_PATH = ASSETS_ROOT / "index.json"
RECENT_USE_WINDOW_DAYS = 60


def _load_index() -> list[dict]:
    text = INDEX_PATH.read_text().strip()
    return json.loads(text) if text else []


def _topic_words(topic: str) -> list[str]:
    return [w.lower() for w in topic.split() if w]


def _matches_topic(entry: dict, words: list[str]) -> list[str]:
    """Returns the list of topic words that matched (bidirectional
    substring containment against topic_tags + compatible_post_topics),
    empty if no match."""
    haystack = " ".join(entry.get("topic_tags", []) + entry.get("compatible_post_topics", [])).lower()
    matched = []
    for word in words:
        if word in haystack:
            matched.append(word)
            continue
        for tag in entry.get("topic_tags", []) + entry.get("compatible_post_topics", []):
            if tag.lower() in word:
                matched.append(word)
                break
    return matched


def _recently_used(entry: dict, today: date) -> bool:
    last_used = entry.get("last_used_date")
    if not last_used:
        return False
    used_date = datetime.fromisoformat(last_used).date()
    return (today - used_date) < timedelta(days=RECENT_USE_WINDOW_DAYS)


def select_asset(
    topic: str,
    exclude: list[str] | None = None,
    today: date | None = None,
    image_description: str | None = None,
) -> dict:
    entries = _load_index()
    exclude = set(exclude or [])
    today = today or date.today()
    words = _topic_words(topic)
    generation_available = bool(image_description)

    candidates = []
    for entry in entries:
        matched_words = _matches_topic(entry, words)
        if not matched_words:
            continue
        if entry["id"] in exclude:
            continue
        if _recently_used(entry, today):
            continue
        candidates.append((entry, matched_words))

    if not candidates:
        return {
            "image_id": None,
            "image_path": None,
            "credit_line": None,
            "is_original": None,
            "selected_because": "no match found — post without image or add more assets",
            "generation_available": generation_available,
        }

    def sort_key(item):
        entry, _ = item
        last_used = entry.get("last_used_date")
        # None sorts first: represent as the minimum possible date string.
        last_used_sort = last_used or "0000-00-00"
        return (
            0 if entry.get("is_original") else 1,
            entry.get("times_used", 0),
            last_used_sort,
        )

    candidates.sort(key=sort_key)
    best_entry, matched_words = candidates[0]

    is_original = best_entry.get("is_original", False)
    creator_handle = best_entry.get("creator_linkedin")
    creator_name = best_entry.get("original_creator")
    # Prefer the @handle; fall back to a plain name if the handle wasn't
    # recognized but a creator name was (still better than no credit at
    # all for a non-original image); omit entirely only if neither exists
    # or the creator is genuinely unknown.
    if is_original:
        credit_line = None
    elif creator_handle:
        credit_line = f"Visual credit: {creator_handle}"
    elif creator_name and creator_name != "Unknown":
        credit_line = f"Visual credit: {creator_name}"
    else:
        credit_line = None

    return {
        "image_id": best_entry["id"],
        "image_path": f"assets_library/{best_entry['filename']}",
        "credit_line": credit_line,
        "is_original": is_original,
        "selected_because": f"topic match on: {', '.join(sorted(set(matched_words)))}",
        "generation_available": generation_available,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--exclude", default="")
    parser.add_argument("--image-description", default=None)
    args = parser.parse_args()

    exclude = [x.strip() for x in args.exclude.split(",") if x.strip()]
    result = select_asset(args.topic, exclude=exclude, image_description=args.image_description)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
