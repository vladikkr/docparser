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


def _decode_qr(image) -> str | None:
    """Try pyzbar first, then OpenCV.

    OpenCV's detector silently fails on some receipt QRs that zbar reads
    without trouble, so it is only a backup.
    """
    try:
        from pyzbar.pyzbar import decode as zb_decode

        for found in zb_decode(image):
            text = found.data.decode("utf-8", errors="ignore")
            if "fn=" in text and "fp=" in text:
                return text
    except Exception:
        pass

    try:
        import cv2
        import numpy as np

        arr = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        text, _, _ = cv2.QRCodeDetector().detectAndDecode(arr)
        if text and "fn=" in text and "fp=" in text:
            return text
    except Exception:
        pass

    return None


def _find_qr_string(data: bytes) -> str | None:
    """Locate the receipt QR payload in an image or PDF."""
    try:
        from PIL import Image
        import io

        if data[:4] == b"%PDF":
            from app.services.ocr import ocr_service

            images = ocr_service.pdf_to_images(data)
        else:
            images = [Image.open(io.BytesIO(data))]

        for image in images:
            text = _decode_qr(image)
            if text:
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


def _payload_from_qr(qr: str, warning: str) -> dict:
    """Build a partial receipt payload from the QR string alone.

    The QR carries date, total, fiscal number, document number and signature.
    Seller name, address and item lines only come from the FNS response, so the
    result is flagged `complete: False`.
    """
    from app.services.fn_api import fns_client

    fields = fns_client.parse_qr_string(qr)
    return {
        "fiscal_number": fields.get("fiscal_number"),
        "fiscal_document_number": fields.get("fiscal_document_number"),
        "fiscal_sign": fields.get("fiscal_sign"),
        "date_time": fields.get("date_time"),
        "total_sum": fields.get("sum"),
        "seller": None,
        "items": [],
        "note": "Seller details and item lines require a FNS lookup.",
        "warning": warning,
    }


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
            result["method"] = "qr"
            result["warning"] = f"FNS rejected the receipt ({exc.code}): {exc.message}"
        except Exception as exc:
            result["method"] = "qr"
            result["warning"] = f"FNS unavailable: {type(exc).__name__}"

        # FNS did not answer, but the QR itself already carries the requisites.
        result["document_type"] = "receipt_kkt"
        result["data"] = _payload_from_qr(qr, result["warning"])
        result["complete"] = False
        if raw_text:
            result["data"] = {"raw_text": qr}
        return result

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
    elif method == "qr":
        data = result.get("data", {})
        lines.append(f"ФН:        {data.get('fiscal_number') or '—'}")
        lines.append(f"ФД:        {data.get('fiscal_document_number') or '—'}")
        lines.append(f"ФП:        {data.get('fiscal_sign') or '—'}")
        lines.append(f"Дата:      {data.get('date_time') or '—'}")
        lines.append(f"Итого:     {data.get('total_sum') or '—'} руб")
        lines.append("Продавец:  недоступно без ответа ФНС")
        if result.get("warning"):
            lines.append(f"Внимание:  {result['warning']}")
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
