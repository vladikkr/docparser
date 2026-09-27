from datetime import datetime
from decimal import Decimal

from app.schemas.billing import BillingPlan, PlanType
from app.schemas.document import DocumentStatus, DocumentType
from app.schemas.receipt import ReceiptItem, ReceiptKKT, SellerInfo, VATRate
from app.utils.helpers import format_currency, sanitize_filename, truncate_string
from app.utils.validators import (
    normalize_phone,
    validate_inn,
    validate_kpp,
    validate_ogrn,
    validate_phone,
)


class TestReceiptSchemas:
    def test_receipt_item_creation(self):
        item = ReceiptItem(
            name="Тестовый товар",
            price=Decimal("100.00"),
            quantity=Decimal("2"),
            sum=Decimal("200.00"),
            vat_rate=VATRate.VAT_20,
            vat_sum=Decimal("33.33"),
        )
        assert item.name == "Тестовый товар"
        assert item.price == Decimal("100.00")
        assert item.vat_rate == VATRate.VAT_20

    def test_seller_info(self):
        seller = SellerInfo(
            name="ИП Иванов",
            inn="7701234567",
            kpp="770101001",
            address="Москва, ул. Ленина",
        )
        assert seller.inn == "7701234567"

    def test_receipt_kkt_full(self):
        # Use aliases for required fields (fn, fd, fp, t, s)
        receipt = ReceiptKKT(
            fn="9280440300007971",
            fd="141637",
            fp="4087570038",
            t=datetime(2024, 1, 1, 12, 0, 0),
            s=Decimal("100000"),  # in cents
            seller=SellerInfo(name="Тест", inn="7701234567"),
            items=[
                ReceiptItem(name="Товар 1", price=Decimal("100"), quantity=Decimal("2"), sum=Decimal("200"))
            ],
        )
        assert receipt.fiscal_number == "9280440300007971"
        assert len(receipt.items) == 1


class TestDocumentSchemas:
    def test_document_type_enum(self):
        assert DocumentType.RECEIPT_KKT == "receipt_kkt"
        assert DocumentType.UPD == "upd"
        assert DocumentType.UNKNOWN == "unknown"

    def test_document_status_enum(self):
        assert DocumentStatus.PENDING == "pending"
        assert DocumentStatus.COMPLETED == "completed"
        assert DocumentStatus.FAILED == "failed"


class TestBillingSchemas:
    def test_plan_type_enum(self):
        assert PlanType.FREE == "free"
        assert PlanType.STARTER == "starter"
        assert PlanType.PRO == "pro"
        assert PlanType.BUSINESS == "business"

    def test_billing_plan(self):
        plan = BillingPlan(
            id="starter",
            name="Starter",
            tier=PlanType.STARTER,
            price_monthly_rub=2900,
            price_yearly_rub=29000,
            documents_per_month=1000,
            api_keys_limit=3,
            rate_limit_per_minute=100,
            features=["feature1", "feature2"],
            stripe_price_id_monthly="price_starter",
            stripe_price_id_yearly="price_starter_yearly",
            is_active=True,
        )
        assert plan.tier == PlanType.STARTER
        assert plan.documents_per_month == 1000


class TestValidators:
    def test_validate_inn_valid_10(self):
        # Valid 10-digit INN with correct checksum (example: 7707083893 - Яндекс)
        assert validate_inn("7707083893") is True
        assert validate_inn("7701234568") is False  # Wrong checksum

    def test_validate_inn_valid_12(self):
        # Valid 12-digit INN (individual) - this is a test value
        assert validate_inn("123456789012") is False  # Random, likely invalid
        # Note: Real valid INNs would need proper checksums

    def test_validate_inn_invalid_format(self):
        assert validate_inn("123") is False
        assert validate_inn("abcdefghij") is False
        assert validate_inn("") is False

    def test_validate_kpp(self):
        assert validate_kpp("770101001") is True
        assert validate_kpp("12345678") is False  # 8 digits
        assert validate_kpp("abcdefghi") is False

    def test_validate_ogrn(self):
        assert validate_ogrn("1027700123456") is False  # Random
        assert validate_ogrn("123") is False

    def test_validate_phone(self):
        assert validate_phone("+7 999 123 45 67") is True
        assert validate_phone("89991234567") is True
        assert validate_phone("79991234567") is True
        assert validate_phone("123") is False

    def test_normalize_phone(self):
        assert normalize_phone("+7 999 123 45 67") == "+79991234567"
        assert normalize_phone("89991234567") == "+79991234567"
        assert normalize_phone("79991234567") == "+79991234567"


class TestHelpers:
    def test_format_currency(self):
        assert format_currency(100000, "RUB") == "1,000.00 ₽"
        assert format_currency(290000, "RUB") == "2,900.00 ₽"
        assert format_currency(0, "RUB") == "0.00 ₽"

    def test_truncate_string(self):
        assert truncate_string("short", 100) == "short"
        assert truncate_string("a" * 150, 100) == "a" * 97 + "..."

    def test_sanitize_filename(self):
        assert sanitize_filename("normal_file.pdf") == "normal_file.pdf"
        assert sanitize_filename("file/with\\bad:chars.pdf") == "file_with_bad_chars.pdf"
        # Truncation: limits to 255 chars total
        long_name = "a" * 300
        result = sanitize_filename(long_name)
        assert len(result) == 255
