"""Every receipt layout must yield the same fields.

The fixtures in `receipt_fixtures` describe the shapes different Belarusian
fiscal printers emit. Each one broke the parser at some point, so each is
pinned here.
"""

from __future__ import annotations

import pytest

from app.services.parsers.receipt_by import parse_belarusian_receipt
from receipt_fixtures import CASES

FIELDS = ("unp", "rn_skko", "document_number", "date", "time", "total_sum")


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
class TestLayouts:
    def test_fields_match_expected(self, case: dict) -> None:
        result = parse_belarusian_receipt(case["text"])
        expected = case["expected"]
        for field in FIELDS:
            if field in expected:
                assert result[field] == expected[field], field

    def test_item_count(self, case: dict) -> None:
        if "item_count" not in case["expected"]:
            pytest.skip("layout has no item expectations")
        result = parse_belarusian_receipt(case["text"])
        assert len(result["items"]) == case["expected"]["item_count"]

    def test_items_sum_to_total(self, case: dict) -> None:
        if "items_sum" not in case["expected"]:
            pytest.skip("layout has no item expectations")
        result = parse_belarusian_receipt(case["text"])
        assert result["items_sum"] == pytest.approx(case["expected"]["items_sum"])
        assert result["items_reconciled"] is True

    def test_document_id_is_found(self, case: dict) -> None:
        result = parse_belarusian_receipt(case["text"])
        assert result["ui"] is not None

    def test_result_is_trustworthy(self, case: dict) -> None:
        result = parse_belarusian_receipt(case["text"])
        assert result["trustworthy"] is True
        assert result["total_trustworthy"] is True


class TestRegressionGuards:
    """Each of these was a real defect found by the layout sweep."""

    def test_adjacent_numbers_are_not_merged(self) -> None:
        # A space inside the number pattern used to turn `2,89 2,89` into one
        # huge figure and wreck every total.
        text = (
            "УНП 100112233\nРН СККО 330223344\nПозиция 1\n"
            "Молоко 3,2% 1,000х2,89 2,89\n"
            "ИТОГО К ОПЛАТЕ 2,89\nСумма наличными 2,89\n"
        )
        result = parse_belarusian_receipt(text)
        assert result["total_sum"] == 2.89
        assert result["items_sum"] == pytest.approx(2.89)

    def test_discount_lines_are_not_items(self) -> None:
        # `Скидка` and `Начислено бонусов` sit between the items and the total
        # and used to be counted as sale lines.
        text = (
            "УНП 590223344\nПозиция 1\nКуртка 1,000х100,00 100,00\n"
            "Скидка 40,00\nНачислено бонусов 12\n"
            "ИТОГО К ОПЛАТЕ 60,00\nСумма наличными 60,00\n"
        )
        result = parse_belarusian_receipt(text)
        assert len(result["items"]) == 1
        assert result["discount"] == 40.0
        assert result["items_reconciled"] is True

    def test_full_discount_reaches_zero_total(self) -> None:
        text = (
            "УНП 310445566\nПозиция 1\nСертификат 1,000х100,00 100,00\n"
            "Скидка 100,00\nИТОГО К ОПЛАТЕ 0,00\nСумма наличными 0,00\n"
        )
        result = parse_belarusian_receipt(text)
        assert result["total_sum"] == 0.0
        assert result["items_reconciled"] is True
        assert result["trustworthy"] is True

    def test_card_payment_corroborates_total(self) -> None:
        # The card line repeats the figure, so it counts as a second source.
        text = (
            "УНП 441190233\nПозиция 1\nСтрижка 1,000х45,00 45,00\n"
            "ИТОГО К ОПЛАТЕ 45,00\nОплата картой 45,00\n"
        )
        result = parse_belarusian_receipt(text)
        assert result["total_lines"] >= 2
        assert result["totals_agree"] is True
        assert result["total_trustworthy"] is True

    def test_description_numbers_stay_in_the_name(self) -> None:
        # `3,2%` and `0,93л` belong to the product description, not to the
        # quantity/price pair.
        text = (
            "УНП 190790789\nПозиция 1\nМолоко 3,2% 0,93л 2,000х2,89 5,78\n"
            "ИТОГО К ОПЛАТЕ 5,78\nСумма наличными 5,78\n"
        )
        result = parse_belarusian_receipt(text)
        row = result["items"][0]
        assert row["quantity"] == 2.0
        assert row["sum"] == 5.78
        assert "Молоко" in row["name"]

    def test_thousands_separator_in_total(self) -> None:
        text = (
            "УНП 291004455\nПозиция 1\nНоутбук 1,000х1 250,00 1 250,00\n"
            "ИТОГО К ОПЛАТЕ 1 250,00\nСумма наличными 1 250,00\n"
        )
        result = parse_belarusian_receipt(text)
        assert result["total_sum"] == 1250.0
        assert result["items_sum"] == pytest.approx(1250.0)

    def test_price_reported_when_it_multiplies_out(self) -> None:
        text = (
            "УНП 790730816\nПозиция 1\nУслуга 1,000х20 20,00\n"
            "ИТОГО К ОПЛАТЕ 20,00\nСумма наличными 20,00\n"
        )
        result = parse_belarusian_receipt(text)
        row = result["items"][0]
        # 1 x 20 does equal 20.00, so the price is confirmed and reported.
        assert row["quantity"] == 1.0
        assert row["price"] == 20.0

    def test_single_digit_decimal_is_not_a_thousands_group(self) -> None:
        # `3,2%` is three point two. Reading the comma as a thousands separator
        # turned it into 32.
        from app.services.parsers.receipt_by import _money

        assert _money("3,2") == 3.2
        assert _money("1,000") == 1000.0
        assert _money("1,50") == 1.5
