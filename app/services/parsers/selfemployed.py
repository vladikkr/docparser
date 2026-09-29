"""Чек самозанятого — печать или скриншот из приложения «Мой налог».

Unlike a кассовый чек this document has no QR naming a fiscal record and no
ФНС register to check it against, so what we add here is arithmetic. A self
employed person's tax is their own liability, and the one thing worth verifying
is that the printed НПД really is the stated percentage of the amount, and that
the total really is cost plus tax. A receipt that fails that check is a receipt
the client should not accept, so the parse says so instead of passing the
numbers through.
"""

from __future__ import annotations

import io
import re
from typing import Any

import structlog

from app.models import Document, DocumentType
from app.services.parsers.base import BaseParser
from app.services.parsers.receipt_by import _canon, _clean_lines, _label_value, _money

logger = structlog.get_logger()

# «Мой налог» has used both the long and the short wording over time.
COST_LABELS = (
    "Стоимость товаров (работ, услуг)",
    "Стоимость товаров, работ, услуг",
    "Стоимость товаров",
    "Стоимость работ, услуг",
    "Стоимость",
)
NPD_LABELS = ("НПД", "Налог на профессиональный доход", "Налог")
TOTAL_LABELS = ("Итого к оплате", "Итого", "Всего к оплате", "К оплате")
INN_LABELS = ("ИНН получателя", "ИНН")

RATE_RE = re.compile(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%")
AMOUNT_RE = re.compile(r"\d[\d\s., ]*\d|\d")
# A single digit is enough for «6%», so the percent must not require two.
PERCENT_RE = re.compile(r"\d[\d\s., ]*%")
DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{2,4})\b")
NUMBER_RE = re.compile(r"(?:№|N|No)\s*([0-9A-Za-zА-Яа-я][0-9A-Za-zА-Яа-я\-/]{2,})")
WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]{2,}")

# Words that appear on the receipt but describe no purchasable thing.
BOILERPLATE = (
    "чек",
    "чек на получение денежных средств",
    "получатель",
    "отправитель",
    "всего",
    "итого",
    "ндс не облагается",
    "ндс не предусмотрен",
    "самозанятость",
    "налог на профессиональный доход",
    "стоимость",
    "стоимость товаров",
    "стоимость работ, услуг",
    "стоимость товаров (работ, услуг)",
    "стоимость товаров, работ, услуг",
    "ндп",
    "налог",
    "итого",
    "итого к оплате",
    "всего к оплате",
    "к оплате",
    "инн",
    "инн получателя",
    "ип",
)


def _tail_after_label(line: str, label: str) -> str | None:
    """The part of a line that follows a label, or None when it is absent."""
    canon = _canon(line)
    needle = _canon(label)
    index = canon.lower().find(needle.lower())
    if index == -1:
        return None
    return line[index + len(label) :].lstrip(" .:;№-—")


def _labelled_money(lines: list[str], labels: tuple[str, ...]) -> float | None:
    """The first amount printed next to any of these labels.

    Percentages are removed first, so a line reading «НПД 6%» yields no amount
    rather than a mistaken 6.00.
    """
    for line in lines:
        for label in labels:
            tail = _tail_after_label(line, label)
            if not tail:
                continue
            cleaned = PERCENT_RE.sub(" ", tail)
            match = AMOUNT_RE.search(cleaned)
            if match:
                value = _money(match.group(0))
                if value is not None:
                    return value
    return None


def _rate(lines: list[str]) -> float | None:
    """The НПД rate, 4% or 6%, wherever the receipt happens to print it."""
    for line in lines:
        match = RATE_RE.search(_canon(line))
        if match:
            return _money(match.group(1))
    return None


def _find_date(lines: list[str]) -> str | None:
    for line in lines:
        match = DATE_RE.search(line)
        if match:
            day, month, year = match.groups()
            if len(year) == 2:
                year = "20" + year
            return f"{int(day):02d}.{int(month):02d}.{year}"
    return None


def _find_number(lines: list[str]) -> str | None:
    for line in lines:
        match = NUMBER_RE.search(line)
        if match:
            return match.group(1).strip()
    return None


def _person(lines: list[str]) -> str | None:
    """The recipient's name, printed above or beside the ИНН."""
    for line in lines:
        canon = _canon(line).strip()
        if canon.startswith("ИП") and WORD_RE.search(canon):
            name = canon[2:].strip(" .:;-")
            if len(name) > 3:
                return name
    return None


