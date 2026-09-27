"""Does the parser survive a printer that words the receipt differently?

Only one real receipt was available, so the fixtures are extrapolations. The
labels below are the alternatives a Belarusian fiscal printer might emit. Every
one of them must still yield the same fields.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.services.parsers.receipt_by import parse_belarusian_receipt  # noqa: E402

HEAD = """ИП Тест Продавец
г. Минск, ул. Тестовая, 1
УНП 190790789
РН СККО 490211004
№ док. 8821
Дата 18.10.26 Время 19:04:51
уи a1b2c3d4e5f60718293a4b5c6d7e8f90
"""

ITEMS = "Молоко 3,2% 1,000х2,89 2,89\n"

# (label, expected)
TOTAL_VARIANTS = [
    "ИТОГО К ОПЛАТЕ 19,49",
    "Итого к оплате 19,49",
    "ИТОГО: 19,49",
    "ВСЕГО К ОПЛАТЕ 19,49",
    "ВСЕГО: 19,49",
    "ИТОГ К ОПЛАТЕ 19,49",
    "К ОПЛАТЕ 19,49",
    "ИТОГО 19,49",
    "Итог 19,49",
]

SECOND_LINE_VARIANTS = [
    "Сумма наличными 19,49",
    "НАЛИЧНЫМИ 19,49",
    "Наличными 19,49",
    "Оплата картой 19,49",
    "ОПЛАТА КАРТОЙ 19,49",
    "Картой 19,49",
    "Банковской картой 19,49",
    "Оплата наличными 19,49",
]

ITEM_HEADER_VARIANTS = [
    "Позиция 1",
    "ПОЗИЦИЯ 1",
    "Позиция №1",
    "1 позиция",
    "Товар 1",
    "Наименование 1",
    "Позиция",
]

DOC_NUMBER_VARIANTS = [
    "№ док. 8821",
    "N док. 8821",
    "№док 8821",
    "Документ 8821",
    "Док. 8821",
]

UNP_VARIANTS = [
    "УНП 190790789",
    "УНП/ИНН 190790789",
    "УНП: 190790789",
]

failures = 0


def check(name: str, text: str, field: str, expected) -> None:
    global failures
    result = parse_belarusian_receipt(text)
    got = result.get(field)
    if got != expected:
        failures += 1
        print(f"FAIL  {name:<34} {field}: ждём {expected!r}, получили {got!r}")
    else:
        print(f"OK    {name:<34} {field} = {got!r}")


print("=== варианты строки итога ===")
for label in TOTAL_VARIANTS:
    body = HEAD + "Позиция 1\n" + ITEMS + label + "\nСумма наличными 19,49\n"
    check(label, body, "total_sum", 19.49)

print()
print("=== варианты второй строки (подтверждение итога) ===")
for label in SECOND_LINE_VARIANTS:
    body = HEAD + "Позиция 1\n" + ITEMS + "ИТОГО К ОПЛАТЕ 19,49\n" + label + "\n"
    check(label, body, "total_trustworthy", True)

print()
print("=== варианты заголовка позиций ===")
for label in ITEM_HEADER_VARIANTS:
    body = HEAD + label + "\n" + ITEMS + "ИТОГО К ОПЛАТЕ 2,89\nСумма наличными 2,89\n"
    check(label, body, "item_count" if False else "items_sum", 2.89)

print()
print("=== варианты номера документа ===")
for label in DOC_NUMBER_VARIANTS:
    head = HEAD.replace("№ док. 8821", label)
    body = head + "Позиция 1\n" + ITEMS + "ИТОГО К ОПЛАТЕ 2,89\nСумма наличными 2,89\n"
    check(label, body, "document_number", "8821")

print()
print("=== варианты УНП ===")
for label in UNP_VARIANTS:
    head = HEAD.replace("УНП 190790789", label)
    body = head + "Позиция 1\n" + ITEMS + "ИТОГО К ОПЛАТЕ 2,89\nСумма наличными 2,89\n"
    check(label, body, "unp", "190790789")

print()
print("=== чек без заголовка позиций ===")
body = HEAD + ITEMS + "ИТОГО К ОПЛАТЕ 2,89\nСумма наличными 2,89\n"
check("без заголовка", body, "items_sum", 2.89)

print()
print(f"провалов: {failures}")
sys.exit(1 if failures else 0)
