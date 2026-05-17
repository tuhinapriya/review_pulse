import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import config_diagnostics, settings
from app.core.logging import setup_logging
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    log = structlog.get_logger()
    log.info("ReviewPulse API starting", environment=settings.environment)
    diagnostics = config_diagnostics()
    log.info("configuration check", **diagnostics)
    yield
    await engine.dispose()
    log.info("ReviewPulse API stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="ReviewPulse API",
        version="0.1.0",
        description="Review intelligence platform for independent authors",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request logging middleware — captures method, path, status, and duration
    # for every request so we can answer "what was happening before this error?"
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        log = structlog.get_logger()
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    # Register all routers
    from app.api.routes import (
        activity,
        authors,
        books,
        comparison,
        digest,
        draft_response,
        jobs,
        metrics,
        reviews,
        search,
        trends,
        webhooks,
    )

    prefix = "/api/v1"
    app.include_router(authors.router, prefix=prefix, tags=["auth"])
    app.include_router(books.router, prefix=prefix, tags=["books"])
    app.include_router(jobs.router, prefix=prefix, tags=["jobs"])
    app.include_router(reviews.router, prefix=prefix, tags=["reviews"])
    app.include_router(search.router, prefix=prefix, tags=["search"])
    app.include_router(trends.router, prefix=prefix, tags=["trends"])
    app.include_router(comparison.router, prefix=prefix, tags=["comparison"])
    app.include_router(activity.router, prefix=prefix, tags=["activity"])
    app.include_router(digest.router, prefix=prefix, tags=["digest"])
    app.include_router(webhooks.router, prefix=prefix, tags=["webhooks"])
    app.include_router(draft_response.router, prefix=prefix, tags=["draft-response"])
    app.include_router(metrics.router, prefix=prefix, tags=["metrics"])

    @app.get("/health")
    async def health_check() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
