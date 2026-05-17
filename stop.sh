#!/usr/bin/env bash
# stop.sh — Stop the ReviewPulse dev stack
# Usage: ./stop.sh [--volumes]
#
# Stops all running ReviewPulse processes (backend, worker, frontend)
# and optionally tears down Docker containers + volumes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[ReviewPulse]${NC} $*"; }
success() { echo -e "${GREEN}[ReviewPulse]${NC} $*"; }

REMOVE_VOLUMES=false
for arg in "$@"; do
  case $arg in
    --volumes|-v)
      REMOVE_VOLUMES=true
      ;;
    -h|--help)
      echo "Usage: $0 [--volumes]"
      echo "  --volumes   Also remove Docker volumes (deletes all database data)"
      exit 0
      ;;
  esac
done

# ── Kill processes started by start.sh ───────────────────────────────────────
# We kill by process name rather than PID file to handle cases where start.sh
# was killed without cleanup (e.g., terminal closed).

info "Stopping backend processes..."

# FastAPI / uvicorn
pkill -f "uvicorn app.main:app" 2>/dev/null && info "  Stopped uvicorn" || true

# Celery worker
pkill -f "celery -A app.tasks.celery_app worker" 2>/dev/null && info "  Stopped Celery worker" || true

# Celery beat (if running)
pkill -f "celery -A app.tasks.celery_app beat" 2>/dev/null && info "  Stopped Celery beat" || true

# Vite dev server
pkill -f "vite" 2>/dev/null && info "  Stopped Vite" || true

# ── Stop Docker Compose ───────────────────────────────────────────────────────
if $REMOVE_VOLUMES; then
  info "Stopping Docker services and removing volumes (all DB data will be deleted)..."
  docker compose down --volumes
  success "Docker containers and volumes removed."
else
  info "Stopping Docker services (data preserved)..."
  docker compose down
  success "Docker containers stopped. Data volumes preserved."
  echo -e "${CYAN}[ReviewPulse]${NC} Tip: run '${RED}./stop.sh --volumes${NC}' to also wipe the database."
fi

success "ReviewPulse stopped."
