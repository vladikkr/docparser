"""Tests for the Telegram bot: state, detection, service gating and rendering.

These run without a Telegram token, because every part they touch sits behind
the token except the parsing itself, which is already covered elsewhere.
"""

from __future__ import annotations

import json
import os

import pytest

from app.bot.detect import detect, detect_from_qr, detect_xml
from app.bot.render import render, render_receipt
from app.bot.service import PENDING_TYPES, Outcome, process
from app.bot.store import UserStore

UPD_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Файл ИдФайл="ID" ВерсФорм="5.03" ВерсПрог="test">'
    '<Документ КНД="1115131" Функция="СЧФДОП" ДатаИнфПр="15.12.2024" ВремИнфПр="12.30.00">'
    '<СвСчФакт НомерДок="12345" ДатаДок="15.12.2024"/>'
    "</Документ></Файл>"
).encode("utf-8")

INVOICE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Файл ИдФайл="ID" ВерсФорм="5.03" ВерсПрог="test">'
    '<Документ КНД="1115131" Функция="СЧФ" ДатаИнфПр="18.01.2024" ВремИнфПр="16.45.00">'
    '<СвСчФакт НомерДок="56789" ДатаДок="18.01.2024"/>'
    "</Документ></Файл>"
).encode("utf-8")

# A УПД that only transfers goods, with no invoice data.
TRANSFER_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Файл ИдФайл="ID" ВерсФорм="5.03" ВерсПрог="test">'
    '<Документ КНД="1115131" Функция="ДОП" ДатаИнфПр="15.12.2024" ВремИнфПр="12.30.00">'
    '<СвСчФакт НомерДок="ТД-45" ДатаДок="15.12.2024"/>'
    "</Документ></Файл>"
).encode("utf-8")

CORRECTION_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Файл ИдФайл="ID" ВерсФорм="5.02" ВерсПрог="test">'
    '<Документ КНД="1115133" Функция="КСЧФ" ДатаИнфПр="20.12.2024" ВремИнфПр="09.15.00">'
    '<СвКСчФ НомерДок="КСФ-12" ДатаДок="20.12.2024"><СчФ НомерСчФ="12345" ДатаСчФ="15.12.2024"/>'
    "<ТаблКСчФ/></СвКСчФ>"
    "</Документ></Файл>"
).encode("utf-8")

# The correction schema also covers a corrected счёт-фактура, which is told
# apart by the absence of the `ТаблКСчФ` goods table.
CORRECTION_INVOICE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Файл ИдФайл="ID" ВерсФорм="5.02" ВерсПрог="test">'
    '<Документ КНД="1115133" Функция="КСЧФ" ДатаИнфПр="20.12.2024" ВремИнфПр="09.15.00">'
    '<СвКСчФ НомерДок="КСФ-99" ДатаДок="20.12.2024"><СчФ НомерСчФ="56789" ДатаСчФ="18.01.2024"/>'
    "</СвКСчФ></Документ></Файл>"
).encode("utf-8")

TORG12_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Файл ИдФайл="ID" ВерсФорм="5.02"><Документ КНД="1175010" ДатаИнфПр="15.12.2024">'
    '<СвДокПТПр><ИдентДок НомДокПТ="Т-1" ДатаДокПТ="15.12.2024"/></СвДокПТПр></Документ></Файл>'
).encode("utf-8")

ACT_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Файл ИдФайл="ID" ВерсФорм="5.02"><Документ КНД="1175012" ДатаИнфИсп="20.12.2024">'
    '<СвДокПРУ><ИдентДок НомДокПРУ="А-1" ДатаДокПРУ="20.12.2024"/></СвДокПРУ></Документ></Файл>'
).encode("utf-8")


# --- store -----------------------------------------------------------------


def test_trial_counts_down_and_blocks(tmp_path):
    store = UserStore(str(tmp_path / "state.json"))
    store.get(1)

    for _ in range(store.get(1).trial_limit):
        user = store.get(1)
        assert user.has_access
        store.consume_document(1)

    blocked = store.get(1)
    assert blocked.trial_left == 0
    assert not blocked.has_access


def test_approval_lifts_the_limit(tmp_path):
    store = UserStore(str(tmp_path / "state.json"))
    for _ in range(store.get(2).trial_limit):
        store.consume_document(2)

    assert not store.get(2).has_access
    store.approve(2, True)

    approved = store.get(2)
    assert approved.has_access
    assert approved.trial_left == -1


def test_state_survives_a_restart(tmp_path):
    path = str(tmp_path / "state.json")
    UserStore(path).approve(7, True)

    reloaded = UserStore(path).get(7)
    assert reloaded.approved
    assert os.path.exists(path)


