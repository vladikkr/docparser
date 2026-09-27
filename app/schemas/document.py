from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, HttpUrl


class DocumentType(str, Enum):
    RECEIPT_KKT = "receipt_kkt"
    UPD = "upd"
    UKD = "ukd"
    INVOICE = "invoice"
    INVOICE_CORRECTION = "invoice_correction"
    ACT = "act"
    TORG12 = "torg12"
    TTN = "ttn"
    SELFEMPLOYED = "selfemployed"
    UNKNOWN = "unknown"


class DocumentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    mime_type: str
    file_size: int
    document_type: DocumentType
    status: DocumentStatus
    created_at: datetime


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    mime_type: str
    file_size: int
    document_type: DocumentType
    status: DocumentStatus
    parsed_data: dict[str, Any] | None
    error_message: str | None
    processing_time_ms: int | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class DocumentList(BaseModel):
    documents: list[DocumentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ParseRequest(BaseModel):
    document_type: DocumentType | None = None
    webhook_url: HttpUrl | None = None
    return_raw_text: bool = False


class ParseResponse(BaseModel):
    document_id: UUID
    status: DocumentStatus
    document_type: DocumentType
    parsed_data: dict[str, Any] | None
    raw_text: str | None = None
    processing_time_ms: int
