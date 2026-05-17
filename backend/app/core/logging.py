import logging

import structlog

from app.config import settings


def setup_logging() -> None:
    """Configure structlog for the application.

    In development we use a human-readable console renderer. In production
    we emit JSON so log aggregators (Axiom, Datadog, CloudWatch) can parse
    structured fields like job_id, review_id, and error without regex.
    """
    renderer: structlog.types.Processor = (
        structlog.dev.ConsoleRenderer(colors=False)
        if settings.environment == "development"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            # Merge any context vars bound earlier in the request lifecycle
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.ExceptionRenderer(),
            renderer,
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Suppress uvicorn's per-request access log — it's noise in structured logging.
    # We capture the fields we care about in our own middleware instead.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger() -> structlog.BoundLogger:
    return structlog.get_logger()
