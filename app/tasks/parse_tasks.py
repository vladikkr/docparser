import asyncio
from uuid import UUID

import structlog
from celery import shared_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import Document, DocumentStatus
from app.services import storage
from app.services.parsers import get_parser, register_parsers

logger = structlog.get_logger()

# Create async engine for Celery tasks
_task_engine = None
_task_session_maker = None


def get_task_db() -> AsyncSession:
    global _task_engine, _task_session_maker
    if _task_engine is None:
        _task_engine = create_async_engine(
            str(settings.DATABASE_URL),
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )
        _task_session_maker = async_sessionmaker(
            _task_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _task_session_maker()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def parse_document_task(self, document_id: str):
    """Parse document asynchronously."""
    try:
        return asyncio.run(_parse_document_async(document_id))
    except Exception as exc:
        # Retrying lives here because only the bound task has `self`.
        logger.warning("parse_task_retry", document_id=document_id, error=str(exc))
        if self.request.retries >= self.max_retries:
            raise
        raise self.retry(exc=exc, countdown=2**self.request.retries * 60) from exc


async def _parse_document_async(document_id: str):
    doc_uuid = UUID(document_id)
    db = get_task_db()

    try:
        async with db as session:
            # Get document
            from sqlalchemy import select
            result = await session.execute(select(Document).where(Document.id == doc_uuid))
            document = result.scalar_one_or_none()

            if not document:
                logger.error("document_not_found", document_id=document_id)
                return {"error": "Document not found"}

            if document.status == DocumentStatus.COMPLETED:
                logger.info("document_already_parsed", document_id=document_id)
                return {"status": "already_completed"}

            # Initialize parsers
            register_parsers(session)

            # Get parser
            parser = get_parser(document.document_type, session)
            if not parser:
                document.status = DocumentStatus.FAILED
                document.error_message = f"No parser for document type: {document.document_type}"
                await session.commit()
                return {"error": "No parser available"}

            # Load the file that /upload put on disk. Without this the parser
            # received an empty buffer and could never succeed.
            try:
                file_bytes = storage.read(document.storage_path)
            except storage.StorageError as exc:
                document.status = DocumentStatus.FAILED
                document.error_message = str(exc)
                await session.commit()
                logger.error("document_file_unavailable", document_id=document_id, error=str(exc))
                return {"error": str(exc)}

            # Parse
            import time
            start_time = time.time()
            parsed_data = await parser.parse(document, file_bytes)
            processing_time = int((time.time() - start_time) * 1000)

            # Save result
            import json
            document.parsed_data = json.dumps(parsed_data, ensure_ascii=False)
            document.status = DocumentStatus.COMPLETED
            document.processing_time_ms = processing_time
            document.completed_at = utcnow()
            await session.commit()

            # Dispatch webhook
            if document.webhook_url:
                from app.services.webhook_dispatcher import dispatch_document_webhook
                await dispatch_document_webhook(document)

            logger.info("document_parsed_success", document_id=document_id, time_ms=processing_time)
            return {"status": "completed", "processing_time_ms": processing_time}

    except Exception as e:
        logger.exception("document_parse_failed", document_id=document_id, error=str(e))

        # Mark the document failed so the client can see why.
        async with db as session:
            result = await session.execute(select(Document).where(Document.id == doc_uuid))
            document = result.scalar_one_or_none()
            if document:
                document.status = DocumentStatus.FAILED
                document.error_message = str(e)
                await session.commit()

        # Re-raised as a plain exception: the retry policy lives in the Celery
        # task, which has a `self`. A bare function has no `self` to retry with.
        raise


@shared_task
def retry_failed_documents():
    """Retry failed documents (scheduled task)"""
    return asyncio.run(_retry_failed_async())


async def _retry_failed_async():
    db = get_task_db()
    async with db as session:
        result = await session.execute(
            select(Document)
            .where(Document.status == DocumentStatus.FAILED)
            .limit(50)
        )
        documents = result.scalars().all()

        for doc in documents:
            # Reset to pending for retry
            doc.status = DocumentStatus.PENDING
            doc.error_message = None
            await session.commit()

            # Queue parse task
            parse_document_task.delay(str(doc.id))

        logger.info("retry_failed_documents_queued", count=len(documents))
        return {"retried": len(documents)}



from app.utils.helpers import utcnow
