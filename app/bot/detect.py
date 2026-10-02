"""Work out what the client actually sent us.

Order matters: a fiscal QR is the most reliable signal, an XML root element is
next, and OCR text is the last resort.

The КНД code in the published XSDs is the authoritative signal, and it settles
a question that is easy to get wrong: a счёт-фактура and a УПД are the *same*
schema under КНД 1115131 and are told apart by the `Функция` attribute. There
is no separate "счёт-фактура" element. A УПД that only transfers goods carries
`Функция="ДОП"`; one that also carries invoice data carries СЧФ or СЧФДОП.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from app.services.parsers.fns_xml import (
    KND_ACT,
    KND_CORRECTION,
    KND_INVOICE_LIKE,
    KND_INVOICE_LIKE_BUYER,
    KND_TORG12,
    FnsParseError,
    function_of,
    knd_of,
    load_xml,
)

# `Функция` values for the correction formats.
CORRECTION_FUNCTIONS = {"КСЧФ", "КСЧФДИС", "ДИС", "СвИСРК", "СвИСЗК"}



@dataclass
class Detection:
    """What we think the file is."""

    doc_type: str
    label: str
    source: str
    note: str = ""


def detect_xml(data: bytes) -> Detection | None:
    """Read the ФНС XML structure: a <Файл> wrapper around a <Документ>."""
    try:
        root = load_xml(data)
        knd = knd_of(root)
    except FnsParseError:
        return None

    knd = knd_of(root)
    function = function_of(root).upper()

    if knd == KND_INVOICE_LIKE_BUYER:
        return Detection("invoice", "Счёт-фактура (титул покупателя)", "xml")

    if knd == KND_CORRECTION:
        # A УКД and a corrected счёт-фактура share one schema (приказ
        # ЕД-1-26/29@), and nothing in the file says which one the sender
        # meant, so they are reported as the single format they are.
        return Detection(
            "ukd", "УКД / корректировочный счёт-фактура", "xml", note=f"Функция={function}"
        )

    if knd == KND_INVOICE_LIKE:
        # Same schema: only `Функция` says whether this is an invoice or a УПД.
        if function == "СЧФ":
            return Detection("invoice", "Счёт-фактура", "xml")
        return Detection("upd", "УПД", "xml", note=f"Функция={function or '—'}")

    if knd == KND_TORG12:
        return Detection("torg12", "ТОРГ-12", "xml")

    if knd == KND_ACT:
        return Detection("act", "Акт выполненных работ", "xml")

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


def _detect_selfemployed(text: str) -> Detection | None:
    """Tell a self-employed receipt from a кассовый one by its own wording.

    There is no QR register behind it, so the words are the only signal: a
    self-employed receipt always names the НПД, which a cash receipt never does.
    """
    lowered = text.lower()
    for needle in ("нпд", "налог на профессиональный доход", "самозанят"):
        if needle in lowered:
            return Detection(
                "selfemployed", "Чек самозанятого", "ocr-text", note=f"найдено «{needle}»"
            )
    return None


def detect_from_text(text: str) -> Detection | None:
    """Use OCR text to separate a self-employed receipt from a кассовый."""
    if not text or not text.strip():
        return None
    return _detect_selfemployed(text)


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

    # No QR: a self-employed receipt has none, so the wording decides. The OCR
    # pass is slow, so it runs only when nothing else identified the file.
    try:
        from PIL import Image

        from app.services.ocr import ocr_service

        text = ocr_service.extract_full_text(Image.open(io.BytesIO(file_bytes)))
        detected = detect_from_text(text)
        if detected:
            return detected
    except Exception:
        pass

    return Detection("receipt_kkt", "Кассовый чек", "fallback", note="QR не найден, читаю текст")