def _purpose(lines: list[str], person: str | None) -> str | None:
    """The free-text description of what was sold, when the receipt carries one.

    A line qualifies only if it is prose: any line holding a digit belongs to a
    field already parsed above, so a number here would be a false positive. The
    recipient's own name is prose too, so it is excluded explicitly.
    """
    for line in lines:
        stripped = line.strip()
        if len(stripped) < 4 or stripped.lower() in BOILERPLATE:
            continue
        if not WORD_RE.search(stripped) or any(ch.isdigit() for ch in stripped):
            continue
        if any(symbol in stripped for symbol in "%№"):
            continue
        if _canon(stripped).startswith("ИП"):
            continue
        if person and _canon(stripped) == _canon(person):
            continue
        return stripped
    return None


def _reconcile(data: dict[str, Any]) -> bool | None:
    """Check that the tax and the total follow from the cost.

    None means there was not enough on the page to decide, which is not the
    same as passing. Every missing field is reported, so a partly legible
    receipt tells the client everything that was lost rather than the first
    thing that was.
    """
    warnings: list[str] = data["warnings"]
    cost, rate = data["cost"], data["npd_rate"]
    npd, total = data["npd_sum"], data["total_sum"]

    verdicts: list[bool] = []

    if rate is not None and cost is not None:
        expected_npd = round(cost * rate / 100, 2)
        if npd is None:
            warnings.append("Налог указан процентом, но сумма НПД не прочитана")
        elif abs(expected_npd - npd) > 0.02:
            warnings.append(
                f"НПД {npd:.2f} не соответствует {rate:g}% от {cost:.2f} — "
                f"ожидалось {expected_npd:.2f}"
            )
            verdicts.append(False)

    if cost is not None and npd is not None and total is not None:
        expected_total = round(cost + npd, 2)
        if abs(expected_total - total) > 0.02:
            warnings.append(
                f"Итого {total:.2f} не равно {cost:.2f} + {npd:.2f} — "
                f"ожидалось {expected_total:.2f}"
            )
            verdicts.append(False)

    if cost is None:
        warnings.append("Стоимость товаров или услуг не прочитана")
    if total is None:
        warnings.append("Итоговая сумма не прочитана")
    if npd is None and rate is None:
        warnings.append("Налог НПД на чеке не найден")

    if False in verdicts:
        return False
    # Nothing failed, but anything unread means the figures stay unverified.
    return True if not warnings else None


def parse_selfemployed_receipt(text: str) -> dict[str, Any]:
    """Parse the printed text of a self-employed receipt."""
    lines = _clean_lines(text)
    if not lines:
        return {
            "error": "На изображении не найден текст",
            "country": "BY",
            "document_type": DocumentType.SELFEMPLOYED.value,
        }

    data: dict[str, Any] = {
        "country": "BY",
        "document_type": DocumentType.SELFEMPLOYED.value,
        "seller": {},
        "person": _person(lines),
        "inn": _label_value(lines, INN_LABELS),
        "document_number": _find_number(lines),
        "date": _find_date(lines),
        "cost": _labelled_money(lines, COST_LABELS),
        "npd_rate": _rate(lines),
        "npd_sum": _labelled_money(lines, NPD_LABELS),
        "total_sum": _labelled_money(lines, TOTAL_LABELS),
        "currency": "BYN",
        "items": [],
        "warnings": [],
    }

    purpose = _purpose(lines, data["person"])
    data["purpose"] = purpose
    if purpose:
        data["seller"] = {"name": data["person"] or ""}
        data["items"] = [{"name": purpose, "sum": data["cost"]}]

    data["reconciled"] = _reconcile(data)
    data["trustworthy"] = data["reconciled"] is True
    data["complete"] = bool(data["total_sum"] is not None and data["inn"])
    return data


class SelfEmployedParser(BaseParser):
    """Чек самозанятого из приложения «Мой налог»."""

    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.SELFEMPLOYED]

    async def parse(self, document: Document, file_bytes: bytes) -> dict[str, Any]:
        from app.services.ocr import Image, ocr_service

        try:
            if file_bytes.startswith(b"%PDF"):
                text = ocr_service.extract_full_text_from_pdf(file_bytes)
            else:
                text = ocr_service.extract_full_text(Image.open(io.BytesIO(file_bytes)))
        except Exception as exc:
            logger.warning("selfemployed_ocr_failed", error=str(exc))
            return {
                "error": "Не удалось прочитать изображение чека",
                "document_type": DocumentType.SELFEMPLOYED.value,
            }

        if not text or not text.strip():
            return {
                "error": "На изображении не найден текст",
                "document_type": DocumentType.SELFEMPLOYED.value,
            }

        return parse_selfemployed_receipt(text)
