"""Parser for УПД / УКД and for a standalone счёт-фактура.

All three live in one ФНС schema (приказ ЕД-7-26/970@, format 5.03): a счёт-фактура
is a УПД whose `Функция` is СЧФ, and a УКД follows the correction schema from
приказ ЕД-1-26/29@ where the item table is `ТаблКСчФ` and the totals are split
into `ВсегоУвел` and `ВсегоУм`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import structlog

from app.models import Document, DocumentType
from app.services.parsers.base import BaseParser
from app.services.parsers.fns_xml import (
    KND_CORRECTION,
    KND_INVOICE_LIKE,
    KND_INVOICE_LIKE_BUYER,
    FnsParseError,
    child_text,
    children,
    direct_child,
    document_root,
    find_first,
    knd_of,
    load_xml,
    localname,
    parse_currency,
    parse_participant,
    parse_tax_amount,
    to_number,
)

logger = structlog.get_logger()

# A seller title carrying `Функция="СЧФ"` is an invoice; `ДОП`/`СЧФДОП` is a УПД
# that also carries invoice data. The buyer title has no goods table at all.
SELLER_KNDS = {KND_INVOICE_LIKE, KND_CORRECTION}
BUYER_KNDS = {KND_INVOICE_LIKE_BUYER}


class FnsXmlParser(BaseParser):
    """Shared implementation for the invoice-family XML formats."""

    doc_type_label = "УПД"
    expected_knds = SELLER_KNDS

    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.UPD, DocumentType.UKD]

    async def parse(self, document: Document, file_bytes: bytes) -> dict[str, Any]:
        try:
            root = load_xml(file_bytes)
            return self._build(root)
        except FnsParseError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.warning("fns_invoice_parse_failed", error=str(exc), kind=self.doc_type_label)
            return {"error": f"Parsing failed: {type(exc).__name__}: {exc}"}

    def _build(self, root: ET.Element) -> dict[str, Any]:
        doc = document_root(root)
        knd = knd_of(root)

        if knd in BUYER_KNDS:
            return self._build_buyer_title(root, doc)

        if self.expected_knds and knd not in self.expected_knds:
            return {
                "error": (
                    f"КНД={knd or '—'} не соответствует формату {self.doc_type_label} "
                    f"(ожидался {'/'.join(sorted(self.expected_knds))})"
                )
            }

        invoice = direct_child(doc, "СвСчФакт", "СвКСчФ")
        if invoice is None:
            invoice = doc
        parsed: dict[str, Any] = {
            "document_type": self.doc_type_label,
            "country": "RU",
            "knd": knd,
            "function": (doc.get("Функция") or "").strip(),
            "format_version": _format_version(root),
            "document_number": (invoice.get("НомерДок") or "").strip(),
            "document_date": (invoice.get("ДатаДок") or "").strip(),
            "information_date": (doc.get("ДатаИнфПр") or "").strip(),
            "currency": parse_currency(root),
            "seller": {},
            "buyer": {},
            "items": [],
            "totals": {},
        }

        seller = direct_child(invoice, "СвПрод")
        buyer = direct_child(invoice, "СвПокуп", "СвПокупатель")
        if seller is not None:
            parsed["seller"] = parse_participant(seller)
        if buyer is not None:
            parsed["buyer"] = parse_participant(buyer)

        parsed["items"], parsed["totals"] = self._read_items(root)
        parsed["basis"] = self._read_basis(root)
        parsed["warnings"] = self._check(parsed)

        return {
            "country": "RU",
            "document_type": self.doc_type_label,
            "parsed": parsed,
        }

    def _read_items(self, root: ET.Element) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        table = find_first(root, "ТаблСчФакт", "ТаблКСчФ")
        if table is None:
            return [], {}

        items: list[dict[str, Any]] = []
        for node in children(table, "СведТов"):
            items.append(self._read_item(node, table))

        return items, self._read_totals(table)

    def _read_item(self, node: ET.Element, table: ET.Element) -> dict[str, Any]:
        is_correction = localname(table.tag) == "ТаблКСчФ"

        item: dict[str, Any] = {
            "line": (node.get("НомСтр") or "").strip(),
            "name": (node.get("НаимТов") or "").strip(),
            "unit": (node.get("НаимЕдИзм") or "").strip(),
            "unit_code": (node.get("ОКЕИ_Тов") or "").strip(),
            "quantity": to_number(node.get("КолТов")),
            "price": to_number(node.get("ЦенаТов")),
            "amount_without_vat": to_number(node.get("СтТовБезНДС")),
            "vat_rate": (node.get("НалСт") or "").strip(),
            "total_with_vat": to_number(node.get("СтТовУчНал")),
        }

        if is_correction:
            # A correction states the values before and after the change, and
            # keeps the restated amount in the `СтТовБезНДС` child element.
            item.update(
                original_line=(node.get("ПорНомТовВСЧФ") or "").strip(),
                quantity_before=to_number(node.get("КолТовДо")),
                quantity_after=to_number(node.get("КолТовПосле")),
                price_before=to_number(node.get("ЦенаТовДо")),
                price_after=to_number(node.get("ЦенаТовПосле")),
                amount_before=to_number(child_text(node, "СтТовБезНДС")),
                vat_before=to_number(child_text(node, "СумНалДо")),
                vat_after=to_number(child_text(node, "СумНалПосле")),
                vat_difference=to_number(child_text(node, "СумНалРазн")),
                total_with_vat=to_number(child_text(node, "СтТовУчНал")),
            )
        else:
            item["vat_sum"] = parse_tax_amount(direct_child(node, "СумНал"))[0]

        # Marked goods carry a tracking and marking number, which is what the
        # client usually wants out of a УПД.
        tracing = find_first(node, "СведПрослеж")
        if tracing is not None:
            item["tracking_number"] = (tracing.get("НомТовПрослеж") or "").strip()
        marking = find_first(node, "НомСредИдентТов")
        if marking is not None:
            kiz = child_text(marking, "КИЗ")
            item["marking"] = kiz or (marking.get("ИдентТрансУпак") or "").strip()

        return item

    def _read_totals(self, table: ET.Element) -> dict[str, Any]:
        """`ВсегоОпл` for an original, `ВсегоУвел`/`ВсегоУм` for a correction."""
        totals: dict[str, Any] = {}
        for name in ("ВсегоОпл", "ВсегоУвел", "ВсегоУм"):
            node = direct_child(table, name)
            if node is None:
                continue
            bucket = "increase" if name == "ВсегоУвел" else "decrease" if name == "ВсегоУм" else None
            values = {
                "amount_without_vat": to_number(node.get("СтТовБезНДСВсего")),
                "total_with_vat": to_number(node.get("СтТовУчНалВсего")),
                "vat_sum": parse_tax_amount(direct_child(node, "СумНалВсего"))[0],
            }
            if bucket:
                totals[bucket] = values
            else:
                totals.update(values)
        return totals

    def _read_basis(self, root: ET.Element) -> dict[str, Any]:
        """The document a correction refers back to, when it names one."""
        transfer = find_first(root, "СвПер")
        if transfer is None:
            # The 2026 УКД schema names the corrected invoice instead.
            corrected = find_first(root, "СчФ")
            if corrected is None:
                return {}
            return {
                "name": "счёт-фактура",
                "number": (corrected.get("НомерСчФ") or "").strip(),
                "date": (corrected.get("ДатаСчФ") or "").strip(),
            }

        basis = direct_child(transfer, "ОснПер")
        if basis is not None:
            return {
                "name": (basis.get("РеквНаимДок") or "").strip(),
                "number": (basis.get("РеквНомерДок") or "").strip(),
                "date": (basis.get("РеквДатаДок") or "").strip(),
            }

        if direct_child(transfer, "БезДокОснПер") is not None:
            return {"name": "без документа-основания", "number": "", "date": ""}

        # A correction may point at the primary document instead.
        primary = find_first(root, "ДокумОснКор")
        if primary is not None:
            return {
                "name": (primary.get("РеквНаимДок") or "").strip(),
                "number": (primary.get("РеквНомерДок") or "").strip(),
                "date": (primary.get("РеквДатаДок") or "").strip(),
            }
        return {}

    def _build_buyer_title(self, root: ET.Element, doc: ET.Element) -> dict[str, Any]:
        """The buyer title carries a confirmation, not a goods table."""
        return {
            "country": "RU",
            "document_type": f"{self.doc_type_label} (титул покупателя)",
            "parsed": {
                "document_type": "buyer_title",
                "country": "RU",
                "knd": knd_of(root),
                "information_date": (doc.get("ДатаИнфПок") or "").strip(),
                "items": [],
                "totals": {},
                "warnings": [],
            },
        }

    def _check(self, parsed: dict[str, Any]) -> list[str]:
        """Flag the failures that make a result unsafe to rely on."""
        warnings: list[str] = []
        items, totals = parsed["items"], parsed["totals"]

        if not items:
            warnings.append("Товарная строка не найдена: в файле нет <ТаблСчФакт>")
        if not parsed["seller"].get("name") and not parsed["buyer"].get("name"):
            warnings.append("Не удалось прочитать ни продавца, ни покупателя")
        if not parsed["document_number"]:
            warnings.append("Не найден номер документа (<СвСчФакт НомерДок>)")

        total = totals.get("total_with_vat")
        if total is not None and items:
            summed = sum(
                item["total_with_vat"]
                for item in items
                if item.get("total_with_vat") is not None
            )
            if abs(summed - total) > 0.02:
                warnings.append(
                    f"Итог {total:.2f} не совпадает с суммой позиций {summed:.2f}"
                )
        return warnings


def _format_version(root: ET.Element) -> str:
    """`ВерсФорм` on the `<Файл>` wrapper, when the file has one."""
    if localname(root.tag) != "Файл":
        return ""
    return (root.get("ВерсФорм") or "").strip()


class UPDParser(FnsXmlParser):
    """Универсальный передаточный документ."""

    doc_type_label = "upd"
    expected_knds = {KND_INVOICE_LIKE}

    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.UPD]


class UKDParser(FnsXmlParser):
    """Универсальный корректировочный документ, приказ ЕД-1-26/29@."""

    doc_type_label = "ukd"
    expected_knds = {KND_CORRECTION}

    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.UKD]


class InvoiceParser(FnsXmlParser):
    """Standalone счёт-фактура: the same schema, `Функция` is СЧФ."""

    doc_type_label = "invoice"
    expected_knds = {KND_INVOICE_LIKE}

    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.INVOICE]


class InvoiceCorrectionParser(FnsXmlParser):
    """Корректировочный счёт-фактура."""

    doc_type_label = "invoice_correction"
    expected_knds = {KND_CORRECTION}

    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.INVOICE_CORRECTION]
