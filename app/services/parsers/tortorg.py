import structlog

from app.models import Document, DocumentType
from app.services.parsers.base import BaseParser

logger = structlog.get_logger()


class Torg12Parser(BaseParser):
    """Parser for ТОРГ-12 / ТТН"""

    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.TORG12, DocumentType.TTN]

    async def parse(self, document: Document, file_bytes: bytes) -> Dict[str, Any]:
        logger.warning("tortorg_parser_not_implemented", document_id=str(document.id))
        return {
            "error": "TORG-12/TTN parser not yet implemented",
            "document_type": document.document_type.value,
        }


class TTNParser(Torg12Parser):
    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.TTN]
