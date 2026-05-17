from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_author, get_db
from app.db.models import Author, Book
from app.services.trends import get_sentiment_trends

router = APIRouter()


@router.get("/books/{book_id}/trends")
async def get_trends(
    book_id: UUID,
    current_author: Annotated[Author, Depends(get_current_author)],
    db: Annotated[AsyncSession, Depends(get_db)],
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
) -> dict:
    """Weekly sentiment time-series and theme frequency for a book (F5)."""
    result = await db.execute(
        select(Book).where(Book.id == book_id, Book.author_id == current_author.id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")

    return await get_sentiment_trends(db, book_id, from_date, to_date)
