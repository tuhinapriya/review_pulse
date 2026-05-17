"""
Integration tests for the ingest pipeline.

These tests run against a real (test) Postgres database with all migrations
applied. The LLM is mocked so tests are deterministic and don't incur cost.

Key scenarios covered:
1. Full happy-path ingest → job reaches completed/partial state, reviews stored
2. Deduplication — re-running ingest for the same book does not create duplicate rows
3. Job status counter increments match stored review count
"""
import asyncio
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Author, Book, IngestionJob, Review
from app.tasks.ingest import _ingest_book_async


async def _persist(session: AsyncSession, *objects) -> None:
    for obj in objects:
        session.add(obj)
    await session.commit()


@pytest_asyncio.fixture
async def seeded_author_and_book(db_session, author_factory, book_factory):
    author = author_factory()
    db_session.add(author)
    await db_session.flush()

    book = book_factory(author_id=author.id)
    db_session.add(book)
    await db_session.flush()

    job = IngestionJob(
        id=uuid.uuid4(),
        book_id=book.id,
        status="queued",
        total_reviews=0,
        processed_reviews=0,
    )
    db_session.add(job)
    await db_session.commit()

    return author, book, job


class TestIngestPipeline:
    @pytest.mark.asyncio
    async def test_happy_path_job_completes(self, db_session, seeded_author_and_book, mock_llm):
        _, book, job = seeded_author_and_book

        with (
            patch("app.tasks.ingest.get_llm_provider", return_value=mock_llm),
            patch("app.tasks.ingest.get_embedding_provider", return_value=mock_llm),
            patch("app.tasks.ingest.fire_webhooks"),  # don't need real delivery in tests
        ):
            await _ingest_book_async(str(job.id))

        await db_session.refresh(job)
        assert job.status in ("completed", "partial")
        # The mock generates 50 reviews, so we should have at least some stored
        assert job.processed_reviews > 0

    @pytest.mark.asyncio
    async def test_deduplication_prevents_duplicate_reviews(
        self, db_session, seeded_author_and_book, mock_llm
    ):
        """Running ingest twice must not double the review count."""
        _, book, job = seeded_author_and_book

        def make_second_job():
            second = IngestionJob(
                id=uuid.uuid4(),
                book_id=book.id,
                status="queued",
                total_reviews=0,
                processed_reviews=0,
            )
            return second

        with (
            patch("app.tasks.ingest.get_llm_provider", return_value=mock_llm),
            patch("app.tasks.ingest.get_embedding_provider", return_value=mock_llm),
            patch("app.tasks.ingest.fire_webhooks"),
        ):
            # First run
            await _ingest_book_async(str(job.id))

            count_after_first = (
                await db_session.execute(
                    select(Review).where(Review.book_id == book.id)
                )
            ).scalars().all().__len__()  # noqa: WPS609

            # Second run — same LLM output → same external_ids → no new rows
            second_job = make_second_job()
            db_session.add(second_job)
            await db_session.commit()

            await _ingest_book_async(str(second_job.id))

            count_after_second = len(
                (await db_session.execute(select(Review).where(Review.book_id == book.id)))
                .scalars()
                .all()
            )

        assert count_after_second == count_after_first, (
            f"Expected {count_after_first} reviews after re-ingest but got {count_after_second}. "
            "Deduplication is broken."
        )

    @pytest.mark.asyncio
    async def test_processed_counter_matches_stored_reviews(
        self, db_session, seeded_author_and_book, mock_llm
    ):
        """processed_reviews on the job must match the actual DB row count."""
        _, book, job = seeded_author_and_book

        with (
            patch("app.tasks.ingest.get_llm_provider", return_value=mock_llm),
            patch("app.tasks.ingest.get_embedding_provider", return_value=mock_llm),
            patch("app.tasks.ingest.fire_webhooks"),
        ):
            await _ingest_book_async(str(job.id))

        await db_session.refresh(job)
        stored_count = len(
            (await db_session.execute(select(Review).where(Review.book_id == book.id)))
            .scalars()
            .all()
        )

        assert job.processed_reviews == stored_count
