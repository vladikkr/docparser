"""Stress the pipeline with degraded real photos and synthetic receipts.

Two questions are being answered:

1. How badly can a real receipt photo be damaged before the pipeline fails?
2. Does the Belarusian parser survive the layouts that different fiscal
   printers produce?
"""

from __future__ import annotations

import io
import pathlib
import sys

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.services.ocr import ocr_service  # noqa: E402
from app.services.parsers.receipt_by import parse_belarusian_receipt  # noqa: E402
from app.services.qr import decode_receipt_qr_bytes  # noqa: E402

REAL = pathlib.Path(r"C:\Users\vladk\Downloads\1.png.jpg")
EXPECTED_UI = "63288429a8fec2242adb4b37"
EXPECTED_TOTAL = 20.0


def _jpeg(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _rotate(img: Image.Image, degrees: float) -> Image.Image:
    return img.rotate(degrees, expand=True, fillcolor=(235, 233, 228))


def _blur(img: Image.Image, radius: float) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(radius))


def _dark(img: Image.Image, factor: float) -> Image.Image:
    return ImageEnhance.Brightness(img).enhance(factor)


def _lowres(img: Image.Image, scale: float) -> Image.Image:
    small = img.resize(
        (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
        Image.LANCZOS,
    )
    return small


def _jpeg_artifacts(img: Image.Image, quality: int) -> Image.Image:
    return Image.open(io.BytesIO(_jpeg(img, quality)))


def _crop_receipt(img: Image.Image, keep: float) -> Image.Image:
    """Cut away the notebook background, as a client would when cropping."""
    return img.crop((0, 0, img.width, int(img.height * keep)))


def _pad(img: Image.Image, factor: float) -> Image.Image:
    """Shrink the receipt inside a large frame: a small QR in a big photo."""
    w, h = img.size
    small = img.resize((int(w * factor), int(h * factor)), Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), (235, 233, 228))
    canvas.paste(small, ((w - small.width) // 2, (h - small.height) // 2))
    return canvas


CASES = [
    ("original", lambda im: im),
    ("jpeg q20", lambda im: _jpeg_artifacts(im, 20)),
    ("jpeg q10", lambda im: _jpeg_artifacts(im, 10)),
    ("jpeg q5", lambda im: _jpeg_artifacts(im, 5)),
    ("blur 1.5", lambda im: _blur(im, 1.5)),
    ("blur 3.0", lambda im: _blur(im, 3.0)),
    ("dark 0.55", lambda im: _dark(im, 0.55)),
    ("dark 0.40", lambda im: _dark(im, 0.40)),
    ("rotate 90", lambda im: _rotate(im, 90)),
    ("rotate 180", lambda im: _rotate(im, 180)),
    ("rotate 270", lambda im: _rotate(im, 270)),
    ("rotate 7deg", lambda im: _rotate(im, 7)),
    ("lowres 60%", lambda im: _lowres(im, 0.6)),
    ("lowres 35%", lambda im: _lowres(im, 0.35)),
    ("lowres 20%", lambda im: _lowres(im, 0.2)),
    ("padded 45%", lambda im: _pad(im, 0.45)),
    ("padded 25%", lambda im: _pad(im, 0.25)),
    ("crop 80%", lambda im: _crop_receipt(im, 0.80)),
    ("combined bad", lambda im: _blur(_jpeg_artifacts(_lowres(im, 0.45), 15), 1.2)),
]


def evaluate(name: str, data: bytes) -> dict:
    qr = decode_receipt_qr_bytes(data)
    text = ""
    total = None
    try:
        image = Image.open(io.BytesIO(data))
        text = ocr_service.extract_full_text(image)
    except Exception as exc:  # noqa: BLE001
        text = ""
        ocr_error = f"{type(exc).__name__}"
    else:
        ocr_error = None

    if text:
        receipt = parse_belarusian_receipt(text, ui_hint=qr)
        total = receipt.get("total_sum")
        unp = receipt.get("unp")
        trustworthy = receipt.get("trustworthy")
    else:
        unp = None
        trustworthy = None

    return {
        "case": name,
        "qr": "OK" if qr == EXPECTED_UI else ("wrong" if qr else "miss"),
        "total": "OK" if total == EXPECTED_TOTAL else total,
        "unp": "OK" if unp else "miss",
        "trust": trustworthy,
        "ocr_error": ocr_error,
    }


def main() -> None:
    base = Image.open(REAL).convert("RGB")
    rows = []
    for name, transform in CASES:
        try:
            data = _jpeg(transform(base), 92)
        except Exception as exc:  # noqa: BLE001
            rows.append({"case": name, "qr": f"error {type(exc).__name__}", "total": None, "unp": None, "trust": None})
            continue
        rows.append(evaluate(name, data))

    print(f"{'case':<16}{'QR':<8}{'total':<10}{'unp':<8}{'trust':<8}")
    print("-" * 50)
    for row in rows:
        print(f"{row['case']:<16}{str(row['qr']):<8}{str(row['total']):<10}{str(row['unp']):<8}{str(row['trust']):<8}")

    qr_ok = sum(1 for r in rows if r["qr"] == "OK")
    total_ok = sum(1 for r in rows if r["total"] == "OK")
    # A wrong number that is not flagged is the only unacceptable outcome.
    silent_wrong = [
        r["case"]
        for r in rows
        if r["total"] not in ("OK", None, "None") and r["trust"] is not False
    ]
    print("-" * 50)
    print(f"QR recovered      : {qr_ok}/{len(rows)}")
    print(f"total recovered   : {total_ok}/{len(rows)}")
    print(f"silent wrong totals: {silent_wrong or 'none'}")


if __name__ == "__main__":
    main()
