"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

One-off backlog repair, 2026-09-15 image relevance audit.

Kelvin asked for a full audit of every post in linkedin_content_queue
that already has an image attached, scoring each MATCH/MISMATCH/PARTIAL
against the post's actual subject. Scope, confirmed with Kelvin before
running anything:

- Only unpublished rows (pending_review/approved/rejected) are in
  scope. The 24 already-published rows are left untouched -- there is
  no way to swap the image on a post already live on LinkedIn, so
  changing our own DB record for a published row would just create a
  record that disagrees with what's actually posted.
- MISMATCH is not "it's a diagram" -- Kelvin's own correction: "every
  image is not going to be of people... the image will be whatever
  gemini decides it to be based on the post." The bar is whether the
  image is specific to THIS post's actual content, not a blanket ban on
  any particular visual style.

Manual audit (Claude Code, viewing every image against its post text
directly) found 22 unpublished rows with an image attached. 10 were a
genuine MATCH (bespoke, on-topic diagram already). 12 needed a new
image:

MISMATCH (10) -- all ten currently point at an image generated for a
DIFFERENT post entirely. Nine share one file (the CI/CD Failure Path Map
diagram, generated 2026-07-23 for row 3c0452fe); one (06d09054) points
at the "multi-agent marketing swarm" diagram generated for row
27430104. Root cause: assets_library/asset_selector.py's topic-word
substring match was loose enough that generic infra vocabulary in these
posts' topics matched the CI/CD image's tags, and since every post in
that batch run was drafted back-to-back with no publishes in between
(times_used=0 for all), the tie-break kept converging on the same
earliest-generated file -- the same failure mode scripts/
fix_august_batch_images.py patched once before, resurfacing in a later
batch.

PARTIAL (2) -- own bespoke image, but a real quality problem:
- 7d3a70be: the garden/layered-systems-thinking post's image is a
  generic cloud-infra stack diagram with no trace of the garden/growth
  metaphor that is the actual hook of the post.
- f10f786b: right topic (graceful failure handling), but the generated
  diagram's text is badly garbled ("Orchterator", "Faflbuck", "EROR",
  "DEBUB") -- illegible/unprofessional as generated.

This script regenerates a fresh, relevance-gated image for exactly
these 12 rows via assets_library/scene_image_gen.py's two-step
(scene-extraction -> Gemini) + relevance-gate pipeline, and updates
each row's image_brief/image_description/notes in place. It does not
touch the shared CI/CD or multi-agent-swarm files themselves -- both are
still the correct, matching image for the post they were originally
generated for (rows 3c0452fe and 27430104), so deleting them would
break a MATCH to fix a MISMATCH elsewhere.

Any row the relevance gate still flags after its one automatic
regeneration is left with hitl_notes set instead of being silently
attached -- surfaces in the dashboard's existing HITL queue for Kelvin
to look at directly, same "flag, don't guess" rule as everywhere else
in this pipeline.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import subprocess

from supabase import create_client

from assets_library.gemini_image_gen import ASSETS_ROOT
from assets_library.scene_image_gen import generate_relevant_image

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

