from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_author, get_db
from app.db.models import Author, Book, Review, SentimentEnum
from app.schemas.review import ReviewListResponse, ReviewResponse

router = APIRouter()

# Valid sort options and their SQLAlchemy column expressions
_SORT_MAP = {
    "review_date_desc": Review.review_date.desc(),
    "review_date_asc": Review.review_date.asc(),
    "rating_desc": Review.rating.desc(),
    "rating_asc": Review.rating.asc(),
}


@router.get("/books/{book_id}/reviews", response_model=ReviewListResponse)
async def list_reviews(
    book_id: UUID,
    current_author: Annotated[Author, Depends(get_current_author)],
    db: Annotated[AsyncSession, Depends(get_db)],
    sentiment: str | None = Query(default=None),
    ai_flagged: bool | None = Query(default=None),
    actionable: bool | None = Query(default=None),
    theme: str | None = Query(default=None),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    sort: str = Query(default="review_date_desc"),
) -> ReviewListResponse:
    """List reviews for a book with filtering, sorting, and pagination (F3)."""
    # Verify book ownership — tenant isolation
    book_result = await db.execute(
        select(Book).where(Book.id == book_id, Book.author_id == current_author.id)
    )
    if book_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")

    # Build filter conditions dynamically so we only add clauses that were
    # actually requested — avoids full-table scans with WHERE 1=1 style patterns.
    conditions = [Review.book_id == book_id]

    if sentiment is not None:
        conditions.append(Review.sentiment == sentiment)
    if ai_flagged is not None:
        conditions.append(Review.is_ai_generated == ai_flagged)
    if actionable is not None:
        conditions.append(Review.is_actionable == actionable)
    if theme is not None:
        # ARRAY contains operator — finds reviews with this specific theme tag
        conditions.append(Review.themes.contains([theme]))
    if from_date is not None:
        conditions.append(Review.review_date >= from_date)
    if to_date is not None:
        conditions.append(Review.review_date <= to_date)

    order_clause = _SORT_MAP.get(sort, Review.review_date.desc())

    # Get total count for pagination metadata
    count_result = await db.execute(
        select(func.count()).select_from(Review).where(and_(*conditions))
    )
    total = count_result.scalar_one()

    offset = (page - 1) * per_page
    reviews_result = await db.execute(
        select(Review)
        .where(and_(*conditions))
        .order_by(order_clause)
        .offset(offset)
        .limit(per_page)
    )
    reviews = reviews_result.scalars().all()

    return ReviewListResponse(
        items=[ReviewResponse.model_validate(r) for r in reviews],
        total=total,
        page=page,
        per_page=per_page,
        has_next=(offset + len(reviews)) < total,
    )
