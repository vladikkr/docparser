import io
import re
from typing import Any

import structlog

from app.models import Document, DocumentType
from app.services.fn_api import FNSApiError, validate_receipt_by_qr
from app.services.ocr import Image, ocr_service
from app.services.parsers.base import BaseParser

logger = structlog.get_logger()


class ReceiptKKTParser(BaseParser):
    """Parser for Russian KKT receipts (ФЗ-54)"""

    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.RECEIPT_KKT]

    async def parse(self, document: Document, file_bytes: bytes) -> dict[str, Any]:
        # Try to extract QR code from image/PDF
        qr_string = await self._extract_qr_string(file_bytes)

        if qr_string:
            # Validate via FNS API
            try:
                receipt = await validate_receipt_by_qr(qr_string)
                return receipt.model_dump(mode="json")
            except FNSApiError as e:
                logger.warning("fns_validation_failed", error=e.message, code=e.code)
                # Fall back to OCR parsing

        # Fallback: OCR parsing
        return await self._parse_via_ocr(file_bytes)

    async def _extract_qr_string(self, file_bytes: bytes) -> str | None:
        """Extract QR code string from image or PDF"""
        try:
            from app.services.qr import decode_receipt_qr_bytes

            return decode_receipt_qr_bytes(file_bytes)
        except Exception as e:
            logger.debug("qr_extraction_failed", error=str(e))
        return None

    async def _parse_via_ocr(self, file_bytes: bytes) -> dict[str, Any]:
        """Parse receipt using OCR"""
        try:
            if file_bytes.startswith(b"%PDF"):
                text = ocr_service.extract_full_text_from_pdf(file_bytes)
            else:
                image = Image.open(io.BytesIO(file_bytes))
                text = ocr_service.extract_full_text(image)

            return self._parse_receipt_text(text)
        except Exception as e:
            logger.error("ocr_parse_failed", error=str(e))
            return {"error": "OCR parsing failed", "raw_text": text[:5000] if 'text' in locals() else ""}

    def _parse_receipt_text(self, text: str) -> dict[str, Any]:
        """Parse receipt text using regex patterns"""
        result = {
            "raw_text": text,
            "parsed": {},
        }

        # Try to find QR string in text
        qr_match = re.search(r't=\d{4}\d{2}\d{2}T\d{2}\d{2}&s=[\d.]+&fn=\d+&i=\d+&fp=\d+', text)
        if qr_match:
            result["qr_string"] = qr_match.group(0)

        # Extract common fields
        patterns = {
            "fn": r'fn[=:]\s*(\d+)',
            "fd": r'fd[=:]\s*(\d+)',
            "fp": r'fp[=:]\s*(\d+)',
            "date": r'(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})',
            "total": r'(?:ИТОГО|SUM|Тотал)[:\s]*([\d\s.,]+)',
            "seller_name": r'(?:ПРОДАВЕЦ|SELLER|Магазин)[:\s]*([^\n]+)',
            "seller_inn": r'(?:ИНН|INN)[:\s]*(\d{10,12})',
        }

        for field, pattern in patterns.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result["parsed"][field] = match.group(1).strip()

        # Try to parse items
        items = self._parse_items(text)
        if items:
            result["parsed"]["items"] = items

        return result

    def _parse_items(self, text: str) -> list[dict[str, Any]]:
        """Extract items from receipt text"""
        items = []
        # Common pattern: name, quantity, price, sum
        lines = text.split('\n')
        for line in lines:
            # Skip header/footer lines
            if any(skip in line.lower() for skip in ['кассовый', 'чек', 'фискал', 'итого', 'налог', 'nds', 'qr', 'fn=', 'fp=']):
                continue

            # Try to match: name qty x price = sum
            match = re.search(r'(.+?)\s+(\d+[.,]?\d*)\s*[xх]\s*([\d.,]+)\s*=\s*([\d.,]+)', line)
            if match:
                items.append({
                    "name": match.group(1).strip(),
                    "quantity": float(match.group(2).replace(',', '.')),
                    "price": float(match.group(3).replace(',', '.')),
                    "sum": float(match.group(4).replace(',', '.')),
                })

        return items

