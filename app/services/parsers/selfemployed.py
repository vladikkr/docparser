"""Чек самозанятого (приложение «Мой налог»).

There is no ФНС XML schema for this document: a self-employed receipt is a
printout or a screenshot produced by the "Мой налог" app, so it has to be read
with OCR like a paper receipt. That is not built yet, and the class says so
instead of guessing, because a wrong figure in a tax document is worse than no
figure at all.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.models import Document, DocumentType
from app.services.parsers.base import BaseParser

logger = structlog.get_logger()


class SelfEmployedParser(BaseParser):
    """Заглушка: чек самозанятого ещё не разбирается."""

    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.SELFEMPLOYED]

    async def parse(self, document: Document, file_bytes: bytes) -> dict[str, Any]:
        # `document` is None when the parser is called directly rather than
        # through the task, so its id must not be read unguarded.
        logger.warning(
            "selfemployed_parser_not_implemented",
            document_id=str(document.id) if document is not None else None,
            size=len(file_bytes or b""),
        )
        return {
            "error": (
                "Чек самозанятого пока не разбирается: это печать из приложения "
                "«Мой налог», её нужно читать распознаванием текста."
            ),
            "document_type": DocumentType.SELFEMPLOYED.value,
        }
