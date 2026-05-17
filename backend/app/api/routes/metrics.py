from datetime import datetime, timezone, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Depends, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db

router = APIRouter()


@router.get("/admin/metrics")
async def get_metrics(
    x_admin_token: Annotated[str, Header()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Observability dashboard data (N12).

    Returns a snapshot useful for answering "what's happening at 3 AM?":
    job queue depth, recent error rate, LLM cost burn, and processing latency.
    Protected by a static admin token — not author-scoped.
    """
    if x_admin_token != settings.admin_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    # Job status breakdown
    job_result = await db.execute(
        text("""
            SELECT status, COUNT(*) AS count
            FROM ingestion_jobs
            GROUP BY status
        """)
    )
    jobs_by_status = {row["status"]: row["count"] for row in job_result.mappings().all()}

    # Review + cost activity in last 24h
    activity_result = await db.execute(
        text("""
            SELECT
                COUNT(*) AS reviews_analyzed,
                ROUND(SUM(COALESCE(cost_usd, 0))::numeric, 4) AS total_cost_usd,
                ROUND(AVG(EXTRACT(EPOCH FROM (analyzed_at - created_at)))::numeric, 2)
                    AS avg_analysis_seconds
            FROM reviews
            WHERE created_at >= :since
        """),
        {"since": since_24h},
    )
    activity = dict(activity_result.mappings().one())

    # p50 / p95 analysis latency (approximated via percentile_cont)
    latency_result = await db.execute(
        text("""
            SELECT
                ROUND(
                    PERCENTILE_CONT(0.5) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (analyzed_at - created_at))
                    )::numeric, 2
                ) AS p50_seconds,
                ROUND(
                    PERCENTILE_CONT(0.95) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (analyzed_at - created_at))
                    )::numeric, 2
                ) AS p95_seconds
            FROM reviews
            WHERE created_at >= :since
              AND analyzed_at IS NOT NULL
        """),
        {"since": since_24h},
    )
    latency = dict(latency_result.mappings().one())

    return {
        "jobs_by_status": jobs_by_status,
        "last_24h": {**activity, **latency},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
