"""Receipt QR decoding that survives real-world phone photos.

A QR on a receipt is usually small relative to a multi-megapixel frame and the
paper is creased, so decoding the file at its native size often returns nothing.
The detector below retries the image at several scales and, failing that,
sweeps overlapping windows. zbar does the actual decoding; OpenCV is a backup.
"""

from __future__ import annotations

import io
import logging
from typing import Any, Iterable

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Receipt QRs carry fiscal number and signature under these keys (RU) or a
# unique document id (BY). A bare token is still worth returning.
_FISCAL_HINT = ("fn=", "fp=", "i=", "s=")


def _looks_like_receipt(text: str) -> bool:
    if not text or len(text) < 8:
        return False
    return any(hint in text for hint in _FISCAL_HINT) or len(text) >= 16


def _zbar(image: Image.Image) -> Iterable[str]:
    from pyzbar.pyzbar import decode

    for found in decode(image):
        text = found.data.decode("utf-8", errors="ignore").strip()
        if text:
            yield text


def _opencv(array: np.ndarray) -> Iterable[str]:
    import cv2

    text, _, _ = cv2.QRCodeDetector().detectAndDecode(array)
    if text:
        yield text.strip()


def _load(data: bytes) -> list[Image.Image]:
    from app.services.ocr import ocr_service

    if data[:4] == b"%PDF":
        return list(ocr_service.pdf_to_images(data))
    return [Image.open(io.BytesIO(data))]


def decode_receipt_qr(image: Image.Image) -> str | None:
    """Return the QR payload from a single image, or None."""
    rgb = image.convert("RGB")
    gray = np.array(rgb.convert("L"))
    width, height = rgb.size

    scales = []
    for target in (1400, 1000, 800, 600, 400, 2400):
        if abs(target - width) > 40:
            scales.append(target)

    import cv2

    best: str | None = None
    for target in scales:
        ratio = target / width
        resized = cv2.resize(gray, (target, max(1, int(height * ratio))))
        for reader in (_zbar, _opencv):
            try:
                if reader is _opencv:
                    payload = list(_opencv(resized))
                else:
                    payload = list(_zbar(Image.fromarray(resized)))
            except Exception:
                payload = []
            for text in payload:
                if _looks_like_receipt(text):
                    return text
                best = best or text
    if best:
        return best

    # Sweep windows: the code may sit in one corner or be creased.
    for tile in (700, 450, 300):
        if tile >= min(width, height):
            break
        step = tile // 2
        for y in range(0, max(1, height - tile), step):
            for x in range(0, max(1, width - tile), step):
                crop = Image.fromarray(gray[y : y + tile, x : x + tile])
                try:
                    for text in _zbar(crop):
                        if _looks_like_receipt(text):
                            return text
                        best = best or text
                except Exception:
                    continue
    return best


def decode_receipt_qr_bytes(data: bytes) -> str | None:
    """Return the QR payload from raw image or PDF bytes."""
    for image in _load(data):
        try:
            text = decode_receipt_qr(image)
        except Exception as exc:
            logger.debug("qr_decode_failed", error=str(exc))
            continue
        if text:
            return text
    return None