# (queue_id, audit verdict) -- verdict is documentation only, not used by the script logic.
FLAGGED_ROWS = [
    ("4fa35503-f5be-49e5-aba2-b70072cda635", "MISMATCH: had the CI/CD diagram (scope discipline post)"),
    ("0a8877a9-1800-4bbd-b27a-74d06dcdfa46", "MISMATCH: had the CI/CD diagram (HITL gates post)"),
    ("103c8fc6-dbdd-4801-8783-efdb5d59228b", "MISMATCH: had the CI/CD diagram (LLM-agnostic production requirement post)"),
    ("1f74ea46-f8df-4112-99c1-0e7affbd70c5", "MISMATCH: had the CI/CD diagram (Kubernetes default-reach post)"),
    ("ad9bb1c4-a4cf-4201-83af-365a257dd651", "MISMATCH: had the CI/CD diagram (multi-tenant isolation post)"),
    ("d27f8bf2-b5a4-4b70-86b5-28d76ee883ff", "MISMATCH: had the CI/CD diagram (governance/HITL blueprint post)"),
    ("06d09054-b623-4f99-ace1-03fd943286f8", "MISMATCH: had the multi-agent-swarm diagram (LLM-agnostic vs vendor lock-in post)"),
    ("d1666556-869e-4764-a097-57a8400c7d07", "MISMATCH: had the CI/CD diagram (LLM-agnostic + HITL governance post)"),
    ("56db52af-7e4d-4ff1-ba67-e058612de719", "MISMATCH: had the CI/CD diagram (LLM-agnostic vendor lock-in gaps post)"),
    ("1bd53296-4f91-48c2-9977-388a0c06fc93", "MISMATCH: had the CI/CD diagram (LLM-agnostic production-safe post)"),
    ("7d3a70be-9c4b-4c84-a920-61cd2d7bbdb9", "PARTIAL: generic stack diagram, missing the garden metaphor"),
    ("f10f786b-7a8d-42e6-8fe7-4dd02eddd779", "PARTIAL: right topic, badly garbled diagram text"),
]


def main() -> None:
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    ids = [row_id for row_id, _ in FLAGGED_ROWS]
    rows = (
        client.table("linkedin_content_queue")
        .select("id,status,topic,pillar_name,post_copy,notes")
        .in_("id", ids)
        .execute()
    ).data
    rows_by_id = {r["id"]: r for r in rows}

    fixed = 0
    flagged = 0
    errors: list[str] = []

    for queue_id, verdict in FLAGGED_ROWS:
        row = rows_by_id.get(queue_id)
        if row is None:
            errors.append(f"{queue_id}: not found in linkedin_content_queue (may already be published/deleted)")
            continue
        if row["status"] == "published":
            errors.append(f"{queue_id}: status is 'published' -- skipping, out of scope")
            continue

        print(f"\n--- {queue_id} | {verdict}")
        print(f"    topic: {row['topic']}")

        try:
            result = generate_relevant_image(
                post_text=row["post_copy"],
                pillar=row["pillar_name"],
                post_topic=row["topic"],
            )
        except Exception as exc:  # noqa: BLE001 -- one row's failure must never stop the rest of the backlog run
            errors.append(f"{queue_id}: generation failed: {exc}")
            print(f"    FAILED: {exc}")
            continue

        print(f"    scene_type={result['scene_type']} attempts={result['attempts']} relevant={result['relevant']}")
        print(f"    scene: {result['scene_description']}")

        relative_path = f"assets_library/{result['image_path'].relative_to(ASSETS_ROOT)}"
        image_brief = {
            "image_id": None,
            "image_path": relative_path,
            "credit_line": None,
            "is_original": True,
            "selected_because": f"scene-gated regeneration {result['scene_type'].lower()} (backlog fix 2026-09-15)",
            "generation_available": True,
        }

        update = {
            "image_brief": image_brief,
            "image_description": result["scene_description"],
        }
        if result["flagged_for_review"]:
            flagged += 1
            note = f"IMAGE RELEVANCE GATE FAILED after regeneration: {result['reason']}"
            existing_notes = row.get("notes") or ""
            update["notes"] = (existing_notes + " | " if existing_notes else "") + note
            update["hitl_notes"] = note
            print(f"    FLAGGED FOR REVIEW: {result['reason']}")
        else:
            fixed += 1

        (
            client.table("linkedin_content_queue")
            .update(update)
            .eq("id", queue_id)
            .eq("status", row["status"])  # never touch a row a human has since moved (e.g. approved mid-run)
            .execute()
        )

    print(f"\n{fixed} images fixed and attached, {flagged} flagged for manual HITL review, {len(errors)} errors.")
    for err in errors:
        print(f"  ERROR: {err}")

    subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent / "assets_library" / "image_indexer.py")], check=False)


if __name__ == "__main__":
    main()
