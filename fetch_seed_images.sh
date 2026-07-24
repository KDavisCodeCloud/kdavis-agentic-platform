#!/usr/bin/env bash
#
# PROPRIETARY AND CONFIDENTIAL
# Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
#
# fetch_seed_images.sh — downloads the first seed batch of images for the
# LinkedIn asset vault (assets_library/) from ByteByteGo's public
# system-design-101 repo, writes an attribution sidecar .json next to
# each successfully downloaded file (so image_indexer.py doesn't have to
# guess the creator from vision alone), then runs image_indexer.py as
# the final step to tag and index everything.
#
# A 404 (or any other curl failure) on one URL is skipped and reported —
# never stops the rest of the batch, per Kelvin's rule.

set -uo pipefail   # deliberately NOT set -e -- a single curl failure must not abort the batch

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSETS_DIR="$REPO_ROOT/assets_library"
CREATOR_NAME="ByteByteGo"
CREATOR_HANDLE="@bytebytego"

FAILED_URLS=()
DOWNLOADED_COUNT=0

download_image() {
  local url="$1"
  local dest_dir="$2"
  local filename
  filename="$(basename "$url")"
  local dest_path="$dest_dir/$filename"

  mkdir -p "$dest_dir"

  if curl -fsSL -o "$dest_path" "$url"; then
    cat > "${dest_path%.*}.json" <<EOF
{
  "original_creator": "$CREATOR_NAME",
  "creator_linkedin": "$CREATOR_HANDLE"
}
EOF
    echo "Downloaded: $filename"
    DOWNLOADED_COUNT=$((DOWNLOADED_COUNT + 1))
  else
    echo "FAILED (skipped): $url"
    FAILED_URLS+=("$url")
  fi
}

echo "=== Fetching system_design images ==="
download_image "https://github.com/ByteByteGoHq/system-design-101/raw/main/images/rest-api.jpg" "$ASSETS_DIR/system_design"
download_image "https://github.com/ByteByteGoHq/system-design-101/raw/main/images/graphql.jpg" "$ASSETS_DIR/system_design"
download_image "https://github.com/ByteByteGoHq/system-design-101/raw/main/images/how-does-https-work.jpg" "$ASSETS_DIR/system_design"
download_image "https://github.com/ByteByteGoHq/system-design-101/raw/main/images/ci-cd-pipeline.jpg" "$ASSETS_DIR/system_design"
download_image "https://github.com/ByteByteGoHq/system-design-101/raw/main/images/kafka.jpg" "$ASSETS_DIR/system_design"
download_image "https://github.com/ByteByteGoHq/system-design-101/raw/main/images/kubernetes.jpg" "$ASSETS_DIR/system_design"

echo "=== Fetching cloud_devops images ==="
download_image "https://github.com/ByteByteGoHq/system-design-101/raw/main/images/devops-tools.jpg" "$ASSETS_DIR/cloud_devops"
download_image "https://github.com/ByteByteGoHq/system-design-101/raw/main/images/linux-commands.jpg" "$ASSETS_DIR/cloud_devops"
download_image "https://github.com/ByteByteGoHq/system-design-101/raw/main/images/docker.jpg" "$ASSETS_DIR/cloud_devops"
download_image "https://github.com/ByteByteGoHq/system-design-101/raw/main/images/git-commands.jpg" "$ASSETS_DIR/cloud_devops"

echo "=== Fetching ai_models images ==="
download_image "https://github.com/ByteByteGoHq/system-design-101/raw/main/images/llm.jpg" "$ASSETS_DIR/ai_models"
download_image "https://github.com/ByteByteGoHq/system-design-101/raw/main/images/rag.jpg" "$ASSETS_DIR/ai_models"

echo
echo "=== Summary ==="
echo "Downloaded: $DOWNLOADED_COUNT"
if [ ${#FAILED_URLS[@]} -gt 0 ]; then
  echo "Failed (${#FAILED_URLS[@]}):"
  for u in "${FAILED_URLS[@]}"; do
    echo "  - $u"
  done
else
  echo "Failed: 0"
fi

echo
echo "=== Running image_indexer.py ==="
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi
"$PYTHON_BIN" "$REPO_ROOT/assets_library/image_indexer.py"
