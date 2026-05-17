from typing import Literal

from pydantic import BaseModel, Field


class ReviewAnalysis(BaseModel):
    """Structured output from an LLM analysis of a single book review.

    All fields map 1-to-1 onto Review model columns so the Celery task can
    unpack them without any translation layer.
    """

    sentiment: Literal["positive", "mixed", "negative"]
    sentiment_confidence: float = Field(ge=0.0, le=1.0)
    # Themes come from a controlled vocabulary defined in each adapter so that
    # both DeepSeek and Anthropic produce consistent tags across providers.
    themes: list[str] = Field(default_factory=list)
    is_ai_generated: bool
    ai_confidence: float = Field(ge=0.0, le=1.0)
    summary: str = Field(max_length=150)
    is_actionable: bool

    # These are populated by the adapter from the API response's usage object,
    # not by the LLM itself — models can't accurately self-report token counts.
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0


class DraftResponse(BaseModel):
    """AI-generated author response to a review (P1 feature)."""

    draft: str
    tone: str
    review_id: str = ""
