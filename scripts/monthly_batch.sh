#!/bin/bash
# monthly_batch.sh
# Runs the drafting half of one monthly LinkedIn content cycle: MKT-LI1
# drafts ~12 posts into linkedin_content_queue as pure text, no image.
#
# Image generation is NOT part of this script (removed 2026-09-15, see
# agents/marketing/mkt_li1_linkedin_brand.py's v2.5 changelog entry and
# api/routes/internal_marketing.py's _generate_and_gate_image_for_approved_row):
# it now fires automatically, per-post, the moment a human approves that
# post's text in the dashboard (single-row PATCH or the "approve entire
# batch" bulk action) — reading the scene out of the APPROVED post copy,
# never a draft that could still be rejected or rewritten. Nothing to
# run here for it anymore.
#
# Nothing here publishes or approves anything — HITL review of the batch
# happens in the dashboard. Once approved (image generation already ran
# as part of that approval), scripts/dispatch_scheduled_posts.py (run on
# a cron) fires each post on its own scheduled_for date across the month.
#
# Usage: bash scripts/monthly_batch.sh --input path/to/request.json [--batch-month YYYY-MM]
#
# request.json shape (research_report/idea_reservoir/kelvin_voice_profile
# are genuinely variable input Kelvin supplies each month — see
# agents/marketing/mkt_li1_linkedin_brand.py's run_li1_brand_agent for
# what each field feeds):
#   {
#     "research_report": {...},
#     "idea_reservoir": [...],
#     "kelvin_voice_profile": {...},
#     "build_updates": [...]
#   }

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$REPO_ROOT/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"

API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
BATCH_MONTH=""
INPUT_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input) INPUT_PATH="$2"; shift 2 ;;
    --batch-month) BATCH_MONTH="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$INPUT_PATH" ]; then
  echo "usage: monthly_batch.sh --input path/to/request.json [--batch-month YYYY-MM]" >&2
  exit 1
fi
if [ ! -f "$INPUT_PATH" ]; then
  echo "Input file not found: $INPUT_PATH" >&2
  exit 1
fi

BATCH_PATH="/tmp/mkt_li1_batch_$(date +%Y%m%d_%H%M%S).json"

echo "=== STEP 1: Generate monthly batch (MKT-LI1) ==="
REQUEST_BODY="$($PYTHON -c "
import json, sys
body = json.load(open('$INPUT_PATH'))
batch_month = '$BATCH_MONTH'
if batch_month:
    body['batch_month'] = batch_month
print(json.dumps(body))
")"

curl -sS -X POST "$API_BASE_URL/api/v1/marketing/linkedin-brand" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${MARKETING_API_KEY:-}" \
  -d "$REQUEST_BODY" \
  -o "$BATCH_PATH"

POST_COUNT="$($PYTHON -c "import json; print(json.load(open('$BATCH_PATH')).get('post_count', 0))")"
echo "MKT-LI1 drafted $POST_COUNT posts -> $BATCH_PATH"

echo "=== DONE ==="
echo "Batch written to $BATCH_PATH — review and approve in the dashboard."
echo "Approving a post (single or batch) generates and gates its image automatically."
echo "Once approved, scripts/dispatch_scheduled_posts.py publishes each post on its scheduled_for date."
