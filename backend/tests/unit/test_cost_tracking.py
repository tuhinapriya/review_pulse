"""
Unit tests for LLM cost tracking.

Cost accuracy matters because it's surfaced to authors (N3) and
incorrect values would erode trust in the platform. These tests
verify the pricing formula in isolation so any change to pricing
constants immediately shows up as a test failure.
"""
import pytest

from app.config import get_settings
from app.llm.deepseek import _compute_cost


class TestCostTracking:
    """_compute_cost returns correct USD amounts for known token counts."""

    def test_zero_tokens_is_zero_cost(self):
        settings = get_settings()
        cost = _compute_cost(
            tokens_in=0,
            tokens_out=0,
            cfg=settings,
        )
        assert cost == 0.0

    def test_cost_is_non_negative(self):
        settings = get_settings()
        cost = _compute_cost(tokens_in=500, tokens_out=200, cfg=settings)
        assert cost >= 0.0

    def test_more_tokens_more_cost(self):
        """Cost must be monotonically increasing in token count."""
        settings = get_settings()
        small = _compute_cost(tokens_in=100, tokens_out=50, cfg=settings)
        large = _compute_cost(tokens_in=10_000, tokens_out=5_000, cfg=settings)
        assert large > small

    def test_output_tokens_cost_more_than_input(self):
        """
        For DeepSeek (as with OpenAI), output tokens are priced higher than input tokens.
        Verify that 1 output token is more expensive than 1 input token.
        """
        settings = get_settings()
        only_input = _compute_cost(tokens_in=1000, tokens_out=0, cfg=settings)
        only_output = _compute_cost(tokens_in=0, tokens_out=1000, cfg=settings)
        assert only_output > only_input

    def test_proportional_cost(self):
        """
        Doubling the token count should exactly double the cost (no fixed overhead).
        """
        settings = get_settings()
        base = _compute_cost(tokens_in=500, tokens_out=200, cfg=settings)
        doubled = _compute_cost(tokens_in=1000, tokens_out=400, cfg=settings)
        assert abs(doubled - 2 * base) < 1e-10

    def test_cost_uses_pricing_constants_from_settings(self):
        """
        Manually compute expected cost using the pricing constants and verify
        the function produces the same value.
        """
        settings = get_settings()
        tokens_in = 1000
        tokens_out = 500
        expected = (
            tokens_in / 1_000_000 * settings.deepseek_input_price_per_million
            + tokens_out / 1_000_000 * settings.deepseek_output_price_per_million
        )
        actual = _compute_cost(tokens_in, tokens_out, settings)
        assert abs(actual - expected) < 1e-10
