import json

from anthropic import AsyncAnthropic

from app.config import settings
from app.core.logging import get_logger
from app.llm.base import LLMProvider
from app.llm.deepseek import THEME_VOCABULARY  # share the same vocabulary across providers
from app.llm.schemas import DraftResponse, ReviewAnalysis

log = get_logger()

# Haiku is the cheapest Claude model — good enough for classification/extraction
# tasks and fast enough to keep ingest times reasonable.
_ANALYSIS_MODEL = "claude-3-haiku-20240307"


class AnthropicProvider(LLMProvider):
    """LLM provider backed by Anthropic's Claude API.

    Uses tool-calling (forced tool use) to get guaranteed structured JSON output.
    This is more reliable than prompting for JSON alone — Claude occasionally
    wraps output in markdown fences or adds explanatory prose before the JSON.
    Forcing a tool call means we always get a clean dict to parse.
    """

    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def analyze_review(
        self,
        body: str,
        rating: int,
        book_title: str,
    ) -> ReviewAnalysis:
        tool = {
            "name": "save_review_analysis",
            "description": "Save the structured analysis of a book review",
            "input_schema": {
                "type": "object",
                "properties": {
                    "sentiment": {
                        "type": "string",
                        "enum": ["positive", "mixed", "negative"],
                    },
                    "sentiment_confidence": {"type": "number"},
                    "themes": {
                        "type": "array",
                        "items": {"type": "string", "enum": THEME_VOCABULARY},
                        "maxItems": 5,
                    },
                    "is_ai_generated": {"type": "boolean"},
                    "ai_confidence": {"type": "number"},
                    "summary": {"type": "string"},
                    "is_actionable": {"type": "boolean"},
                },
                "required": [
                    "sentiment",
                    "sentiment_confidence",
                    "themes",
                    "is_ai_generated",
                    "ai_confidence",
                    "summary",
                    "is_actionable",
                ],
            },
        }

        response = await self._client.messages.create(
            model=_ANALYSIS_MODEL,
            max_tokens=500,
            tools=[tool],
            # Forcing the specific tool ensures we always get structured data
            # and never a free-text response that we'd need to parse.
            tool_choice={"type": "tool", "name": "save_review_analysis"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        f'Analyze this {rating}/5 star review of "{book_title}":\n\n{body}'
                    ),
                }
            ],
        )

        tool_block = next(b for b in response.content if b.type == "tool_use")
        data = tool_block.input
        usage = response.usage
        cost = _compute_cost_anthropic(usage.input_tokens, usage.output_tokens)

        return ReviewAnalysis(
            sentiment=data["sentiment"],
            sentiment_confidence=float(data.get("sentiment_confidence", 0.8)),
            themes=data.get("themes", [])[:5],
            is_ai_generated=bool(data.get("is_ai_generated", False)),
            ai_confidence=float(data.get("ai_confidence", 0.5)),
            summary=str(data.get("summary", ""))[:150],
            is_actionable=bool(data.get("is_actionable", False)),
            tokens_input=usage.input_tokens,
            tokens_output=usage.output_tokens,
            cost_usd=cost,
        )

    async def suggest_response(
        self,
        reviewer_name: str,
        review_body: str,
        rating: int,
        tone: str = "warm",
    ) -> DraftResponse:
        tone_guide = {
            "professional": "formal and business-like",
            "warm": "genuine, personal, and appreciative",
            "concise": "under 3 sentences, direct and clear",
        }

        response = await self._client.messages.create(
            model=_ANALYSIS_MODEL,
            max_tokens=350,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Write a {tone_guide.get(tone, 'warm')} author response to this "
                        f"{rating}/5-star review from {reviewer_name}:\n\n"
                        f'"{review_body}"\n\n'
                        "Requirements: reference specific details from the review, "
                        "stay under 150 words, avoid defensiveness about criticism."
                    ),
                }
            ],
        )

        return DraftResponse(
            draft=response.content[0].text.strip(),
            tone=tone,
        )

    async def generate_embedding(self, text: str) -> list[float]:
        # Anthropic doesn't expose an embedding API. The provider factory
        # always routes embedding requests to DeepSeek regardless of which
        # provider is used for analysis — so this path should never be called.
        raise NotImplementedError(
            "Anthropic does not provide an embedding API. "
            "Ensure DEEPSEEK_API_KEY is set — embeddings always use DeepSeek."
        )

    async def generate_synthetic_reviews(
        self,
        book_title: str,
        count: int,
    ) -> list[dict]:
        response = await self._client.messages.create(
            model=_ANALYSIS_MODEL,
            max_tokens=8000,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f'Generate {count} realistic Amazon book reviews for "{book_title}" '
                        'as a JSON array. Each element: '
                        '{"reviewer_name": str, "rating": 1-5, "body": "50-250 words", '
                        '"review_date": "ISO-8601 date"}. '
                        "Mix sentiments naturally (~60% positive, ~25% mixed, ~15% negative). "
                        "Return only the JSON array."
                    ),
                }
            ],
        )

        text = response.content[0].text.strip()

        # Strip markdown fences that Claude sometimes adds even when instructed not to
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1].lstrip("json").strip()

        raw = json.loads(text)
        if isinstance(raw, list):
            return raw
        for value in raw.values():
            if isinstance(value, list):
                return value
        return []


def _compute_cost_anthropic(tokens_in: int, tokens_out: int) -> float:
    cost = (
        tokens_in * settings.anthropic_input_price_per_million / 1_000_000
        + tokens_out * settings.anthropic_output_price_per_million / 1_000_000
    )
    return round(cost, 8)
