import hashlib
import json
import math
import re
from datetime import UTC, datetime, timedelta

from openai import APIStatusError, AsyncOpenAI, NotFoundError

from app.config import settings
from app.core.logging import get_logger
from app.llm.base import LLMProvider
from app.llm.schemas import DraftResponse, ReviewAnalysis

log = get_logger()

# DeepSeek exposes an OpenAI-compatible REST API, so the openai SDK works
# verbatim with just a base_url override. This also means this adapter doubles
# as a template for any OpenAI-compatible provider (Groq, Together, Fireworks).
_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_ANALYSIS_MODEL = "deepseek-chat"
_EMBEDDING_MODEL = "deepseek-embedding"
_embedding_remote_available = True

# Controlled vocabulary for themes. Keeping this list explicit prevents the LLM
# from inventing synonyms ("narrative pace" vs "pacing") that would fragment
# theme analytics into near-duplicate buckets.
THEME_VOCABULARY = [
    "pacing",
    "characters",
    "plot",
    "ending",
    "writing_style",
    "cover",
    "narration",
    "world_building",
    "dialogue",
    "price",
    "length",
    "emotional_impact",
    "accuracy",
    "humor",
]

_ANALYSIS_SYSTEM_PROMPT = f"""You are an expert book review analyst. Analyze the review and
return a JSON object with exactly these fields:
{{
  "sentiment": "positive" | "mixed" | "negative",
  "sentiment_confidence": <float 0-1>,
  "themes": ["theme1", ...],
  "is_ai_generated": <bool>,
  "ai_confidence": <float 0-1>,
  "summary": "<one sentence, max 120 chars>",
  "is_actionable": <bool>
}}

themes must come from this list only: {", ".join(THEME_VOCABULARY)}
is_actionable = true if the author could meaningfully respond to or act on this review.
Return only valid JSON — no markdown fences, no extra keys."""


class DeepSeekProvider(LLMProvider):
    """LLM provider backed by DeepSeek's API.

    Uses the openai SDK with a base_url override — no separate DeepSeek SDK
    needed. The adapter is intentionally thin so swapping the base_url to
    any other OpenAI-compatible endpoint (Groq, Together, etc.) requires
    only changing config constants.
    """

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=_DEEPSEEK_BASE_URL,
        )

    async def analyze_review(
        self,
        body: str,
        rating: int,
        book_title: str,
    ) -> ReviewAnalysis:
        response = await self._client.chat.completions.create(
            model=_ANALYSIS_MODEL,
            messages=[
                {"role": "system", "content": _ANALYSIS_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f'Book: "{book_title}"\nRating: {rating}/5\nReview:\n{body}',
                },
            ],
            response_format={"type": "json_object"},
            # Low temperature for consistent structured output — we don't want
            # creative variation in a classification/extraction task.
            temperature=0.1,
        )

        data = json.loads(response.choices[0].message.content)
        usage = response.usage
        cost = _compute_cost(usage.prompt_tokens, usage.completion_tokens, settings)

        # Clamp confidence values to [0, 1] — the LLM occasionally returns
        # values like 0.95000001 or even numbers > 1 due to floating-point
        # noise. Clamping here is safer than relying on Pydantic's ge/le
        # constraint (which raises ValidationError rather than silently fixing).
        s_conf = max(0.0, min(1.0, float(data.get("sentiment_confidence", 0.8))))
        ai_conf = max(0.0, min(1.0, float(data.get("ai_confidence", 0.5))))

        # Filter themes against the controlled vocabulary — ignore any term the
        # LLM invented that isn't in our predefined set.
        raw_themes = data.get("themes", [])
        filtered_themes = [t for t in raw_themes if t in THEME_VOCABULARY][:5]

        return ReviewAnalysis(
            sentiment=data["sentiment"],
            sentiment_confidence=s_conf,
            themes=filtered_themes,
            is_ai_generated=bool(data.get("is_ai_generated", False)),
            ai_confidence=ai_conf,
            summary=str(data.get("summary", ""))[:150],
            is_actionable=bool(data.get("is_actionable", False)),
            tokens_input=usage.prompt_tokens,
            tokens_output=usage.completion_tokens,
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
            "professional": "formal and business-like, appropriate for a public response",
            "warm": (
                "genuine, personal, and appreciative — write like a real person, "
                "not a PR department"
            ),
            "concise": "3 sentences max, direct and clear",
        }

        prompt = f"""Help an author write a reply to this {rating}/5-star review
from {reviewer_name}:

"{review_body}"

Tone: {tone_guide.get(tone, tone_guide['warm'])}

Rules:
- Reference at least one specific detail from the review (not generic)
- Stay under 150 words
- Don't be defensive about criticism
- If it's a positive review, be genuine rather than just saying "thank you"
- End with an invitation to continue the conversation if appropriate"""

        response = await self._client.chat.completions.create(
            model=_ANALYSIS_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.7,
        )

        return DraftResponse(
            draft=response.choices[0].message.content.strip(),
            tone=tone,
        )

    async def generate_embedding(self, text: str) -> list[float]:
        global _embedding_remote_available

        # Truncate to avoid token limit errors on very long review bodies.
        # DeepSeek's embedding model has a context limit; 32K characters is
        # a safe ceiling that covers any realistic review text.
        truncated = text[:32_000]

        if not _embedding_remote_available:
            return _local_embedding(truncated, settings.embedding_dim)

        try:
            response = await self._client.embeddings.create(
                model=_EMBEDDING_MODEL,
                input=truncated,
            )
            return response.data[0].embedding
        except (NotFoundError, APIStatusError) as exc:
            if getattr(exc, "status_code", None) != 404:
                raise
            _embedding_remote_available = False
            log.warning(
                "DeepSeek embedding endpoint unavailable; using local deterministic embeddings",
                model=_EMBEDDING_MODEL,
                status_code=404,
                embedding_dim=settings.embedding_dim,
            )
            return _local_embedding(truncated, settings.embedding_dim)

    async def generate_synthetic_reviews(
        self,
        book_title: str,
        count: int,
    ) -> list[dict]:
        """Generate realistic synthetic reviews in a single API call.

        We batch all reviews into one request to minimise API calls. Keeping
        this batch small makes the JSON output much more reliable.

        json_object mode requires returning an object, not an array, so we
        ask for {"reviews": [...]} and unwrap it.
        """
        prompt = f"""Generate exactly {count} realistic Amazon-style book reviews
for "{book_title}".

Return only valid JSON in exactly this shape:
{{
  "reviews": [
    {{
      "reviewer_name": "realistic person's full name",
      "rating": 1,
      "body": "50-250 words of review text",
      "review_date": "YYYY-MM-DD"
    }}
  ]
}}

Rules:
- The "reviews" array must contain exactly {count} objects.
- Do not include markdown fences, comments, explanations, or additional top-level keys.
- "rating" must be an integer from 1 to 5.
- "review_date" must be an ISO date string, spread randomly over the last 24 months.

Sentiment distribution: ~60% positive (4-5 stars), ~25% mixed (3 stars), ~15% negative (1-2 stars).
Make reviews feel authentic — vary sentence length, vocabulary level, and what reviewers focus on.
Some should mention specific story details; some should be short and blunt."""

        response = await self._client.chat.completions.create(
            model=_ANALYSIS_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=8000,
            # High temperature for variety — we want diverse, realistic reviews,
            # not repetitive ones that would make the demo look fake.
            temperature=0.9,
        )

        raw = json.loads(response.choices[0].message.content)
        reviews = _normalize_synthetic_reviews(raw, count)
        log.info(
            "Synthetic reviews generated",
            requested_count=count,
            returned_count=len(reviews),
            wrapper_keys=list(raw.keys()) if isinstance(raw, dict) else None,
        )
        return reviews


