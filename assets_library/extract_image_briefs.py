"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
LinkedIn Asset Vault — extract_image_briefs.py

Reads a MKT-LI1 batch response (the JSON body POST /marketing/linkedin-brand
returns — a "posts" array, each shaped per run_li1_brand_agent's output in
agents/marketing/mkt_li1_linkedin_brand.py) and prints just the fields
gemini_image_gen.py needs, as a JSON array on stdout:

  [{"post_topic": str, "pillar": str, "image_description": str, "queue_id": str}, ...]

queue_id (post["id"], the linkedin_content_queue row already written by
MKT-LI1) rides along so gemini_image_gen.py can re-attach the generated
image directly to the exact post it was written for by id — not by fuzzy
topic-tag re-matching through asset_selector, which is designed for
sharing one photo across many future posts, not binding a bespoke
generated diagram to the one post it was drafted for.

Skips (does not error on) any post with no image_description — carousel
posts (image_description is null by design) and any text_post where the
model didn't produce one. Used by scripts/monthly_batch.sh:

  python assets_library/extract_image_briefs.py "$BATCH_PATH" > /tmp/image_briefs.json
"""

import json
import sys


def extract_image_briefs(batch: dict | list) -> list[dict]:
    posts = batch.get("posts", []) if isinstance(batch, dict) else batch
    briefs = []
    for post in posts:
        image_description = post.get("image_description")
        if not image_description:
            continue
        briefs.append({
            "post_topic": post.get("topic", ""),
            "pillar": post.get("pillar_name", post.get("pillar", "")),
            "image_description": image_description,
            "queue_id": post.get("id"),
        })
    return briefs


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: extract_image_briefs.py <mkt_li1_batch.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        batch = json.load(f)

    print(json.dumps(extract_image_briefs(batch), indent=2))


if __name__ == "__main__":
    main()
