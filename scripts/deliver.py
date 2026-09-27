"""Deliver one parsed receipt, ready to send.

The operator's only job between a client sending a photo and the client getting
an answer should be a single command. This runs the parse, writes the JSON
file, and prints a message that can be pasted into Telegram as-is.

    python scripts\deliver.py "C:\путь\чек.jpg"
    python scripts\deliver.py "C:\путь\чек.jpg" --price 3
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import pathlib
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# A Russian Windows console defaults to cp1251 and cannot encode the
# multiplication sign or the guillemets used in the message. Reconfigure rather
# than crash on the first client.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from app.services.ocr import available_languages, ocr_service  # noqa: E402
from app.services.parsers.receipt_by import parse_belarusian_receipt  # noqa: E402
from app.services.qr import decode_receipt_qr_bytes  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "out"


def _format_date(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d.%m.%y")
    except ValueError:
        return iso


def _build_message(result: dict, took: float, price: float | None) -> str:
    data = result.get("data") or {}
    seller = data.get("seller") or {}

    if result.get("method") == "fns":
        title = "Российский чек ККТ"
    elif result.get("method") == "belarus_ocr":
        title = "Чек ККТ Беларуси"
    else:
        title = "Чек"

    lines = [f"Готово. {title}, {took:.0f} сек.", ""]

    if seller.get("name"):
        lines.append(f"Продавец: {seller['name']}")
    if data.get("unp"):
        lines.append(f"УНП: {data['unp']}")
    if data.get("rn_skko"):
        lines.append(f"РН СККО: {data['rn_skko']}")
    if data.get("document_number"):
        lines.append(f"Документ: № {data['document_number']}")
    if data.get("date"):
        when = _format_date(data.get("date"))
        if data.get("time"):
            when += f", {data['time']}"
        lines.append(f"Дата: {when}")

    total = data.get("total_sum")
    currency = data.get("currency") or ""
    if total is not None:
        lines.append(f"Итого: {total:.2f} {currency}".rstrip())

    items = data.get("items") or []
    if items:
        lines.append("")
        lines.append("Позиции:")
        for row in items:
            name = row.get("name") or "(название не прочитано)"
            qty = row.get("quantity")
            price_val = row.get("price")
            amount = row.get("sum")
            if qty is not None and price_val is not None:
                lines.append(f"  - {name}: {qty:g} x {price_val:.2f} = {amount:.2f}")
            else:
                lines.append(f"  - {name}: {amount:.2f}")

    if data.get("ui"):
        lines.append("")
        lines.append(f"УИ: {data['ui']}")

    if not data.get("trustworthy"):
        lines.append("")
        lines.append("ВНИМАНИЕ: итог не подтверждён второй строкой чека,")
        lines.append("цифры позиций могут быть неточными. Сверьте, пожалуйста.")

    if price:
        lines.append("")
        lines.append(f"Оплата переводом: {price:.0f} BYN.")

    return "\n".join(lines)


def _build_failure_message(result: dict, took: float) -> str:
    reason = result.get("error") or "данные не восстановились"
    return (
        f"К сожалению, этот чек разобрать не получилось ({took:.0f} сек).\n\n"
        f"Причина: {reason}\n\n"
        "Скиньте, пожалуйста, фото ещё раз — ближе, без теней и блика, "
        "чтобы хорошо читался QR-код."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Разобрать чек и подготовить ответ клиенту")
    parser.add_argument("file", type=pathlib.Path, help="фото чека")
    parser.add_argument("--price", type=float, default=None, help="сумма к оплате, BYN")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"Файл не найден: {args.file}", file=sys.stderr)
        return 2

    if "rus" not in available_languages():
        print("Нет языкового пакета Tesseract для русского. См. docs/manual_mode.md", file=sys.stderr)
        return 3

    started = time.perf_counter()
    data = args.file.read_bytes()

    qr = decode_receipt_qr_bytes(data)
    try:
        from PIL import Image

        text = ocr_service.extract_full_text(Image.open(io.BytesIO(data)))
    except Exception as exc:  # noqa: BLE001
        result = {"method": "failed", "data": {}, "error": f"{type(exc).__name__}: {exc}"}
    else:
        if not text:
            result = {
                "method": "failed",
                "data": {},
                "error": "текст на фото не распознался, попробуйте снять чётче",
            }
        elif qr and "fn=" not in qr:
            result = {
                "method": "belarus_ocr",
                "data": parse_belarusian_receipt(text, ui_hint=qr),
            }
        else:
            result = {
                "method": "qr",
                "data": parse_belarusian_receipt(text, ui_hint=qr),
            }

    took = time.perf_counter() - started

    OUT.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    json_path = OUT / f"{args.file.stem}-{stamp}.json"
    payload = {
        "source": args.file.name,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "method": result.get("method"),
        "trustworthy": (result.get("data") or {}).get("trustworthy"),
        "elapsed_sec": round(took, 1),
        "data": result.get("data"),
    }
    if result.get("error"):
        payload["error"] = result["error"]
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    message = (
        _build_message(result, took, args.price)
        if result.get("data")
        else _build_failure_message(result, took)
    )

    print("=" * 64)
    print(message)
    print("=" * 64)
    print(f"\nJSON сохранён: {json_path}")

    return 0 if result.get("data") else 1


if __name__ == "__main__":
    raise SystemExit(main())
