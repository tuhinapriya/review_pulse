# ReviewPulse

ReviewPulse is a review-intelligence dashboard for independent authors. It ingests book reviews asynchronously, analyzes sentiment/themes/actionability with an LLM, stores embeddings in Postgres/pgvector, and gives authors catalog, per-book, search, comparison, digest, and "what's new" views.

Built for the Tweeds full-stack take-home with the stack they called out: **FastAPI, SQLAlchemy 2.0, Celery, Redis, Postgres/pgvector, React, TypeScript, Vite, and Tailwind**.

## What Works

- Author registration/login with Supabase Auth JWTs.
- Multi-book catalog, per-book review deep dives, filters, trend metrics, and cross-book comparison.
- Async ingestion jobs with queued/running/completed/failed/partial status.
- Idempotent synthetic review ingestion with SHA-256 dedupe.
- LLM adapter layer with DeepSeek primary and Anthropic fallback for analysis; embeddings stay on DeepSeek.
- Semantic search scoped to the signed-in author's catalog.
- Cost tracking, structured logs, admin metrics, signed completion webhooks, and weekly digest preview.
- Unit tests for analysis/auth/cost/trend logic and integration tests for ingest and tenant isolation.

## Local Setup

Prerequisites:

- Docker and Docker Compose
- Python 3.12+ with `uv`
- Node.js 20+ with npm
- Supabase project credentials
- DeepSeek API key; Anthropic key is optional unless `LLM_PROVIDER=anthropic`

```bash
git clone <repo-url>
cd review_pulse
cp .env.example .env
```

Fill in `.env`. The local `.env` file is intentionally ignored by git.

Start Postgres and Redis:

```bash
make docker-up
```

Install dependencies and run migrations:

```bash
make install
make migrate
```

Run the app in separate terminals:

```bash
make run-backend   # FastAPI: http://localhost:8000
make run-worker    # Celery ingest worker
make run-beat      # optional scheduled re-ingest
make run-frontend  # Vite: http://localhost:5173
```

Open [http://localhost:5173](http://localhost:5173), register an author, add a book, and trigger ingestion.

## Environment

| Variable | Required | Notes |
|---|---:|---|
| `DATABASE_URL` | yes | Local default: `postgresql+asyncpg://reviewpulse:reviewpulse@localhost:5432/reviewpulse` |
| `REDIS_URL` | yes | Local default: `redis://localhost:6379/0` |
| `SUPABASE_URL` | yes | Supabase project URL |
| `SUPABASE_ANON_KEY` | yes | Public anon key |
| `SUPABASE_SERVICE_KEY` | yes by default | Used for dev-friendly server-side signup when `USE_SUPABASE_ADMIN_SIGNUP=true` |
| `SUPABASE_JWT_SECRET` | yes | Used for local JWT verification |
| `LLM_PROVIDER` | yes | `deepseek` or `anthropic` |
| `DEEPSEEK_API_KEY` | yes | Required for embeddings and DeepSeek analysis |
| `ANTHROPIC_API_KEY` | provider-dependent | Required only when `LLM_PROVIDER=anthropic` |
| `EMBEDDING_DIM` | yes | Keep at `1024` unless the migration changes too |
| `ADMIN_TOKEN` | yes | Protects `GET /api/v1/admin/metrics` |
| `CORS_ORIGINS` | deploy-dependent | Comma-separated allowed frontend origins |

## Tests

```bash
make test             # all backend tests
make test-unit        # fast tests
make test-integration # requires docker-up + migrate
```

## API Map

Base URL: `http://localhost:8000/api/v1`

All endpoints except registration/login require `Authorization: Bearer <jwt>`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/register` | Create an author account |
| `POST` | `/login` | Sign in and return a JWT |
| `GET` | `/authors/me` | Current author profile |
| `GET` | `/authors/me/books` | Catalog with aggregate stats |
| `POST` | `/books` | Add a book |
| `POST` | `/books/{id}/ingest` | Queue async review ingestion |
| `GET` | `/jobs/{id}` | Poll ingestion status |
| `GET` | `/books/{id}/reviews` | Paginated reviews with filters |
| `GET` | `/books/{id}/trends` | Sentiment/theme trends |
| `POST` | `/books/compare` | Cross-book comparison |
| `POST` | `/search` | Semantic search across the author's catalog |
| `GET` | `/authors/{id}/activity` | What's new since last login |
| `GET` | `/authors/{id}/digest` | Weekly digest preview |
| `POST` | `/reviews/{id}/draft-response` | P1 feature: AI-drafted author reply |
| `POST` | `/webhooks` | Register signed ingestion-complete webhooks |
| `GET` | `/admin/metrics` | Observability panel data |
| `GET` | `/health` | Service health check |

## Deployment

- Backend: Render reads `render.yaml`.
- Frontend: Vercel reads `frontend/vercel.json`.
- Database: Supabase Postgres with the `vector` extension enabled.
- Set `VITE_API_URL` in Vercel to the deployed backend URL.
- Set backend env vars in Render; do not commit `.env`.

## Design Notes

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the compact architecture walkthrough: async ingest, tenant boundary, LLM adapter, pgvector choice, webhook signing, and key trade-offs.
