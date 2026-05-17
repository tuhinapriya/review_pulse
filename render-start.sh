#!/usr/bin/env bash
set -euo pipefail

cd backend

uv run alembic upgrade head

uv run celery -A app.tasks.celery_app worker --loglevel=info --concurrency=1 &
uv run celery -A app.tasks.celery_app beat --loglevel=info &

exec uv run uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
