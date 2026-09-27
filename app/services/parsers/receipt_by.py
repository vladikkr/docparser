"""Parser for Belarusian fiscal receipts (чек ККТ, УНП/РН СККО).

A Belarusian receipt cannot be resolved through the Russian FNS API: the QR
carries only a unique document id (УИ) and the register itself is maintained by
the Ministry of Finance of Belarus. Everything a client needs is nevertheless
printed on the paper, so this parser works on the OCR text.

Layout varies between fiscal printers, so each field is matched by several
labels and the parser degrades field by field instead of failing outright.
"""

from __future__ import annotations

import re
from typing import Any

_CYRILLIC = "а-яА-ЯёЁіІўЎ"

# Latin glyphs that look identical to Cyrillic ones. Tesseract emits whichever
# model won, so `РН СККО` can arrive as `PH CKKO`. The map is 1:1, which keeps
# character offsets aligned with the original string.
_LOOKALIKE = str.maketrans(
    {
        "P": "Р", "p": "р", "H": "Н", "h": "н", "C": "С", "c": "с",
        "K": "К", "k": "к", "O": "О", "o": "о", "M": "М", "m": "м",
        "A": "А", "a": "а", "E": "Е", "e": "е", "T": "Т", "t": "т",
        "B": "В", "b": "в", "X": "Х", "x": "х", "Y": "У", "y": "у",
    }
)


def _canon(text: str) -> str:
    """Fold Latin lookalikes onto Cyrillic so labels match either reading."""
    return text.translate(_LOOKALIKE)

# OCR confuses lookalike glyphs; receipts are printed in a monospaced face.
_TRANSLIT = str.maketrans(
    {
        "О": "0",
        "о": "0",
        "Ч": "4",
        "З": "3",
        "б": "6",
        "В": "B",
    }
)

_MONEY_RE = re.compile(r"(\d[\d\s.,]*\d|\d)")
_SUM_RE = _MONEY_RE


def _looks_like_amount(raw: str) -> bool:
    """Receipt amounts always carry two decimals, e.g. `20,00`.

    A bare integer on a total line is almost always an OCR artefact, and so is a
    fragment such as `,00` left behind when a band of the photo is cut short.
    Both are rejected: a real amount has digits on each side of the separator.
    """
    return bool(re.search(r"\d\s*[.,]\s*\d{1,2}\s*$", raw.strip()))


def _digits(value: str) -> str:
    """Reduce a possibly mistyped token to digits."""
    return re.sub(r"\D", "", value.translate(_TRANSLIT))


def _money(value: str) -> float | None:
    """Parse a receipt amount. Receipts use both `1 234,56` and `1,234.56`."""
    cleaned = value.translate(_TRANSLIT).replace(" ", "").replace(" ", "")
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        # The right-most separator is the decimal one.
        dec = "," if cleaned.rindex(",") > cleaned.rindex(".") else "."
        thousands = "." if dec == "," else ","
        cleaned = cleaned.replace(thousands, "").replace(dec, ".")
    elif "," in cleaned:
        head, _, tail = cleaned.rpartition(",")
        # `1,50` is a decimal, `1,500` is a thousands separator.
        cleaned = f"{head}.{tail}" if len(tail) == 2 else cleaned.replace(",", "")
    digits = re.sub(r"[^0-9.]", "", cleaned)
    if not digits or digits.count(".") > 1:
        return None
    try:
        return round(float(digits), 2)
    except ValueError:
        return None


def _label_value(lines: list[str], labels: tuple[str, ...]) -> str | None:
    """Find `label: value` on one line, tolerating OCR spacing noise."""
    for line in lines:
        canon = _canon(line)
        for label in labels:
            needle = _canon(label).lower()
            idx = canon.lower().find(needle)
            if idx == -1:
                continue
            # Offsets are preserved by the 1:1 translation.
            tail = line[idx + len(label) :]
            tail = tail.lstrip(" .:;№-—")
            match = _SUM_RE.search(tail)
            if match:
                return match.group(1).strip()
            if tail.strip():
                return tail.strip()
    return None


def _has_label(line: str, labels: tuple[str, ...]) -> bool:
    canon = _canon(line).lower()
    return any(_canon(label).lower() in canon for label in labels)


