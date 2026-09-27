"""Parser for UPD/UKD (Universal Transfer Document) — XML-based ФНС format."""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from typing import Any

from app.models import Document, DocumentType
from app.services.parsers.base import BaseParser


class UPDParser(BaseParser):
    """Parser for UPD/UKD (Universal Transfer Document) — XML-based ФНС format."""

    @property
    def supported_types(self) -> list:
        from app.models import DocumentType
        return [DocumentType.UPD, DocumentType.UKD]

    async def parse(self, document: Document, file_bytes: bytes) -> dict[str, Any]:
        """Parse UPD/UKD XML document."""
        try:
            # Try to parse as XML
            if file_bytes.startswith(b"%PDF"):
                # PDF: try to extract text and find XML
                text = await self._extract_text_from_pdf(file_bytes)
                xml_content = self._extract_xml_from_text(text)
                if not xml_content:
                    return {"error": "No XML found in PDF", "raw_text": text[:5000]}
                root = ET.fromstring(xml_content)
            else:
                # Try to parse as XML directly
                root = ET.fromstring(file_bytes)

            return self._parse_upd_xml(root)
        except ET.ParseError as e:
            return {"error": f"XML parsing failed: {e}", "raw_text": file_bytes[:5000].decode("utf-8", errors="ignore")}
        except Exception as e:
            return {"error": f"Parsing failed: {type(e).__name__}: {e}"}

    def _extract_text_from_pdf(self, file_bytes: bytes) -> str:
        """Extract text from PDF using OCR service."""
        from app.services.ocr import ocr_service
        from PIL import Image
        import io

        if file_bytes.startswith(b"%PDF"):
            images = ocr_service.pdf_to_images(file_bytes)
            if images:
                texts = [ocr_service.extract_full_text(img) for img in images]
                return "\n".join(texts)
        return ""

    def _extract_xml_from_text(self, text: str) -> str | None:
        """Extract XML content from extracted text."""
        # Try to find XML declaration and root element
        xml_start = text.find("<?xml")
        if xml_start == -1:
            xml_start = text.find("<")
        if xml_start == -1:
            return None

        # Try to find the closing tag of the root element
        # Simple approach: find the last closing tag
        last_gt = text.rfind(">")
        if last_gt == -1:
            return None

        return text[xml_start:last_gt + 1]

    def _parse_upd_xml(self, root) -> dict:
        """Parse UPD XML structure."""
        ns = {
            "ns": "urn:1C:ru:ed2:schemas:upd:1.0",
            "xsi": "http://www.w3.org/2001/XMLSchema-instance",
        }

        # Register namespaces for easier parsing
        for prefix, uri in ns.items():
            ET.register_namespace(prefix, uri)

        result = {
            "document_type": "upd",
            "country": "RU",
            "seller": {},
            "buyer": {},
            "items": [],
            "totals": {},
            "raw_xml": ET.tostring(root, encoding="unicode"),
        }

        # Helper to get text from element
        def get_text(element, path, default=""):
            elem = root.find(path, ns)
            return elem.text.strip() if elem is not None and elem.text else default

        def get_attr(element, path, attr, default=""):
            elem = root.find(path, ns)
            return elem.get(attr, default) if elem is not None else default

        # Document info
        result = {
            "document_type": "upd",
            "country": "RU",
            "seller": {},
            "buyer": {},
            "items": [],
            "totals": {},
            "raw_xml": ET.tostring(root, encoding="unicode"),
        }

        # Helper to get text from element
        def get_text(element, path, default=""):
            elem = root.find(path, ns)
            return elem.text.strip() if elem is not None and elem.text else default

        def get_attr(element, path, attr, default=""):
            elem = root.find(path, ns)
            return elem.get(attr, default) if elem is not None else default

        # Document info
        result["document_number"] = get_attr(root, ".", "Номер", "")
        result["document_date"] = get_attr(root, ".", "Дата", "")
        result["function"] = get_attr(root, ".", "Функция", "")

        # Seller (Продавец)
        seller_elem = root.find(".//ns:СвПродавец", ns)
        if seller_elem is not None:
            result["seller"] = {
                "name": get_attr(seller_elem, ".//ns:СвНаимОрг", "НаимОрг", ""),
                "inn": get_attr(seller_elem, ".//ns:СвИНН", "ИНН", ""),
                "kpp": get_attr(seller_elem, ".//ns:СвИНН", "КПП", ""),
            }

        # Buyer (Покупатель)
        buyer_elem = root.find(".//ns:СвПокупатель", ns)
        if buyer_elem is not None:
            result["buyer"] = {
                "name": get_attr(buyer_elem, ".//ns:СвНаимОрг", "НаимОрг", ""),
                "inn": get_attr(buyer_elem, ".//ns:СвИНН", "ИНН", ""),
                "kpp": get_attr(buyer_elem, ".//ns:СвИНН", "КПП", ""),
            }

        # Items (ТаблСчФакт/ТаблСвед)
        items = []
        for item_elem in root.findall(".//ns:ТаблСчФакт/ns:СведТов", ns):
            item = {
                "name": get_attr(item_elem, ".//ns:НаимТов", "НаимТов", ""),
                "quantity": get_attr(item_elem, ".//ns:КолТов", "КолТов", ""),
                "unit": get_attr(item_elem, ".//ns:ЕдИзм", "ЕдИзм", ""),
                "price": get_attr(item_elem, ".//ns:ЦенаТов", "ЦенаТов", ""),
                "sum": get_attr(item_elem, ".//ns:СтТовБезНДС", "СтТовБезНДС", ""),
                "vat_rate": get_attr(item_elem, ".//ns:НалСт", "НалСт", ""),
                "vat_sum": get_attr(item_elem, ".//ns:СумНал", "СумНал", ""),
                "total_with_vat": get_attr(item_elem, ".//ns:СтТовУчНал", "СтТовУчНал", ""),
            }
            items.append(item)

        result["items"] = items

        # Totals (ВсегоОпл/СумНал/СтТовБезНДС/СтТовУчНал)
        totals_elem = root.find(".//ns:ВсегоОпл", ns)
        if totals_elem is not None:
            result["totals"] = {
                "total_with_vat": get_attr(totals_elem, ".", "СтТовУчНалВсего", ""),
                "total_without_vat": get_attr(totals_elem, ".", "СтТовБезНДСВсего", ""),
                "vat_total": get_attr(totals_elem, ".", "СумНалВсего", ""),
            }

        return {
            "country": "RU",
            "document_type": "upd",
            "parsed": result,
            "raw_xml": ET.tostring(root, encoding="unicode"),
        }


