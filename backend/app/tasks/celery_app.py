from celery import Celery

from app.config import settings

celery_app = Celery(
    "reviewpulse",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.ingest", "app.tasks.scheduled"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Retry failed tasks after 60s, up to 3 times. This covers transient
    # failures like Redis restarts or brief network blips — not LLM errors,
    # which are handled per-review inside the task body.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Scheduled re-ingestion — finds all books and re-runs ingestion for any
    # that haven't been refreshed in the last hour. Idempotent because ingest
    # deduplicates by external_id, so re-running produces no duplicates (F9, F11).
    beat_schedule={
        "scheduled-reingest": {
            "task": "app.tasks.scheduled.run_scheduled_reingest",
            "schedule": 3600,  # every hour
        }
    },
)
