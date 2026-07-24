"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
LinkedIn Asset Vault — gemini_image_gen.py

Generates one custom technical diagram per post via the Gemini image API,
for posts MKT-LI1 drafted an image_description for (agents/marketing/
mkt_li1_linkedin_brand.py's VOICE_SYSTEM_PROMPT composes that prompt
already — this script sends it to Gemini verbatim, never re-composes or
merges multiple prompts into one call).

Talks to the REST API directly via `requests` rather than the google-genai
SDK: google-genai>=2.x requires httpx>=0.28, which conflicts with
supabase==2.7.4's httpx<0.28 pin (confirmed by installing it — it forced
an httpx/pydantic upgrade that broke the supabase/postgrest/realtime
import chain repo-wide). Not worth a repo-wide supabase upgrade for one
script's SDK choice — the REST endpoint needs nothing beyond `requests`
(already a dependency) and stdlib `base64`.

Model: gemini-2.5-flash-image ("Nano Banana") — current stable image-gen
model as of 2026-07, chosen specifically for its documented reliable text
rendering, which matters here since every diagram is dense with labels.
If diagram text legibility isn't good enough in practice, gemini-3-pro-
image-preview ("Nano Banana Pro") is the documented upgrade path — swap
MODEL below, no other code change needed.

One call, one image, one topic — the input is always a per-post
image_description already ending in "Single standalone diagram..." /
never a batch of descriptions concatenated into one prompt.

