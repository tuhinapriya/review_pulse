from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class BookCreate(BaseModel):
    title: str
    isbn: str | None = None
    url: str | None = None


class BookResponse(BaseModel):
    id: UUID
    author_id: UUID
    title: str
    isbn: str | None
    url: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BookWithStats(BookResponse):
    """Book response enriched with aggregated review metrics for catalog view."""
    review_count: int = 0
    avg_rating: float | None = None
    positive_pct: float | None = None
    total_cost_usd: float | None = None
    last_ingested_at: datetime | None = None
