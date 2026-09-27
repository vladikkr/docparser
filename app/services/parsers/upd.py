from typing import Any

import structlog

from app.models import Document, DocumentType
from app.services.parsers.base import BaseParser

logger = structlog.get_logger()


class UPDParser(BaseParser):
    """Parser for УПД/УКД (Универсальный передаточный документ)"""

    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.UPD, DocumentType.UKD]

    async def parse(self, document: Document, file_bytes: bytes) -> dict[str, Any]:
        # TODO: Implement UPD parsing
        # - XML parsing for structured UPD
        # - PDF layout analysis for printed UPD
        # - Extract: seller/buyer info, items table, VAT breakdown, totals

        logger.warning("upd_parser_not_implemented", document_id=str(document.id))
        return {
            "error": "UPD parser not yet implemented",
            "document_type": document.document_type.value,
        }


class UKDParser(UPDParser):
    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.UKD]