Input: JSON array path (assets_library/extract_image_briefs.py's output):
  [{"post_topic": str, "pillar": str, "image_description": str, "queue_id": str|null}, ...]

Behavior per item:
- Skips (does not regenerate) if the target file already exists —
  idempotent by topic slug + today's date, same key used to name the file.
- Calls Gemini, saves the PNG to
  assets_library/my_originals/[pillar_slug]/[post_topic_slug]_[YYYYMMDD].png
- Writes a sidecar .json (image_indexer.py already knows how to read
  original_creator/creator_linkedin from a sidecar — see its
  _load_sidecar docstring)
- Never blocks the batch on one failure: logs and continues, per Kelvin's
  rule that a Gemini outage should degrade to text-only posts, not stop
  the whole monthly batch.
- If queue_id is present and generation succeeded, re-attaches the image
  directly to that exact linkedin_content_queue row (by id, only while
  status='pending_review' — never overwrites a row a human has already
  reviewed). This is the fix for a real sequencing gap: MKT-LI1 already
  wrote each row with select_asset()'s (necessarily empty, since the
  image doesn't exist yet) result before this script ever runs — fuzzy
  topic re-matching afterward would risk two similar-topic posts
  grabbing each other's diagrams, so re-attach goes by id instead.

After all items: runs image_indexer.py so every new file (and its
sidecar's category/tags) is indexed before HITL review.

GEMINI_API_KEY read from .env — never hardcoded. Never blocks the batch
if generation fails; all generated images still require HITL approval
before publish (unchanged — this script only drafts a file and updates
image_brief on a pending_review row, nothing here bypasses HITL).
"""

import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

ASSETS_ROOT = Path(__file__).parent
MY_ORIGINALS_ROOT = ASSETS_ROOT / "my_originals"
REPO_ROOT = ASSETS_ROOT.parent

# Standalone CLI script, not run inside the FastAPI process — same
# explicit-path reasoning as image_indexer.py's load_dotenv call.
load_dotenv(REPO_ROOT / ".env")

MODEL = "gemini-2.5-flash-image"
_GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

CREATOR_NAME = "Kelvin Davis"
CREATOR_LINKEDIN = "linkedin.com/in/kelvin-davis"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "untitled"


def _target_paths(pillar: str, post_topic: str, today: date) -> tuple[Path, Path]:
    pillar_slug = _slugify(pillar)
    topic_slug = _slugify(post_topic)
    filename = f"{topic_slug}_{today.strftime('%Y%m%d')}"
    image_dir = MY_ORIGINALS_ROOT / pillar_slug
    return image_dir / f"{filename}.png", image_dir / f"{filename}.json"


def _generate_image(api_key: str, image_description: str) -> bytes:
    response = requests.post(
        _GEMINI_URL,
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": image_description}]}],
            "generationConfig": {"responseModalities": ["image"]},
        },
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()

    candidates = data.get("candidates", [])
    for candidate in candidates:
        for part in candidate.get("content", {}).get("parts", []):
            inline_data = part.get("inlineData")
            if inline_data and inline_data.get("data"):
                import base64
                return base64.b64decode(inline_data["data"])

    raise RuntimeError(f"Gemini response contained no image data: {json.dumps(data)[:500]}")


def _reattach_to_queue_row(queue_id: str, image_path: Path, generation_date: str) -> bool:
    """Updates the exact linkedin_content_queue row this image was
    generated for, only while it's still awaiting review. Returns True if
    a row was actually updated, False if the row is gone or already
    reviewed (not an error — the image still exists in the vault either way)."""
    from supabase import create_client

    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    relative_path = f"assets_library/{image_path.relative_to(ASSETS_ROOT)}"

    image_brief = {
        "image_id": None,
        "image_path": relative_path,
        "credit_line": None,
        "is_original": True,
        "selected_because": f"gemini-generated {generation_date} for this post",
        "generation_available": True,
    }
    result = (
        client.table("linkedin_content_queue")
        .update({"image_brief": image_brief})
        .eq("id", queue_id)
        .eq("status", "pending_review")
        .execute()
    )
    return bool(getattr(result, "data", None))


def generate_batch(briefs: list[dict]) -> dict:
    api_key = os.environ["GEMINI_API_KEY"]
    today = date.today()

    generated = 0
    skipped_existing = 0
    failed = 0
    reattached = 0
    failures: list[str] = []

    for brief in briefs:
        post_topic = brief.get("post_topic", "")
        pillar = brief.get("pillar", "")
        image_description = brief.get("image_description", "")
        queue_id: Optional[str] = brief.get("queue_id")

        if not image_description:
            continue

        image_path, sidecar_path = _target_paths(pillar, post_topic, today)

        if image_path.exists():
            skipped_existing += 1
            continue

        try:
            image_bytes = _generate_image(api_key, image_description)
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(image_bytes)

            generation_date = today.isoformat()
            sidecar_path.write_text(json.dumps({
                "original_creator": CREATOR_NAME,
                "creator_linkedin": CREATOR_LINKEDIN,
                "generated_by": "gemini",
                "generation_date": generation_date,
                "post_topic": post_topic,
                "image_description": image_description,
            }, indent=2))
            generated += 1

            if queue_id:
                try:
                    if _reattach_to_queue_row(queue_id, image_path, generation_date):
                        reattached += 1
                except Exception as exc:  # noqa: BLE001 — a re-attach failure must not lose the generated image
                    failures.append(f"{post_topic}: image saved but re-attach to queue_id={queue_id} failed: {exc}")

        except Exception as exc:  # noqa: BLE001 — never block the batch on one image's failure
            failed += 1
            failures.append(f"{post_topic}: {exc}")

    if generated:
        subprocess.run(
            [sys.executable, str(ASSETS_ROOT / "image_indexer.py")],
            check=False,
            cwd=REPO_ROOT,
        )

    return {
        "generated": generated,
        "skipped_existing": skipped_existing,
        "failed": failed,
        "reattached": reattached,
        "failures": failures,
    }


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: gemini_image_gen.py <image_briefs.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        briefs = json.load(f)

    summary = generate_batch(briefs)

    print(
        f"{summary['generated']} images generated, saved to assets_library/my_originals/ "
        f"({summary['skipped_existing']} already existed, {summary['failed']} failed, "
        f"{summary['reattached']} re-attached to queued posts)."
    )
    for failure in summary["failures"]:
        print(f"  FAILED: {failure}", file=sys.stderr)


if __name__ == "__main__":
    main()
