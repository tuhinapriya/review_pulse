#!/usr/bin/env bash
# start.sh — Start the full ReviewPulse local dev stack
# Usage: ./start.sh [--skip-install] [--skip-migrate]
#
# What this does:
#   1. Checks all required tools are available
#   2. Starts Postgres + Redis via Docker Compose
#   3. Installs backend and frontend dependencies (skippable)
#   4. Runs database migrations (skippable)
#   5. Launches backend, Celery worker, and frontend in separate processes
#   6. Prints URLs and waits — Ctrl+C stops everything cleanly

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[ReviewPulse]${NC} $*"; }
success() { echo -e "${GREEN}[ReviewPulse]${NC} $*"; }
warn()    { echo -e "${YELLOW}[ReviewPulse]${NC} $*"; }
error()   { echo -e "${RED}[ReviewPulse]${NC} $*" >&2; }

# ── Argument parsing ──────────────────────────────────────────────────────────
SKIP_INSTALL=false
SKIP_MIGRATE=false
for arg in "$@"; do
  case $arg in
    --skip-install) SKIP_INSTALL=true ;;
    --skip-migrate) SKIP_MIGRATE=true ;;
    -h|--help)
      echo "Usage: $0 [--skip-install] [--skip-migrate]"
      echo "  --skip-install   Skip 'uv sync' and 'npm install'"
      echo "  --skip-migrate   Skip 'alembic upgrade head'"
      exit 0
      ;;
  esac
done

# ── Track child PIDs so cleanup can kill them all ─────────────────────────────
PIDS=()

cleanup() {
  echo ""
  info "Shutting down all processes..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  success "All processes stopped. Run './stop.sh' to also stop Docker."
  exit 0
}
trap cleanup SIGINT SIGTERM

# ── 1. Prerequisite checks ────────────────────────────────────────────────────
info "Checking prerequisites..."

check_tool() {
  if ! command -v "$1" &>/dev/null; then
    error "Required tool not found: $1"
    error "Install it with: $2"
    exit 1
  fi
}

check_tool docker   "https://docs.docker.com/get-docker/"
check_tool node     "brew install node"
check_tool npm      "brew install node"

# uv may be installed to ~/.local/bin which might not be on PATH in all shells
if ! command -v uv &>/dev/null; then
  if [ -f "$HOME/.local/bin/uv" ]; then
    export PATH="$HOME/.local/bin:$PATH"
  else
    error "uv not found. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
  fi
fi

# Verify Docker daemon is running
if ! docker info &>/dev/null; then
  warn "Docker daemon is not running. Attempting to start Docker Desktop..."
  open -a Docker 2>/dev/null || true
  info "Waiting up to 30s for Docker to start..."
  for i in $(seq 1 30); do
    sleep 1
    if docker info &>/dev/null; then
      success "Docker started."
      break
    fi
    if [ "$i" -eq 30 ]; then
      error "Docker did not start in time. Please start Docker Desktop manually."
      exit 1
    fi
  done
fi

# Check .env exists
if [ ! -f .env ]; then
  warn ".env not found — copying from .env.example"
  cp .env.example .env
  warn "Edit .env with your real API keys before using LLM features."
fi

success "Prerequisites OK."

# ── 2. Start infrastructure (Postgres + Redis) ────────────────────────────────
info "Starting Postgres + Redis via Docker Compose..."
docker compose up -d

# Wait for Postgres to be healthy before running migrations
info "Waiting for Postgres to be ready..."
for i in $(seq 1 30); do
  if docker compose exec -T postgres pg_isready -U reviewpulse &>/dev/null; then
    success "Postgres is ready."
    break
  fi
  sleep 1
  if [ "$i" -eq 30 ]; then
    error "Postgres did not become ready in 30s."
    exit 1
  fi
done

# ── 3. Install dependencies ───────────────────────────────────────────────────
if [ "$SKIP_INSTALL" = false ]; then
  info "Installing backend dependencies (uv sync)..."
  (cd backend && uv sync --all-extras)

  info "Installing frontend dependencies (npm install)..."
  (cd frontend && npm install)

  success "Dependencies installed."
else
  info "Skipping dependency install (--skip-install)."
fi

# ── 4. Database migrations ────────────────────────────────────────────────────
if [ "$SKIP_MIGRATE" = false ]; then
  info "Running database migrations (alembic upgrade head)..."
  (cd backend && uv run alembic upgrade head)
  success "Migrations applied."
else
  info "Skipping migrations (--skip-migrate)."
fi

# ── 5. Launch services ────────────────────────────────────────────────────────
LOG_DIR="$SCRIPT_DIR/.logs"
mkdir -p "$LOG_DIR"

info "Starting FastAPI backend (port 8000)..."
(cd backend && uv run uvicorn app.main:app --reload --port 8000) \
  > "$LOG_DIR/backend.log" 2>&1 &
PIDS+=($!)

info "Starting Celery worker..."
(cd backend && uv run celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2) \
  > "$LOG_DIR/worker.log" 2>&1 &
PIDS+=($!)

info "Starting frontend dev server (port 5173)..."
(cd frontend && npm run dev) \
  > "$LOG_DIR/frontend.log" 2>&1 &
PIDS+=($!)

# Give services a moment to start, then show status
sleep 3

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║        ReviewPulse is running!           ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║${NC}  Frontend:  ${CYAN}http://localhost:5173${NC}       ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  API:       ${CYAN}http://localhost:8000${NC}       ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}  API docs:  ${CYAN}http://localhost:8000/docs${NC}  ${GREEN}║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║${NC}  Logs:  ${YELLOW}.logs/backend.log${NC}             ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}         ${YELLOW}.logs/worker.log${NC}              ${GREEN}║${NC}"
echo -e "${GREEN}║${NC}         ${YELLOW}.logs/frontend.log${NC}            ${GREEN}║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║${NC}  Press ${RED}Ctrl+C${NC} to stop all services      ${GREEN}║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""

# Keep running until user presses Ctrl+C
wait
