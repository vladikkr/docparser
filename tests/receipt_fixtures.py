"""Belarusian receipt layouts and the fields each one must yield.

Real Belarusian receipts come from several fiscal printers with different
wording and column layouts. Each case below pairs OCR-style text with the values
a correct parser has to recover, so a regression in any field is visible.
"""

from __future__ import annotations

from typing import Any

Case = dict[str, Any]

CASES: list[Case] = []


def case(name: str, text: str, **expected: Any) -> None:
    CASES.append({"name": name, "text": text, "expected": expected})


# A single untitled service line, as on the sample receipt.
case(
    "service_single_line",
    """
ф-т
ИП Рощина Татьяна
Александровна
Ателье у Татьяны
г, Бобруйск , пр-т.
Строителей д. 58
УНП 790730816
РН СККО 719014711
Платежный документ
№ док. 1539
Позиция 1
1,000х20,00BYN 20,00
ИТОГО К ОПЛАТЕ 20,00
Сумма наличными 20,00
Кассир 01
Дата 24.09.26 Время 15:12:23
уи 63288429a8fec2242adb4b37
""",
    unp="790730816",
    rn_skko="719014711",
    document_number="1539",
    date="2026-09-24",
    time="15:12:23",
    total=20.0,
    item_count=1,
    items_sum=20.0,
)

# Several named lines, the ordinary supermarket shape.
case(
    "supermarket_multi_item",
    """
ООО «Евроопт»
Ул. Ленина, 25
г. Минск
УНП 190790789
РН СККО 490211004
Платежный документ
№ док. 8821
Позиция 1
Молоко 3,2% 0,93л 1,000х2,89 2,89
Позиция 2
Хлеб Бородинский 1,000х3,15 3,15
Позиция 3
Масло сливочное 82,5% 1,000х5,47 5,47
Позиция 4
Сахар-песок 1кг 2,000х3,99 7,98
ИТОГО К ОПЛАТЕ 19,49
Сумма наличными 20,00
Кассир 112
Дата 18.10.26 Время 19:04:51
уи a1b2c3d4e5f60718293a4b5c6d7e8f90
""",
    unp="190790789",
    rn_skko="490211004",
    document_number="8821",
    date="2026-10-18",
    time="19:04:51",
    total=19.49,
    item_count=4,
    items_sum=19.49,
)

# Payment by card instead of cash: there is no cash line to corroborate.
case(
    "card_payment",
    """
ИП Смирнова Ольга Петровна
г. Гомель, ул. Советская, 7
УНП 441190233
РН СККО 550118877
Платежный документ
№ док. 1204
Позиция 1
Стрижка волос 1,000х45,00 45,00
ИТОГО К ОПЛАТЕ 45,00
Оплата картой 45,00
Кассир 03
Дата 02.11.26 Время 11:30:00
уи 0f1e2d3c4b5a69788796a5b4c3d2e1f0
""",
    unp="441190233",
    rn_skko="550118877",
    document_number="1204",
    date="2026-11-02",
    time="11:30:00",
    total=45.0,
    item_count=1,
    items_sum=45.0,
)

# A large total with a thousands separator.
case(
    "large_total_thousands",
    """
ИП Кузнецов Павел
г. Брест, пр-т. Победы, 30
УНП 291004455
РН СККО 610455100
Платежный документ
№ док. 5512
Позиция 1
Ноутбук 1,000х1 250,00 1 250,00
ИТОГО К ОПЛАТЕ 1 250,00
Сумма наличными 1 250,00
Кассир 07
Дата 15.12.26 Время 17:45:10
уи 112233445566778899aabbccddeeff00
""",
    unp="291004455",
    rn_skko="610455100",
    document_number="5512",
    date="2026-12-15",
    time="17:45:10",
    total=1250.0,
    item_count=1,
    items_sum=1250.0,
)

