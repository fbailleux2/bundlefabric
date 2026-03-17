#!/bin/bash
# BundleFabric — Sync Mac mini depuis VPS3
# Fait un git fetch + merge fast-forward si possible, sinon avertit

REPO="/Users/franck/git-work/bundlefabric"
LOG="$HOME/.bundlefabric-sync.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"; }

cd "$REPO" || exit 1

# Vérifier si des changements locaux non committés existent
if ! git diff --quiet || ! git diff --cached --quiet; then
  log "⚠ Changements locaux non committés — sync annulée"
  exit 0
fi

# Fetch depuis origin (VPS3 bare repo)
git fetch origin main >> "$LOG" 2>&1

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
  exit 0  # À jour — silencieux
fi

# Merge fast-forward uniquement (safe)
if git merge --ff-only origin/main >> "$LOG" 2>&1; then
  log "Sync OK → $(git log --oneline -1)"
else
  log "⚠ Merge FF impossible — pull manuel requis (git pull origin main)"
fi
