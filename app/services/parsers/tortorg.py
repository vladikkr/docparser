"""Парсеры ТОРГ-12, акта выполненных работ и электронной транспортной накладной.

These formats come from a different pair of приказов than the invoice family
(ММВ-7-10/551@ and ММВ-7-10/552@), and the difference shows in the element
names: participants are `СвЮЛ` nested under `ИдСв/СвОрг` rather than `СвЮЛУч`,
the item element is `СвТов` rather than `СведТов`, and the money sits in
`НеттоПередано` / `Цена` / `СтБезНДС` rather than `КолТов` / `ЦенаТов`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import structlog

from app.models import Document, DocumentType
from app.services.parsers.base import BaseParser
from app.services.parsers.fns_xml import (
    KND_ACT,
    KND_TORG12,
    FnsParseError,
    child_text,
    children,
    direct_child,
    document_root,
    find_all,
    find_first,
    knd_of,
    load_xml,
    parse_currency,
    parse_participant,
    to_number,
)

logger = structlog.get_logger()


def _document_identity(root: ET.Element, doc: ET.Element) -> dict[str, Any]:
    """Number, date and the version stamp, which live on different elements."""
    ident = find_first(root, "ИдентДок")
    named = find_first(root, "НаимДок")
    return {
        "knd": knd_of(root),
        "format_version": (root.get("ВерсФорм") or "").strip() if root.tag == "Файл" else "",
        "document_name": (named.get("НаимДокОпр") or "").strip() if named is not None else "",
        "document_number": _first_attr(ident, "НомДокПТ", "НомДокПРУ"),
        "document_date": _first_attr(ident, "ДатаДокПТ", "ДатаДокПРУ"),
        "information_date": (
            doc.get("ДатаИнфПр") or doc.get("ДатаИнфИсп") or doc.get("ДатаИнфПрв") or ""
        ).strip(),
        "currency": parse_currency(root),
    }


def _first_attr(element: ET.Element | None, *names: str) -> str:
    """First non-empty attribute among the given names."""
    if element is None:
        return ""
    for name in names:
        value = (element.get(name) or "").strip()
        if value:
            return value
    return ""


def _reconcile(items: list[dict[str, Any]], total: float | None, key: str) -> list[str]:
    warnings: list[str] = []
    if total is None or not items:
        return warnings
    summed = sum(item[key] for item in items if item.get(key) is not None)
    if abs(summed - total) > 0.02:
        warnings.append(f"Итог {total:.2f} не совпадает с суммой позиций {summed:.2f}")
    return warnings


class Torg12Parser(BaseParser):
    """Товарная накладная по форме ТОРГ-12, приказ ММВ-7-10/551@."""

    doc_type_label = "torg12"
    expected_knds = {KND_TORG12}

    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.TORG12]

    async def parse(self, document: Document, file_bytes: bytes) -> dict[str, Any]:
        try:
            root = load_xml(file_bytes)
        except FnsParseError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.warning("torg12_parse_failed", error=str(exc))
            return {"error": f"Parsing failed: {type(exc).__name__}: {exc}"}

        try:
            doc = document_root(root)
        except FnsParseError as exc:
            return {"error": str(exc)}

        knd = knd_of(root)
        if knd not in self.expected_knds:
            return {"error": f"КНД={knd or '—'} не является ТОРГ-12 (ожидался {KND_TORG12})"}

        parsed: dict[str, Any] = {
            "document_type": self.doc_type_label,
            "country": "RU",
            **_document_identity(root, doc),
            "seller": {},
            "buyer": {},
            "items": [],
            "totals": {},
        }

        body = find_first(root, "СвДокПТПр")
        if body is None:
            body = doc
        facts = find_first(body, "СодФХЖ1")
        seller = direct_child(facts, "Продавец") if facts is not None else None
        buyer = direct_child(facts, "Покупатель", "ГрузПолуч") if facts is not None else None
        if seller is not None:
            parsed["seller"] = parse_participant(seller)
        if buyer is not None:
            parsed["buyer"] = parse_participant(buyer)

        table = find_first(body, "СодФХЖ2")
        if table is not None:
            for node in children(table, "СвТов"):
                parsed["items"].append(
                    {
                        "line": (node.get("НомТов") or "").strip(),
                        "name": (node.get("НаимТов") or "").strip(),
                        "characteristic": (node.get("ХарактерТов") or "").strip(),
                        "unit": (node.get("НаимЕдИзм") or "").strip(),
                        "unit_code": (node.get("ОКЕИ_Тов") or "").strip(),
                        "packages": to_number(node.get("КолМест")),
                        "gross_weight": to_number(node.get("Брутто")),
                        "quantity": to_number(node.get("НеттоПередано")),
                        "price": to_number(node.get("Цена")),
                        "amount_without_vat": to_number(node.get("СтБезНДС")),
                        "vat_rate": (node.get("НалСт") or "").strip(),
                        "vat_sum": to_number(node.get("СумНДС")),
                        "total_with_vat": to_number(node.get("СтУчНДС")),
                    }
                )

            totals = direct_child(table, "Всего")
            if totals is not None:
                parsed["totals"] = {
                    "packages": to_number(totals.get("КолМестВс")),
                    "gross_weight": to_number(totals.get("БруттоВс")),
                    "quantity": to_number(totals.get("НеттоВс")),
                    "amount_without_vat": to_number(totals.get("СтБезНДСВс")),
                    "vat_sum": to_number(totals.get("СумНДСВс")),
                    "total_with_vat": to_number(totals.get("СтУчНДСВс")),
                }

        operation = find_first(body, "СодФХЖ3")
        if operation is not None:
            parsed["operation"] = (operation.get("СодОпер") or "").strip()
            parsed["release_date"] = (operation.get("ДатаОтпуск") or "").strip()

        basis = find_first(body, "Основание")
        if basis is not None:
            parsed["basis"] = {
                "name": (basis.get("НаимОсн") or "").strip(),
                "number": (basis.get("НомОсн") or "").strip(),
                "date": (basis.get("ДатаОсн") or "").strip(),
            }

        warnings: list[str] = []
        if not parsed["items"]:
            warnings.append("Товарная строка не найдена: в файле нет <СвТов>")
        if not parsed["document_number"]:
            warnings.append("Не найден номер документа (<ИдентДок НомДокПТ>)")
        warnings += _reconcile(parsed["items"], parsed["totals"].get("total_with_vat"), "total_with_vat")
        parsed["warnings"] = warnings

        return {"country": "RU", "document_type": self.doc_type_label, "parsed": parsed}


class ActParser(BaseParser):
    """Акт выполненных работ/оказанных услуг, приказ ММВ-7-10/552@."""

    doc_type_label = "act"
    expected_knds = {KND_ACT}

    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.ACT]

    async def parse(self, document: Document, file_bytes: bytes) -> dict[str, Any]:
        try:
            root = load_xml(file_bytes)
        except FnsParseError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.warning("act_parse_failed", error=str(exc))
            return {"error": f"Parsing failed: {type(exc).__name__}: {exc}"}

        try:
            doc = document_root(root)
        except FnsParseError as exc:
            return {"error": str(exc)}

        knd = knd_of(root)
        if knd not in self.expected_knds:
            return {"error": f"КНД={knd or '—'} не является актом (ожидался {KND_ACT})"}

        parsed: dict[str, Any] = {
            "document_type": self.doc_type_label,
            "country": "RU",
            **_document_identity(root, doc),
            "seller": {},
            "buyer": {},
            "items": [],
            "totals": {},
        }

        body = find_first(root, "СвДокПРУ")
        if body is None:
            body = doc
        facts = find_first(body, "СодФХЖ1")
        performer = direct_child(facts, "Исполнитель", "Подрядчик") if facts is not None else None
        customer = direct_child(facts, "Заказчик", "Покупатель") if facts is not None else None
        if performer is not None:
            parsed["seller"] = parse_participant(performer)
        if customer is not None:
            parsed["buyer"] = parse_participant(customer)

        # An act groups its lines under one or more <ОписРабот> blocks, and the
        # block already carries its own totals, so they are read alongside.
        group_totals: list[float] = []
        for group in (find_all(facts, "ОписРабот") if facts is not None else []):
            for node in children(group, "Работа"):
                parsed["items"].append(
                    {
                        "line": (node.get("Номер") or "").strip(),
                        "name": (node.get("НаимРабот") or "").strip(),
                        "unit": (node.get("НаимЕдИзм") or "").strip(),
                        "unit_code": (node.get("ОКЕИ") or "").strip(),
                        "quantity": to_number(node.get("Количество")),
                        "price": to_number(node.get("Цена")),
                        "amount_without_vat": to_number(node.get("СтоимБезНДС")),
                        "vat_rate": (node.get("НалСт") or "").strip(),
                        "vat_sum": to_number(node.get("СумНДС")),
                        "total_with_vat": to_number(node.get("СтоимУчНДС")),
                        "period_start": (group.get("НачРабот") or "").strip(),
                        "period_end": (group.get("КонРабот") or "").strip(),
                    }
                )
            value = to_number(group.get("СтУчНДСИт"))
            if value is not None:
                group_totals.append(value)

        if group_totals:
            parsed["totals"] = {"total_with_vat": sum(group_totals)}

        operation = find_first(body, "СодФХЖ2")
        if operation is not None:
            parsed["operation"] = (operation.get("СодОпер") or "").strip()
            parsed["completion_date"] = (operation.get("ДатаПер") or "").strip()

        basis = find_first(body, "Основание")
        if basis is not None:
            parsed["basis"] = {
                "name": (basis.get("НаимОсн") or "").strip(),
                "number": (basis.get("НомОсн") or "").strip(),
                "date": (basis.get("ДатаОсн") or "").strip(),
            }

        warnings: list[str] = []
        if not parsed["items"]:
            warnings.append("Работа не найдена: в файле нет <Работа>")
        if not parsed["document_number"]:
            warnings.append("Не найден номер документа (<ИдентДок НомДокПРУ>)")
        warnings += _reconcile(parsed["items"], parsed["totals"].get("total_with_vat"), "total_with_vat")
        parsed["warnings"] = warnings

        return {"country": "RU", "document_type": self.doc_type_label, "parsed": parsed}


class TTNParser(BaseParser):
    """Электронная транспортная накладная, приказ ЕД-7-26/1065@.

    Unlike a goods note this document has no line table: the cargo is
    aggregated into `<ОпГруз>` blocks and the money lives only on the 997/07
    title. Both parts are read, because an operator sends them separately.
    """

    doc_type_label = "ttn"
    expected_knds = {"1110345", "1110347"}

    @property
    def supported_types(self) -> list[DocumentType]:
        return [DocumentType.TTN]

    async def parse(self, document: Document, file_bytes: bytes) -> dict[str, Any]:
        try:
            root = load_xml(file_bytes)
            doc = document_root(root)
        except FnsParseError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.warning("ttn_parse_failed", error=str(exc))
            return {"error": f"Parsing failed: {type(exc).__name__}: {exc}"}

        knd = knd_of(root)
        if knd not in self.expected_knds:
            return {"error": f"КНД={knd or '—'} не является ЭТрН (ожидался 1110345 или 1110347)"}

        parsed: dict[str, Any] = {
            "document_type": self.doc_type_label,
            "country": "RU",
            "knd": knd,
            "format_version": (root.get("ВерсФорм") or "").strip(),
            "information_date": (doc.get("ДатИнфПрв") or "").strip(),
            "items": [],
            "totals": {},
            "sender": {},
            "receiver": {},
        }

        consignment = find_first(root, "СодСВИнфПрв")
        if consignment is not None:
            parsed["document_number"] = (consignment.get("НомерСВ") or "").strip()
            parsed["document_date"] = (consignment.get("ДатаСВ") or "").strip()
            parsed["uid"] = (consignment.get("УИД_СВ") or "").strip()

            cargo_owner = direct_child(consignment, "СвГО")
            parsed["sender"] = parse_participant(
                cargo_owner if cargo_owner is not None else consignment
            )
            cargo_receiver = direct_child(consignment, "СвГП")
            parsed["receiver"] = parse_participant(
                cargo_receiver if cargo_receiver is not None else consignment
            )

            cargo = find_first(root, "СвГруз")
            if cargo is None:
                cargo = consignment
            for node in find_all(cargo, "ОпГруз"):
                parsed["items"].append(
                    {
                        "name": (node.get("НаимГруз") or "").strip(),
                        "composition": (node.get("СостГруз") or "").strip(),
                        "packaging": (node.get("СпУпак") or "").strip(),
                        "volume": to_number(node.get("Объем")),
                        "weight": to_number(node.get("Масса")),
                        "places": to_number(node.get("ПлКолМест")),
                    }
                )

        # The 997/07 title is what actually carries the amount.
        fact = find_first(root, "СодФХЖ1")
        if fact is not None:
            parsed["totals"] = {
                "amount_without_vat": to_number(fact.get("СтТовБезНДС")),
                "total_with_vat": to_number(fact.get("СтТовУчНал")),
                "vat_rate": (fact.get("НалСт") or "").strip(),
            }
            nested = find_first(fact, "СумНал")
            if nested is not None:
                parsed["totals"]["vat_sum"] = to_number(child_text(nested, "СумНДС"))

        warnings: list[str] = []
        if not parsed["items"]:
            warnings.append("Груз не найден: в файле нет <ОпГруз>")
        if not parsed["totals"].get("total_with_vat"):
            warnings.append("Сумма находится в титуле 997/07 — приложите его вместе с ведомостью")
        parsed["warnings"] = warnings

        return {"country": "RU", "document_type": self.doc_type_label, "parsed": parsed}
