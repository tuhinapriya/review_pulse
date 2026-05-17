from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_activity_since_last_login(
    db: AsyncSession,
    author_id: UUID,
    since: datetime | None,
) -> dict:
    """Surface the most important review activity since the author's last visit (F8).

    'Important' is defined by a priority score:
      is_actionable × 3 + (sentiment == negative) × 2 + is_ai_generated × 1

    This ordering reflects what authors actually care about most urgently:
    - Actionable reviews need a response (highest priority)
    - Negative reviews affect sales and reputation (high priority)
    - AI-flagged reviews may indicate manipulation (worth knowing)

    We return the top 10 so the "since last login" strip on the dashboard
    stays digestible rather than overwhelming.
    """
    # If this is the author's first visit, show the last 7 days
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=7)

    result = await db.execute(
        text("""
            SELECT
                r.id,
                r.reviewer_name,
                r.rating,
                LEFT(r.body, 200) AS snippet,
                r.sentiment,
                r.is_actionable,
                r.is_ai_generated,
                r.summary,
                r.review_date,
                b.id AS book_id,
                b.title AS book_title,
                -- Priority score drives the ordering
                (CASE WHEN r.is_actionable = true THEN 3 ELSE 0 END
                 + CASE WHEN r.sentiment = 'negative' THEN 2 ELSE 0 END
                 + CASE WHEN r.is_ai_generated = true THEN 1 ELSE 0 END) AS priority_score
            FROM reviews r
            JOIN books b ON r.book_id = b.id
            WHERE b.author_id = :author_id
              AND r.created_at > :since
            ORDER BY priority_score DESC, r.review_date DESC
            LIMIT 10
        """),
        {"author_id": str(author_id), "since": since},
    )

    reviews = [dict(row) for row in result.mappings().all()]

    # Group by book for the UI to render per-book sections
    by_book: dict[str, dict] = {}
    for r in reviews:
        book_id = str(r["book_id"])
        if book_id not in by_book:
            by_book[book_id] = {"book_id": book_id, "book_title": r["book_title"], "reviews": []}
        by_book[book_id]["reviews"].append(r)

    return {
        "since": since.isoformat(),
        "total_new": len(reviews),
        "by_book": list(by_book.values()),
    }
