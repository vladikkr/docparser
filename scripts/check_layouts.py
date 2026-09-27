"""Check the Belarusian parser against every fixture layout."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tests"))

from app.services.parsers.receipt_by import parse_belarusian_receipt  # noqa: E402
from receipt_fixtures import CASES  # noqa: E402

CHECKS = (
    ("unp", "УНП"),
    ("rn_skko", "РН СККО"),
    ("document_number", "№ док"),
    ("date", "дата"),
    ("time", "время"),
    ("total_sum", "итог"),
)

failures = 0

for case in CASES:
    expected = case["expected"]
    result = parse_belarusian_receipt(case["text"])

    problems: list[str] = []
    for field, label in CHECKS:
        want = expected.get(field)
        got = result.get(field)
        if want is not None and got != want:
            problems.append(f"{label}: ждём {want!r}, получили {got!r}")

    items = result.get("items") or []
    if "item_count" in expected and len(items) != expected["item_count"]:
        problems.append(f"позиций: ждём {expected['item_count']}, получили {len(items)}")
    if "items_sum" in expected:
        if result.get("items_sum") is None or abs(result["items_sum"] - expected["items_sum"]) > 0.01:
            problems.append(f"сумма позиций: ждём {expected['items_sum']}, получили {result.get('items_sum')}")
    if result.get("ui") is None:
        problems.append("УИ не найден")
    if not result.get("trustworthy"):
        problems.append("не trustworthy")

    status = "OK  " if not problems else "FAIL"
    if problems:
        failures += 1
    print(f"{status} {case['name']}")
    for problem in problems:
        print(f"       - {problem}")

print()
print(f"{len(CASES) - failures}/{len(CASES)} layouts correct")
sys.exit(1 if failures else 0)
