#!/bin/bash
# BundleFabric — Auto-deploy script
# Vérifie si le bare repo a de nouveaux commits → pull + redeploy
set -e

BARE_REPO="/opt/git/bundlefabric.git"
WORK_DIR="/opt/bundlefabric"
LOG="/var/log/bundlefabric-deploy.log"
WEB_ROOT="/var/www/bundlefabric"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"; }

# Comparer HEAD du bare repo vs HEAD du working dir
BARE_HEAD=$(git -C "$BARE_REPO" rev-parse HEAD 2>/dev/null)
WORK_HEAD=$(git -C "$WORK_DIR" rev-parse HEAD 2>/dev/null)

if [ "$BARE_HEAD" = "$WORK_HEAD" ]; then
  exit 0  # Rien à faire — silencieux
fi

log "Nouveau commit détecté: $BARE_HEAD (actuel: $WORK_HEAD)"

# Pull vers le working dir
git -C "$WORK_DIR" pull /opt/git/bundlefabric.git main >> "$LOG" 2>&1
log "Pull OK → $(git -C $WORK_DIR log --oneline -1)"

# Copier WebUI si modifiée
if git -C "$WORK_DIR" diff HEAD~1 HEAD --name-only 2>/dev/null | grep -q "webui/"; then
  sudo cp "$WORK_DIR/webui/index.html" "$WEB_ROOT/index.html"
  log "WebUI copiée dans $WEB_ROOT"
fi

# Reconstruire et redémarrer si code Python ou Dockerfile modifié
if git -C "$WORK_DIR" diff HEAD~1 HEAD --name-only 2>/dev/null | grep -qE "\.py$|Dockerfile|requirements\.txt"; then
  log "Code Python modifié — rebuild Docker…"
  cd "$WORK_DIR"
  docker compose --profile phase2 build >> "$LOG" 2>&1
  docker compose --profile phase2 up -d --force-recreate >> "$LOG" 2>&1
  log "Redéploiement terminé"
else
  # Juste redémarrer (ex: bundles YAML modifiés)
  docker compose --profile phase2 up -d --force-recreate >> "$LOG" 2>&1
  log "Redémarrage container OK"
fi

log "Deploy terminé ✓"
