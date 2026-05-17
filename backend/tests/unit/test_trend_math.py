"""
Unit tests for sentiment trend computation.

_compute_wow_delta is a pure function that classifies week-over-week
changes as improving / declining / stable based on a ±5% threshold.
Testing it in isolation (without a DB) lets us cover all branches
quickly and be confident before integration tests run.
"""
import pytest

from app.services.trends import _compute_wow_delta


class TestWoWDelta:
    """_compute_wow_delta classifies changes correctly."""

    def test_large_positive_change_is_improving(self):
        # 60% this week vs 40% last week → +20 percentage points
        assert _compute_wow_delta(current=60.0, previous=40.0) == "improving"

    def test_large_negative_change_is_declining(self):
        # 35% this week vs 60% last week → -25 percentage points
        assert _compute_wow_delta(current=35.0, previous=60.0) == "declining"

    def test_small_positive_change_is_stable(self):
        # 52% vs 50% → +2 pp, within the ±5% noise floor
        assert _compute_wow_delta(current=52.0, previous=50.0) == "stable"

    def test_small_negative_change_is_stable(self):
        # 48% vs 50% → -2 pp, within the ±5% noise floor
        assert _compute_wow_delta(current=48.0, previous=50.0) == "stable"

    def test_exact_threshold_positive_is_improving(self):
        # Exactly +5 pp — boundary should be classified as improving
        assert _compute_wow_delta(current=55.0, previous=50.0) == "improving"

    def test_exact_threshold_negative_is_declining(self):
        # Exactly -5 pp — boundary should be classified as declining
        assert _compute_wow_delta(current=45.0, previous=50.0) == "declining"

    def test_zero_previous_no_change(self):
        # Edge case: no reviews last week, 0 this week too → stable
        assert _compute_wow_delta(current=0.0, previous=0.0) == "stable"

    def test_zero_previous_with_reviews_now_is_improving(self):
        # Went from 0% to 80% positive — obviously improving
        assert _compute_wow_delta(current=80.0, previous=0.0) == "improving"

    def test_return_type_is_string(self):
        result = _compute_wow_delta(current=55.0, previous=50.0)
        assert isinstance(result, str)
        assert result in ("improving", "declining", "stable")
