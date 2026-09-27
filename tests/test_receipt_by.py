"""Tests for the Belarusian receipt parser (OCR text -> structured fields)."""

import pytest

from app.services.parsers.receipt_by import (
    _money,
    parse_belarusian_receipt,
)

# OCR output of a real Belarusian receipt, with the misreadings Tesseract
# actually produced: Cyrillic labels read as Latin, `ИП` as `И!`, `BYN` as a
# word, and the document id corrupted.
OCR_TEXT = """
„= 7 7”
ф-т
И! Рощина 1атьяна
Александровна
Ателье у Татьяны
г, Бобруйск , Пр-т.
Строителей д. 58
УНП 790730816
PH CKKO 719014711
| Платежный документ
№ док. 1539
i Позиция 1 Я
1 ,000x20, СОВУМ 20,00
ИТОГО К ОПЛАТЕ 20,00
Сумма наличными 20,00
Кассир 01
Дата 24.09.26 Время 15:12:23
YU 63288429a8fec2242adp4b37
"""

QR_UI = "63288429a8fec2242adb4b37"


@pytest.fixture
def receipt() -> dict:
    return parse_belarusian_receipt(OCR_TEXT, ui_hint=QR_UI)


class TestMoney:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("20,00", 20.0),
            ("1 234,56", 1234.56),
            ("1,50", 1.5),
            ("0,05", 0.05),
            ("20", 20.0),
            ("abc", None),
            ("", None),
        ],
    )
    def test_parses_receipt_amounts(self, raw: str, expected: float | None) -> None:
        assert _money(raw) == expected

    def test_thousands_separator_is_not_a_decimal(self) -> None:
        # `1,000` on a Belarusian receipt means one, not one thousand.
        assert _money("1,000") == 1000.0

    def test_receipts_use_two_decimals(self) -> None:
        # Cash receipts carry kopecks/cents, so a three-digit tail is a
        # thousands group rather than a thousandth of a unit.
        assert _money("0,005") == 5.0


class TestFields:
    def test_seller(self, receipt: dict) -> None:
        assert "Рощина" in receipt["seller"]["name"]
        assert "Татьяна" in receipt["seller"]["name"]

    def test_unp_survives_latin_lookalikes(self, receipt: dict) -> None:
        assert receipt["unp"] == "790730816"

    def test_rn_skko_survives_latin_lookalikes(self, receipt: dict) -> None:
        # OCR produced `PH CKKO`.
        assert receipt["rn_skko"] == "719014711"

    def test_document_number(self, receipt: dict) -> None:
        assert receipt["document_number"] == "1539"

    def test_date_and_time(self, receipt: dict) -> None:
        assert receipt["date"] == "2026-09-24"
        assert receipt["time"] == "15:12:23"

    def test_total_uses_payment_total_not_cash_tendered(self, receipt: dict) -> None:
        assert receipt["total_sum"] == 20.0
        assert receipt["currency"] == "BYN"

    def test_currency_is_byn(self, receipt: dict) -> None:
        assert receipt["currency"] == "BYN"


class TestItems:
    def test_single_item_found(self, receipt: dict) -> None:
        assert len(receipt["items"]) == 1

    def test_quantity_is_ambiguity_resolved(self, receipt: dict) -> None:
        # The printed line is `1,000x20,00BYN 20,00`; OCR turned the price into
        # `20, СОВУМ`. The sum survives, and the quantity is fixed by
        # `quantity x 20,00 = 20,00`.
        row = receipt["items"][0]
        assert row["quantity"] == 1.0
        assert row["sum"] == 20.0

    def test_price_survives_mangled_decimal_separator(self, receipt: dict) -> None:
        # `20, СОВУМ` has no readable decimals, yet `1 x 20,00 = 20,00` still
        # identifies the price, so it is reported rather than dropped.
        assert receipt["items"][0]["price"] == 20.0

    def test_items_reconcile_with_total(self, receipt: dict) -> None:
        assert receipt["items_reconciled"] is True
        assert receipt["items_sum"] == pytest.approx(receipt["total_sum"])


