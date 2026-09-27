import re


def validate_inn(inn: str) -> bool:
    """Validate Russian INN (10 or 12 digits)"""
    inn = inn.strip()
    if not re.match(r"^\d{10}$|^\d{12}$", inn):
        return False

    def check_inn(inn_str: str, coeffs: list[int]) -> bool:
        total = sum(int(d) * c for d, c in zip(inn_str, coeffs))
        return total % 11 % 10 == int(inn_str[-1])

    if len(inn) == 10:
        # Legal entity
        coeffs = [2, 4, 10, 3, 5, 9, 4, 6, 8]
        return check_inn(inn, coeffs)
    else:
        # Individual
        coeffs1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        coeffs2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        return check_inn(inn, coeffs1) and check_inn(inn, coeffs2)


def validate_kpp(kpp: str) -> bool:
    """Validate Russian KPP (9 digits)"""
    kpp = kpp.strip()
    return bool(re.match(r"^\d{9}$", kpp))


def validate_ogrn(ogrn: str) -> bool:
    """Validate Russian OGRN (13 or 15 digits)"""
    ogrn = ogrn.strip()
    if not re.match(r"^\d{13}$|^\d{15}$", ogrn):
        return False

    check_digit = int(ogrn[-1])
    base = int(ogrn[:-1])
    return base % 11 % 10 == check_digit


def validate_bik(bik: str) -> bool:
    """Validate Russian BIK (9 digits)"""
    bik = bik.strip()
    return bool(re.match(r"^\d{9}$", bik))


def validate_phone(phone: str) -> bool:
    """Validate Russian phone number"""
    phone = re.sub(r"[^\d+]", "", phone)
    return bool(re.match(r"^(\+7|7|8)\d{10}$", phone))


def validate_email(email: str) -> bool:
    """Validate email"""
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def normalize_inn(inn: str) -> str:
    """Normalize INN to 10/12 digits"""
    return re.sub(r"\D", "", inn)


def normalize_kpp(kpp: str) -> str:
    """Normalize KPP to 9 digits"""
    return re.sub(r"\D", "", kpp)


def normalize_phone(phone: str) -> str:
    """Normalize phone to +7XXXXXXXXXX format"""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    elif digits.startswith("7") and len(digits) == 11:
        pass
    elif len(digits) == 10:
        digits = "7" + digits
    return "+" + digits if digits.startswith("7") else phone
