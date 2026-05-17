from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_author, get_db
from app.db.models import Author, Book, IngestionJob
from app.schemas.job import JobResponse

router = APIRouter()


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job_status(
    job_id: UUID,
    current_author: Annotated[Author, Depends(get_current_author)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IngestionJob:
    """Poll ingest job progress (F2).

    The job record is updated after each review is processed, so polling
    clients see incremental progress (processed_reviews counts up in real time)
    rather than waiting for the entire batch to complete.
    """
    result = await db.execute(
        select(IngestionJob).where(IngestionJob.id == job_id)
    )
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    # Verify the job belongs to the requesting author via the book → author chain.
    # This prevents author B from polling author A's job status.
    book_result = await db.execute(
        select(Book).where(Book.id == job.book_id, Book.author_id == current_author.id)
    )
    if book_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return job
