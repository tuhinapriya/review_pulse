from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ReviewResponse(BaseModel):
    id: UUID
    book_id: UUID
    reviewer_name: str
    rating: int
    body: str
    review_date: datetime
    sentiment: str | None
    sentiment_confidence: float | None
    themes: list[str] | None
    is_ai_generated: bool | None
    ai_confidence: float | None
    summary: str | None
    is_actionable: bool | None
    tokens_used: int | None
    cost_usd: float | None
    analyzed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReviewListParams(BaseModel):
    """Query parameters for the review listing endpoint (F3)."""
    sentiment: str | None = None
    ai_flagged: bool | None = None
    actionable: bool | None = None
    theme: str | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None
    page: int = 1
    per_page: int = 20
    sort: str = "review_date_desc"  # review_date_desc | review_date_asc | rating_desc | rating_asc


class ReviewListResponse(BaseModel):
    items: list[ReviewResponse]
    total: int
    page: int
    per_page: int
    has_next: bool
