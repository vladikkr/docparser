"""End-to-end check for a self-employed receipt: render an image, then read it.

The parser works on OCR text, so the only way to know it survives a real photo
is to make one. The layout mirrors the «Мой налог» print as closely as a text
render can, and the same case is reused for the tax mismatch.
"""

from __future__ import annotations

import asyncio
import io
import pathlib
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.bot.detect import detect, detect_from_text
from app.bot.render import render
from app.bot.service import process
from app.services.parsers.selfemployed import parse_selfemployed_receipt

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
)

GOOD = [
    "ЧЕК",
    "№ 000012345",
    "от 24.09.2026",
    "ИП Иванов Иван Иванович",
    "ИНН 790730816",
    "Ремонт холодильника",
    "Стоимость товаров (работ, услуг): 1 200,00",
    "НПД 6%: 72,00",
    "Итого к оплате: 1 272,00",
]

BAD = [
    "ЧЕК",
    "№ 000012346",
    "от 25.09.2026",
    "ИП Иванов Иван Иванович",
    "ИНН 790730816",
    "Стоимость товаров (работ, услуг): 1 000,00",
    "НПД 6%: 50,00",
    "Итого к оплате: 1 050,00",
]


def _font(size: int):
    for path in FONT_CANDIDATES:
        if pathlib.Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render_image(lines: list[str]) -> bytes:
    width, line_height = 900, 46
    height = line_height * len(lines) + 80
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = _font(30)

    for index, line in enumerate(lines):
        draw.text((40, 40 + index * line_height), line, fill="black", font=font)

    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def check(name: str, lines: list[str], expect_reconciled) -> bool:
    image = render_image(lines)
    print(f"\n=== {name} ===")
    print(f"  rendered {len(image)} bytes")

    parsed = parse_selfemployed_receipt("\n".join(lines))
    print(f"  direct parse: cost={parsed['cost']} rate={parsed['npd_rate']} "
          f"npd={parsed['npd_sum']} total={parsed['total_sum']} "
          f"reconciled={parsed['reconciled']}")

    detection = detect(image)
    print(f"  detection   : {detection.doc_type} ({detection.source})")

    outcome = asyncio.run(process(image, "check.png"))
    print(f"  bot parse   : ok={outcome.ok} type={outcome.doc_type}")
    if not outcome.ok:
        print(f"  note        : {outcome.note}")
        return False

    print("  --- what the client would see ---")
    for line in render(outcome).splitlines():
        print(f"  {line}")

    ok = outcome.ok and parsed["reconciled"] is expect_reconciled
    if outcome.ok and outcome.data.get("reconciled") != expect_reconciled:
        ok = False
    print(f"  RESULT      : {'OK' if ok else 'MISMATCH'}")
    return ok


def main() -> int:
    text_detection = detect_from_text("\n".join(GOOD))
    print(f"text-only detection: {text_detection.doc_type if text_detection else None}")

    good = check("correct tax, 6%", GOOD, True)
    bad = check("tax understated", BAD, False)

    print()
    print("All self-employed checks passed." if good and bad else "Self-employed checks FAILED.")
    return 0 if good and bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
