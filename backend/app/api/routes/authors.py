from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_author
from app.config import _is_missing_or_placeholder, auth_config_issues, settings
from app.core.logging import get_logger
from app.db.models import Author
from app.db.session import get_db
from app.schemas.author import AuthorCreate, AuthorLogin, AuthorLoginResponse, AuthorResponse
from app.schemas.book import BookWithStats

router = APIRouter()
log = get_logger()


@router.post(
    "/register",
    response_model=AuthorLoginResponse,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/authors/register",
    response_model=AuthorLoginResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_author(
    body: AuthorCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Register a new author account via Supabase Auth (F1).

    Creates the Supabase Auth user first, then creates our Author record
    linking to it. If the DB insert fails after Supabase succeeds, the
    user is left in a half-created state — acceptable for a demo; in
    production you'd wrap this in a Supabase Auth hook or use a saga pattern.
    """
    # Check for existing email to give a clear error before hitting Supabase
    existing = await db.execute(select(Author).where(Author.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    # Create Supabase Auth user
    supabase_user, access_token = await _supabase_sign_up(body.email, body.password)

    author = Author(
        email=body.email,
        name=body.name,
        supabase_uid=supabase_user["id"],
        created_at=datetime.now(UTC),
    )
    db.add(author)
    await db.commit()
    await db.refresh(author)

    log.info("Author registered", author_id=str(author.id), email=author.email)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "author": author,
    }


@router.post("/login", response_model=AuthorLoginResponse)
@router.post("/authors/login", response_model=AuthorLoginResponse)
async def login_author(
    body: AuthorLogin,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Authenticate an author and return a Supabase JWT."""
    access_token, supabase_uid = await _supabase_sign_in(body.email, body.password)

    result = await db.execute(select(Author).where(Author.supabase_uid == supabase_uid))
    author = result.scalar_one_or_none()

    if author is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    return {"access_token": access_token, "token_type": "bearer", "author": author}


@router.get("/authors/me", response_model=AuthorResponse)
async def get_me(
    current_author: Annotated[Author, Depends(get_current_author)],
) -> Author:
    return current_author


@router.get("/authors/me/books", response_model=list[BookWithStats])
async def list_my_books_with_stats(
    current_author: Annotated[Author, Depends(get_current_author)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    return await _list_books_with_stats(str(current_author.id), db)


@router.get("/authors/{author_id}/books", response_model=list[BookWithStats])
async def list_books_with_stats(
    author_id: str,
    current_author: Annotated[Author, Depends(get_current_author)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    """Return the author's catalog with aggregated stats for the catalog view."""
    if str(current_author.id) != author_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return await _list_books_with_stats(author_id, db)


async def _list_books_with_stats(author_id: str, db: AsyncSession) -> list[dict]:
    from sqlalchemy import text

    result = await db.execute(
        text("""
            SELECT
                b.id, b.author_id, b.title, b.isbn, b.url, b.created_at,
                COUNT(r.id) AS review_count,
                ROUND(AVG(r.rating)::numeric, 2) AS avg_rating,
                ROUND(
                    SUM(CASE WHEN r.sentiment = 'positive' THEN 1 ELSE 0 END)::numeric
                    / NULLIF(COUNT(r.id), 0), 4
                ) AS positive_pct,
                ROUND(SUM(COALESCE(r.cost_usd, 0))::numeric, 6) AS total_cost_usd,
                MAX(j.completed_at) AS last_ingested_at
            FROM books b
            LEFT JOIN reviews r ON r.book_id = b.id
            LEFT JOIN ingestion_jobs j ON j.book_id = b.id AND j.status = 'completed'
            WHERE b.author_id = :author_id
            GROUP BY b.id
            ORDER BY b.created_at DESC
        """),
        {"author_id": author_id},
    )
    return [dict(row) for row in result.mappings().all()]


# ── Supabase Auth helpers ─────────────────────────────────────────────────────

GENERIC_REGISTRATION_ERROR = "Could not create account. Please try again later."
GENERIC_AUTH_SERVICE_ERROR = "Authentication service is unavailable. Please try again later."


def _supabase_auth_url(path: str) -> str:
    supabase_url = settings.supabase_url.strip().rstrip("/")
    parsed = urlparse(supabase_url)
    config_issues = auth_config_issues()

    if config_issues or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        log.warning("Supabase auth is not configured", issues=config_issues)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is not configured. Please contact support.",
        )

    return f"{supabase_url}{path}"


def _supabase_admin_enabled() -> bool:
    return (
        settings.use_supabase_admin_signup
        and not _is_missing_or_placeholder(settings.supabase_service_key)
    )


def _supabase_error_detail(resp: httpx.Response, fallback: str) -> str:
    try:
        data = resp.json()
    except ValueError:
        return fallback

    if isinstance(data, dict):
        detail = data.get("msg") or data.get("message") or data.get("error_description")
        if isinstance(detail, str) and detail:
            return detail

    return fallback


def _log_supabase_rejection(
    *,
    operation: str,
    endpoint: str,
    status_code: int,
    detail: str,
    email: str | None = None,
) -> None:
    log.warning(
        "Supabase auth call rejected",
        operation=operation,
        endpoint=endpoint,
        status_code=status_code,
        detail=detail,
        email=email,
        supabase_url_host=urlparse(settings.supabase_url).netloc,
        anon_key_configured=bool(settings.supabase_anon_key.strip()),
        service_key_configured=bool(settings.supabase_service_key.strip()),
        admin_signup_enabled=_supabase_admin_enabled(),
    )


async def _supabase_sign_up(email: str, password: str) -> tuple[dict, str]:
    if _supabase_admin_enabled():
        return await _supabase_admin_create_and_sign_in(email, password)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _supabase_auth_url("/auth/v1/signup"),
                json={"email": email, "password": password},
                headers={
                    "apikey": settings.supabase_anon_key,
                    "Content-Type": "application/json",
                },
            )
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        log.error(
            "Supabase auth request failed",
            operation="signup",
            endpoint="/auth/v1/signup",
            error=str(exc),
            email=email,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=GENERIC_AUTH_SERVICE_ERROR,
        ) from exc

    if resp.status_code not in (200, 201):
        detail = _supabase_error_detail(resp, "Registration failed")
        _log_supabase_rejection(
            operation="signup",
            endpoint="/auth/v1/signup",
            status_code=resp.status_code,
            detail=detail,
            email=email,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GENERIC_REGISTRATION_ERROR,
        )

    data = resp.json()
    session = data.get("session") or {}
    access_token = data.get("access_token") or session.get("access_token")
    user = data.get("user")

    if not user or not access_token:
        log.error("Supabase signup response missing user or access token")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Authentication service returned an invalid response.",
        )

    return user, access_token


async def _supabase_admin_create_and_sign_in(email: str, password: str) -> tuple[dict, str]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _supabase_auth_url("/auth/v1/admin/users"),
                json={
                    "email": email,
                    "password": password,
                    "email_confirm": True,
                },
                headers={
                    "apikey": settings.supabase_service_key,
                    "Authorization": f"Bearer {settings.supabase_service_key}",
                    "Content-Type": "application/json",
                },
            )
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        log.error(
            "Supabase auth request failed",
            operation="admin_create_user",
            endpoint="/auth/v1/admin/users",
            error=str(exc),
            email=email,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=GENERIC_AUTH_SERVICE_ERROR,
        ) from exc

    if resp.status_code not in (200, 201):
        detail = _supabase_error_detail(resp, "Registration failed")
        _log_supabase_rejection(
            operation="admin_create_user",
            endpoint="/auth/v1/admin/users",
            status_code=resp.status_code,
            detail=detail,
            email=email,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GENERIC_REGISTRATION_ERROR,
        )

    user = resp.json()
    access_token, user_id = await _supabase_sign_in(email, password)
    if user.get("id") != user_id:
        log.error("Supabase admin user id did not match login user id")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Authentication service returned an invalid response.",
        )

    log.info("Supabase admin signup succeeded", user_id=user_id)
    return user, access_token


async def _supabase_sign_in(email: str, password: str) -> tuple[str, str]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _supabase_auth_url("/auth/v1/token?grant_type=password"),
                json={"email": email, "password": password},
                headers={
                    "apikey": settings.supabase_anon_key,
                    "Content-Type": "application/json",
                },
            )
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        log.error(
            "Supabase auth request failed",
            operation="login",
            endpoint="/auth/v1/token?grant_type=password",
            error=str(exc),
            email=email,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=GENERIC_AUTH_SERVICE_ERROR,
        ) from exc

    if resp.status_code != 200:
        detail = _supabase_error_detail(resp, "Invalid email or password")
        _log_supabase_rejection(
            operation="login",
            endpoint="/auth/v1/token?grant_type=password",
            status_code=resp.status_code,
            detail=detail,
            email=email,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    data = resp.json()
    access_token = data.get("access_token")
    user_id = (data.get("user") or {}).get("id")

    if not access_token or not user_id:
        log.error("Supabase login response missing user or access token")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Authentication service returned an invalid response.",
        )

    return access_token, user_id