def test_damaged_state_file_does_not_crash(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")

    store = UserStore(str(path))
    assert store.get(5).documents_used == 0


def test_touch_keeps_latest_profile(tmp_path):
    store = UserStore(str(tmp_path / "state.json"))
    store.touch(store.get(3), "old", "Old")
    user = store.touch(store.get(3), "new", "New")

    assert user.username == "new"
    assert user.first_name == "New"


# --- detection -------------------------------------------------------------


def test_fiscal_qr_means_a_russian_receipt():
    detection = detect_from_qr("t=20240115T103000&s=1240.00&fn=9280440300007971&i=123456&fp=9876543210&n=1")
    assert detection.doc_type == "receipt_kkt"
    assert "РФ" in detection.label


def test_bare_qr_id_means_a_belarusian_receipt():
    detection = detect_from_qr("63288429a8fec2242adb4b37")
    assert detection.doc_type == "receipt_kkt"
    assert "РБ" in detection.label


def test_upd_is_recognised_by_knd():
    assert detect_xml(TRANSFER_XML).doc_type == "upd"


def test_invoice_is_told_apart_by_function_not_knd():
    # Same КНД as a УПД; only `Функция` differs. СЧФ is a счёт-фактура, while
    # СЧФДОП and ДОП are УПД, one of which also carries invoice data.
    assert detect_xml(INVOICE_XML).doc_type == "invoice"
    assert detect_xml(UPD_XML).doc_type == "upd"
    assert detect_xml(TRANSFER_XML).doc_type == "upd"


def test_torg12_and_act_are_recognised():
    assert detect_xml(TORG12_XML).doc_type == "torg12"
    assert detect_xml(ACT_XML).doc_type == "act"


def test_correction_is_reported_as_the_single_format_it_is():
    # ФНС ships one schema for a УКД and for a corrected счёт-фактура, and
    # nothing in the file distinguishes them, so the bot must not guess.
    assert detect_xml(CORRECTION_XML).doc_type == "ukd"
    assert detect_xml(CORRECTION_INVOICE_XML).doc_type == "ukd"


def test_unknown_knd_is_reported_not_guessed():
    detection = detect_xml(
        '<Файл><Документ КНД="9999999"/></Файл>'.encode("utf-8")
    )
    assert detection.doc_type == "unknown"


def test_broken_xml_does_not_raise():
    assert detect_xml(b"<not-closed>") is None


def test_non_xml_file_falls_back_to_the_receipt_path():
    assert detect(b"\x89PNG\r\n\x1a\n garbage").doc_type == "receipt_kkt"


# --- service ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_fixed_format_is_parsed_not_declared_pending():
    # УПД, ТОРГ-12 and the act are implemented, so the bot must not apologise
    # for them. A УПД with no goods table is still a valid parse.
    outcome = await process(TRANSFER_XML)

    assert outcome.ok
    assert "в разработке" not in render(outcome)


def test_a_pending_format_is_honest_about_not_being_ready():
    # A чек самозанятого is a printout from "Мой налог", not an XML format, so
    # there is deliberately no fixture for it: the message is what matters.
    outcome = Outcome(
        ok=False,
        doc_type="selfemployed",
        label="Чек самозанятого",
        source="fallback",
        error="not_implemented",
        note="Чек самозанятого: формат принят, но парсер ещё не доведён до продакшена.",
    )

    assert outcome.pending
    assert "не доведён" in render(outcome)
    assert "не буду выдумывать цифры" in render(outcome)


def test_pending_formats_cover_every_unimplemented_type():
    # Everything else is implemented and asserted by scripts/validate_all.py.
    assert set(PENDING_TYPES) == {"selfemployed"}


@pytest.mark.asyncio
async def test_unrecognised_file_is_not_claimed_as_a_receipt():
    outcome = await process('<Файл><Документ КНД="9999999"/></Файл>'.encode("utf-8"))

    assert not outcome.ok
    assert outcome.error == "unrecognised"


# --- rendering -------------------------------------------------------------


def test_belarusian_receipt_shows_the_money():
    message = render_receipt(
        {
            "country": "BY",
            "seller": {"name": "Евроопт", "unp": "790730816"},
            "unp": "790730816",
            "rn_skko": "719014711",
            "total_sum": 20.0,
            "currency": "BYN",
            "ui": "63288429a8fec2242adb4b37",
            "items": [{"name": "Молоко", "quantity": 2, "price": 10.0, "sum": 20.0}],
            "trustworthy": True,
            "complete": True,
        }
    )

    assert "20,00 BYN" in message
    assert "Евроопт" in message
    assert "790730816" in message
    assert "сходится" in message


def test_distrusted_total_is_flagged_instead_of_hidden():
    message = render_receipt(
        {
            "country": "BY",
            "total_sum": 20.0,
            "currency": "BYN",
            "trustworthy": False,
            "items_reconciled": False,
        }
    )

    assert "не совпадает" in message


def test_russian_receipt_shows_fiscal_details():
    message = render_receipt(
        {
            "country": "RU",
            "fiscal_number": "9280440300007971",
            "fiscal_document_number": "123456",
            "fiscal_sign": "9876543210",
            "total_sum": 1240.0,
            "seller": {"name": "Магазин"},
            "items": [],
            "is_validated_fns": True,
        }
    )

    assert "1 240,00" in message
    assert "9280440300007971" in message
    assert "ФНС" in message


def test_message_fits_into_a_telegram_message():
    message = render_receipt(
        {
            "country": "BY",
            "total_sum": 1.0,
            "items": [{"name": f"Позиция {i} " + "я" * 100} for i in range(200)],
        }
    )

    assert len(message) < 4096


def test_ocr_fallback_shape_is_unwrapped():
    message = render_receipt(
        {
            "raw_text": "текст чека",
            "parsed": {"total": 15.5, "items": [{"name": "Хлеб", "sum": 15.5}]},
        }
    )

    assert "15,50" in message
    assert "Хлеб" in message
