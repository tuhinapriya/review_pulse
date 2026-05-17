"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector must be installed before creating vector columns.
    # On Supabase this is a one-click extension; locally docker-compose uses
    # the pgvector/pgvector image which ships with it pre-compiled.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "authors",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String, nullable=False, unique=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("supabase_uid", sa.String, nullable=True, unique=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("previous_last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_authors_email", "authors", ["email"])
    op.create_index("ix_authors_supabase_uid", "authors", ["supabase_uid"])

    op.create_table(
        "books",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "author_id",
            UUID(as_uuid=True),
            sa.ForeignKey("authors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("isbn", sa.String, nullable=True),
        sa.Column("url", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_books_author_id", "books", ["author_id"])

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "book_id",
            UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued", "running", "completed", "failed", "partial",
                name="jobstatusenum",
            ),
            nullable=False,
        ),
        sa.Column("total_reviews", sa.Integer, nullable=False, server_default="0"),
        sa.Column("processed_reviews", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_reviews", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ingestion_jobs_book_id", "ingestion_jobs", ["book_id"])

    op.create_table(
        "reviews",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "book_id",
            UUID(as_uuid=True),
            sa.ForeignKey("books.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String, nullable=False, unique=True),
        sa.Column("reviewer_name", sa.String, nullable=False),
        sa.Column("rating", sa.Integer, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("review_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "sentiment",
            sa.Enum("positive", "mixed", "negative", name="sentimentenum"),
            nullable=True,
        ),
        sa.Column("sentiment_confidence", sa.Float, nullable=True),
        sa.Column("themes", ARRAY(sa.String), nullable=True),
        sa.Column("is_ai_generated", sa.Boolean, nullable=True),
        sa.Column("ai_confidence", sa.Float, nullable=True),
        sa.Column("summary", sa.String(200), nullable=True),
        sa.Column("is_actionable", sa.Boolean, nullable=True),
        sa.Column("tokens_used", sa.Integer, nullable=True),
        sa.Column("cost_usd", sa.Float, nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Add vector column separately — SQLAlchemy's migration autogenerate doesn't
    # natively support pgvector types, so raw SQL is the reliable path here.
    op.execute("ALTER TABLE reviews ADD COLUMN embedding vector(1024)")

    op.create_index("ix_reviews_book_id", "reviews", ["book_id"])
    op.create_index("ix_reviews_external_id", "reviews", ["external_id"], unique=True)
    op.create_index("ix_reviews_sentiment", "reviews", ["sentiment"])
    op.create_index("ix_reviews_review_date", "reviews", ["review_date"])

    # IVFFlat index on embeddings for approximate nearest-neighbour search.
    # lists=100 is a reasonable default for < 1M vectors; increase for larger datasets.
    # We create it after inserting data in production for better index quality;
    # creating it empty is fine for the demo.
    op.execute(
        "CREATE INDEX ix_reviews_embedding ON reviews "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "author_id",
            UUID(as_uuid=True),
            sa.ForeignKey("authors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String, nullable=False),
        sa.Column("secret", sa.String, nullable=False),
        sa.Column("events", ARRAY(sa.String), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_webhook_subscriptions_author_id", "webhook_subscriptions", ["author_id"])


def downgrade() -> None:
    op.drop_table("webhook_subscriptions")
    op.drop_index("ix_reviews_embedding", table_name="reviews")
    op.drop_table("reviews")
    op.execute("DROP TYPE IF EXISTS sentimentenum")
    op.drop_table("ingestion_jobs")
    op.execute("DROP TYPE IF EXISTS jobstatusenum")
    op.drop_table("books")
    op.drop_table("authors")
    op.execute("DROP EXTENSION IF EXISTS vector")