def _clean_lines(text: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            out.append(line)
    return out


_STOP_LABELS = (
    "УНП",
    "РН СККО",
    "Платежный документ",
    "Позиция",
    "ИТОГО",
    "Сумма наличными",
    "Кассир",
    "Дата",
)


# Lines that open a postal address; the name block ends at the first of these.
_ADDRESS_START = re.compile(
    r"^\s*(г|город|ул|улица|д|дом|пр-т|пр-т|просп|переулок|мкр)\b",
    re.IGNORECASE,
)

# Short markers such as `ф-т` (fax) are not part of the seller name.
_NOISE_LINE = re.compile(rf"^[{_CYRILLIC}]{{1,3}}\s*[-–]\s*[{_CYRILLIC}]{{1,3}}$")

_NAME_FIXES = (
    # `ИП` misread as `И!` or `И1` in a monospaced receipt font.
    (re.compile(r"\bИ[!1](?=\s|$)"), "ИП"),
    # A capitalised word starting with a digit is almost always the letter `Т`.
    (re.compile(rf"(?<![{_CYRILLIC}\w])([1])(?=[{_CYRILLIC}]{{3,}})"), "Т"),
)


def _seller(lines: list[str]) -> dict[str, str | None]:
    """The seller block is the head of the receipt, above the address."""
    name_lines: list[str] = []
    for line in lines[:8]:
        if _has_label(line, _STOP_LABELS) or _ADDRESS_START.match(line):
            break
        if not re.search(rf"[{_CYRILLIC}]", line):
            continue
        if re.search(r"\d{4,}", line) or _NOISE_LINE.match(line):
            continue
        name_lines.append(line)
        if len(name_lines) >= 3:
            break

    name = " ".join(name_lines).strip() or None
    if name:
        for pattern, replacement in _NAME_FIXES:
            name = pattern.sub(replacement, name)
    return {
        "name": name,
        "unp": _digits(_label_value(lines, ("УНП",)) or "") or None,
        "rn_skko": _digits(_label_value(lines, ("РН СККО",)) or "") or None,
    }



def _total_candidates(lines: list[str]) -> list[tuple[str, float, bool]]:
    """Every amount found on a total-like line, with a decimals flag."""
    groups = (
        ("ИТОГО К ОПЛАТЕ", "ИТОГО", "ВСЕГО К ОПЛАТЕ"),
        ("Сумма наличными",),
        ("Наличными",),
    )
    found: list[tuple[str, float, bool]] = []
    for labels in groups:
        for line in lines:
            if not _has_label(line, labels):
                continue
            canon = _canon(line)
            for label in labels:
                needle = _canon(label).lower()
                idx = canon.lower().find(needle)
                if idx == -1:
                    continue
                match = _MONEY_RE.search(line[idx + len(label) :])
                if not match:
                    continue
                raw = match.group(1)
                amount = _money(raw)
                if amount is None:
                    continue
                # One amount per line: `ИТОГО К ОПЛАТЕ` also contains `ИТОГО`,
                # and counting it twice would fake corroboration.
                found.append((labels[0], amount, _looks_like_amount(raw)))
                break
    return found


def _find_total(lines: list[str]) -> tuple[float | None, bool | None, int]:
    """Return the payment total, whether the printed totals agree, and how many
    independent total lines were readable.

    Two independent lines usually carry the same figure (`ИТОГО К ОПЛАТЕ` and
    `Сумма наличными`). When they disagree the OCR mistook something, so the
    caller is told rather than handed a confident wrong number. The count matters
    too: a single readable total is not corroborated by anything.

    Only amounts written with decimals are accepted. Thermal printers always
    print two, so a bare integer on a total line is an OCR artefact — taking it
    at face value is how `20,00` once turned into `90`.
    """
    candidates = [c for c in _total_candidates(lines) if c[2]]
    if not candidates:
        return None, None, 0

    payment = next((c[1] for c in candidates if c[0] == "ИТОГО К ОПЛАТЕ"), None)
    if payment is None:
        payment = candidates[0][1]

    distinct = {c[1] for c in candidates}
    agree = True if len(distinct) == 1 else False
    return payment, agree, len(candidates)




def _find_datetime(lines: list[str]) -> dict[str, str | None]:
    date = re.search(r"\b(\d{2})[.\-/](\d{2})[.\-/](\d{2,4})\b", " ".join(lines))
    time = re.search(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b", " ".join(lines))
    iso_date = None
    if date:
        day, month, year = date.groups()
        century = "20" if len(year) == 2 else ""
        iso_date = f"{century}{year}-{month}-{day}"
    return {
        "date": iso_date,
        "time": time.group(1) if time else None,
    }


def _find_ui(lines: list[str], hint: str | None = None) -> str | None:
    """Prefer the QR-decoded id, which OCR tends to corrupt (b -> p)."""
    if hint:
        return hint

    for line in lines:
        # `УИ` arrives as `YU`; match any token of hex-ish characters.
        for token in re.findall(r"[0-9a-zA-Z]{16,}", line):
            if not re.match(r"^[0-9a-fA-F]{16,}$", token):
                continue
            lowered = token.lower()
            # Real ids are lowercase hex; OCR often keeps case.
            if sum(c.isdigit() or c in "abcdefABCDEF" for c in token) == len(token):
                return lowered[:24]
    return None


def _find_document_number(lines: list[str]) -> str | None:
    return _digits(_label_value(lines, ("№ док.", "N док.", "№док.")) or "") or None


def _quantity_candidates(token: str) -> list[float]:
    """A separator is ambiguous: `1,000` is one thousand, `1,50` is one point five.

    Both readings are offered so the caller can pick the one that matches the
    line total.
    """
    readings: list[float] = []
    primary = _money(token)
    if primary is not None:
        readings.append(primary)

    if "," in token:
        head, _, tail = token.partition(",")
        if head.strip() and tail.strip().isdigit():
            try:
                as_decimal = float(f"{_digits(head)}.{tail.strip()}")
                if as_decimal not in readings:
                    readings.append(as_decimal)
            except ValueError:
                pass
    if not readings:
        digits = _digits(token)
        if digits:
            readings.append(float(digits))
    return readings


def _resolve_row(numbers: list[str]) -> dict[str, Any] | None:
    """Build one item row, using `quantity * price = sum` to settle ambiguity."""
    amounts = [(token, _money(token)) for token in numbers]
    amounts = [(token, value) for token, value in amounts if value is not None]
    if not amounts:
        return None

    line_total = amounts[-1][1]
    row: dict[str, Any] = {"sum": line_total, "price": line_total}

    if len(amounts) < 2:
        return row

    qty_token = amounts[0][0]
    price = amounts[1][1]
    for candidate in _quantity_candidates(qty_token):
        if candidate and abs(candidate * price - line_total) < 0.01:
            row["quantity"] = candidate
            row["price"] = price
            return row

    # No reading multiplies out: report the plain values rather than guessing.
    row["quantity"] = _money(qty_token)
    row["price"] = price
    return row


def _find_items(lines: list[str], total: float | None) -> list[dict[str, Any]]:
    """Rows between the `Позиция` header and the total line."""
    items: list[dict[str, Any]] = []
    start = None
    for i, line in enumerate(lines):
        if _has_label(line, ("Позиция", "Позици")):
            start = i
            break
    if start is None:
        return items

    for line in lines[start + 1 :]:
        if _has_label(line, ("ИТОГО", "ВСЕГО", "Сумма наличными", "Кассир", "Дата")):
            break
        if _has_label(line, ("Позиция", "Позици")):
            continue

        numbers = [n for n in re.findall(r"\d[\d\s.,]*", line) if _digits(n)]
        if not numbers:
            continue

        name = re.split(r"\d[\d\s.,]*", line, maxsplit=1)[0].strip(" .,;")
        row = _resolve_row(numbers)
        if row is None:
            continue
        row["name"] = name or None
        items.append(row)

    return items



def parse_belarusian_receipt(text: str, ui_hint: str | None = None) -> dict[str, Any]:
    """Turn OCR text of a Belarusian receipt into structured fields.

    `ui_hint` is the id decoded from the QR. OCR corrupts hex characters, so
    the QR value wins whenever it is available.
    """
    lines = _clean_lines(text)
    if not lines:
        return {"country": "BY", "complete": False, "error": "no text recognised"}

    total, totals_agree, total_lines = _find_total(lines)
    items = _find_items(lines, total)
    seller = _seller(lines)
    when = _find_datetime(lines)

    parsed_sum = sum(r["sum"] for r in items if r.get("sum"))
    if items:
        # With no line items there is nothing to check the total against, so
        # reconciliation is unknown rather than passed.
        reconciled: bool | None = abs(parsed_sum - total) < 0.01 if total is not None else None
    else:
        reconciled = None

    # A total is believed when either the line items add up to it, or two
    # separately printed totals agree. One uncorroborated line is not enough:
    # that is exactly the shape of a silent misread.
    verified = reconciled is True
    corroborated = totals_agree is True and total_lines >= 2
    trustworthy = bool(total is not None and (verified or corroborated))


    return {
        "country": "BY",
        "document_type": "receipt_kkt",
        "seller": seller,
        "unp": seller["unp"],
        "rn_skko": seller["rn_skko"],
        "document_number": _find_document_number(lines),
        "date": when["date"],
        "time": when["time"],
        "total_sum": total,
        "currency": "BYN",
        "items": items,
        "ui": _find_ui(lines, ui_hint),
        "complete": bool(total is not None and seller["name"] and seller["unp"]),
        "trustworthy": trustworthy,
        "totals_agree": totals_agree,
        "total_lines": total_lines,
        "reconciled": reconciled,
        "items_sum": round(parsed_sum, 2) if items else None,
        "raw_text": text,
    }

