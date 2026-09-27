from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentStatus, DocumentType

logger = structlog.get_logger()


class BaseParser(ABC):
    """Abstract base class for document parsers"""

    def __init__(self, db: AsyncSession):
        self.db = db

    @property
    @abstractmethod
    def supported_types(self) -> list[DocumentType]:
        """List of document types this parser supports"""
        pass

    @abstractmethod
    async def parse(self, document: Document, file_bytes: bytes) -> dict[str, Any]:
        """
        Parse document and return structured data
        Should raise DocumentProcessingError on failure
        """
        pass

    async def process(self, document_id: UUID) -> dict[str, Any]:
        """Main entry point - loads document, parses, saves result"""
        document = await self.db.get(Document, document_id)
        if not document:
            raise ValueError(f"Document {document_id} not found")

        if document.document_type not in self.supported_types:
            raise ValueError(f"Parser does not support type {document.document_type}")

        # Update status
        document.status = DocumentStatus.PROCESSING
        await self.db.commit()

        try:
            # TODO: Load file from storage
            # For now, use placeholder
            file_bytes = b""  # Load from Supabase Storage

            # Parse
            parsed_data = await self.parse(document, file_bytes)

            # Save result
            import json
            document.parsed_data = json.dumps(parsed_data, ensure_ascii=False)
            document.status = DocumentStatus.COMPLETED
            document.completed_at = datetime.utcnow()
            await self.db.commit()

            # Dispatch webhook if configured
            if document.webhook_url:
                from app.services.webhook_dispatcher import dispatch_document_webhook
                await dispatch_document_webhook(document)

            logger.info("document_parsed", document_id=str(document_id), type=document.document_type.value)
            return parsed_data

        except Exception as e:
            document.status = DocumentStatus.FAILED
            document.error_message = str(e)
            await self.db.commit()
            logger.error("document_parse_failed", document_id=str(document_id), error=str(e))
            raise


# Import here to avoid circular imports
from datetime import datetime
