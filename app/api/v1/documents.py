import json
import time
import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_key_user, get_current_user
from app.config import settings
from app.core.exceptions import NotFoundError, ValidationError
from app.database import get_db
from app.models import Document, DocumentStatus, DocumentType, User
from app.schemas import (
    DocumentList,
    DocumentResponse,
    DocumentUploadResponse,
    PaginationParams,
    ParseResponse,
)
from app.services import storage
from app.services.dispatcher import dispatch_parse

logger = structlog.get_logger()

router = APIRouter(prefix="/documents", tags=["documents"])


ALLOWED_MIME_TYPES = set(settings.ALLOWED_MIME_TYPES)
MAX_FILE_SIZE = settings.MAX_FILE_SIZE_MB * 1024 * 1024


def validate_file(file: UploadFile) -> None:
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise ValidationError(
            f"Unsupported file type: {file.content_type}. Allowed: {', '.join(ALLOWED_MIME_TYPES)}"
        )
    # Note: actual size check happens after reading


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    document_type: DocumentType | None = Form(None),
    webhook_url: str | None = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    validate_file(file)

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise ValidationError(f"File too large. Max size: {settings.MAX_FILE_SIZE_MB}MB")

    # Determine document type from content if not provided
    if document_type is None:
        document_type = DocumentType.UNKNOWN

    # The bytes have to be on disk before the parse task can read them back.
    storage_path = storage.save(content, str(user.id), file.filename or "upload")

    document = Document(
        user_id=user.id,
        filename=file.filename,
        mime_type=file.content_type,
        file_size=len(content),
        storage_path=storage_path,
        document_type=document_type,
        status=DocumentStatus.PENDING,
        webhook_url=webhook_url,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    # Queue parsing task (Celery if available, otherwise inline)
    mode = dispatch_parse(document.id)

    logger.info(
        "document_uploaded",
        document_id=str(document.id),
        user_id=str(user.id),
        mode=mode,
    )
    return document


@router.post("/parse", response_model=ParseResponse)
async def parse_document_sync(
    file: UploadFile = File(...),
    document_type: DocumentType | None = Form(None),
    return_raw_text: bool = Form(False),
    user: User = Depends(get_api_key_user),
    db: AsyncSession = Depends(get_db),
):
    """Parse a document and return the result in the same request."""
    validate_file(file)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise ValidationError(f"File too large. Max size: {settings.MAX_FILE_SIZE_MB}MB")

    doc_type = document_type or DocumentType.RECEIPT_KKT
    if doc_type == DocumentType.UNKNOWN:
        doc_type = DocumentType.RECEIPT_KKT

    started = time.perf_counter()
    document = Document(
        user_id=user.id,
        filename=file.filename,
        mime_type=file.content_type,
        file_size=len(content),
        storage_path=storage.save(content, str(user.id), file.filename or "upload"),
        document_type=doc_type,
        status=DocumentStatus.PROCESSING,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    parsed_data: dict[str, Any] | None = None
    error: str | None = None
    try:
        from app.services.parsers import get_parser, register_parsers

        register_parsers(db)
        parser = get_parser(doc_type, db)
        if parser is None:
            raise ValueError(f"No parser registered for {doc_type}")
        parsed_data = await parser.parse(document, content)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("inline_parse_error", document_id=str(document.id), error=error)

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    document.parsed_data = json.dumps(parsed_data, ensure_ascii=False) if parsed_data else None
    document.error_message = error
    document.processing_time_ms = elapsed_ms
    document.status = DocumentStatus.FAILED if error else DocumentStatus.COMPLETED
    document.completed_at = datetime.utcnow()
    await db.commit()
    await db.refresh(document)

    return ParseResponse(
        document_id=document.id,
        status=document.status,
        document_type=document.document_type,
        parsed_data=parsed_data,
        raw_text=(parsed_data or {}).get("raw_text") if return_raw_text else None,
        processing_time_ms=elapsed_ms,
    )


@router.get("", response_model=DocumentList)
async def list_documents(
    pagination: PaginationParams = Depends(),
    status_filter: DocumentStatus | None = Query(None),
    type_filter: DocumentType | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Document).where(Document.user_id == user.id)

    if status_filter:
        query = query.where(Document.status == status_filter)
    if type_filter:
        query = query.where(Document.document_type == type_filter)

    # Total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # Paginated results
    query = query.order_by(desc(Document.created_at)).offset(
        (pagination.page - 1) * pagination.page_size
    ).limit(pagination.page_size)

    result = await db.execute(query)
    documents = result.scalars().all()

    return DocumentList(
        documents=[_to_response(d) for d in documents],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=(total + pagination.page_size - 1) // pagination.page_size,
    )


def _to_response(document: Document) -> DocumentResponse:
    """Build the response body.

    `parsed_data` is a JSON string in the database, while the schema expects a
    mapping. Returning the model straight from the ORM made every retrieval of a
    parsed document fail response validation with a 500.
    """
    parsed: dict[str, Any] | None = None
    raw = document.parsed_data
    if raw:
        if isinstance(raw, dict):
            parsed = raw
        else:
            try:
                decoded = json.loads(raw)
            except (TypeError, ValueError):
                logger.warning("parsed_data_unreadable", document_id=str(document.id))
                decoded = None
            parsed = decoded if isinstance(decoded, dict) else None

    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        mime_type=document.mime_type,
        file_size=document.file_size,
        document_type=document.document_type,
        status=document.status,
        parsed_data=parsed,
        error_message=document.error_message,
        processing_time_ms=document.processing_time_ms,
        webhook_status=document.webhook_status,
        created_at=document.created_at,
        updated_at=document.updated_at,
        completed_at=document.completed_at,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise NotFoundError("Document", str(document_id))

    return _to_response(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    document = result.scalar_one_or_none()

    if not document:
        raise NotFoundError("Document", str(document_id))

    await db.delete(document)
    await db.commit()
