from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def build_weekly_digest(db: AsyncSession, author_id: UUID) -> dict:
    """Assemble the data for the weekly digest preview (F10).

    Covers the last 7 days across all of the author's books. The digest is
    designed to answer "what do I need to know this week?" in under 30 seconds.
    """
    week_start = datetime.now(UTC) - timedelta(days=7)

    # ── Headline stats ────────────────────────────────────────────────────────
    stats_result = await db.execute(
        text("""
            SELECT
                COUNT(*) AS new_reviews,
                ROUND(AVG(r.rating)::numeric, 2) AS avg_rating,
                SUM(CASE WHEN r.sentiment = 'positive' THEN 1 ELSE 0 END) AS positive_count,
                SUM(CASE WHEN r.sentiment = 'mixed' THEN 1 ELSE 0 END) AS mixed_count,
                SUM(CASE WHEN r.sentiment = 'negative' THEN 1 ELSE 0 END) AS negative_count,
                SUM(CASE WHEN r.is_actionable = true THEN 1 ELSE 0 END) AS actionable_count,
                SUM(CASE WHEN r.is_ai_generated = true THEN 1 ELSE 0 END) AS ai_flagged_count,
                ROUND(SUM(COALESCE(r.cost_usd, 0))::numeric, 4) AS total_cost_usd
            FROM reviews r
            JOIN books b ON r.book_id = b.id
            WHERE b.author_id = :author_id
              AND r.created_at >= :week_start
        """),
        {"author_id": str(author_id), "week_start": week_start},
    )
    stats = dict(stats_result.mappings().one())

    # ── Top themes this week ──────────────────────────────────────────────────
    themes_result = await db.execute(
        text("""
            SELECT theme, COUNT(*) AS count
            FROM reviews r
            JOIN books b ON r.book_id = b.id, unnest(r.themes) AS theme
            WHERE b.author_id = :author_id
              AND r.created_at >= :week_start
              AND r.themes IS NOT NULL
            GROUP BY theme
            ORDER BY count DESC
            LIMIT 5
        """),
        {"author_id": str(author_id), "week_start": week_start},
    )
    top_themes = [dict(row) for row in themes_result.mappings().all()]

    # ── Most impactful reviews (actionable + negative) ────────────────────────
    impactful_result = await db.execute(
        text("""
            SELECT
                r.id, r.book_id, r.reviewer_name, r.rating, r.body, r.summary,
                r.sentiment, r.is_actionable, r.themes,
                b.title AS book_title
            FROM reviews r
            JOIN books b ON r.book_id = b.id
            WHERE b.author_id = :author_id
              AND r.created_at >= :week_start
              AND (r.is_actionable = true OR r.sentiment = 'negative')
            ORDER BY
                CASE WHEN r.is_actionable = true AND r.sentiment = 'negative' THEN 0
                     WHEN r.is_actionable = true THEN 1
                     ELSE 2 END,
                r.rating ASC
            LIMIT 5
        """),
        {"author_id": str(author_id), "week_start": week_start},
    )
    impactful = [dict(row) for row in impactful_result.mappings().all()]

    # ── Best review (to end the digest on a high note) ────────────────────────
    best_result = await db.execute(
        text("""
            SELECT r.reviewer_name, r.rating, LEFT(r.body, 300) AS snippet, b.title AS book_title
            FROM reviews r
            JOIN books b ON r.book_id = b.id
            WHERE b.author_id = :author_id
              AND r.created_at >= :week_start
              AND r.sentiment = 'positive'
            ORDER BY r.sentiment_confidence DESC, r.rating DESC
            LIMIT 1
        """),
        {"author_id": str(author_id), "week_start": week_start},
    )
    best_row = best_result.mappings().first()
    best_review = dict(best_row) if best_row else None

    # Determine trend signal from the last two weeks for context
    trend = await _get_two_week_trend(db, author_id)

    return {
        "week_start": week_start.isoformat(),
        "headline": {
            "new_reviews": stats["new_reviews"] or 0,
            "positive_pct": _percentage(stats["positive_count"], stats["new_reviews"]),
            "actionable_count": stats["actionable_count"] or 0,
            "trend": trend,
        },
        "stats": stats,
        "top_themes": top_themes,
        "impactful_reviews": impactful,
        "best_review": best_review,
        "trend": trend,
    }


async def _get_two_week_trend(db: AsyncSession, author_id: UUID) -> str:
    """Compare positive sentiment rate: this week vs the prior week."""
    this_week_start = datetime.now(UTC) - timedelta(days=7)
    prev_week_start = this_week_start - timedelta(days=7)

    result = await db.execute(
        text("""
            SELECT
                SUM(CASE WHEN r.created_at >= :this_week_start
                         AND r.sentiment = 'positive' THEN 1 ELSE 0 END) AS this_positive,
                SUM(CASE WHEN r.created_at >= :this_week_start THEN 1 ELSE 0 END) AS this_total,
                SUM(CASE WHEN r.created_at < :this_week_start
                         AND r.created_at >= :prev_week_start
                         AND r.sentiment = 'positive' THEN 1 ELSE 0 END) AS prev_positive,
                SUM(CASE WHEN r.created_at < :this_week_start
                         AND r.created_at >= :prev_week_start THEN 1 ELSE 0 END) AS prev_total
            FROM reviews r
            JOIN books b ON r.book_id = b.id
            WHERE b.author_id = :author_id
        """),
        {
            "author_id": str(author_id),
            "this_week_start": this_week_start,
            "prev_week_start": prev_week_start,
        },
    )
    row = result.mappings().one()

    this_pct = (row["this_positive"] or 0) / max(row["this_total"] or 1, 1)
    prev_pct = (row["prev_positive"] or 0) / max(row["prev_total"] or 1, 1)
    delta = this_pct - prev_pct

    if delta > 0.05:
        return "improving"
    elif delta < -0.05:
        return "declining"
    return "stable"


def _percentage(part: int | None, total: int | None) -> float:
    if not total:
        return 0.0
    return ((part or 0) / total) * 100
