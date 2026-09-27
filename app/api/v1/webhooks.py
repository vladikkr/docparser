from uuid import UUID

import stripe
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.database import get_db
from app.models import Document, User
from app.services.stripe_service import handle_stripe_event

logger = structlog.get_logger()

if settings.STRIPE_SECRET_KEY:
    stripe.api_key = settings.STRIPE_SECRET_KEY

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
):
    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        logger.error("stripe_webhook_invalid_payload", error=str(e))
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        logger.error("stripe_webhook_invalid_signature", error=str(e))
        raise HTTPException(status_code=400, detail="Invalid signature")

    logger.info("stripe_webhook_received", event_type=event.type, event_id=event.id)

    try:
        await handle_stripe_event(event, db)
    except Exception as e:
        logger.exception("stripe_webhook_handling_failed", error=str(e))
        # Don't raise - we want to return 200 to Stripe to avoid retries for processing errors
        # But log the error for investigation

    return {"received": True}


@router.post("/document/{document_id}")
async def document_webhook_callback(
    document_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Callback endpoint for clients to receive parsed document results"""
    # This is called by our system to deliver results to client's webhook_url
    # Clients don't call this directly
    pass


# Client-facing webhook management
@router.post("/client", status_code=status.HTTP_201_CREATED)
async def register_client_webhook(
    document_id: UUID,
    webhook_url: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a webhook URL for a specific document"""
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    document.webhook_url = webhook_url
    await db.commit()

    return {"message": "Webhook registered"}


@router.delete("/client/{document_id}")
async def remove_client_webhook(
    document_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    document.webhook_url = None
    await db.commit()

    return {"message": "Webhook removed"}
