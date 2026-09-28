"""Turn a parser result into a message a client can read.

Every value is printed with the confidence the parser actually reported, so a
shaky OCR read is never dressed up as a clean extraction.
"""

from __future__ import annotations

from typing import Any

MAX_MESSAGE = 4000  # Telegram rejects anything above 4096 characters


def _money(value: Any, currency: str = "") -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, (int, float)):
        text = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    else:
        text = str(value)
    return f"{text} {currency}".strip()


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _line(label: str, value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    return f"{label}: {value}"


def _items_block(items: list[dict[str, Any]], currency: str) -> list[str]:
    lines = []
    for index, item in enumerate(items[:40], 1):
        name = _first(item, "name", "НаимТов", "товар") or "без названия"
        lines.append(f"{index}. {name}")
        detail = []
        qty = _first(item, "quantity", "qty", "КолТов", "count")
        if qty is not None:
            detail.append(f"{qty} шт")
        price = _first(item, "price", "ЦенаТов", "цена")
        if price is not None:
            detail.append(f"× {_money(price, currency)}")
        total = _first(item, "sum", "total", "СтТовУчНал", "СтТовБезНДС", "сумма")
        if total is not None:
            detail.append(f"= {_money(total, currency)}")
        if detail:
            lines.append("    " + " · ".join(detail))
    if len(items) > 40:
        lines.append(f"…и ещё {len(items) - 40} позиций")
    return lines


def _trust_note(data: dict[str, Any]) -> str | None:
    if data.get("trustworthy") is True:
        return "✅ Итог сходится с позициями — можно оплачивать."
    if data.get("trustworthy") is False:
        reasons = []
        if data.get("items_reconciled") is False:
            reasons.append("сумма позиций не совпадает с итогом")
        if data.get("totals_agree") is False:
            reasons.append("в чеке напечатано несколько разных итогов")
        if not reasons:
            reasons.append("итог не подтверждён позициями")
        return "⚠️ " + "; ".join(reasons) + ". Лучше переснять чек."
    return None


def render_receipt(data: dict[str, Any]) -> str:
    """Render either a Russian ФНС receipt or a Belarusian one."""
    # The Russian path returns the FNS schema, the OCR path returns a nested
    # "parsed" dict, so unwrap the latter first.
    if "parsed" in data and isinstance(data.get("parsed"), dict):
        inner = dict(data["parsed"])
        inner["raw_text"] = data.get("raw_text")
        return render_receipt(inner)

    country = data.get("country", "RU")
    currency = data.get("currency") or ("BYN" if country == "BY" else "RUB")

    header = f"🧾 {data.get('document_type_label') or ('Кассовый чек РБ' if country == 'BY' else 'Кассовый чек РФ')}"

    parts: list[str] = [header]

    seller = data.get("seller") or {}
    seller_name = seller.get("name") if isinstance(seller, dict) else None
    if seller_name:
        parts.append(f"🏪 {seller_name}")

    if country == "BY":
        details = [
            _line("УНП", data.get("unp")),
            _line("РН СККО", data.get("rn_skko")),
        ]
    else:
        details = [
            _line("ФН", data.get("fiscal_number")),
            _line("ФД", data.get("fiscal_document_number")),
            _line("ФП", data.get("fiscal_sign")),
        ]
    details += [
        _line("Дата", " ".join(filter(None, [str(data.get("date") or ""), str(data.get("time") or ""), str(data.get("date_time") or "")])).strip() or None),
        _line("Номер документа", data.get("document_number")),
        _line("УИ", data.get("ui")),
    ]
    details = [d for d in details if d]
    if details:
        parts.append("\n".join(details))

    total = _first(data, "total_sum", "total", "s")
    if total is not None:
        parts.append(f"\n💰 <b>Итого: {_money(total, currency)}</b>")

    items = data.get("items") or []
    if items:
        parts.append(f"\n🧺 Позиций: {len(items)}")
        parts.append("\n".join(_items_block(items, currency)))

    if country == "RU" and data.get("is_validated_fns"):
        parts.append("\n🟢 Проверен в реестре ФНС.")
    elif data.get("validation_errors"):
        problems = "; ".join(str(e) for e in data["validation_errors"][:3])
        parts.append(f"\n🟡 ФНС не подтвердил: {problems}")

    if data.get("discount"):
        parts.append(f"Скидка: {_money(data['discount'], currency)}")

    trust = _trust_note(data)
    if trust:
        parts.append(f"\n{trust}")
    if data.get("complete") is False:
        parts.append("\nЧек обрезан или размыт — часть полей не прочитана.")

    text = "\n".join(parts)
    return text[:MAX_MESSAGE]


def render(outcome) -> str:
    """Render any Outcome produced by app.bot.service.process."""
    if outcome.ok:
        return render_receipt(outcome.data) if outcome.doc_type == "receipt_kkt" else str(outcome.data)

    if outcome.pending:
        return (
            f"📄 Принял: <b>{outcome.label}</b>.\n\n"
            f"{outcome.note}\n\n"
            "Формат уже определён правильно, но разбор пока не доведён до продакшена — "
            "не буду выдумывать цифры. Напишите, что именно нужно, и я пришлю результат вручную."
        )

    reasons = {
        "unrecognised": "Не понял, что это за документ.",
        "parse_error": "Не удалось разобрать файл.",
        "crash": "Парсер упал на этом файле.",
    }
    return (
        f"⚠️ {reasons.get(outcome.error, 'Не удалось разобрать файл.')}\n\n"
        f"<i>{outcome.note}</i>".strip()
    )
