from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlparse

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.db.models import Author
from app.db.session import get_db

log = get_logger()
security = HTTPBearer(auto_error=False)


async def get_current_author(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Author:
    """Validate a Supabase JWT and return the corresponding Author record.

    We validate locally using the Supabase JWT secret (HS256) rather than
    calling Supabase on every request. This is faster, more resilient to
    Supabase downtime, and the standard pattern for Supabase server-side auth.

    The JWT secret lives in SUPABASE_JWT_SECRET (project settings → API → JWT).
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        log.warning("Authentication failed", reason="missing_bearer_token")
        raise credentials_exception

    token_header: dict | None = None
    try:
        token_header = jwt.get_unverified_header(credentials.credentials)
        token_alg = token_header.get("alg")
        if token_alg == "HS256":
            payload = jwt.decode(
                credentials.credentials,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                # Supabase sets audience to "authenticated" but we're lenient here
                # to work with both Supabase JWTs and any custom tokens in testing.
                options={"verify_aud": False},
            )
        else:
            payload = await _validate_token_with_supabase(
                credentials.credentials,
                token_alg=token_alg,
            )
        supabase_uid: str | None = payload.get("sub")
        if supabase_uid is None:
            log.warning(
                "Authentication failed",
                reason="jwt_missing_sub",
                token_alg=token_header.get("alg"),
                token_typ=token_header.get("typ"),
            )
            raise credentials_exception
    except JWTError as exc:
        log.warning(
            "Authentication failed",
            reason="jwt_decode_failed",
            error=str(exc),
            token_alg=token_header.get("alg") if token_header else None,
            token_typ=token_header.get("typ") if token_header else None,
        )
        raise credentials_exception from exc

    result = await db.execute(
        select(Author).where(Author.supabase_uid == supabase_uid)
    )
    author = result.scalar_one_or_none()

    if author is None:
        log.warning("Authenticated user not found in DB", supabase_uid=supabase_uid)
        raise credentials_exception

    # Update last_login_at at most once per hour to avoid a DB write on every
    # API request. The previous value is preserved in previous_last_login_at
    # so the "since last login" feature (F8) always has a sensible reference point.
    now = datetime.now(UTC)
    needs_update = (
        author.last_login_at is None
        or (now - author.last_login_at.replace(tzinfo=UTC)) > timedelta(hours=1)
    )
    if needs_update:
        await db.execute(
            update(Author)
            .where(Author.id == author.id)
            .values(
                previous_last_login_at=Author.last_login_at,
                last_login_at=now,
            )
        )
        await db.commit()
        author.previous_last_login_at = author.last_login_at
        author.last_login_at = now

    return author


async def _validate_token_with_supabase(token: str, token_alg: str | None) -> dict:
    supabase_url = settings.supabase_url.strip().rstrip("/")
    parsed = urlparse(supabase_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        log.warning(
            "Authentication failed",
            reason="supabase_url_not_configured_for_token_validation",
            token_alg=token_alg,
        )
        raise JWTError("Supabase URL is not configured")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{supabase_url}/auth/v1/user",
                headers={
                    "apikey": settings.supabase_anon_key,
                    "Authorization": f"Bearer {token}",
                },
            )
    except httpx.RequestError as exc:
        log.warning(
            "Authentication failed",
            reason="supabase_user_validation_request_failed",
            token_alg=token_alg,
            error=str(exc),
        )
        raise JWTError("Supabase user validation request failed") from exc

    if resp.status_code != 200:
        detail = _auth_error_detail(resp)
        log.warning(
            "Authentication failed",
            reason="supabase_user_validation_rejected",
            token_alg=token_alg,
            status_code=resp.status_code,
            detail=detail,
        )
        raise JWTError("Supabase rejected bearer token")

    user = resp.json()
    user_id = user.get("id")
    if not isinstance(user_id, str) or not user_id:
        log.warning(
            "Authentication failed",
            reason="supabase_user_response_missing_id",
            token_alg=token_alg,
        )
        raise JWTError("Supabase user response missing id")

    log.info("Bearer token validated with Supabase", token_alg=token_alg)
    return {"sub": user_id}


def _auth_error_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return resp.text[:200]

    if isinstance(data, dict):
        detail = data.get("msg") or data.get("message") or data.get("error_description")
        if isinstance(detail, str) and detail:
            return detail

    return str(data)[:200]
