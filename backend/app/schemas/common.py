from pydantic import BaseModel


class SearchRequest(BaseModel):
    query: str
    k: int | None = 10  # number of results; capped at 50 in the route handler


class SearchResult(BaseModel):
    review_id: str
    book_id: str
    book_title: str
    reviewer_name: str
    body: str
    similarity: float
    sentiment: str | None
    rating: int | None


class WebhookCreate(BaseModel):
    url: str
    events: list[str] = ["ingestion.completed"]


class WebhookResponse(BaseModel):
    id: str
    url: str
    events: list[str]
    created_at: str


class CompareRequest(BaseModel):
    book_ids: list[str]


class DraftResponseRequest(BaseModel):
    tone: str = "warm"  # "professional" | "warm" | "concise"
