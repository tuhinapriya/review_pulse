import enum
import uuid
from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# ── Enums ─────────────────────────────────────────────────────────────────────

class SentimentEnum(str, enum.Enum):
    positive = "positive"
    mixed = "mixed"
    negative = "negative"


class JobStatusEnum(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    partial = "partial"  # some reviews processed, some failed


# ── Models ────────────────────────────────────────────────────────────────────

class Author(Base):
    __tablename__ = "authors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # supabase_uid links our Author record to the Supabase Auth user.
    # We look up authors by this field on every authenticated request.
    supabase_uid: Mapped[Optional[str]] = mapped_column(
        String, unique=True, nullable=True, index=True
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # previous_last_login_at lets the "since last login" feature (F8) show
    # what's new since the *previous* session, not the current one.
    previous_last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    books: Mapped[list["Book"]] = relationship(
        "Book", back_populates="author", cascade="all, delete-orphan"
    )
    webhooks: Mapped[list["WebhookSubscription"]] = relationship(
        "WebhookSubscription", back_populates="author", cascade="all, delete-orphan"
    )


class Book(Base):
    __tablename__ = "books"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # author_id is the tenant boundary. Every service function that queries
    # books or reviews MUST include this in its WHERE clause. The invariant
    # is enforced structurally at the service layer, not by convention.
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("authors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    isbn: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    author: Mapped["Author"] = relationship("Author", back_populates="books")
    reviews: Mapped[list["Review"]] = relationship(
        "Review", back_populates="book", cascade="all, delete-orphan"
    )
    ingestion_jobs: Mapped[list["IngestionJob"]] = relationship(
        "IngestionJob", back_populates="book", cascade="all, delete-orphan"
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    book_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[JobStatusEnum] = mapped_column(
        SAEnum(JobStatusEnum), nullable=False, default=JobStatusEnum.queued
    )
    total_reviews: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_reviews: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_reviews: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    book: Mapped["Book"] = relationship("Book", back_populates="ingestion_jobs")


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    book_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Stable fingerprint for dedup: SHA-256("{book_id}:{reviewer_name}:{body}").
    # Combining all three prevents false matches if a person reviews multiple
    # books, and ensures that an edited review generates a new record rather
    # than silently overwriting the old one.
    external_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    reviewer_name: Mapped[str] = mapped_column(String, nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    review_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # ── LLM analysis fields (populated by the Celery task) ───────────────────
    sentiment: Mapped[Optional[SentimentEnum]] = mapped_column(
        SAEnum(SentimentEnum), nullable=True, index=True
    )
    sentiment_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    themes: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), nullable=True)
    is_ai_generated: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    ai_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    is_actionable: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # 1024-dimensional vector from deepseek-embedding. The dimension must match
    # the vector(N) column in the migration — pgvector will reject mismatches.
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(1024), nullable=True)

    # Cost tracking per review — aggregated to per-book and per-author in the API.
    # This lets authors see real LLM spend, which matters for a cost-conscious startup (N3).
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    book: Mapped["Book"] = relationship("Book", back_populates="reviews")


class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("authors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(String, nullable=False)
    # The raw HMAC secret. In a production system this would be encrypted at
    # rest (e.g. with AWS KMS or Supabase Vault). For this demo it lives in
    # a Postgres instance that's only accessible to the backend service.
    secret: Mapped[str] = mapped_column(String, nullable=False)
    events: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    author: Mapped["Author"] = relationship("Author", back_populates="webhooks")
