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
from app.tasks.parse_tasks import parse_document_task

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

    # TODO: Upload to Supabase Storage / S3
    # For now, store path as local placeholder
    storage_path = f"users/{user.id}/{file.filename}"

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

    # Queue parsing task
    parse_document_task.delay(str(document.id))

    logger.info("document_uploaded", document_id=str(document.id), user_id=str(user.id))
    return document


@router.post("/parse", response_model=ParseResponse)
async def parse_document_sync(
    file: UploadFile = File(...),
    document_type: DocumentType | None = Form(None),
    return_raw_text: bool = Form(False),
    user: User = Depends(get_api_key_user),
    db: AsyncSession = Depends(get_db),
):
    """Synchronous parsing for API key users"""
    validate_file(file)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise ValidationError(f"File too large. Max size: {settings.MAX_FILE_SIZE_MB}MB")

    # TODO: Call parser directly
    # For now, create document and return pending
    document = Document(
        user_id=user.id,
        filename=file.filename,
        mime_type=file.content_type,
        file_size=len(content),
        storage_path=f"users/{user.id}/{file.filename}",
        document_type=document_type or DocumentType.UNKNOWN,
        status=DocumentStatus.PROCESSING,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    # Queue task
    parse_document_task.delay(str(document.id))

    return ParseResponse(
        document_id=document.id,
        status=DocumentStatus.PROCESSING,
        document_type=document.document_type,
        parsed_data=None,
        processing_time_ms=0,
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
        documents=documents,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=(total + pagination.page_size - 1) // pagination.page_size,
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

    return document


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
