from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_author, get_db
from app.db.models import Author
from app.services.digest import build_weekly_digest

router = APIRouter()


@router.get("/authors/me/digest")
async def get_my_digest(
    current_author: Annotated[Author, Depends(get_current_author)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    return await build_weekly_digest(db=db, author_id=current_author.id)


@router.get("/authors/{author_id}/digest")
async def get_digest(
    author_id: UUID,
    current_author: Annotated[Author, Depends(get_current_author)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Build and return the weekly digest preview (F10).

    Returns the data structure that the weekly email would render from.
    No real email is sent here — the frontend renders a preview that shows
    what the author would receive in their inbox.
    """
    if author_id != current_author.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return await build_weekly_digest(db=db, author_id=current_author.id)
