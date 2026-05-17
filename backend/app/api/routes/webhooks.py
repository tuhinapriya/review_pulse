import secrets
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_author, get_db
from app.db.models import Author, WebhookSubscription
from app.schemas.common import WebhookCreate, WebhookResponse

router = APIRouter()


@router.post("/webhooks", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    body: WebhookCreate,
    current_author: Annotated[Author, Depends(get_current_author)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Register a webhook endpoint (N10).

    The generated secret is returned only once in this response — store it.
    It's used to verify the X-ReviewPulse-Signature header on deliveries.
    """
    # Generate a cryptographically random secret for this subscription.
    # We return it here but never again — the receiver must store it securely.
    secret = secrets.token_hex(32)

    sub = WebhookSubscription(
        author_id=current_author.id,
        url=body.url,
        secret=secret,
        events=body.events,
        created_at=datetime.now(timezone.utc),
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)

    return {
        "id": str(sub.id),
        "url": sub.url,
        "events": sub.events,
        "secret": secret,  # only shown once
        "created_at": sub.created_at.isoformat(),
    }


@router.get("/webhooks", response_model=list[WebhookResponse])
async def list_webhooks(
    current_author: Annotated[Author, Depends(get_current_author)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    result = await db.execute(
        select(WebhookSubscription).where(
            WebhookSubscription.author_id == current_author.id
        )
    )
    subs = result.scalars().all()
    return [
        {
            "id": str(s.id),
            "url": s.url,
            "events": s.events,
            # Don't return the secret after initial creation
            "created_at": s.created_at.isoformat(),
        }
        for s in subs
    ]


@router.delete("/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: UUID,
    current_author: Annotated[Author, Depends(get_current_author)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(
        select(WebhookSubscription).where(
            WebhookSubscription.id == webhook_id,
            WebhookSubscription.author_id == current_author.id,
        )
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")

    await db.delete(sub)
    await db.commit()
