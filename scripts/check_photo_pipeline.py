"""Render fixture receipts as photos and run the whole pipeline on them.

The text-level fixtures prove the parser's logic. This proves the OCR front end
handles a real monospaced thermal printout, with a QR code and the usual
photographic noise.
"""

from __future__ import annotations

import io
import pathlib
import sys

import numpy as np
import qrcode
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tests"))

from app.services.ocr import ocr_service  # noqa: E402
from app.services.parsers.receipt_by import parse_belarusian_receipt  # noqa: E402
from app.services.qr import decode_receipt_qr_bytes  # noqa: E402
from receipt_fixtures import CASES  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "testdata" / "rendered"
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\cour.ttf",
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\lucon.ttf",
    r"C:\Windows\Fonts\arial.ttf",
)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if pathlib.Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render(case: dict) -> Image.Image:
    """Draw a receipt on thermal-paper stock with a QR code under the total."""
    lines = [ln.rstrip() for ln in case["text"].splitlines() if ln.strip()]

    ui = None
    for line in lines:
        parts = line.split()
        if parts and parts[0].lower() in ("уи", "yu") and len(parts) > 1:
            ui = parts[1]
            break
    if ui is None:
        ui = f"{abs(hash(case['name'])):024x}"[:24]

    # Thermal text is large relative to the paper width. A narrow strip with
    # small type is a harder problem than a real receipt actually is.
    font = _font(28)
    width = 520
    pad = 22
    line_h = 36
    qr_size = 160
    height = pad * 2 + line_h * len(lines) + qr_size + 40

    paper = (243, 240, 232)
    img = Image.new("RGB", (width, height), paper)
    draw = ImageDraw.Draw(img)

    y = pad
    for line in lines:
        draw.text((pad, y), line, font=font, fill=(38, 36, 34))
        y += line_h

    qr = qrcode.QRCode(version=2, box_size=4, border=2)
    qr.add_data(ui)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_img = qr_img.resize((qr_size, qr_size), Image.NEAREST)
    img.paste(qr_img, ((width - qr_size) // 2, y + 20))

    return img


def photograph(img: Image.Image, seed: int) -> bytes:
    """Simulate a phone photo: angled, uneven light, softened, re-compressed."""
    rng = np.random.default_rng(seed)
    img = img.rotate(rng.uniform(-3, 3), expand=True, fillcolor=(214, 210, 200))

    w, h = img.size
    scale = rng.uniform(0.95, 1.1)
    img = img.resize((int(w * scale), int(h * scale)), Image.BICUBIC)
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.9, 1.02))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.9, 1.1))
    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.2, 0.6)))

    arr = np.array(img).astype(np.float32)
    arr += rng.normal(0, 3, arr.shape)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=int(rng.integers(78, 95)))
    return buf.getvalue()


CHECKS = (
    ("unp", "УНП"),
    ("rn_skko", "РН СККО"),
    ("document_number", "№ док"),
    ("total_sum", "итог"),
)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    wrong = 0
    unverified = 0
    total_cases = 0

    for index, case in enumerate(CASES):
        expected = case["expected"]
        data = photograph(render(case), index)
        (OUT / f"{case['name']}.jpg").write_bytes(data)

        qr = decode_receipt_qr_bytes(data)
        text = ocr_service.extract_full_text(Image.open(io.BytesIO(data)))
        result = parse_belarusian_receipt(text, ui_hint=qr)
        total_cases += 1

        wrong_fields = []
        for field, label in CHECKS:
            want = expected.get(field)
            got = result.get(field)
            if want is not None and got != want:
                wrong_fields.append(f"{label}: ждём {want!r}, получили {got!r}")
        if qr is None:
            wrong_fields.append("QR не прочитан")

        if wrong_fields:
            wrong += 1
            print(f"FAIL {case['name']}")
            for problem in wrong_fields:
                print(f"       - {problem}")
        elif not result.get("trustworthy"):
            unverified += 1
            print(
                f"OK   {case['name']}   (поля верны, но не подтверждены: "
                f"позиции {result.get('items_sum')} против итога {result.get('total_sum')})"
            )
        else:
            print(f"OK   {case['name']}")

    print()
    print(f"values correct : {total_cases - wrong}/{total_cases}")
    print(f"self-verified  : {total_cases - wrong - unverified}/{total_cases}")
    print(f"images in {OUT}")
    sys.exit(1 if wrong else 0)


if __name__ == "__main__":
    main()
