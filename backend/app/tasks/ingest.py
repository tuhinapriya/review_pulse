import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.logging import get_logger
from app.db.models import Book, IngestionJob, JobStatusEnum, Review
from app.llm.client import _concurrency_semaphore, get_embedding_provider, get_llm_provider
from app.llm.schemas import ReviewAnalysis
from app.services.webhooks import fire_webhooks
from app.tasks.celery_app import celery_app

log = get_logger()
REVIEWS_PER_INGEST = 10


def compute_external_id(book_id: str, reviewer_name: str, body: str) -> str:
    """Create a stable fingerprint for a review to prevent duplicate ingestion (F11).

    We hash all three fields together rather than using reviewer name alone.
    Hashing just the name would create false collisions if the same person
    reviews multiple books. Including the full body means an edited review
    generates a new record (showing up as a new review) rather than silently
    overwriting the original — which is the right behavior for a review tracker.
    """
    content = f"{book_id}:{reviewer_name}:{body}"
    return hashlib.sha256(content.encode()).hexdigest()


@celery_app.task(bind=True, max_retries=0)
def ingest_book_task(self, job_id: str) -> dict:
    """Ingest, analyze, and store reviews for a book.

    max_retries=0 because we handle errors at the individual-review level.
    A task-level retry would re-process all reviews from the start, wasting
    LLM budget on reviews that were already successfully analyzed.

    We use asyncio.run() because Celery workers are sync by default. Each
    task invocation gets a fresh event loop to avoid state leaks between tasks.
    """
    return asyncio.run(_ingest_book_async(job_id))


async def _ingest_book_async(job_id: str) -> dict:
    task_engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    task_session = async_sessionmaker(
        task_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with task_session() as db:
            return await _ingest_book_with_session(db, job_id)
    finally:
        await task_engine.dispose()


async def _ingest_book_with_session(db: AsyncSession, job_id: str) -> dict:
    job = await _get_job(db, UUID(job_id))
    if job is None:
        log.error("Job not found, cannot proceed", job_id=job_id)
        return {"status": "error", "message": "Job not found"}

    book = await _get_book(db, job.book_id)
    if book is None:
        log.error("Book not found for job", job_id=job_id, book_id=str(job.book_id))
        return {"status": "error"}

    job.status = JobStatusEnum.running
    job.started_at = datetime.now(UTC)
    await db.commit()

    log.info(
        "Ingest job started",
        job_id=job_id,
        book_id=str(book.id),
        book_title=book.title,
    )

    llm = get_llm_provider()
    embedder = get_embedding_provider()

    try:
        raw_reviews = await llm.generate_synthetic_reviews(
            book.title,
            count=REVIEWS_PER_INGEST,
        )
    except Exception as exc:
        log.error(
            "Synthetic review generation failed",
            job_id=job_id,
            error=str(exc),
            exc_info=True,
        )
        job.status = JobStatusEnum.failed
        job.error_message = f"Review generation failed: {exc}"
        job.completed_at = datetime.now(UTC)
        await db.commit()
        return {"status": "failed"}

    job.total_reviews = len(raw_reviews)
    await db.commit()
    log.info(
        "Synthetic reviews ready for processing",
        job_id=job_id,
        requested=REVIEWS_PER_INGEST,
        received=len(raw_reviews),
    )

    # Process reviews one at a time with this session. SQLAlchemy async sessions
    # are not safe for concurrent use; sharing one across gathered tasks can
    # make every review fail before anything is stored.
    for raw in raw_reviews:
        await _process_single_review(db, job, book, raw, llm, embedder)

    job.status = JobStatusEnum.completed if job.failed_reviews == 0 else JobStatusEnum.partial
    job.completed_at = datetime.now(UTC)
    await db.commit()

    log.info(
        "Ingest job completed",
        job_id=job_id,
        processed=job.processed_reviews,
        failed=job.failed_reviews,
        status=job.status.value,
    )

    await fire_webhooks(
        db=db,
        author_id=book.author_id,
        event="ingestion.completed",
        payload={
            "job_id": job_id,
            "book_id": str(book.id),
            "book_title": book.title,
            "processed_reviews": job.processed_reviews,
            "failed_reviews": job.failed_reviews,
            "status": job.status.value,
        },
    )

    return {"status": job.status.value, "processed": job.processed_reviews}


async def _process_single_review(
    db: AsyncSession,
    job: IngestionJob,
    book: Book,
    raw: dict,
    llm,
    embedder,
) -> None:
    """Analyze and persist a single review.

    Errors here are intentionally non-fatal — we log them and increment the
    failure counter so the job completes as "partial" rather than "failed".
    This design choice means a single flaky LLM response doesn't block an
    author from seeing the other 49 reviews.
    """
    async with _concurrency_semaphore:
        try:
            body = str(raw.get("body", "")).strip()
            reviewer_name = str(raw.get("reviewer_name", "Anonymous")).strip()
            rating = int(raw.get("rating", 3))

            external_id = compute_external_id(str(book.id), reviewer_name, body)

            # Dedup check — idempotent ingest means running the same job twice
            # produces the same number of reviews, never duplicates (F11).
            existing = await db.execute(
                select(Review.id).where(Review.external_id == external_id)
            )
            if existing.scalar_one_or_none() is not None:
                log.debug("Skipping duplicate review", external_id=external_id[:16])
                return

            review_date = _parse_date(raw.get("review_date", ""))

            analysis: ReviewAnalysis = await llm.analyze_review(
                body=body,
                rating=rating,
                book_title=book.title,
            )

            embedding = await embedder.generate_embedding(body)

            review = Review(
                book_id=book.id,
                external_id=external_id,
                reviewer_name=reviewer_name,
                rating=rating,
                body=body,
                review_date=review_date,
                sentiment=analysis.sentiment,
                sentiment_confidence=analysis.sentiment_confidence,
                themes=analysis.themes,
                is_ai_generated=analysis.is_ai_generated,
                ai_confidence=analysis.ai_confidence,
                summary=analysis.summary,
                is_actionable=analysis.is_actionable,
                embedding=embedding,
                tokens_used=analysis.tokens_input + analysis.tokens_output,
                cost_usd=analysis.cost_usd,
                analyzed_at=datetime.now(UTC),
            )
            db.add(review)
            await db.commit()

            # Increment counter immediately after each commit so polling clients
            # see live progress rather than waiting for the whole batch to finish.
            job.processed_reviews += 1
            await db.commit()

            log.info(
                "Review processed",
                job_id=str(job.id),
                external_id=external_id[:16],
                sentiment=analysis.sentiment,
                cost_usd=analysis.cost_usd,
            )

        except Exception as exc:
            log.error(
                "Failed to process review",
                job_id=str(job.id),
                book_id=str(book.id),
                step="analyze_and_store",
                error=str(exc),
                exc_info=True,
            )
            job.failed_reviews += 1
            await db.commit()


def _parse_date(date_str: str) -> datetime:
    """Parse ISO-8601 date from the LLM's synthetic review output.

    Falls back to the current time if the model returns a malformed date.
    A review with a slightly wrong date is better than failing the whole ingest.
    """
    try:
        return datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(UTC)


async def _get_job(db: AsyncSession, job_id: UUID) -> IngestionJob | None:
    result = await db.execute(select(IngestionJob).where(IngestionJob.id == job_id))
    return result.scalar_one_or_none()


async def _get_book(db: AsyncSession, book_id: UUID) -> Book | None:
    result = await db.execute(select(Book).where(Book.id == book_id))
    return result.scalar_one_or_none()