def _normalize_synthetic_reviews(raw: object, count: int) -> list[dict]:
    """Validate and normalize the one-call synthetic review response."""
    if not isinstance(raw, dict) or set(raw.keys()) != {"reviews"}:
        raise ValueError('Synthetic review response must be an object with only a "reviews" key')

    reviews = raw.get("reviews")
    if not isinstance(reviews, list):
        raise ValueError('Synthetic review response "reviews" must be an array')
    if len(reviews) != count:
        raise ValueError(
            f"Synthetic review response returned {len(reviews)} reviews, expected {count}"
        )

    normalized: list[dict] = []
    for idx, item in enumerate(reviews):
        if not isinstance(item, dict):
            raise ValueError(f"Synthetic review #{idx + 1} must be an object")

        reviewer_name = str(item.get("reviewer_name", "")).strip()
        body = str(item.get("body", "")).strip()
        if not reviewer_name:
            raise ValueError(f"Synthetic review #{idx + 1} is missing reviewer_name")
        if not body:
            raise ValueError(f"Synthetic review #{idx + 1} is missing body")

        try:
            rating = int(item.get("rating"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Synthetic review #{idx + 1} rating must be an integer") from exc
        if rating < 1 or rating > 5:
            raise ValueError(f"Synthetic review #{idx + 1} rating must be between 1 and 5")

        review_date = _normalize_review_date(item.get("review_date"))
        normalized.append(
            {
                "reviewer_name": reviewer_name,
                "rating": rating,
                "body": body,
                "review_date": review_date,
            }
        )

    return normalized


def _normalize_review_date(value: object) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        parsed = datetime.now(UTC)
    oldest = datetime.now(UTC) - timedelta(days=730)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if parsed > datetime.now(UTC) or parsed < oldest:
        parsed = datetime.now(UTC)
    return parsed.date().isoformat()


def _local_embedding(text: str, dimensions: int) -> list[float]:
    """Return a deterministic fallback vector when remote embeddings are unavailable."""
    vector = [0.0] * dimensions
    tokens = re.findall(r"[a-z0-9']+", text.lower()) or [text[:256].lower()]
    for token in tokens:
        digest = hashlib.sha256(token.encode()).digest()
        idx = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        weight = 1.0 + digest[5] / 255.0
        vector[idx] += sign * weight

    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [round(value / norm, 6) for value in vector]


def _compute_cost(tokens_in: int, tokens_out: int, cfg: object) -> float:
    """Calculate USD cost for a DeepSeek API call.

    Tracked per-review so the dashboard can show granular spend data (N3).
    Rounded to 8 decimal places to avoid floating-point accumulation errors
    when summing thousands of reviews.
    """
    cost = (
        tokens_in * cfg.deepseek_input_price_per_million / 1_000_000
        + tokens_out * cfg.deepseek_output_price_per_million / 1_000_000
    )
    return round(cost, 8)
