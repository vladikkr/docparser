"""Tests for the ФНС XML parsers, driven by the real-format fixtures.

`scripts/validate_all.py` already checks these documents end to end, but it is
a separate program, so a plain `pytest` run did not: coverage of the TORG-12, act
and ЭТрН parsers sat at 15% and a regression in them would have gone unnoticed
until someone remembered to run the script. Every value asserted here is read
out of a fixture that follows the published schema.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from app.models import DocumentType
from app.services.parsers import get_parser
from app.services.parsers.fns_xml import FnsParseError, load_xml

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "test_xml"


def parse(doc_type: DocumentType, relative: str) -> dict:
    """Run the registered parser for a document type over a fixture."""
    data = (FIXTURES / relative).read_bytes()
    parser = get_parser(doc_type, None)
    assert parser is not None, f"no parser registered for {doc_type}"
    result = asyncio.run(parser.parse(None, data))
    assert "error" not in result, result.get("error")
    return result["parsed"]


# --- УПД ------------------------------------------------------------------


def test_upd_reads_parties_items_and_totals():
    parsed = parse(DocumentType.UPD, "upd/upd_valid.xml")

    assert parsed["knd"] == "1115131"
    assert parsed["function"] == "СЧФДОП"
    assert parsed["format_version"] == "5.03"
    assert parsed["document_number"] == "0000000123"
    assert parsed["document_date"] == "15.12.2024"
    assert parsed["seller"]["name"] == 'ООО "ТехноСервис"'
    assert parsed["seller"]["inn"] == "7701234567"
    assert parsed["seller"]["kpp"] == "770101001"
    assert parsed["buyer"]["name"] == 'ООО "Ромашка"'
    assert parsed["warnings"] == []


def test_upd_items_carry_quantities_prices_and_vat():
    parsed = parse(DocumentType.UPD, "upd/upd_valid.xml")
    items = parsed["items"]

    assert len(items) == 3
    first = items[0]
    assert first["line"] == "1"
    assert first["name"] == "Молоко пастеризованное 3.2% 1л"
    assert first["quantity"] == 10.0
    assert first["price"] == 89.0
    assert first["vat_rate"] == "10%"
    assert first["vat_sum"] == 80.91
    assert first["total_with_vat"] == 890.0
    assert first["unit"] == "шт"
    assert first["unit_code"] == "598"


def test_upd_totals_match_the_sum_of_its_items():
    parsed = parse(DocumentType.UPD, "upd/upd_valid.xml")

    assert parsed["totals"]["amount_without_vat"] == pytest.approx(2004.54, abs=0.02)
    assert parsed["totals"]["vat_sum"] == pytest.approx(290.46, abs=0.02)
    assert parsed["totals"]["total_with_vat"] == pytest.approx(2295.00, abs=0.02)
    summed = sum(item["total_with_vat"] for item in parsed["items"])
    assert summed == pytest.approx(2295.00, abs=0.02)


def test_upd_records_the_basis_document_it_refers_to():
    parsed = parse(DocumentType.UPD, "upd/upd_valid.xml")

    assert parsed["basis"]["name"] == "Договор поставки"
    assert parsed["basis"]["number"] == "44/24"
    assert parsed["basis"]["date"] == "01.12.2024"


# --- счёт-фактура ---------------------------------------------------------


def test_invoice_reads_all_three_lines():
    parsed = parse(DocumentType.INVOICE, "invoice/invoice_valid.xml")

    assert parsed["function"] == "СЧФ"
    assert parsed["document_number"] == "56789"
    assert len(parsed["items"]) == 3
    assert parsed["totals"]["total_with_vat"] == pytest.approx(264000.00, abs=0.02)
    assert parsed["warnings"] == []


# --- корректировки --------------------------------------------------------


def test_ukd_reports_increase_and_the_line_it_corrects():
    parsed = parse(DocumentType.UKD, "ukd/ukd_valid.xml")

    assert parsed["knd"] == "1115133"
    assert parsed["function"] == "КСЧФ"
    assert parsed["document_number"] == "КСФ-00012"

    item = parsed["items"][0]
    assert item["original_line"] == "3"
    assert item["quantity_before"] == 2.0
    assert item["quantity_after"] == 1.0
    assert item["vat_before"] == 180.0
    assert item["vat_after"] == 90.0
    assert item["vat_difference"] == -90.0

    assert parsed["totals"]["increase"]["total_with_vat"] == pytest.approx(540.00, abs=0.02)
    assert parsed["basis"]["number"] == "0000000123"


def test_invoice_correction_reports_a_decrease():
    parsed = parse(DocumentType.INVOICE_CORRECTION, "invoice_correction/invoice_correction_valid.xml")

    assert parsed["knd"] == "1115133"
    assert "decrease" in parsed["totals"], "a cancellation must land under decrease"
    assert parsed["totals"]["decrease"]["total_with_vat"] == pytest.approx(60000.00, abs=0.02)
    assert parsed["items"][0]["quantity_after"] == 0.0
    assert parsed["basis"]["number"] == "56789"


# --- ТОРГ-12 --------------------------------------------------------------


def test_torg12_reads_goods_and_totals():
    parsed = parse(DocumentType.TORG12, "torg12/torg12_valid.xml")

    assert parsed["knd"] == "1175010"
    assert parsed["document_number"] == "ТОРГ12-0001"
    assert parsed["seller"]["name"] == 'ООО "ТехноСервис"'
    assert parsed["buyer"]["name"] == 'ООО "Ромашка"'
    assert len(parsed["items"]) == 3
    assert parsed["warnings"] == []


def test_torg12_item_uses_its_own_field_names():
    """A накладная is not a УПД: it says НеттоПередано, not КолТов."""
    parsed = parse(DocumentType.TORG12, "torg12/torg12_valid.xml")
    first = parsed["items"][0]

    assert first["line"] == "1"
    assert first["quantity"] == 10.0          # НеттоПередано
    assert first["price"] == 89.0             # Цена
    assert first["amount_without_vat"] == pytest.approx(809.09, abs=0.02)  # СтБезНДС
    assert first["vat_sum"] == pytest.approx(80.91, abs=0.02)             # СумНДС
    assert first["total_with_vat"] == pytest.approx(890.00, abs=0.02)     # СтУчНДС
    assert first["unit"] == "шт"


def test_torg12_totals_reconcile_with_the_lines():
    parsed = parse(DocumentType.TORG12, "torg12/torg12_valid.xml")

    assert parsed["totals"]["total_with_vat"] == pytest.approx(2295.00, abs=0.02)
    summed = sum(item["total_with_vat"] for item in parsed["items"])
    assert summed == pytest.approx(2295.00, abs=0.02)


# --- акт ------------------------------------------------------------------


def test_act_reads_work_lines_and_their_group_total():
    parsed = parse(DocumentType.ACT, "act/act_valid.xml")

    assert parsed["knd"] == "1175012"
    assert parsed["document_number"] == "АКТ-0031"
    assert parsed["seller"]["name"] == 'ООО "ТехноСервис"'  # Исполнитель
    assert parsed["buyer"]["name"] == 'ООО "Ромашка"'      # Заказчик
    assert len(parsed["items"]) == 1

    work = parsed["items"][0]
    assert work["name"] == "Внедрение 1С:ERP"
    assert work["quantity"] == 40.0
    assert work["price"] == 3750.0
    assert work["total_with_vat"] == pytest.approx(180000.00, abs=0.02)
    assert work["unit"] == "час"
    assert work["unit_code"] == "356"  # the act spells it ОКЕИ, not ОКЕИ_Тов
    assert parsed["totals"]["total_with_vat"] == pytest.approx(180000.00, abs=0.02)


# --- ЭТрН -----------------------------------------------------------------


def test_ettn_reads_cargo_and_admits_the_money_is_elsewhere():
    parsed = parse(DocumentType.TTN, "ttn/ttn_valid.xml")

    assert parsed["knd"] == "1110347"
    assert parsed["document_number"] == "СВ-0001"
    assert len(parsed["items"]) == 2
    assert parsed["items"][0]["name"] == "Стройматериалы"
    assert parsed["items"][0]["weight"] == 1500.0

    # An ЭТрН has no price column, so saying the total is missing is the
    # honest answer rather than inventing one.
    assert any("997/07" in warning for warning in parsed["warnings"])


# --- shared XML layer ------------------------------------------------------


def test_load_xml_rejects_an_entity_bomb():
    bomb = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE lolz [<!ENTITY a "xx">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
        '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>'
        "<Файл>&c;</Файл>"
    ).encode("utf-8")

    with pytest.raises(FnsParseError):
        load_xml(bomb)


def test_load_xml_handles_windows_1251():
    """Real ФНС files are windows-1251, not UTF-8."""
    text = '<?xml version="1.0" encoding="windows-1251"?><Файл><Документ>чек</Документ></Файл>'
    root = load_xml(text.encode("cp1251"))

    assert root.tag == "Файл"
    assert root[0].text == "чек"


def test_load_xml_rejects_an_empty_file():
    with pytest.raises(FnsParseError):
        load_xml(b"   ")


@pytest.mark.parametrize(
    "doc_type,relative",
    [
        (DocumentType.UPD, "torg12/torg12_valid.xml"),
        (DocumentType.UPD, "act/act_valid.xml"),
        (DocumentType.TORG12, "upd/upd_valid.xml"),
        (DocumentType.ACT, "invoice/invoice_valid.xml"),
        (DocumentType.INVOICE, "act/act_valid.xml"),
    ],
)
def test_every_parser_refuses_a_document_of_another_kind(doc_type, relative):
    """Each parser must reject a КНД it does not own.

    The pairs are crossed deliberately: feeding a parser its own document would
    prove nothing, and accepting a ТОРГ-12 as a УПД would mean a client
    uploading the wrong file gets confident wrong numbers.
    """
    data = (FIXTURES / relative).read_bytes()
    result = asyncio.run(get_parser(doc_type, None).parse(None, data))

    assert "error" in result, f"{doc_type} accepted {relative}"