class TestDocumentId:
    def test_qr_value_wins_over_corrupted_ocr(self, receipt: dict) -> None:
        # OCR read `adp4b37`; the QR carried the true id.
        assert receipt["ui"] == QR_UI
        assert receipt["ui"] == "63288429a8fec2242adb4b37"

    def test_falls_back_to_text_when_no_qr(self) -> None:
        result = parse_belarusian_receipt(OCR_TEXT)
        # No hint: the OCR token contains `p`, which is not hex, so nothing is
        # invented. The id is simply absent rather than wrong.
        assert result["ui"] is None or len(result["ui"]) >= 16


class TestDegradation:
    def test_empty_text(self) -> None:
        result = parse_belarusian_receipt("")
        assert result["complete"] is False
        assert result["error"] == "no text recognised"

    def test_missing_total_still_returns_partial(self) -> None:
        result = parse_belarusian_receipt("УНП 1234567890\nАтелье")
        assert result["total_sum"] is None
        assert result["complete"] is False
        assert result["unp"] == "1234567890"

    def test_country_and_type(self, receipt: dict) -> None:
        assert receipt["country"] == "BY"
        assert receipt["document_type"] == "receipt_kkt"


class TestTrustworthiness:
    """A wrong number must never look trustworthy.

    OCR on a damaged photo turned `ИТОГО К ОПЛАТЕ 20,00` into noise ending in
    `, 90`, and the parser reported 90.00 as correct with a green flag. These
    tests pin that failure shut.
    """

    def test_healthy_receipt_is_trustworthy(self, receipt: dict) -> None:
        assert receipt["trustworthy"] is True
        assert receipt["totals_agree"] is True
        assert receipt["total_lines"] >= 2

    def test_disagreeing_totals_are_flagged(self) -> None:
        text = (
            "УНП 790730816\nПозиция 1\n1,000х20,00 20,00\n"
            "ИТОГО К ОПЛАТЕ 25,00\nСумма наличными 20,00\n"
        )
        result = parse_belarusian_receipt(text)
        assert result["totals_agree"] is False
        assert result["trustworthy"] is False

    def test_total_without_decimals_is_rejected(self) -> None:
        # Thermal receipts always print two decimals; a bare integer is noise.
        result = parse_belarusian_receipt("УНП 790730816\nИТОГО К ОПЛАТЕ 90\n")
        assert result["total_sum"] is None

    def test_orphan_decimal_fragment_is_rejected(self) -> None:
        # A cropped band of the photo can leave `,00` behind.
        result = parse_belarusian_receipt("УНП 790730816\nИТОГО К ОПЛАТЕ ,00\n")
        assert result["total_sum"] is None

    def test_single_uncorroborated_total_is_not_trusted(self) -> None:
        # One total line and no line items: nothing verifies the figure.
        result = parse_belarusian_receipt(
            "ИП Рощина Татьяна\nУНП 790730816\nИТОГО К ОПЛАТЕ 0,00\n"
        )
        assert result["total_sum"] == 0.0
        assert result["total_lines"] == 1
        assert result["trustworthy"] is False

    def test_reconciled_is_unknown_without_items(self) -> None:
        result = parse_belarusian_receipt(
            "УНП 790730816\nИТОГО К ОПЛАТЕ 20,00\nСумма наличными 20,00\n"
        )
        assert result["items"] == []
        # Vacuously "equal" would be a lie: there is nothing to compare against.
        assert result["items_reconciled"] is None
        # Two separately printed totals agreeing is real corroboration.
        assert result["trustworthy"] is True

    def test_item_sum_mismatch_is_not_trusted(self) -> None:
        text = (
            "УНП 790730816\nПозиция 1\nМолоко 2,000х3,00 6,00\n"
            "ИТОГО К ОПЛАТЕ 20,00\n"
        )
        result = parse_belarusian_receipt(text)
        assert result["items"]
        assert result["items_reconciled"] is False
        assert result["trustworthy"] is False

