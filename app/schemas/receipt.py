from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class PaymentMethod(str, Enum):
    CASH = "cash"
    CARD = "card"
    OTHER = "other"


class VATRate(str, Enum):
    VAT_20 = "20"
    VAT_10 = "10"
    VAT_20_120 = "20/120"
    VAT_10_110 = "10/110"
    VAT_0 = "0"
    NO_VAT = "no_vat"


class ReceiptItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str = Field(..., max_length=500)
    price: Decimal = Field(..., ge=0, decimal_places=2)
    quantity: Decimal = Field(..., ge=0, decimal_places=3)
    sum: Decimal = Field(..., ge=0, decimal_places=2)
    vat_rate: VATRate | None = None
    vat_sum: Decimal | None = Field(None, ge=0, decimal_places=2)
    payment_method: PaymentMethod | None = None
    payment_subject: str | None = None  # признак предмета расчета
    nomenclature_code: str | None = None
    measurement_unit: str | None = None


class SellerInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str | None = Field(None, max_length=500)
    inn: str | None = Field(None, pattern=r"^\d{10}(\d{2})?$")
    kpp: str | None = Field(None, pattern=r"^\d{9}$")
    address: str | None = None
    place: str | None = None  # место расчетов


class ReceiptKKT(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Основные реквизиты
    fiscal_number: str = Field(..., alias="fn")  # номер фискального накопителя
    fiscal_document_number: str = Field(..., alias="fd")  # номер фискального документа
    fiscal_sign: str = Field(..., alias="fp")  # фискальный признак
    date_time: datetime = Field(..., alias="t")  # дата и время
    total_sum: Decimal = Field(..., alias="s", ge=0, decimal_places=2)  # сумма в копейках

    # Продавец
    seller: SellerInfo | None = None

    # Позиции
    items: list[ReceiptItem] = []

    # Оплата
    cash_sum: Decimal | None = Field(None, ge=0, decimal_places=2)
    card_sum: Decimal | None = Field(None, ge=0, decimal_places=2)
    other_sum: Decimal | None = Field(None, ge=0, decimal_places=2)

    # Дополнительные
    raw_qr: str | None = None
    is_validated_fns: bool = False
    validation_errors: list[str] = []

    # Расчетные поля
    vat_20_sum: Decimal | None = Field(None, ge=0, decimal_places=2)
    vat_10_sum: Decimal | None = Field(None, ge=0, decimal_places=2)
    vat_0_sum: Decimal | None = Field(None, ge=0, decimal_places=2)
    no_vat_sum: Decimal | None = Field(None, ge=0, decimal_places=2)


class ReceiptValidationRequest(BaseModel):
    qr_string: str = Field(..., description="Строка из QR-кода: t=20240101T1200&s=10000&fn=1234567890&i=1&fp=1234567890")
    phone: str | None = Field(None, description="Телефон для авторизации в ФНС")


class ReceiptValidationResponse(BaseModel):
    success: bool
    receipt: ReceiptKKT | None = None
    errors: list[str] = []
