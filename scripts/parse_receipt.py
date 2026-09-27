#!/usr/bin/env python3
"""Parse a Russian receipt/invoice into structured JSON from the command line.

This is the manual-delivery path: the operator runs one command per document and
hands the JSON to the client. No always-on server required.

    python scripts/parse_receipt.py receipt.jpg
    python scripts/parse_receipt.py receipt.jpg --raw-text
    python scripts/parse_receipt.py receipt.jpg --out result.json
"""

import argparse
import asyncio
import json
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def _find_qr_string(data: bytes) -> str | None:
    """Locate the receipt QR payload in an image or PDF.

    Tries OpenCV's detector; falls back to scanning the raw bytes for the
    characteristic `t=...&s=...&fn=...&i=...&fp=...` pattern.
    """
    try:
        import cv2
        import numpy as np
        from PIL import Image
        import io

        if data[:4] == b"%PDF":
            from app.services.ocr import ocr_service

            pages = ocr_service.pdf_to_images(data)
            images = pages
        else:
            images = [Image.open(io.BytesIO(data))]

        detector = cv2.QRCodeDetector()
        for image in images:
            arr = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
            text, _, _ = detector.detectAndDecode(arr)
            if text and "fn=" in text and "fp=" in text:
                return text
    except Exception:
        pass

    # Fallback: search the raw payload for a QR string
    marker = b"t=20"
    start = data.find(marker)
    if start != -1:
        chunk = data[start : start + 200].split(b"\x00")[0]
        try:
            candidate = chunk.decode("ascii", errors="ignore")
        except Exception:
            candidate = ""
        if "fn=" in candidate and "fp=" in candidate:
            return candidate

    return None


async def _parse(path: pathlib.Path, raw_text: bool) -> dict:
    from app.services.fn_api import FNSApiError, fns_client, validate_receipt_by_qr
    from app.services.ocr import ocr_service

    data = path.read_bytes()
    result: dict = {
        "source_file": path.name,
        "size_bytes": len(data),
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }

    qr = _find_qr_string(data)
    result["qr_found"] = bool(qr)

    if qr:
        try:
            receipt = await validate_receipt_by_qr(qr)
            payload = receipt.model_dump(mode="json")
            result["method"] = "fns"
            result["document_type"] = "receipt_kkt"
            result["data"] = payload
            if raw_text:
                result.pop("data", None)
            return result
        except FNSApiError as exc:
            result["method"] = "ocr"
            result["warning"] = f"FNS lookup failed ({exc.code}): {exc.message}"
        except Exception as exc:
            result["method"] = "ocr"
            result["warning"] = f"FNS lookup error: {type(exc).__name__}: {exc}"

    # OCR fallback
    try:
        if data[:4] == b"%PDF":
            text = ocr_service.extract_full_text_from_pdf(data)
        else:
            from PIL import Image
            import io

            text = ocr_service.extract_full_text(Image.open(io.BytesIO(data)))
        result["method"] = "ocr"
        result["document_type"] = "receipt_kkt"
        result["data"] = {"raw_text": text}
    except Exception as exc:
        result["method"] = "failed"
        result["error"] = (
            f"{type(exc).__name__}: {exc}. "
            "Install OCR extras: pip install -r requirements-ocr.txt"
        )

    return result


def _summarise(result: dict) -> str:
    """Human-readable digest for quick checking before sending to a client."""
    lines: list[str] = []
    method = result.get("method")
    lines.append(f"Файл:      {result.get('source_file')}")
    lines.append(f"Метод:     {method}")

    if method == "fns":
        data = result.get("data", {})
        seller = data.get("seller") or {}
        lines.append(f"Продавец:  {seller.get('name') or '—'} (ИНН {seller.get('inn') or '—'})")
        lines.append(f"Дата:      {data.get('date_time') or '—'}")
        lines.append(f"Итого:     {data.get('total_sum') or '—'} руб")
        items = data.get("items") or []
        lines.append(f"Позиций:   {len(items)}")
        for row in items[:8]:
            lines.append(
                f"   - {row.get('name', '?')} | {row.get('quantity', '?')} x "
                f"{row.get('price', '?')} = {row.get('sum', '?')} | НДС {row.get('vat_rate') or '—'}"
            )
        if len(items) > 8:
            lines.append(f"   ... ещё {len(items) - 8}")
    else:
        if result.get("warning"):
            lines.append(f"Внимание:  {result['warning']}")
        if result.get("error"):
            lines.append(f"Ошибка:    {result['error']}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse a receipt into JSON")
    parser.add_argument("file", type=pathlib.Path, help="receipt image or PDF")
    parser.add_argument("--raw-text", action="store_true", help="keep only recognised text")
    parser.add_argument("--out", type=pathlib.Path, help="write JSON to a file")
    parser.add_argument("--quiet", action="store_true", help="skip the human summary")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"File not found: {args.file}", file=sys.stderr)
        return 2

    result = asyncio.run(_parse(args.file, args.raw_text))
    text = json.dumps(result, ensure_ascii=False, indent=2)

    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"Saved: {args.out}")
    if not args.quiet:
        print()
        print(_summarise(result))
        print()
    if not args.out:
        print(text)

    return 0 if result.get("method") != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
