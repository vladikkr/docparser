"""Чек самозанятого: раскладки печати «Мой налог» и поля, которые нужны.

These are synthetic renderings of the layout, not captures of a real app
screen, so they are labelled as such. They exist to pin the arithmetic, which
is the part that has to be right: a НПД that is not the stated percentage of
the cost, or a total that is not cost plus tax, means the receipt is wrong and
the client should not accept it.
"""

from __future__ import annotations

from typing import Any

Case = dict[str, Any]

CASES: list[Case] = []


def case(name: str, text: str, **expected: Any) -> None:
    CASES.append({"name": name, "text": text, "expected": expected})


# The common case: 1200.00 at 6% is 72.00, total 1272.00.
case(
    "npd_6_percent",
    """
ЧЕК № 000012345
от 24.09.2026
ИП Иванов Иван Иванович
ИНН 790730816
Ремонт холодильника
Стоимость товаров (работ, услуг): 1 200,00
НПД 6%: 72,00
Итого к оплате: 1 272,00
""",
    cost=1200.00,
    npd_rate=6.0,
    npd_sum=72.00,
    total_sum=1272.00,
    date="24.09.2026",
    inn="790730816",
    purpose="Ремонт холодильника",
    reconciled=True,
    trustworthy=True,
)

# The 4% rate that applies to a sale to another business.
case(
    "npd_4_percent",
    """
ЧЕК
№ 42
от 01.10.2026
ИП Петрова Ольга Петровна
ИНН 790730999
Консультационные услуги
Стоимость товаров, работ, услуг: 2 500,00
НПД 4%: 100,00
Итого: 2 600,00
""",
    cost=2500.00,
    npd_rate=4.0,
    npd_sum=100.00,
    total_sum=2600.00,
    reconciled=True,
    trustworthy=True,
)

# A receipt where the tax does not follow from the rate. Must be refused.
case(
    "wrong_npd_amount",
    """
ЧЕК № 7
от 05.09.2026
ИП Сидоров Пётр
ИНН 790730111
Стоимость: 1 000,00
НПД 6%: 50,00
Итого к оплате: 1 050,00
""",
    cost=1000.00,
    npd_rate=6.0,
    npd_sum=50.00,
    total_sum=1050.00,
    reconciled=False,
    trustworthy=False,
)

# A receipt where the total does not equal cost plus tax. Must be refused.
case(
    "total_does_not_add_up",
    """
ЧЕК № 8
от 06.09.2026
ИП Козлов Иван
ИНН 790730222
Стоимость: 800,00
НПД 6%: 48,00
Итого к оплате: 900,00
""",
    cost=800.00,
    npd_rate=6.0,
    npd_sum=48.00,
    total_sum=900.00,
    reconciled=False,
    trustworthy=False,
)

# Only a percentage, no amount: not enough to decide, which is not a pass.
case(
    "rate_without_amount",
    """
ЧЕК № 9
от 07.09.2026
ИП Иванов Иван Иванович
ИНН 790730816
Стоимость: 300,00
НПД 6%
Итого к оплате: 318,00
""",
    cost=300.00,
    npd_rate=6.0,
    npd_sum=None,
    total_sum=318.00,
    reconciled=None,
    trustworthy=False,
)
