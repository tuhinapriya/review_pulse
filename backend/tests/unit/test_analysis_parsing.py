"""
Unit tests for ReviewAnalysis JSON parsing and error handling.

These tests validate that the DeepSeek provider correctly parses
LLM output into structured ReviewAnalysis objects, and that
malformed or boundary-case responses are handled gracefully.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm.deepseek import DeepSeekProvider
from app.llm.schemas import ReviewAnalysis


def _make_valid_analysis_json(**overrides) -> str:
    """Return a minimal valid analysis JSON string matching the LLM output format."""
    base = {
        "sentiment": "positive",
        "sentiment_confidence": 0.92,
        "themes": ["pacing", "characters"],
        "is_ai_generated": False,
        "ai_confidence": 0.08,
        "summary": "Excellent world-building kept me reading.",
        "is_actionable": False,
    }
    return json.dumps({**base, **overrides})


class TestAnalysisParsing:
    """DeepSeek provider correctly maps LLM JSON output to ReviewAnalysis."""

    def _make_openai_response(self, content: str) -> MagicMock:
        """Construct a mock that mirrors the openai ChatCompletion structure."""
        msg = MagicMock()
        msg.content = content
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        resp.usage.prompt_tokens = 100
        resp.usage.completion_tokens = 60
        return resp

    @pytest.mark.asyncio
    async def test_parses_positive_sentiment(self):
        provider = DeepSeekProvider.__new__(DeepSeekProvider)
        provider._client = MagicMock()
        provider._client.chat.completions.create = AsyncMock(
            return_value=self._make_openai_response(_make_valid_analysis_json(sentiment="positive"))
        )

        result = await provider.analyze_review(
            body="Loved it!",
            rating=5,
            book_title="Test Book",
        )

        assert isinstance(result, ReviewAnalysis)
        assert result.sentiment == "positive"
        assert result.sentiment_confidence == 0.92
        assert "pacing" in result.themes

    @pytest.mark.asyncio
    async def test_parses_negative_sentiment(self):
        provider = DeepSeekProvider.__new__(DeepSeekProvider)
        provider._client = MagicMock()
        provider._client.chat.completions.create = AsyncMock(
            return_value=self._make_openai_response(
                _make_valid_analysis_json(sentiment="negative", sentiment_confidence=0.88, is_actionable=True)
            )
        )

        result = await provider.analyze_review(
            body="Very slow pacing and confusing plot.",
            rating=2,
            book_title="Test Book",
        )

        assert result.sentiment == "negative"
        assert result.is_actionable is True

    @pytest.mark.asyncio
    async def test_themes_clamped_to_vocabulary(self):
        """Themes not in the known vocabulary should be dropped during parsing."""
        provider = DeepSeekProvider.__new__(DeepSeekProvider)
        provider._client = MagicMock()
        provider._client.chat.completions.create = AsyncMock(
            return_value=self._make_openai_response(
                _make_valid_analysis_json(themes=["pacing", "TOTALLY_INVALID_THEME", "characters"])
            )
        )

        result = await provider.analyze_review(
            body="Great book.",
            rating=4,
            book_title="Test Book",
        )

        # Only known themes should survive — invalid ones are quietly dropped
        for theme in result.themes:
            assert theme in ("pacing", "characters"), f"Unexpected theme: {theme}"

    @pytest.mark.asyncio
    async def test_cost_computed_from_token_counts(self):
        provider = DeepSeekProvider.__new__(DeepSeekProvider)
        provider._client = MagicMock()
        # 1000 input tokens + 500 output tokens
        resp = self._make_openai_response(_make_valid_analysis_json())
        resp.usage.prompt_tokens = 1000
        resp.usage.completion_tokens = 500
        provider._client.chat.completions.create = AsyncMock(return_value=resp)

        result = await provider.analyze_review(
            body="Wonderful.",
            rating=5,
            book_title="Test Book",
        )

        assert result.tokens_input == 1000
        assert result.tokens_output == 500
        # Cost must be a small positive number; exact value depends on pricing constants
        assert result.cost_usd > 0

    @pytest.mark.asyncio
    async def test_confidence_clipped_to_unit_interval(self):
        """Confidence values outside [0, 1] must be clipped to avoid downstream issues."""
        provider = DeepSeekProvider.__new__(DeepSeekProvider)
        provider._client = MagicMock()
        # Malformed response: confidence > 1 and ai_confidence < 0
        provider._client.chat.completions.create = AsyncMock(
            return_value=self._make_openai_response(
                _make_valid_analysis_json(sentiment_confidence=1.5, ai_confidence=-0.1)
            )
        )

        result = await provider.analyze_review(
            body="Okay.",
            rating=3,
            book_title="Test Book",
        )

        assert 0.0 <= result.sentiment_confidence <= 1.0
        assert 0.0 <= result.ai_confidence <= 1.0