# Discount and bonus card lines sit between the items and the total.
case(
    "discount_and_bonus_card",
    """
ИП Петрова Наталья
г. Гродно, ул. Городская, 14
УНП 590223344
РН СККО 720334455
Платежный документ
№ док. 3390
Позиция 1
Куртка джинсовая 1,000х180,00 180,00
Позиция 2
Ремень кожаный 1,000х35,00 35,00
Скидка 0,00
Начислено бонусов 21
ИТОГО К ОПЛАТЕ 215,00
Оплата бонусной картой 21,00
Сумма наличными 194,00
Кассир 14
Дата 28.12.26 Время 20:11:05
уи 99887766554433221100ffeeddccbbaa
""",
    unp="590223344",
    rn_skko="720334455",
    document_number="3390",
    date="2026-12-28",
    time="20:11:05",
    total=215.0,
    item_count=2,
    items_sum=215.0,
)

# A fully discounted purchase: the total is legitimately zero.
case(
    "zero_total_discounted",
    """
ИП Сидоров Иван
г. Витебск, пр-т. Зари, 3
УНП 310445566
РН СККО 810556677
Платежный документ
№ док. 77
Позиция 1
Подарочный сертификат 1,000х100,00 100,00
Скидка 100,00
ИТОГО К ОПЛАТЕ 0,00
Сумма наличными 0,00
Кассир 02
Дата 01.01.27 Время 12:00:00
уи 0a0b0c0d0e0f0a0b0c0d0e0f0a0b0c0d
""",
    unp="310445566",
    rn_skko="810556677",
    document_number="77",
    date="2027-01-01",
    time="12:00:00",
    total=0.0,
    item_count=1,
)

# A long product name wraps onto a second line, as thermal printers do.
case(
    "wrapped_item_name",
    """
ООО «Белпродукт»
г. Бобруйск, ул. Мясникова, 20
УНП 100112233
РН СККО 330223344
Платежный документ
№ док. 4410
Позиция 1
Йогурт черничный
0,5л 1,000х4,25 4,25
ИТОГО К ОПЛАТЕ 4,25
Сумма наличными 4,25
Кассир 05
Дата 07.09.26 Время 08:20:33
уи 5566778899aabbccddeeff0011223344
""",
    unp="100112233",
    rn_skko="330223344",
    document_number="4410",
    date="2026-09-07",
    time="08:20:33",
    total=4.25,
)

# Extra marketing lines at the bottom, as many printers emit.
case(
    "marketing_footer",
    """
ИП Алейникова Светлана
г. Могилев, ул. Ленинская, 5
УНП 701223344
РН СККО 440334455
Платежный документ
№ док. 664
Позиция 1
Кофе молотый 250г 1,000х12,90 12,90
ИТОГО К ОПЛАТЕ 12,90
Сумма наличными 20,00
Сдача 7,10
Кассир 09
Дата 21.08.26 Время 09:15:00
уи ccdd00112233445566778899aabbccdd
ОГРН 000000000000000
СПАСИБО ЗА ПОКУПКУ
К вашим услугам
""",
    unp="701223344",
    rn_skko="440334455",
    document_number="664",
    date="2026-08-21",
    time="09:15:00",
    total=12.9,
    item_count=1,
    items_sum=12.9,
)

# Latin product names, which the OCR mixes with Cyrillic.
case(
    "latin_item_names",
    """
ИП IMPORT-TRADE
г. Минск, ул. Ванеева, 12
УНП 191556677
РН СККО 990887766
Платежный документ
№ док. 9080
Позиция 1
NIMBUS THERMO 1,000х89,90 89,90
Позиция 2
STARBUCKS Caffe Latte 1,000х14,50 14,50
ИТОГО К ОПЛАТЕ 104,40
Сумма наличными 110,00
Кассир 11
Дата 12.06.26 Время 13:37:22
уи eeff0011223344556677889900aabbcc
""",
    unp="191556677",
    rn_skko="990887766",
    document_number="9080",
    date="2026-06-12",
    time="13:37:22",
    total=104.4,
    item_count=2,
    items_sum=104.4,
)
