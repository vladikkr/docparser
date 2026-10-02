import re
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.schemas.receipt import PaymentMethod, ReceiptItem, ReceiptKKT, SellerInfo, VATRate

logger = structlog.get_logger()


class FNSApiError(Exception):
    def __init__(self, message: str, code: str = "fns_error"):
        self.message = message
        self.code = code
        super().__init__(message)


class FNSApiClient:
    def __init__(self):
        self.base_url = settings.FNS_API_BASE_URL
        self.timeout = settings.FNS_API_TIMEOUT

    def parse_qr_string(self, qr_string: str) -> dict[str, str]:
        """Parse QR code string from receipt"""
        params = {}
        for match in re.finditer(r'(\w+)=([^&]+)', qr_string):
            params[match.group(1)] = match.group(2)

        # Normalize known parameters
        mapping = {
            't': 'date_time',
            's': 'sum',
            'fn': 'fiscal_number',
            'i': 'fiscal_document_number',
            'fp': 'fiscal_sign',
            'n': 'receipt_type',
        }

        return {mapping.get(k, k): v for k, v in params.items()}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def get_receipt(
        self,
        fiscal_number: str,
        fiscal_document_number: str,
        fiscal_sign: str,
        date_time: str,
        sum_cents: int,
        phone: str | None = None,
    ) -> dict[str, Any]:
        """Get full receipt data from FNS"""
        url = f"{self.base_url}/inns/*/kkts/*/fss/{fiscal_number}/tickets/{fiscal_document_number}"

        params = {
            "fiscalSign": fiscal_sign,
            "date": date_time,
            "sum": str(sum_cents),
        }

        headers = {
            "Device-Id": "",
            "Device-OS": "",
        }

        auth = None
        if phone:
            # For authenticated requests, phone/password needed
            # This is simplified - real implementation needs proper auth flow
            pass

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                url,
                params=params,
                headers=headers,
                auth=auth,
            )

            if response.status_code == 404:
                raise FNSApiError("Receipt not found in FNS", "not_found")
            elif response.status_code == 400:
                raise FNSApiError("Invalid request parameters", "invalid_params")
            elif response.status_code == 429:
                raise FNSApiError("Rate limited by FNS", "rate_limited")
            elif response.status_code != 200:
                raise FNSApiError(f"FNS API error: {response.status_code}", "api_error")

            return response.json()

    def parse_receipt_response(self, data: dict[str, Any]) -> ReceiptKKT:
        """Parse FNS response into ReceiptKKT schema"""
        doc = data.get("document", {}).get("receipt", {})

        # Seller info
        seller = SellerInfo(
            name=doc.get("user"),
            inn=doc.get("userInn"),
            kpp=doc.get("kpp"),
            address=doc.get("retailPlaceAddress"),
            place=doc.get("retailPlace"),
        )

        # Items
        items = []
        for item in doc.get("items", []):
            # The rate comes from whichever of the per-rate flags ФНС sent, and
            # vat_sum below is read straight from ndsSum, so there is no need
            # to resolve a combined amount here.
            vat_rate = None
            if item.get("nds20") is not None:
                vat_rate = VATRate.VAT_20
            elif item.get("nds10") is not None:
                vat_rate = VATRate.VAT_10
            elif item.get("nds0") is not None:
                vat_rate = VATRate.VAT_0

            items.append(ReceiptItem(
                name=item.get("name", ""),
                price=Decimal(str(item.get("price", 0))) / 100,
                quantity=Decimal(str(item.get("quantity", 1))),
                sum=Decimal(str(item.get("sum", 0))) / 100,
                vat_rate=vat_rate,
                vat_sum=Decimal(str(item.get("ndsSum", 0))) / 100 if item.get("ndsSum") else None,
                payment_method=PaymentMethod.CARD if item.get("paymentMethod") == 1 else PaymentMethod.CASH,
                measurement_unit=item.get("measurementUnit"),
            ))

        # Totals by VAT
        vat_20 = Decimal(str(doc.get("nds20", 0))) / 100 if doc.get("nds20") else None
        vat_10 = Decimal(str(doc.get("nds10", 0))) / 100 if doc.get("nds10") else None
        vat_0 = Decimal(str(doc.get("nds0", 0))) / 100 if doc.get("nds0") else None

        return ReceiptKKT(
            fiscal_number=doc.get("fn", ""),
            fiscal_document_number=doc.get("fd", ""),
            fiscal_sign=doc.get("fp", ""),
            date_time=datetime.fromisoformat(doc.get("dateTime", "").replace("T", "T")),
            total_sum=Decimal(str(doc.get("totalSum", 0))) / 100,
            seller=seller,
            items=items,
            cash_sum=Decimal(str(doc.get("cashTotalSum", 0))) / 100 if doc.get("cashTotalSum") else None,
            card_sum=Decimal(str(doc.get("ecashTotalSum", 0))) / 100 if doc.get("ecashTotalSum") else None,
            is_validated_fns=True,
            vat_20_sum=vat_20,
            vat_10_sum=vat_10,
            vat_0_sum=vat_0,
        )


fns_client = FNSApiClient()


async def validate_receipt_by_qr(qr_string: str, phone: str | None = None) -> ReceiptKKT:
    """Validate receipt using QR string"""
    params = fns_client.parse_qr_string(qr_string)

    required = ["fiscal_number", "fiscal_document_number", "fiscal_sign", "date_time", "sum"]
    for req in required:
        if req not in params:
            raise FNSApiError(f"Missing required parameter: {req}", "invalid_qr")

    # Convert sum to cents
    sum_cents = int(Decimal(params["sum"]) * 100)

    # Format date for FNS API
    date_str = params["date_time"].replace("T", "")

    data = await fns_client.get_receipt(
        fiscal_number=params["fiscal_number"],
        fiscal_document_number=params["fiscal_document_number"],
        fiscal_sign=params["fiscal_sign"],
        date_time=date_str,
        sum_cents=sum_cents,
        phone=phone,
    )

    receipt = fns_client.parse_receipt_response(data)
    receipt.raw_qr = qr_string
    return receipt
