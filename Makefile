.PHONY: install run-backend run-worker run-beat run-frontend migrate test docker-up docker-down seed

install:
	cd backend && uv sync --all-extras
	cd frontend && npm install

docker-up:
	docker compose up -d

docker-down:
	docker compose down

migrate:
	cd backend && alembic upgrade head

run-backend:
	cd backend && uvicorn app.main:app --reload --port 8000

run-worker:
	cd backend && celery -A app.tasks.celery_app worker --loglevel=info --concurrency=4

run-beat:
	cd backend && celery -A app.tasks.celery_app beat --loglevel=info

run-frontend:
	cd frontend && npm run dev

test:
	cd backend && pytest tests/ -v --tb=short

test-unit:
	cd backend && pytest tests/unit/ -v

test-integration:
	cd backend && pytest tests/integration/ -v

lint:
	cd backend && ruff check app/ tests/

# Full local dev setup from scratch
dev-setup: docker-up
	sleep 3
	$(MAKE) migrate
	@echo "✓ Ready. Run 'make run-backend' and 'make run-worker' in separate terminals."
