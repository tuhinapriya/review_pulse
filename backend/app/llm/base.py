from abc import ABC, abstractmethod

from app.llm.schemas import DraftResponse, ReviewAnalysis


class LLMProvider(ABC):
    """Abstract interface for all LLM providers.

    The whole point of this layer is that swapping from DeepSeek to Anthropic
    requires only changing the LLM_PROVIDER env var — no business logic changes.
    Two concrete implementations live below: DeepSeekProvider (primary) and
    AnthropicProvider (secondary). Both satisfy this interface.

    Embedding is treated separately because not every provider offers it.
    The factory (client.py) always routes embedding requests to DeepSeek,
    regardless of which provider is used for analysis.
    """

    @abstractmethod
    async def analyze_review(
        self,
        body: str,
        rating: int,
        book_title: str,
    ) -> ReviewAnalysis:
        """Extract structured insights from a review text.

        The returned ReviewAnalysis includes token counts and cost so every
        analysis call is tracked from the start (N3 cost-tracking requirement).
        """
        ...

    @abstractmethod
    async def suggest_response(
        self,
        reviewer_name: str,
        review_body: str,
        rating: int,
        tone: str,
    ) -> DraftResponse:
        """Generate a draft author reply to a review (P1 feature).

        The draft should reference specific details from the review rather
        than being a generic template response — authors can tell the difference.
        """
        ...

    @abstractmethod
    async def generate_embedding(self, text: str) -> list[float]:
        """Produce a dense vector embedding for semantic search (F4).

        The returned vector's length must match EMBEDDING_DIM in config,
        which in turn must match the vector(N) column dimension in Postgres.
        A mismatch causes pgvector to reject the insert with a type error.
        """
        ...

    @abstractmethod
    async def generate_synthetic_reviews(
        self,
        book_title: str,
        count: int,
    ) -> list[dict]:
        """Generate realistic fake reviews for database seeding.

        We use synthetic reviews so the demo requires no real Amazon scraping.
        Returns a list of dicts: {reviewer_name, rating, body, review_date}.
        """
        ...
