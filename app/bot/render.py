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


def _item_name(item: dict[str, Any]) -> Any:
    return _first(item, "name", "НаимТов", "товар", "НаимРабот", "НаимГруз")


def render_fns_document(data: dict[str, Any], label: str = "") -> str:
    """Render a УПД, счёт-фактуру, ТОРГ-12 or an act."""
    header = f"📄 {label or data.get('document_type') or 'Документ'}"
    parts: list[str] = [header]

    details = [
        _line("Номер", data.get("document_number")),
        _line("Дата", data.get("document_date")),
        _line("КНД", data.get("knd")),
        _line("Функция", data.get("function")),
        _line("Формат", data.get("format_version")),
        _line("Валюта", (data.get("currency") or {}).get("name") or (data.get("currency") or {}).get("code")),
    ]
    details = [d for d in details if d]
    if details:
        parts.append("\n".join(details))

    for role, title in (("seller", "Продавец"), ("buyer", "Покупатель")):
        party = data.get(role) or {}
        name = party.get("name")
        if name:
            inn = f" (ИНН {party['inn']})" if party.get("inn") else ""
            parts.append(f"{title}: {name}{inn}")

    items = data.get("items") or []
    if items:
        parts.append(f"\n🧺 Позиций: {len(items)}")
        for index, item in enumerate(items[:40], 1):
            parts.append(f"{index}. {_item_name(item) or 'без названия'}")
            row = []
            for key, label_text in (
                ("quantity", None),
                ("price", None),
                ("total_with_vat", "Итого"),
            ):
                value = item.get(key)
                if value is None:
                    continue
                row.append(f"{label_text}: {value}" if label_text else str(value))
            if item.get("vat_rate"):
                row.append(f"НДС {item['vat_rate']}")
            if row:
                parts.append("    " + " · ".join(row))

    totals = data.get("totals") or {}
    for key, title in (
        ("amount_without_vat", "Без НДС"),
        ("vat_sum", "НДС"),
        ("total_with_vat", "Итого"),
    ):
        value = totals.get(key)
        if value is not None:
            parts.append(f"{title}: {_money(value)}")

    basis = data.get("basis") or {}
    if basis.get("name") or basis.get("number"):
        parts.append(
            f"\n📎 Основание: {basis.get('name') or '—'} "
            f"№ {basis.get('number') or '—'} от {basis.get('date') or '—'}"
        )

    warnings = data.get("warnings") or []
    if warnings:
        parts.append("\n⚠️ " + "\n⚠️ ".join(str(w) for w in warnings))

    return "\n".join(parts)[:MAX_MESSAGE]


def render_selfemployed(data: dict[str, Any]) -> str:
    """Render a self-employed receipt, leading with the tax check.

    The reason to look at this document at all is whether the НПД is right, so
    the verdict comes before the figures.
    """
    parts = ["🧾 Чек самозанятого (НПД)"]

    if data.get("person"):
        parts.append(f"👤 {data['person']}")

    details = [
        _line("ИНН", data.get("inn")),
        _line("Дата", data.get("date")),
        _line("№ чека", data.get("document_number")),
        _line("Услуга / товар", data.get("purpose")),
    ]
    details = [d for d in details if d]
    if details:
        parts.append("\n".join(details))

    cost = data.get("cost")
    rate = data.get("npd_rate")
    npd = data.get("npd_sum")
    money = [
        f"Стоимость: {_money(cost, 'BYN')}" if cost is not None else None,
        (
            f"НПД {rate:g}%: {_money(npd, 'BYN')}"
            if rate is not None and npd is not None
            else (f"НПД {rate:g}%" if rate is not None else None)
        ),
    ]
    money = [m for m in money if m]
    if money:
        parts.append("\n".join(money))

    if data.get("total_sum") is not None:
        parts.append(f"\n💰 <b>Итого: {_money(data['total_sum'], 'BYN')}</b>")

    if data.get("reconciled") is True:
        parts.append("\n✅ Налог сходится: НПД = ставка от стоимости, итог = стоимость + налог.")
    elif data.get("reconciled") is False:
        parts.append(
            "\n🛑 <b>Такой чек принимать нельзя.</b>\n"
            "Налог не соответствует сумме — попросите клиента показать заново."
        )

    warnings = data.get("warnings") or []
    if warnings:
        parts.append("\n" + "\n".join(f"⚠️ {w}" for w in warnings))

    return "\n".join(parts)[:MAX_MESSAGE]


def render(outcome) -> str:
    """Render any Outcome produced by app.bot.service.process."""
    if outcome.ok:
        if outcome.doc_type == "receipt_kkt":
            return render_receipt(outcome.data)
        if outcome.doc_type == "selfemployed":
            return render_selfemployed(outcome.data)
        return render_fns_document(outcome.data.get("parsed", outcome.data), outcome.label)

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
