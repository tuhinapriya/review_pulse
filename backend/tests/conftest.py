"""
Shared pytest fixtures for all test suites.

The key design decision here is transactional test isolation:
every test runs inside a transaction that is always rolled back,
so tests are hermetically isolated without needing to recreate
the schema from scratch between runs.
"""
import asyncio
import hashlib
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.base import Base
from app.db.models import Author, Book, Review
from app.llm.schemas import DraftResponse, ReviewAnalysis

# ─── Test database ────────────────────────────────────────────────────────────

TEST_DB_URL = settings.database_url.replace("postgresql+asyncpg://", "postgresql+asyncpg://")


@pytest.fixture(scope="session")
def event_loop():
    """Single event loop shared across the session — avoids setup/teardown overhead."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    engine = create_async_engine(
        TEST_DB_URL,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a session that wraps every test in a savepoint.
    Rolling back to the savepoint at the end is cheaper than DROP+CREATE tables.
    """
    connection = await db_engine.connect()
    transaction = await connection.begin()

    session_factory = async_sessionmaker(connection, expire_on_commit=False)
    session = session_factory()

    yield session

    await session.close()
    await transaction.rollback()
    await connection.close()


# ─── Object factories ─────────────────────────────────────────────────────────


def _make_author(**kwargs: Any) -> Author:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "supabase_uid": str(uuid.uuid4()),
        "email": f"author_{uuid.uuid4().hex[:8]}@example.com",
        "name": "Test Author",
        "created_at": datetime.now(timezone.utc),
    }
    return Author(**{**defaults, **kwargs})


def _make_book(author_id: uuid.UUID, **kwargs: Any) -> Book:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "author_id": author_id,
        "title": f"Test Book {uuid.uuid4().hex[:6]}",
        "created_at": datetime.now(timezone.utc),
    }
    return Book(**{**defaults, **kwargs})


def _make_review(book_id: uuid.UUID, **kwargs: Any) -> Review:
    body = kwargs.get("body", f"Review body {uuid.uuid4().hex[:8]}")
    reviewer_name = kwargs.get("reviewer_name", "Jane Reader")
    # Compute external_id the same way the ingest pipeline does
    raw = f"{book_id}:{reviewer_name}:{body}"
    external_id = hashlib.sha256(raw.encode()).hexdigest()

    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "book_id": book_id,
        "external_id": external_id,
        "reviewer_name": reviewer_name,
        "body": body,
        "rating": 4,
        "sentiment": "positive",
        "sentiment_confidence": 0.9,
        "themes": ["pacing"],
        "is_ai_generated": False,
        "ai_confidence": 0.1,
        "summary": "Good review",
        "is_actionable": False,
        "tokens_used": 200,
        "cost_usd": 0.0001,
        "created_at": datetime.now(timezone.utc),
    }
    return Review(**{**defaults, **kwargs})


@pytest.fixture
def author_factory():
    return _make_author


@pytest.fixture
def book_factory():
    return _make_book


@pytest.fixture
def review_factory():
    return _make_review


# ─── LLM mock ─────────────────────────────────────────────────────────────────


def _make_mock_llm() -> MagicMock:
    """
    Returns a mock LLMProvider that behaves predictably in tests.
    All LLM-touching code should receive this via dependency override
    rather than making real network calls.
    """
    mock = MagicMock()

    mock.analyze_review = AsyncMock(
        return_value=ReviewAnalysis(
            sentiment="positive",
            sentiment_confidence=0.95,
            themes=["pacing", "characters"],
            is_ai_generated=False,
            ai_confidence=0.05,
            summary="A genuinely positive review praising the story.",
            is_actionable=False,
            tokens_input=150,
            tokens_output=80,
            cost_usd=0.00012,
        )
    )

    mock.suggest_response = AsyncMock(
        return_value=DraftResponse(
            review_id="",
            draft="Thank you for your thoughtful review!",
            tone="professional",
        )
    )

    # Return a deterministic 1024-dim zero vector — real similarity math
    # isn't what we're testing in unit tests
    mock.generate_embedding = AsyncMock(return_value=[0.0] * 1024)

    mock.generate_synthetic_reviews = AsyncMock(
        return_value=[
            {
                "reviewer_name": f"Reviewer {i}",
                "body": f"Synthetic review body number {i}",
                "rating": (i % 5) + 1,
                "review_date": "2024-01-15",
            }
            for i in range(50)
        ]
    )
    return mock


@pytest.fixture
def mock_llm():
    return _make_mock_llm()
