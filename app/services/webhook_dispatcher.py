import json
from datetime import datetime

import httpx
import structlog

from app.config import settings
from app.models import Document, DocumentStatus

logger = structlog.get_logger()


async def dispatch_document_webhook(document: Document) -> bool:
    """Send parsed document result to client's webhook URL"""
    if not document.webhook_url:
        return False

    if document.status != DocumentStatus.COMPLETED:
        return False

    payload = {
        "event": "document.parsed",
        "timestamp": datetime.utcnow().isoformat(),
        "document": {
            "id": str(document.id),
            "filename": document.filename,
            "document_type": document.document_type.value,
            "status": document.status.value,
            "parsed_data": json.loads(document.parsed_data) if document.parsed_data else None,
            "processing_time_ms": document.processing_time_ms,
            "created_at": document.created_at.isoformat() if document.created_at else None,
            "completed_at": document.completed_at.isoformat() if document.completed_at else None,
        },
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "DocParser.ru Webhook/1.0",
        "X-DocParser-Event": "document.parsed",
        "X-DocParser-Document-ID": str(document.id),
        "X-DocParser-Signature": _generate_signature(payload),
    }

    for attempt in range(settings.WEBHOOK_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=settings.WEBHOOK_TIMEOUT) as client:
                response = await client.post(
                    document.webhook_url,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()

                document.webhook_status = "delivered"
                document.webhook_attempts = attempt + 1
                document.webhook_last_attempt = datetime.utcnow()
                logger.info("webhook_delivered", document_id=str(document.id), attempt=attempt + 1)
                return True

        except httpx.HTTPStatusError as e:
            logger.warning(
                "webhook_http_error",
                document_id=str(document.id),
                attempt=attempt + 1,
                status_code=e.response.status_code,
            )
        except httpx.RequestError as e:
            logger.warning(
                "webhook_request_error",
                document_id=str(document.id),
                attempt=attempt + 1,
                error=str(e),
            )

        # Wait before retry
        if attempt < settings.WEBHOOK_MAX_RETRIES - 1:
            import asyncio
            delay = settings.WEBHOOK_RETRY_DELAYS[attempt] if attempt < len(settings.WEBHOOK_RETRY_DELAYS) else 60
            await asyncio.sleep(delay)

    document.webhook_status = "failed"
    document.webhook_attempts = settings.WEBHOOK_MAX_RETRIES
    document.webhook_last_attempt = datetime.utcnow()
    logger.error("webhook_failed_after_retries", document_id=str(document.id))
    return False


def _generate_signature(payload: dict) -> str:
    """Generate HMAC signature for webhook verification"""
    import hashlib
    import hmac

    secret = settings.STRIPE_WEBHOOK_SECRET  # Reuse secret or add dedicated one
    payload_bytes = json.dumps(payload, sort_keys=True).encode()
    signature = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={signature}"


async def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify incoming webhook signature"""
    expected = _generate_signature(json.loads(payload))
    return hmac.compare_digest(expected, signature)
