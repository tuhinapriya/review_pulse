# ReviewPulse Architecture

ReviewPulse is a stateless web app plus durable background ingestion pipeline:

```text
React/Vite on Vercel
        |
        | HTTPS + Supabase JWT
        v
FastAPI on Render -------- Celery workers + Celery beat
        |                         |
        | async SQLAlchemy        | Redis broker
        v                         v
Supabase Postgres 16 + pgvector   Scheduled re-ingest
```

## Major Decisions

**Async ingestion with Celery.** `POST /books/{id}/ingest` returns `202` after creating an ingestion job and queueing work. The worker generates synthetic reviews, skips existing review hashes, analyzes new reviews, embeds them, stores costs/tokens, updates progress, and fires completion webhooks. Celery was chosen over in-process FastAPI background tasks because jobs can run 30-60 seconds and should survive web-worker restarts.

**Synthetic reviews, real pipeline.** The assignment allowed synthetic mode, so ingestion generates realistic structured reviews instead of scraping Amazon. The rest of the system is intentionally the same shape a real scraper/API feed would use: raw review text in, analysis/embedding/dedupe/storage out.

**Multi-tenant boundary in service queries.** `books.author_id` is the tenant boundary. Endpoints that touch books, reviews, jobs, trends, comparison, or search join through books and filter by the current author. I chose explicit service-layer checks over Postgres RLS because they are easy to audit in code review and straightforward with async connection pooling. The integration tests include a tenant-isolation bypass check; failure there should be treated as P0.

**Provider-agnostic LLM layer.** The backend depends on an `LLMProvider` interface with methods for review analysis, draft responses, embeddings, and synthetic reviews. DeepSeek is primary because it supports JSON-mode analysis and embeddings. Anthropic is secondary for structured analysis/drafting. Embeddings always use DeepSeek so vector similarity is not corrupted by mixing embedding spaces.

**Rate limits and partial success.** LLM calls are guarded by a semaphore, retried with exponential backoff and jitter, and logged with review/job context. Per-review failures are collected rather than aborting the whole job; a 47/50 ingest is marked `partial` and remains useful.

**pgvector IVFFlat.** Review embeddings live in Postgres next to relational review/book/author data. IVFFlat is the initial index because it is fast to build and memory-light for the expected demo scale. If this reached millions of vectors, I would switch to HNSW and tune `m`, `ef_construction`, and query-time `ef_search`.

**P1 feature: AI draft responses.** I added `POST /reviews/{id}/draft-response` because authors do not just need to read reviews; they need to decide whether and how to respond. Drafts are shown as editable starting points, not auto-sent replies.

**Webhook signing.** Completion webhooks use a Stripe-style HMAC payload:

```text
signature = HMAC-SHA256(subscription_secret, f"{timestamp}.{body}")
```

Receivers should reject timestamps outside a 5-minute replay window, recompute the digest, and compare with constant-time equality.

## Trade-Offs

| Choice | Upside | Cost / Next Step |
|---|---|---|
| Synthetic mode | Avoids scraping risk and keeps the demo reproducible | Replace generator with Amazon/review API adapter |
| Celery + Redis | Durable async work and scheduled refresh | More moving parts than one web process |
| Service-layer tenant checks | Obvious in code and easy to test | Add RLS before handling real customer data |
| Digest preview only | Shows product value without email plumbing | Add Resend/SendGrid and unsubscribe handling |
| Simple admin metrics endpoint | Enough to debug jobs/costs quickly | Add hosted logs/tracing for production |
