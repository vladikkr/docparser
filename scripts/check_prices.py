"""Check the prices and currencies agree between the README and the landing.

They drifted once: the README advertised 2 900 / 9 900 / 29 900 in roubles
while the landing sold the same tiers for 9 / 29 / 89 BYN. A client reading two
pages of the same product gets two different prices, and the cheaper page is
the one that has to be corrected later.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
LANDING = ROOT / "site" / "index.html"

TIERS = ("Free", "Starter", "Pro", "Business")


def _cells(row: str) -> list[str]:
    return [re.sub(r"<[^>]+>", "", cell).strip() for cell in row.split("</td>")[:-1]]


def prices_from_landing() -> dict[str, int | None]:
    """Read the price out of each table row on the landing page.

    Parsed row by row rather than with one big regex, because the markup wraps
    and only the first row is bold, and a single pattern kept matching the wrong
    row or none at all.
    """
    html = LANDING.read_text(encoding="utf-8")
    found: dict[str, int | None] = {}

    for row in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        cells = _cells(row)
        if not cells or cells[0] not in TIERS:
            continue
        for cell in cells[1:]:
            if "BYN" in cell:
                digits = re.sub(r"[^\d]", "", cell.split("BYN")[0])
                found[cells[0]] = int(digits) if digits else 0
                break
    return found


def prices_from_readme() -> dict[str, int | None]:
    text = README.read_text(encoding="utf-8")
    found: dict[str, int | None] = {}
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2 or cells[0] not in TIERS:
            continue
        digits = re.sub(r"[^\d]", "", cells[1])
        found[cells[0]] = int(digits) if digits else None
    return found


def main() -> int:
    print("=" * 58)
    print("PRICES: README vs LANDING")
    print("=" * 58)

    landing = prices_from_landing()
    readme = prices_from_readme()

    problems: list[str] = []

    for tier in TIERS:
        left, right = readme.get(tier), landing.get(tier)
        print(f"  {tier:9} README {str(left):>6}   landing {str(right):>6}")
        if left is None or right is None:
            problems.append(f"{tier}: price not found (README={left}, landing={right})")
        elif left != right:
            problems.append(f"{tier}: README says {left}, landing says {right}")

    # A price in roubles next to a BYN price is the original defect, and it
    # would slip past a value comparison because the numbers differ.
    for path in (README,):
        if "₽" in path.read_text(encoding="utf-8"):
            problems.append(f"{path.name} still quotes prices in roubles")

    if problems:
        print("\nProblems:")
        for line in problems:
            print(f"  - {line}")
        return 1

    print("\nOK: the same product is not advertised at two different prices.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
