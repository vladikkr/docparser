import structlog

from app.models import Document, DocumentType
from app.services.parsers.base import BaseParser

logger = structlog.get_logger()


class SelfEmployedParser(BaseParser):
    """Parser for Чек самозанятого (Мой Налог)"""

    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.SELFEMPLOYED]

    async def parse(self, document: Document, file_bytes: bytes) -> Dict[str, Any]:
        logger.warning("selfemployed_parser_not_implemented", document_id=str(document.id))
        return {
            "error": "Self-employed receipt parser not yet implemented",
            "document_type": document.document_type.value,
        }
