import asyncio
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Book, IngestionJob, JobStatusEnum
from app.db.session import AsyncSessionLocal
from app.tasks.celery_app import celery_app

log = get_logger()


@celery_app.task
def run_scheduled_reingest() -> dict:
    """Re-ingest books that haven't been refreshed recently (F9).

    Only re-ingests books whose most recent completed job is older than 1 hour,
    preventing a flood of jobs if beat fires multiple times in quick succession.

    Trade-off documented: We use Celery beat here because the backend already
    runs a Celery worker. On Render free tier, Render cron jobs would be a
    simpler alternative (no beat process to manage), but they can't inspect
    the DB to decide which books actually need refreshing.
    """
    return asyncio.run(_run_reingest_async())


async def _run_reingest_async() -> dict:
    # Import here to avoid circular import at module load time
    from app.tasks.ingest import ingest_book_task

    async with AsyncSessionLocal() as db:
        stale_books = await _get_stale_books(db)
        dispatched = 0

        for book in stale_books:
            job = IngestionJob(
                book_id=book.id,
                status=JobStatusEnum.queued,
                created_at=datetime.now(timezone.utc),
            )
            db.add(job)
            await db.commit()
            await db.refresh(job)

            ingest_book_task.delay(str(job.id))
            dispatched += 1
            log.info("Scheduled reingest dispatched", book_id=str(book.id), job_id=str(job.id))

        return {"dispatched": dispatched}


async def _get_stale_books(db: AsyncSession) -> list[Book]:
    """Return books whose last completed ingest was more than 1 hour ago."""
    stale_threshold = datetime.now(timezone.utc) - timedelta(hours=1)

    result = await db.execute(
        select(Book).where(
            ~Book.id.in_(
                select(IngestionJob.book_id).where(
                    IngestionJob.status == JobStatusEnum.completed,
                    IngestionJob.completed_at >= stale_threshold,
                )
            )
        )
    )
    return list(result.scalars().all())
