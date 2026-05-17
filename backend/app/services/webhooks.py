import json
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import current_unix_timestamp, sign_webhook_payload
from app.db.models import WebhookSubscription

log = get_logger()


async def fire_webhooks(
    db: AsyncSession,
    author_id: UUID,
    event: str,
    payload: dict,
) -> None:
    """Deliver a webhook event to all registered endpoints for an author.

    Delivery is fire-and-forget: failures are logged but don't propagate to
    the caller. In a production system you'd want a retry queue (dead-letter
    store + Celery retries) and delivery status tracking. For this demo, a
    single best-effort attempt is sufficient to demonstrate the mechanism.
    """
    try:
        result = await db.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.author_id == author_id,
                WebhookSubscription.events.contains([event]),
            )
        )
        subscriptions = result.scalars().all()
    except Exception as exc:
        log.error(
            "Webhook subscription lookup failed",
            author_id=str(author_id),
            event=event,
            error=str(exc),
            exc_info=True,
        )
        return

    if not subscriptions:
        return

    timestamp = current_unix_timestamp()
    body = json.dumps({"event": event, "data": payload}, separators=(",", ":"))

    async with httpx.AsyncClient(timeout=10.0) as client:
        for sub in subscriptions:
            signature = sign_webhook_payload(sub.secret, timestamp, body)
            try:
                resp = await client.post(
                    sub.url,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-ReviewPulse-Signature": f"sha256={signature}",
                        "X-ReviewPulse-Timestamp": timestamp,
                        "X-ReviewPulse-Event": event,
                    },
                )
                log.info(
                    "Webhook delivered",
                    webhook_id=str(sub.id),
                    event=event,
                    status_code=resp.status_code,
                )
            except Exception as exc:
                log.error(
                    "Webhook delivery failed",
                    webhook_id=str(sub.id),
                    url=sub.url,
                    event=event,
                    error=str(exc),
                )
