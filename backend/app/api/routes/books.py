from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_author, get_db
from app.db.models import Author, Book, IngestionJob, JobStatusEnum
from app.schemas.book import BookCreate, BookResponse
from app.schemas.job import JobResponse

router = APIRouter()


@router.post("/books", response_model=BookResponse, status_code=status.HTTP_201_CREATED)
async def add_book(
    book_in: BookCreate,
    current_author: Annotated[Author, Depends(get_current_author)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Book:
    """Add a book to the author's catalog (F1)."""
    book = Book(
        author_id=current_author.id,
        title=book_in.title,
        isbn=book_in.isbn,
        url=book_in.url,
        created_at=datetime.now(timezone.utc),
    )
    db.add(book)
    await db.commit()
    await db.refresh(book)
    return book


@router.post(
    "/books/{book_id}/ingest",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_ingest(
    book_id: UUID,
    current_author: Annotated[Author, Depends(get_current_author)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IngestionJob:
    """Queue a background ingestion job for a book (F1, F2).

    Returns 202 Accepted immediately with the job ID. The client polls
    GET /jobs/{job_id} to track progress. This decoupling means the HTTP
    response never blocks on LLM analysis time — essential for the N1
    sub-60s goal where ingest runs async while the dashboard loads.
    """
    result = await db.execute(
        select(Book).where(Book.id == book_id, Book.author_id == current_author.id)
    )
    book = result.scalar_one_or_none()
    if book is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")

    job = IngestionJob(
        book_id=book_id,
        status=JobStatusEnum.queued,
        created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Lazy import to avoid circular dependency at module load time
    from app.tasks.ingest import ingest_book_task
    ingest_book_task.delay(str(job.id))

    return job
