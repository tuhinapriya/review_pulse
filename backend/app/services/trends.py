from collections import defaultdict
from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_sentiment_trends(
    db: AsyncSession,
    book_id: UUID,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> dict:
    """Compute weekly sentiment time-series and week-over-week delta (F5).

    We do the aggregation in SQL (GROUP BY date_trunc) rather than pulling
    all rows into Python. For books with thousands of reviews this is
    significantly faster and avoids memory pressure in the worker.
    """
    from_date = from_date or (datetime.now(timezone.utc) - timedelta(days=90))
    to_date = to_date or datetime.now(timezone.utc)

    result = await db.execute(
        text("""
            SELECT
                date_trunc('week', review_date) AS week,
                sentiment,
                COUNT(*) AS count
            FROM reviews
            WHERE book_id = :book_id
              AND review_date BETWEEN :from_date AND :to_date
              AND sentiment IS NOT NULL
            GROUP BY date_trunc('week', review_date), sentiment
            ORDER BY week
        """),
        {"book_id": str(book_id), "from_date": from_date, "to_date": to_date},
    )
    rows = result.mappings().all()

    # Reshape flat rows into {"week": ISO, "positive": N, "mixed": N, "negative": N}
    weeks: dict[str, dict] = defaultdict(
        lambda: {"positive": 0, "mixed": 0, "negative": 0}
    )
    for row in rows:
        week_str = row["week"].isoformat()
        weeks[week_str][row["sentiment"]] = row["count"]

    timeline = [{"week": w, **counts} for w, counts in sorted(weeks.items())]

    # Week-over-week delta: compare the last two complete weeks
    wow_delta = _compute_wow_delta_from_timeline(timeline)

    # Theme frequency over time
    theme_result = await db.execute(
        text("""
            SELECT
                date_trunc('week', r.review_date) AS week,
                unnest(r.themes) AS theme,
                COUNT(*) AS count
            FROM reviews r
            WHERE r.book_id = :book_id
              AND r.review_date BETWEEN :from_date AND :to_date
              AND r.themes IS NOT NULL
            GROUP BY week, theme
            ORDER BY week, count DESC
        """),
        {"book_id": str(book_id), "from_date": from_date, "to_date": to_date},
    )
    theme_rows = theme_result.mappings().all()

    theme_weeks: dict[str, list] = defaultdict(list)
    for row in theme_rows:
        week_str = row["week"].isoformat()
        theme_weeks[week_str].append({"theme": row["theme"], "count": row["count"]})

    theme_timeline = [
        {"week": w, "themes": themes}
        for w, themes in sorted(theme_weeks.items())
    ]

    return {
        "sentiment_over_time": timeline,
        "theme_frequency_over_time": theme_timeline,
        "wow_delta": wow_delta,
    }


def _compute_wow_delta(current: float, previous: float) -> str:
    """Classify week-over-week positive sentiment percentage-point change.

    Args:
        current:  positive-sentiment percentage this week (0–100 scale).
        previous: positive-sentiment percentage last week (0–100 scale).

    Returns:
        ``"improving"``  — current exceeds previous by more than 5 pp.
        ``"declining"``  — current trails previous by more than 5 pp.
        ``"stable"``     — change is within the ±5 pp threshold.
    """
    delta = current - previous
    if delta >= 5.0:
        return "improving"
    if delta <= -5.0:
        return "declining"
    return "stable"


def _compute_wow_delta_from_timeline(timeline: list[dict]) -> dict:
    """Compute the week-over-week positive sentiment percentage change.

    Returns the delta in percentage points and a human-readable trend label.
    Returns None if there are fewer than two weeks of data.
    """
    if len(timeline) < 2:
        return {"positive_pct_change": None, "trend": "insufficient_data"}

    def positive_pct(week: dict) -> float:
        total = week["positive"] + week["mixed"] + week["negative"]
        if total == 0:
            return 0.0
        return week["positive"] / total * 100

    prev_pct = positive_pct(timeline[-2])
    curr_pct = positive_pct(timeline[-1])
    delta = round(curr_pct - prev_pct, 4)
    trend = _compute_wow_delta(curr_pct, prev_pct)

    return {"positive_pct_change": delta, "trend": trend}


async def get_book_comparison(
    db: AsyncSession,
    book_ids: list[UUID],
    author_id: UUID,
) -> list[dict]:
    """Compute side-by-side metrics for a set of books (F6).

    The author_id check in the WHERE clause is the tenant isolation guard —
    even if a client sends book IDs belonging to another author, they'll
    simply return no data rather than exposing it.
    """
    if not book_ids:
        return []

    result = await db.execute(
        text("""
            SELECT
                b.id,
                b.title,
                COUNT(r.id) AS review_count,
                ROUND(AVG(r.rating)::numeric, 2) AS avg_rating,
                ROUND(
                    SUM(CASE WHEN r.sentiment = 'positive' THEN 1 ELSE 0 END)::numeric
                    / NULLIF(COUNT(r.id), 0), 4
                ) AS positive_pct,
                ROUND(
                    SUM(CASE WHEN r.sentiment = 'mixed' THEN 1 ELSE 0 END)::numeric
                    / NULLIF(COUNT(r.id), 0), 4
                ) AS mixed_pct,
                ROUND(
                    SUM(CASE WHEN r.sentiment = 'negative' THEN 1 ELSE 0 END)::numeric
                    / NULLIF(COUNT(r.id), 0), 4
                ) AS negative_pct,
                ROUND(
                    SUM(CASE WHEN r.is_ai_generated = true THEN 1 ELSE 0 END)::numeric
                    / NULLIF(COUNT(r.id), 0), 4
                ) AS ai_flagged_rate,
                ROUND(SUM(COALESCE(r.cost_usd, 0))::numeric, 6) AS total_cost_usd
            FROM books b
            LEFT JOIN reviews r ON r.book_id = b.id
            WHERE b.id = ANY(:book_ids)
              AND b.author_id = :author_id
            GROUP BY b.id, b.title
        """),
        {
            "book_ids": [str(bid) for bid in book_ids],
            "author_id": str(author_id),
        },
    )

    books_data = [dict(row) for row in result.mappings().all()]

    # Fetch top 5 themes per book in a second query — cleaner than a lateral join
    for book in books_data:
        theme_result = await db.execute(
            text("""
                SELECT theme, COUNT(*) AS count
                FROM reviews, unnest(themes) AS theme
                WHERE book_id = :book_id AND themes IS NOT NULL
                GROUP BY theme
                ORDER BY count DESC
                LIMIT 5
            """),
            {"book_id": str(book["id"])},
        )
        book["top_themes"] = [
            {"theme": row["theme"], "count": row["count"]}
            for row in theme_result.mappings().all()
        ]

    return books_data
