import hashlib
import hmac
import json

import httpx
import structlog

from app.config import settings
from app.models import Document, DocumentStatus
from app.utils.helpers import utcnow

logger = structlog.get_logger()


async def dispatch_document_webhook(document: Document) -> bool:
    """Send parsed document result to client's webhook URL"""
    if not document.webhook_url:
        return False

    if document.status != DocumentStatus.COMPLETED:
        return False

    payload = {
        "event": "document.parsed",
        "timestamp": utcnow().isoformat(),
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

    # Sign the exact bytes that go on the wire. The payload used to be signed
    # after one re-serialisation while httpx serialised it again on the way out,
    # so the two byte strings differed and the verification documented in
    # docs/webhook_guide.md, which uses the raw request body, never matched.
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "DocParser.ru Webhook/1.0",
        "X-DocParser-Event": "document.parsed",
        "X-DocParser-Document-ID": str(document.id),
        "X-DocParser-Signature": sign_body(body),
    }

    for attempt in range(settings.WEBHOOK_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=settings.WEBHOOK_TIMEOUT) as client:
                response = await client.post(
                    document.webhook_url,
                    content=body,
                    headers=headers,
                )
                response.raise_for_status()

                document.webhook_status = "delivered"
                document.webhook_attempts = attempt + 1
                document.webhook_last_attempt = utcnow()
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
    document.webhook_last_attempt = utcnow()
    logger.error("webhook_failed_after_retries", document_id=str(document.id))
    return False


def sign_body(body: bytes) -> str:
    """HMAC-SHA256 of the exact request body, as documented for customers.

    Customers verify against the raw body they received, so this must take
    bytes rather than a dict: re-serialising a dict here is how the signature
    and the body drifted apart in the first place.
    """
    secret = settings.WEBHOOK_SIGNING_SECRET
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _generate_signature(payload: dict) -> str:
    """Sign a payload dict. Kept for the docs and for tests."""
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return sign_body(body)


async def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify a signature against the raw request body."""
    if not signature or not signature.startswith("sha256="):
        return False
    return hmac.compare_digest(sign_body(payload), signature)
