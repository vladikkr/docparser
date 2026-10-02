"""Tests for the self-employed receipt parser.

The synthetic layouts in `receipt_fixtures_selfemployed` are not captures of
the «Мой налог» app, so these tests pin the arithmetic and the failure
reporting rather than a pixel-perfect reading of someone else's layout.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

TESTS_DIR = pathlib.Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from receipt_fixtures_selfemployed import CASES

from app.models import DocumentType
from app.services.parsers.selfemployed import (
    SelfEmployedParser,
    parse_selfemployed_receipt,
)


def _all_fields(case: dict) -> None:
    result = parse_selfemployed_receipt(case["text"])
    for field, expected in case["expected"].items():
        assert result.get(field) == expected, (
            f"{case['name']}: {field} was {result.get(field)!r}, expected {expected!r}"
        )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_layout(case: dict) -> None:
    _all_fields(case)


def test_a_wrong_tax_is_refused_with_a_reason() -> None:
    case = next(c for c in CASES if c["name"] == "wrong_npd_amount")
    result = parse_selfemployed_receipt(case["text"])

    assert result["reconciled"] is False
    assert result["trustworthy"] is False
    assert any("НПД" in w and "ожидалось" in w for w in result["warnings"])


def test_a_total_that_does_not_add_up_is_refused() -> None:
    case = next(c for c in CASES if c["name"] == "total_does_not_add_up")
    result = parse_selfemployed_receipt(case["text"])

    assert result["reconciled"] is False
    assert any("Итого" in w for w in result["warnings"])


def test_missing_tax_amount_is_unknown_not_a_pass() -> None:
    """Not being able to check is not the same as checking out fine."""
    result = parse_selfemployed_receipt("Стоимость: 100,00\nИтого к оплате: 106,00")

    assert result["reconciled"] is None
    assert result["trustworthy"] is False
    assert result["warnings"]


def test_a_percentage_is_never_read_as_an_amount() -> None:
    """«НПД 6%» must not yield a cost of 6.00."""
    result = parse_selfemployed_receipt("Стоимость: 1 000,00\nНПД 6%: 60,00\nИтого: 1 060,00")

    assert result["cost"] == 1000.00
    assert result["npd_rate"] == 6.0
    assert result["npd_sum"] == 60.00


def test_empty_text_is_reported_not_guessed() -> None:
    result = parse_selfemployed_receipt("   \n  \n")

    assert "error" in result
    assert result["document_type"] == DocumentType.SELFEMPLOYED.value


def test_blank_receipt_reports_missing_total() -> None:
    result = parse_selfemployed_receipt("ЧЕК № 1\nИП Иванов Иван Иванович\n")

    assert result["total_sum"] is None
    assert any("Итоговая сумма" in w for w in result["warnings"])
    assert result["trustworthy"] is False


def test_ocr_noise_does_not_crash_the_parser() -> None:
    result = parse_selfemployed_receipt("№1\n~~~\n\u0421\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c: \uffff\n\u041d\u041f\u0414 6%: 60,00\n")

    assert isinstance(result, dict)
    assert "cost" in result


def test_the_parser_is_registered_for_its_type() -> None:
    from app.services.parsers import get_parser

    parser = get_parser(DocumentType.SELFEMPLOYED, None)

    assert isinstance(parser, SelfEmployedParser)
    assert DocumentType.SELFEMPLOYED in parser.supported_types


@pytest.mark.asyncio
async def test_garbage_bytes_do_not_crash_the_api() -> None:
    result = await SelfEmployedParser(None).parse(None, b"not an image at all")

    assert "error" in result
    assert result["document_type"] == DocumentType.SELFEMPLOYED.value


# --- detection ------------------------------------------------------------


def test_detector_recognises_a_selfemployed_receipt() -> None:
    """The tax acronym marker has to match the real wording.

    It was once written with the last two letters transposed, so the search
    never fired and every self-employed photo was parsed as a кассовый чек.
    Running the detector over the real sample text is what catches that.
    """
    from app.bot.detect import detect_from_text

    for case in CASES:
        detected = detect_from_text(case["text"])
        assert detected is not None, f"{case['name']}: not detected"
        assert detected.doc_type == "selfemployed", case["name"]


def test_detector_does_not_claim_a_cash_receipt() -> None:
    from app.bot.detect import detect_from_text

    cash = "ИП Рощина Татьяна\nУНП 790730816\nРН СККО 719014711\nИТОГО 20,00 BYN"

    assert detect_from_text(cash) is None
    assert detect_from_text("") is None
    assert detect_from_text("   \n ") is None


def test_the_acronym_marker_is_spelled_correctly() -> None:
    """Guard the exact code points, since a swap here is invisible to review.

    The expected marker is read out of the sample document rather than typed,
    because typing it by hand reproduced the same transposition it is meant to
    catch.
    """
    import re

    source = (pathlib.Path(__file__).resolve().parent.parent / "app" / "bot" / "detect.py").read_text(
        encoding="utf-8"
    )
    markers = re.findall(r'"([а-яё]{3,})"', source)

    sample = next(line for line in CASES[0]["text"].splitlines() if "%" in line)
    expected = sample.split()[0].lower()

    assert expected in markers, f"the detector does not look for {expected!r}: {markers}"

