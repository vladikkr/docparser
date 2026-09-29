"""Check the button labels in the bot and the labels written in the docs agree.

The docs tell the owner to press a specific button, and the admin notification
is the only place that button exists. If the two drift, the owner is pressing a
label that is not there and paid access never gets handed over.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
HANDLERS = ROOT / "app" / "bot" / "handlers.py"
DOCS = [ROOT / "docs" / "sales.md", ROOT / "docs" / "bot.md"]


def button_labels() -> list[str]:
    source = HANDLERS.read_text(encoding="utf-8")
    return re.findall(r'InlineKeyboardButton\(\s*"([^"]+)"', source)


def bare(label: str) -> str:
    """The label without its leading emoji, which the docs do not repeat."""
    return label.lstrip("✅❌✔✖️✔️ ").strip()


def main() -> int:
    labels = button_labels()
    print("=" * 58)
    print("BUTTON LABELS")
    print("=" * 58)
    for label in labels:
        print(f"  {label}")

    if not labels:
        print("\nNo inline buttons found in handlers.py, which cannot be right.")
        return 1

    docs_text = "\n".join(path.read_text(encoding="utf-8") for path in DOCS if path.exists())
    problems: list[str] = []

    approve = next((label for label in labels if "Выдать" in label), None)
    if approve is None:
        problems.append("no button that grants access, expected one containing 'Выдать'")
    elif bare(approve) not in docs_text:
        problems.append(f"docs never name the approve button: {bare(approve)!r}")

    # A label mixing Cyrillic and Latin reads as a typo, and that is exactly
    # how "Выдать access" got into the docs once.
    for label in labels:
        if re.search(r"[A-Za-z]", label) and re.search(r"[А-Яа-яЁё]", label):
            problems.append(f"button label mixes alphabets: {label!r}")

    if problems:
        print("\nProblems:")
        for line in problems:
            print(f"  - {line}")
        return 1

    print("\nOK: the docs name the buttons that actually exist.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
