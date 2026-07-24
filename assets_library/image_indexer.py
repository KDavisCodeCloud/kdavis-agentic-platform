"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
LinkedIn Asset Vault — image_indexer.py

Scans assets_library/ for image files not yet in index.json, tags each
one via Claude vision (claude-sonnet-4-6), and appends a structured
entry. Run with: python assets_library/image_indexer.py

Deliberate exception to this repo's "never import anthropic directly,
route through providers/router.py" rule: this is a standalone internal
curation tool, not a product agent, and providers/anthropic.py's
complete() is text-only today (no vision support) — extending shared
provider infrastructure for one internal script wasn't in scope here.

Idempotent by design: an image already present in index.json (matched
by its filename, relative to assets_library/) is never re-tagged or
re-appended, so running this twice never duplicates entries.
"""

import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

from anthropic import Anthropic
from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError

ASSETS_ROOT = Path(__file__).parent
INDEX_PATH = ASSETS_ROOT / "index.json"
MODEL = "claude-sonnet-4-6"

# This is a standalone CLI script, not run inside the FastAPI app's
# process -- nothing else loads .env into os.environ for it. Explicit
# path so it works regardless of the caller's current working directory
# (e.g. fetch_seed_images.sh invokes this from wherever it was run).
load_dotenv(ASSETS_ROOT.parent / ".env")

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

SYSTEM_PROMPT = """You are an image tagging assistant for a technical LinkedIn content library.
Analyze this image and return JSON only, no other text, in this exact format:
{
  "category": "<one of: AI / Agents | Cloud / DevOps | System Design | AI / Models | Cheat Sheet | Career / Growth | Original>",
  "topic_tags": ["tag1", "tag2", "tag3", "tag4"],
  "compatible_post_topics": ["topic1", "topic2", "topic3", "topic4", "topic5"],
  "original_creator": "<creator name if watermarked or recognizable, else Unknown>",
  "creator_linkedin": "<@handle if recognizable, else null>"
}"""


def _load_index() -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    text = INDEX_PATH.read_text().strip()
    return json.loads(text) if text else []


def _write_index_atomic(entries: list[dict]) -> None:
    """Read -> modify in memory -> write full file atomically, per spec.
    Writes to a temp file then os.replace()'s it into place so a crash
    mid-write can never leave index.json truncated or partially written."""
    tmp_path = INDEX_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(entries, indent=2))
    os.replace(tmp_path, INDEX_PATH)


def _scan_image_files() -> list[Path]:
    files = []
    for path in sorted(ASSETS_ROOT.rglob("*")):
        if path.suffix.lower() in _IMAGE_EXTENSIONS and path.is_file():
            files.append(path)
    return files


def _next_id(entries: list[dict]) -> str:
    highest = 0
    for entry in entries:
        m = re.fullmatch(r"img_(\d+)", entry.get("id", ""))
        if m:
            highest = max(highest, int(m.group(1)))
    return f"img_{highest + 1:03d}"


_PIL_FORMAT_TO_MEDIA_TYPE = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


def _detect_media_type(path: Path) -> str:
    """Uses Pillow to confirm the file actually opens as a valid image and
    to read its real format, rather than trusting the file extension --
    catches a corrupt or mislabeled file with a clear error here instead
    of a confusing failure from the Anthropic API later."""
    try:
        with Image.open(path) as img:
            fmt = img.format
    except UnidentifiedImageError as exc:
        raise ValueError(f"{path} does not appear to be a valid image file") from exc

    media_type = _PIL_FORMAT_TO_MEDIA_TYPE.get(fmt)
    if not media_type:
        raise ValueError(f"{path} has unsupported image format '{fmt}' (expected PNG/JPEG/WEBP)")
    return media_type


def _tag_image(client: Anthropic, path: Path) -> dict:
    media_type = _detect_media_type(path)
    image_b64 = base64.standard_b64encode(path.read_bytes()).decode()

    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                {"type": "text", "text": "Tag this image per the system instructions."},
            ],
        }],
    )
    raw = response.content[0].text.strip()
    # Strip a ```json ... ``` fence if the model wraps its output despite
    # the "JSON only" instruction -- cheap insurance, not a full narrative
    # parser like the research pipeline needs, since this prompt is far
    # more constrained.
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    return json.loads(raw)


def _load_sidecar(path: Path) -> Optional[dict]:
    """
    Checks for a metadata sidecar (same filename, .json extension)
    alongside an image -- e.g. fetch_seed_images.sh writes one with
    original_creator/creator_linkedin for every image it downloads, so
    attribution doesn't depend on vision recognizing/guessing a known
    creator. Only original_creator/creator_linkedin are ever sourced
    from the sidecar; category/topic_tags/compatible_post_topics always
    come from vision regardless of whether a sidecar exists.
    """
    sidecar_path = path.with_suffix(".json")
    if not sidecar_path.exists():
        return None
    return json.loads(sidecar_path.read_text())


def main() -> None:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    entries = _load_index()
    indexed_filenames = {entry["filename"] for entry in entries}

    all_files = _scan_image_files()
    scanned = len(all_files)
    added = 0
    already_indexed = 0

    for path in all_files:
        relative = str(path.relative_to(ASSETS_ROOT)).replace(os.sep, "/")
        if relative in indexed_filenames:
            already_indexed += 1
            continue

        tags = _tag_image(client, path)
        sidecar = _load_sidecar(path)

        entry = {
            "id": _next_id(entries),
            "filename": relative,
            "category": tags.get("category", ""),
            "topic_tags": tags.get("topic_tags", []),
            "original_creator": sidecar["original_creator"] if sidecar else tags.get("original_creator", "Unknown"),
            "creator_linkedin": sidecar["creator_linkedin"] if sidecar else tags.get("creator_linkedin"),
            "is_original": relative.startswith("my_originals/"),
            "last_used_date": None,
            "times_used": 0,
            "compatible_post_topics": tags.get("compatible_post_topics", []),
        }
        entries.append(entry)
        indexed_filenames.add(relative)
        _write_index_atomic(entries)
        added += 1

    print(f"{scanned} images scanned, {added} new entries added, {already_indexed} already indexed.")


if __name__ == "__main__":
    main()
