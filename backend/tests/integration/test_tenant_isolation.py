"""
Integration tests for multi-tenant isolation.

This is the most security-critical test suite in the codebase.
Author A must NEVER be able to read or mutate data belonging to Author B,
regardless of which endpoint they hit.

Each test:
1. Creates two authors with separate books and reviews
2. Authenticates as Author A
3. Attempts to access Author B's resources
4. Asserts 403 or 404 — never 200
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Author, Book, IngestionJob, Review
from app.main import app


def _make_jwt_for(author: Author) -> str:
    """
    Generate a minimal JWT that the get_current_author dependency will accept.
    In tests we bypass Supabase and generate the token ourselves using the
    same JWT_SECRET the app is configured with.
    """
    import time

    from jose import jwt

    from app.config import get_settings

    settings = get_settings()
    payload = {
        "sub": author.supabase_uid,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, settings.supabase_jwt_secret, algorithm="HS256")


@pytest_asyncio.fixture
async def two_authors(db_session: AsyncSession, author_factory, book_factory, review_factory):
    """Persist two fully-isolated authors each with a book and a review."""
    author_a = author_factory(name="Author A")
    author_b = author_factory(name="Author B")
    db_session.add_all([author_a, author_b])
    await db_session.flush()

    book_a = book_factory(author_id=author_a.id, title="Book A")
    book_b = book_factory(author_id=author_b.id, title="Book B")
    db_session.add_all([book_a, book_b])
    await db_session.flush()

    review_b = review_factory(book_id=book_b.id, reviewer_name="Reader")
    db_session.add(review_b)

    job_b = IngestionJob(
        id=uuid.uuid4(),
        book_id=book_b.id,
        status="completed",
        total_reviews=1,
        processed_reviews=1,
    )
    db_session.add(job_b)
    await db_session.commit()

    return author_a, author_b, book_a, book_b, review_b, job_b


class TestTenantIsolation:
    """Author A cannot access Author B's data through any endpoint."""

    @pytest.fixture
    def client_as_author_a(self, two_authors, db_session):
        author_a, *_ = two_authors
        token = _make_jwt_for(author_a)

        # Override get_current_author to return author_a without touching Supabase
        async def override_get_current_author():
            return author_a

        async def override_get_db():
            yield db_session

        from app.api.deps import get_current_author, get_db

        app.dependency_overrides[get_current_author] = override_get_current_author
        app.dependency_overrides[get_db] = override_get_db

        with TestClient(app) as client:
            client.headers["Authorization"] = f"Bearer {token}"
            yield client

        app.dependency_overrides.clear()

    def test_cannot_list_reviews_for_other_authors_book(
        self, client_as_author_a, two_authors
    ):
        _, _, _, book_b, *_ = two_authors
        resp = client_as_author_a.get(f"/api/v1/books/{book_b.id}/reviews")
        assert resp.status_code in (403, 404), (
            f"Expected 403/404 but got {resp.status_code}. "
            "Author A can read Author B's reviews — isolation is broken."
        )

    def test_cannot_get_job_for_other_authors_book(
        self, client_as_author_a, two_authors
    ):
        _, _, _, _, _, job_b = two_authors
        resp = client_as_author_a.get(f"/api/v1/jobs/{job_b.id}")
        assert resp.status_code in (403, 404)

    def test_cannot_trigger_ingest_on_other_authors_book(
        self, client_as_author_a, two_authors
    ):
        _, _, _, book_b, *_ = two_authors
        resp = client_as_author_a.post(f"/api/v1/books/{book_b.id}/ingest")
        assert resp.status_code in (403, 404)

    def test_cannot_get_trends_for_other_authors_book(
        self, client_as_author_a, two_authors
    ):
        _, _, _, book_b, *_ = two_authors
        resp = client_as_author_a.get(f"/api/v1/books/{book_b.id}/trends")
        assert resp.status_code in (403, 404)

    def test_cannot_access_other_authors_activity(
        self, client_as_author_a, two_authors
    ):
        _, author_b, *_ = two_authors
        resp = client_as_author_a.get(f"/api/v1/authors/{author_b.id}/activity")
        assert resp.status_code in (403, 404)

    def test_cannot_draft_response_for_other_authors_review(
        self, client_as_author_a, two_authors
    ):
        _, _, _, _, review_b, _ = two_authors
        resp = client_as_author_a.post(
            f"/api/v1/reviews/{review_b.id}/draft-response",
            json={"tone": "professional"},
        )
        assert resp.status_code in (403, 404)

    def test_semantic_search_does_not_return_other_authors_reviews(
        self, client_as_author_a, two_authors
    ):
        """Search results must be scoped to the requesting author only."""
        _, _, _, book_b, review_b, _ = two_authors

        with patch("app.api.routes.search.get_embedding_provider") as mock_ep:
            mock_provider = AsyncMock()
            mock_provider.generate_embedding.return_value = [0.0] * 1024
            mock_ep.return_value = mock_provider

            resp = client_as_author_a.post("/api/v1/search", json={"query": "test"})

        assert resp.status_code == 200
        result_ids = [r["review_id"] for r in resp.json()]
        assert str(review_b.id) not in result_ids, (
            "Semantic search returned a review belonging to another author."
        )
