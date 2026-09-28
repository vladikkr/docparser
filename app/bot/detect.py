"""Work out what the client actually sent us.

Order matters: a fiscal QR is the most reliable signal, an XML root element is
next, and OCR text is the last resort. The ФНС КНД codes below are the
authoritative way to tell a УПД from a счёт-фактура, and `Функция` tells an
original document from a correction.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

# КНД codes published by ФНС (приказ ЕД-7-26/970@, format 5.02/5.03).
KND_UPD = "1115131"  # универсальный передаточный документ
KND_INVOICE = "1115130"  # счёт-фактура

# Функция tells whether this is an original or a corrected document.
ORIGINAL_FUNCTIONS = {"СЧФ", "СЧФДОП", "ДОП"}
CORRECTION_FUNCTIONS = {"ИСЧ", "ИСФДОП", "КСФ", "КСФДОП"}


@dataclass
class Detection:
    """What we think the file is."""

    doc_type: str
    label: str
    source: str
    note: str = ""


def _localname(tag: str) -> str:
    """Strip any XML namespace from a tag name."""
    return tag.rsplit("}", 1)[-1]


def _find_by_localname(element: ET.Element, name: str) -> ET.Element | None:
    for node in element.iter():
        if _localname(node.tag) == name:
            return node
    return None


def detect_xml(data: bytes) -> Detection | None:
    """Read the ФНС XML structure: a <Файл> wrapper around a <Документ>."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None

    root_name = _localname(root.tag)

    if root_name == "СчетФактура":
        return Detection("invoice", "Счёт-фактура", "xml")

    document = root if root_name == "Документ" else _find_by_localname(root, "Документ")
    if document is None:
        return Detection("unknown", "XML (не ФНС)", "xml", note=f"Корень <{root_name}>")

    knd = (document.get("КНД") or "").strip()
    function = (document.get("Функция") or "").strip().upper()

    if knd == KND_UPD:
        if function in CORRECTION_FUNCTIONS:
            return Detection("ukd", "УКД (корректировочный УПД)", "xml", note=f"Функция={function}")
        return Detection("upd", "УПД", "xml", note=f"Функция={function or '—'}")

    if knd == KND_INVOICE:
        if function in CORRECTION_FUNCTIONS:
            return Detection(
                "invoice_correction", "Корректировочный счёт-фактура", "xml", note=f"Функция={function}"
            )
        return Detection("invoice", "Счёт-фактура", "xml")

    return Detection("unknown", "XML (неизвестный КНД)", "xml", note=f"КНД={knd or '—'}")


_PDF_MARKERS: list[tuple[str, str, str]] = [
    (r"ТОРГ[\s\-]?12|товарная\s+накладная", "torg12", "ТОРГ-12"),
    (r"товарно[\s\-]?транспортн|транспортная\s+накладная", "ttn", "Товарно-транспортная накладная"),
    (r"универсальн\w*\s+передаточн|УПД", "upd", "УПД"),
    (r"счет[\s\-]?фактур[аы]|счёт[\s\-]?фактур[аы]", "invoice", "Счёт-фактура"),
    (r"акт\s+выполненных\s+работ|оказанных\s+услуг", "act", "Акт выполненных работ"),
]


def detect_pdf(data: bytes) -> Detection:
    """Look for document names in the text layer of a PDF."""
    from app.services.ocr import ocr_service

    try:
        text = ocr_service.extract_full_text_from_pdf(data)
    except Exception:
        return Detection("unknown", "PDF", "pdf", note="Не удалось прочитать текст")

    if not text:
        return Detection("unknown", "PDF", "pdf", note="Пустой текстовый слой")

    lowered = text.lower()
    for pattern, doc_type, label in _PDF_MARKERS:
        if re.search(pattern, lowered):
            return Detection(doc_type, label, "pdf-text")

    return Detection("unknown", "PDF", "pdf", note="Не опознан по тексту")


def detect_from_qr(qr_string: str) -> Detection:
    """A fiscal QR proves a Russian receipt; a bare id is a Belarusian one."""
    if "fn=" in qr_string and "fp=" in qr_string:
        return Detection("receipt_kkt", "Кассовый чек РФ", "qr", note="Фискальный QR")
    return Detection("receipt_kkt", "Кассовый чек РБ", "qr", note="QR с УИ, ФНС не применим")


def detect(file_bytes: bytes, filename: str | None = None) -> Detection:
    """Best-effort classification of an incoming file."""
    head = file_bytes.lstrip(b"\xef\xbb\xbf \t\r\n")

    if head.startswith(b"%PDF"):
        return detect_pdf(file_bytes)

    if head.startswith(b"<?xml") or head.startswith(b"<") or b"\xef\xbb\xbf<?xml" in head[:64]:
        detection = detect_xml(file_bytes)
        if detection:
            return detection

    # Image: the QR code is the fastest and most reliable read.
    try:
        from app.services.qr import decode_receipt_qr_bytes

        qr_string = decode_receipt_qr_bytes(file_bytes)
        if qr_string:
            return detect_from_qr(qr_string)
    except Exception:
        pass

    return Detection("receipt_kkt", "Кассовый чек", "fallback", note="QR не найден, читаю текст")
