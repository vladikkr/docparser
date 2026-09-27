import structlog

from app.models import Document, DocumentType
from app.services.parsers.base import BaseParser

logger = structlog.get_logger()


class InvoiceParser(BaseParser):
    """Parser for Счёт-фактура / ИСФ"""

    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.INVOICE, DocumentType.INVOICE_CORRECTION]

    async def parse(self, document: Document, file_bytes: bytes) -> Dict[str, Any]:
        logger.warning("invoice_parser_not_implemented", document_id=str(document.id))
        return {
            "error": "Invoice parser not yet implemented",
            "document_type": document.document_type.value,
        }


class InvoiceCorrectionParser(InvoiceParser):
    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.INVOICE_CORRECTION]
