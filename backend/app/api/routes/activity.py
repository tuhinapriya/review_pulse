from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_author, get_db
from app.db.models import Author
from app.services.activity import get_activity_since_last_login

router = APIRouter()


@router.get("/authors/{author_id}/activity")
async def get_activity(
    author_id: UUID,
    current_author: Annotated[Author, Depends(get_current_author)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Return the most important review activity since the author's last login (F8)."""
    if author_id != current_author.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return await get_activity_since_last_login(
        db=db,
        author_id=current_author.id,
        # previous_last_login_at is the time of the session before the current one.
        # Using it (rather than last_login_at) means the author sees reviews that
        # arrived since they last closed the dashboard, not just this session.
        since=current_author.previous_last_login_at,
    )
