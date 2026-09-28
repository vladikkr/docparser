#!/usr/bin/env python3
"""Parse every test document and assert the result is actually usable.

The previous version of this script called a parse successful whenever the
result carried no `error` key, which a parser returning zero items and empty
totals passes happily. It also skipped four document types entirely. Every case
below therefore states what it expects, and a run only succeeds when the fields
are really there and the arithmetic really reconciles.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.models import DocumentType
from app.services.parsers import get_parser

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEST_XML = ROOT / "test_xml"


class CheckFailed(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


def expect_invoice_like(
    name: str,
    file_path: pathlib.Path,
    doc_type: DocumentType,
    *,
    document_number: str,
    item_count: int,
    total_with_vat: float | None = None,
    totals_bucket: str | None = None,
    seller: str | None = None,
    buyer: str | None = None,
    basis_number: str | None = None,
    reconcile_items: bool = True,
) -> None:
    parser = get_parser(doc_type, None)
    require(parser is not None, f"{name}: no parser registered for {doc_type}")
    require(file_path.exists(), f"{name}: fixture {file_path} is missing")

    result = asyncio.run(parser.parse(None, file_path.read_bytes()))
    require("error" not in result, f"{name}: parser returned an error: {result.get('error')}")

    parsed = result["parsed"]
    require(
        parsed.get("warnings") == [],
        f"{name}: parser reported warnings: {parsed.get('warnings')}",
    )
    require(
        len(parsed["items"]) == item_count,
        f"{name}: expected {item_count} items, got {len(parsed['items'])}",
    )
    require(
        parsed.get("document_number") == document_number,
        f"{name}: document number {parsed.get('document_number')!r} != {document_number!r}",
    )

    totals = parsed.get("totals") or {}
    bucket = totals.get(totals_bucket) if totals_bucket else totals
    require(bucket is not None, f"{name}: totals bucket {totals_bucket!r} is missing")

    if total_with_vat is not None:
        actual = bucket.get("total_with_vat")
        require(
            actual is not None and abs(actual - total_with_vat) < 0.02,
            f"{name}: total_with_vat {actual} != {total_with_vat}",
        )
        # In a correction `ВсегоУвел`/`ВсегоУм` hold the amount being increased
        # or decreased, which is the value *before* the change. The restated
        # line values therefore must not be summed against it.
        if reconcile_items:
            summed = sum(i["total_with_vat"] for i in parsed["items"] if i.get("total_with_vat"))
            require(
                abs(summed - total_with_vat) < 0.02,
                f"{name}: items sum to {summed:.2f} but the total says {total_with_vat:.2f}",
            )

    if seller:
        require(
            parsed["seller"].get("name") == seller,
            f"{name}: seller {parsed['seller'].get('name')!r} != {seller!r}",
        )
    if buyer:
        require(
            parsed["buyer"].get("name") == buyer,
            f"{name}: buyer {parsed['buyer'].get('name')!r} != {buyer!r}",
        )
    if basis_number:
        require(
            (parsed.get("basis") or {}).get("number") == basis_number,
            f"{name}: basis number {(parsed.get('basis') or {}).get('number')!r} != {basis_number!r}",
        )

    print(f"  OK  {name}: {len(parsed['items'])} items, итого {total_with_vat}")


def expect_rejected(name: str, file_path: pathlib.Path, doc_type: DocumentType, why: str) -> None:
    """A parser must refuse a file of the wrong shape rather than invent data."""
    parser = get_parser(doc_type, None)
    require(parser is not None, f"{name}: no parser registered for {doc_type}")

    result = asyncio.run(parser.parse(None, file_path.read_bytes()))
    require("error" in result, f"{name}: {why} — but the parser accepted it anyway")
    print(f"  OK  {name}: refused as expected ({result['error'][:60]}…)")


def expect_ttn(
    name: str,
    file_path: pathlib.Path,
    doc_type: DocumentType,
    *,
    document_number: str,
    item_count: int,
) -> None:
    """An ЭТрН carries cargo, not prices, so only those fields are asserted."""
    parser = get_parser(doc_type, None)
    require(parser is not None, f"{name}: no parser registered for {doc_type}")
    require(file_path.exists(), f"{name}: fixture {file_path} is missing")

    result = asyncio.run(parser.parse(None, file_path.read_bytes()))
    require("error" not in result, f"{name}: parser returned an error: {result.get('error')}")

    parsed = result["parsed"]
    require(
        len(parsed["items"]) == item_count,
        f"{name}: expected {item_count} cargo items, got {len(parsed['items'])}",
    )
    require(
        parsed.get("document_number") == document_number,
        f"{name}: document number {parsed.get('document_number')!r} != {document_number!r}",
    )
    require(
        parsed["items"][0].get("name"),
        f"{name}: cargo item has no name",
    )
    # The amount lives on the other title, so saying so is the correct answer.
    require(
        any("997/07" in w for w in parsed["warnings"]),
        f"{name}: expected a warning about the missing 997/07 title, got {parsed['warnings']}",
    )
    print(f"  OK  {name}: {len(parsed['items'])} cargo items, номер {document_number}")


CASES: list[Any] = [
    # УПД with invoice data, format 5.03, two VAT rates and an individual buyer.
    lambda: expect_invoice_like(
        "upd",
        TEST_XML / "upd" / "upd_valid.xml",
        DocumentType.UPD,
        document_number="0000000123",
        item_count=3,
        total_with_vat=2295.00,
        seller='ООО "ТехноСервис"',
        buyer='ООО "Ромашка"',
    ),
    # УПД without a basis document says so explicitly rather than staying silent.
    lambda: expect_invoice_like(
        "ukd",
        TEST_XML / "ukd" / "ukd_valid.xml",
        DocumentType.UKD,
        document_number="КСФ-00012",
        item_count=1,
        totals_bucket="increase",
        total_with_vat=540.00,
        basis_number="0000000123",
        reconcile_items=False,
    ),
    lambda: expect_invoice_like(
        "invoice",
        TEST_XML / "invoice" / "invoice_valid.xml",
        DocumentType.INVOICE,
        document_number="56789",
        item_count=3,
        total_with_vat=264000.00,
    ),
    lambda: expect_invoice_like(
        "invoice_correction",
        TEST_XML / "invoice_correction" / "invoice_correction_valid.xml",
        DocumentType.INVOICE_CORRECTION,
        document_number="КСФ-00099",
        item_count=1,
        totals_bucket="decrease",
        total_with_vat=60000.00,
        basis_number="56789",
        reconcile_items=False,
    ),
    # ТОРГ-12 and an act come from a different приказ, and their item elements
    # are named differently, so they get their own expectations.
    lambda: expect_invoice_like(
        "torg12",
        TEST_XML / "torg12" / "torg12_valid.xml",
        DocumentType.TORG12,
        document_number="ТОРГ12-0001",
        item_count=3,
        total_with_vat=2295.00,
        seller='ООО "ТехноСервис"',
        buyer='ООО "Ромашка"',
    ),
    lambda: expect_invoice_like(
        "act",
        TEST_XML / "act" / "act_valid.xml",
        DocumentType.ACT,
        document_number="АКТ-0031",
        item_count=1,
        total_with_vat=180000.00,
        seller='ООО "ТехноСервис"',
        buyer='ООО "Ромашка"',
    ),
    # ЭТрН has no line table: the cargo is aggregated and the money lives on
    # the 997/07 title, so this case checks the cargo and the honest warning.
    lambda: expect_ttn(
        "ttn",
        TEST_XML / "ttn" / "ttn_valid.xml",
        DocumentType.TTN,
        document_number="СВ-0001",
        item_count=2,
    ),
    # A счёт-фактура must not be accepted as a УПД with a different КНД.
    lambda: expect_rejected(        "upd_rejects_torg12",
        TEST_XML / "torg12" / "torg12_valid.xml",
        DocumentType.UPD,
        "ТОРГ-12 is КНД 1175010, not an invoice",
    ),
    lambda: expect_rejected(
        "upd_rejects_act",
        TEST_XML / "act" / "act_valid.xml",
        DocumentType.UPD,
        "an act is КНД 1175012, not an invoice",
    ),
    lambda: expect_rejected(
        "upd_rejects_garbage",
        ROOT / "test_xml" / "receipt_kkt_ru" / "receipt_kkt_ru_qr.txt",
        DocumentType.UPD,
        "the fixture is not XML at all",
    ),
]


def main() -> int:
    print("=" * 66)
    print("VALIDATING EVERY DOCUMENT TYPE AGAINST ITS PARSER")
    print("=" * 66)

    failures: list[str] = []
    for case in CASES:
        try:
            case()
        except CheckFailed as exc:
            failures.append(str(exc))
            print(f"  FAIL {exc}")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed:")
        for line in failures:
            print(f"  - {line}")
        return 1

    print(f"All {len(CASES)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
