from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_author, get_db
from app.db.models import Author
from app.schemas.common import CompareRequest
from app.services.trends import get_book_comparison

router = APIRouter()


@router.post("/books/compare")
async def compare_books(
    body: CompareRequest,
    current_author: Annotated[Author, Depends(get_current_author)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    """Side-by-side comparison of multiple books (F6).

    The get_book_comparison service enforces tenant isolation by joining
    through author_id — books belonging to other authors return no data
    rather than raising an error, so partial cross-tenant requests
    silently omit the unauthorized books.
    """
    if not body.book_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one book_id",
        )
    if len(body.book_ids) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Compare at most 10 books at a time",
        )

    book_uuids = [UUID(bid) for bid in body.book_ids]
    return await get_book_comparison(db, book_uuids, current_author.id)
