#!/bin/bash
# backup-vault.sh
# Commits and pushes the Obsidian vault to the git remote.
# Run weekly or after any major vault update.
# Usage: bash scripts/backup-vault.sh

set -e

VAULT_DIR="knowledge"
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")

echo "[$TIMESTAMP] Starting vault backup..."

# Stage all vault changes
git add "$VAULT_DIR/"

# Check if there's anything to commit
if git diff --cached --quiet; then
  echo "No vault changes to commit. Already up to date."
  exit 0
fi

git commit -m "vault: backup $TIMESTAMP"

# Push if remote exists
if git remote | grep -q origin; then
  git push origin master
  echo "Vault pushed to remote."
else
  echo "No remote configured. Commit saved locally only."
  echo "To add a remote: git remote add origin git@github.com:KDavisCodeCloud/kdavis-agentic-platform.git"
fi

echo "Backup complete."
