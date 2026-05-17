import asyncio
import functools
import logging
from typing import Any, Callable

import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
    before_sleep_log,
)

from app.config import settings
from app.llm.base import LLMProvider

log = structlog.get_logger()

# ── Concurrency limiter ───────────────────────────────────────────────────────
# Cap concurrent LLM calls to avoid hammering rate limits during bulk ingest.
# With 50 reviews per book and a limit of 5, we run 10 rounds of parallel calls.
# That's fast enough for the N1 sub-60s goal while staying well under typical
# API rate limits (DeepSeek free tier: ~60 RPM).
_concurrency_semaphore = asyncio.Semaphore(5)

# ── Retry policy ──────────────────────────────────────────────────────────────
# Retry on rate-limit and transient server errors (5xx).
# Failure mode after 3 attempts: the exception propagates to the Celery task,
# which logs it, increments failed_reviews, and continues to the next review.
# One bad review doesn't fail the entire ingest job.
def _make_retry_decorator() -> Any:
    try:
        from openai import RateLimitError as OpenAIRateLimitError, APIStatusError
        from anthropic import RateLimitError as AnthropicRateLimitError

        return retry(
            stop=stop_after_attempt(3),
            # 1s → 2s → 4s + random jitter to avoid thundering-herd retries
            wait=wait_exponential_jitter(initial=1, max=16),
            retry=retry_if_exception_type(
                (OpenAIRateLimitError, AnthropicRateLimitError, APIStatusError)
            ),
            before_sleep=before_sleep_log(log, logging.WARNING),
            reraise=True,
        )
    except ImportError:
        # Fallback: no-op decorator if SDK imports fail (e.g. in test environments
        # that don't install all providers)
        def noop(f: Callable) -> Callable:
            return f
        return noop


with_retry = _make_retry_decorator()


# ── Provider singletons ───────────────────────────────────────────────────────
# Singletons because both provider clients maintain internal connection pools.
# Re-creating them on every request would waste connections and ignore pooling.
_llm_provider: LLMProvider | None = None
_embedding_provider: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    """Return the singleton LLM provider for analysis tasks.

    Provider is chosen by the LLM_PROVIDER env var — swap it to change
    providers without touching any business logic (N2).
    """
    global _llm_provider
    if _llm_provider is None:
        if settings.llm_provider == "anthropic":
            from app.llm.anthropic_provider import AnthropicProvider
            _llm_provider = AnthropicProvider()
        else:
            from app.llm.deepseek import DeepSeekProvider
            _llm_provider = DeepSeekProvider()
    return _llm_provider


def get_embedding_provider() -> LLMProvider:
    """Always return DeepSeek for embeddings.

    Anthropic doesn't provide an embedding API, so we always route embedding
    calls to DeepSeek regardless of the LLM_PROVIDER setting. This means
    DEEPSEEK_API_KEY must be set even when using Anthropic for analysis.
    """
    global _embedding_provider
    if _embedding_provider is None:
        from app.llm.deepseek import DeepSeekProvider
        _embedding_provider = DeepSeekProvider()
    return _embedding_provider


def reset_providers() -> None:
    """Reset cached provider singletons. Used in tests to inject mocks."""
    global _llm_provider, _embedding_provider
    _llm_provider = None
    _embedding_provider = None