class UKDParser(UPDParser):
    """Parser for UKD (Correction UPD) - same structure as UPD."""

    @property
    def supported_types(self):
        from app.models import DocumentType
        return [DocumentType.UKD]


class InvoiceParser:
    """Parser for Invoice (Счёт-фактура) — XML-based ФНС format."""

    @property
    def supported_types(self):
        from app.models import DocumentType
        return [DocumentType.INVOICE, DocumentType.INVOICE_CORRECTION]

    async def parse(self, document, file_bytes):
        """Parse Invoice XML document."""
        try:
            import xml.etree.ElementTree as ET

            if file_bytes.startswith(b"%PDF"):
                # PDF: try to extract text and find XML
                text = await self._extract_text_from_pdf(file_bytes)
                xml_content = self._extract_xml_from_text(text)
                if not xml_content:
                    return {"error": "No XML found in PDF", "raw_text": text[:5000]}
                root = ET.fromstring(xml_content)
            else:
                root = ET.fromstring(file_bytes)

            return self._parse_invoice_xml(root)
        except ET.ParseError as e:
            return {"error": f"XML parsing failed: {e}", "raw_text": file_bytes[:5000].decode("utf-8", errors="ignore")}
        except Exception as e:
            return {"error": f"Parsing failed: {type(e).__name__}: {e}"}

    def _extract_text_from_pdf(self, file_bytes):
        from app.services.ocr import ocr_service
        from PIL import Image
        import io

        if file_bytes.startswith(b"%PDF"):
            images = ocr_service.pdf_to_images(file_bytes)
            if images:
                texts = [ocr_service.extract_full_text(img) for img in images]
                return "\n".join(texts)
        return ""

    def _extract_xml_from_text(self, text):
        xml_start = text.find("<?xml")
        if xml_start == -1:
            xml_start = text.find("<")
        if xml_start == -1:
            return None
        last_gt = text.rfind(">")
        if last_gt == -1:
            return None
        return text[xml_start:last_gt + 1]

    def _parse_invoice_xml(self, root):
        ns = {
            "ns": "urn:1C:ru:ed2:schemas:schet:1.0",
            "xsi": "http://www.w3.org/2001/XMLSchema-instance",
        }

        for prefix, uri in ns.items():
            ET.register_namespace(prefix, uri)

        def get_text(element, path, default=""):
            elem = root.find(path, ns)
            return elem.text.strip() if elem is not None and elem.text else default

        def get_attr(element, path, attr, default=""):
            elem = root.find(path, ns)
            return elem.get(attr, default) if elem is not None else default

        result = {
            "document_type": "invoice",
            "country": "RU",
            "seller": {},
            "buyer": {},
            "items": [],
            "totals": {},
        }

        # Document info
        result["document_number"] = root.get("Номер", "")
        result["document_date"] = root.get("Дата", "")
        result["function"] = root.get("Функция", "")

        # Seller (Продавец)
        seller_elem = root.find(".//ns:СвПродавец", ns)
        if seller_elem is not None:
            result["seller"] = {
                "name": get_attr(seller_elem, ".//ns:СвНаимОрг", "НаимОрг", ""),
                "inn": get_attr(seller_elem, ".//ns:СвИНН", "ИНН", ""),
                "kpp": get_attr(seller_elem, ".//ns:СвИНН", "КПП", ""),
            }

        # Buyer (Покупатель)
        buyer_elem = root.find(".//ns:СвПокупатель", ns)
        if buyer_elem is not None:
            result["buyer"] = {
                "name": get_attr(buyer_elem, ".//ns:СвНаимОрг", "НаимОрг", ""),
                "inn": get_attr(buyer_elem, ".//ns:СвИНН", "ИНН", ""),
                "kpp": get_attr(buyer_elem, ".//ns:СвИНН", "КПП", ""),
            }

        # Items
        items = []
        for item_elem in root.findall(".//ns:ТаблСчФакт/ns:СведТов", ns):
            item = {
                "name": get_attr(item_elem, ".//ns:НаимТов", "НаимТов", ""),
                "quantity": get_attr(item_elem, ".//ns:КолТов", "КолТов", ""),
                "unit": get_attr(item_elem, ".//ns:ЕдИзм", "ЕдИзм", ""),
                "price": get_attr(item_elem, ".//ns:ЦенаТов", "ЦенаТов", ""),
                "sum": get_attr(item_elem, ".//ns:СтТовБезНДС", "СтТовБезНДС", ""),
                "vat_rate": get_attr(item_elem, ".//ns:НалСт", "НалСт", ""),
                "vat_sum": get_attr(item_elem, ".//ns:СумНал", "СумНал", ""),
                "total_with_vat": get_attr(item_elem, ".//ns:СтТовУчНал", "СтТовУчНал", ""),
            }
            items.append(item)

        result["items"] = items

        # Totals
        totals_elem = root.find(".//ns:ВсегоОпл", ns)
        if totals_elem is not None:
            result["totals"] = {
                "total_with_vat": get_attr(totals_elem, ".", "СтТовУчНалВсего", ""),
                "total_without_vat": get_attr(totals_elem, ".", "СтТовБезНДСВсего", ""),
                "vat_total": get_attr(totals_elem, ".", "СумНалВсего", ""),
            }

        return {
            "country": "RU",
            "document_type": "invoice",
            "parsed": result,
        }


# Parser factory
def get_parser(doc_type, db):
    """Get the appropriate parser for a document type."""
    from app.services.parsers.receipt_kkt import ReceiptKKTParser
    from app.services.parsers.receipt_by import parse_belarusian_receipt
    from app.services.ocr import ocr_service

    if doc_type in ("upd", "ukd"):
        return UPDParser(db)
    elif doc_type in ("invoice", "invoice_correction"):
        return InvoiceParser()
    elif doc_type == "receipt_kkt":
        return ReceiptKKTParser(db)
    else:
        # Fallback - raise an error instead of trying to instantiate abstract base
        raise ValueError(f"Unknown document type: {doc_type}")