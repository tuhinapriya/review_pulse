from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_author, get_db
from app.db.models import Author, Book, Review
from app.llm.client import get_llm_provider
from app.llm.schemas import DraftResponse
from app.schemas.common import DraftResponseRequest

router = APIRouter()


@router.post("/reviews/{review_id}/draft-response", response_model=DraftResponse)
async def draft_response(
    review_id: UUID,
    body: DraftResponseRequest,
    current_author: Annotated[Author, Depends(get_current_author)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DraftResponse:
    """Generate an AI-suggested author reply to a review (P1 feature).

    This is the feature not in the spec that I chose to add. Authors spend
    significant time crafting responses to negative or actionable reviews —
    a poor response can make things worse, a thoughtful one can recover the
    reader. AI-assisted drafts give authors a starting point that's specific
    to the review rather than a generic template, which they then personalise.

    Tone options: "professional" | "warm" | "concise"
    """
    # Verify the review belongs to a book owned by this author (tenant isolation)
    result = await db.execute(
        select(Review)
        .join(Book, Review.book_id == Book.id)
        .where(Review.id == review_id, Book.author_id == current_author.id)
    )
    review = result.scalar_one_or_none()

    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

    llm = get_llm_provider()
    draft = await llm.suggest_response(
        reviewer_name=review.reviewer_name,
        review_body=review.body,
        rating=review.rating,
        tone=body.tone,
    )
    draft.review_id = str(review_id)
    return draft
