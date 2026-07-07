#!/usr/bin/env bash
# CLAUDE.md Phase 1, Step 14 — GitHub + Gitea dual remote.
# Owner runs this manually, once, from the repo root.
#
# Configures a single `origin` remote with two push URLs so that a plain
# `git push` sends the same ref to both GitHub (public portfolio) and the
# self-hosted Gitea mirror (private internal), per CLAUDE.md's non-negotiable
# "CI/CD pushes to GitHub AND Gitea simultaneously on every merge to main."
#
# Idempotent — safe to re-run. Does not overwrite an existing origin fetch
# URL, and will not add a push URL that's already configured.
#
# Usage:
#   export GITEA_REMOTE_URL=git@your-gitea-server.com:kdavis/agentic-platform.git
#   ./cicd/git_remotes.sh

set -euo pipefail

# This repo's actual GitHub origin (confirmed via `git remote -v`) —
# not the "agentic-platform" name used in CLAUDE.md's own example.
GITHUB_URL="https://github.com/KDavisCodeCloud/kdavis-agentic-platform.git"
GITEA_URL="${GITEA_REMOTE_URL:-}"

if [[ -z "$GITEA_URL" ]]; then
    echo "ERROR: GITEA_REMOTE_URL is not set." >&2
    echo "CLAUDE.md references a self-hosted Gitea server with no real" >&2
    echo "hostname on record — set the actual URL before running this script:" >&2
    echo "  export GITEA_REMOTE_URL=git@your-gitea-server.com:kdavis/agentic-platform.git" >&2
    echo "  ./cicd/git_remotes.sh" >&2
    exit 1
fi

if git remote get-url origin >/dev/null 2>&1; then
    current_url="$(git remote get-url origin)"
    echo "origin already exists (fetch: $current_url) — leaving fetch URL as is."
else
    git remote add origin "$GITHUB_URL"
    echo "Added origin -> $GITHUB_URL"
fi

if git remote get-url --all origin | grep -qxF "$GITEA_URL"; then
    echo "Gitea push URL already configured on origin."
else
    git remote set-url --add origin "$GITEA_URL"
    echo "Added Gitea push URL -> $GITEA_URL"
fi

echo
echo "origin push URLs now:"
git remote get-url --all origin

echo
echo "Verify with: git push origin <branch>"
echo "Both URLs above should receive the push."
