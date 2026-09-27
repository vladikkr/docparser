#!/usr/bin/env python3
"""Test FNS API connectivity"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import structlog

from app.services.fn_api import FNSApiError, validate_receipt_by_qr

structlog.configure(
    processors=[structlog.dev.ConsoleRenderer()],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)


async def test_fns():
    # Test QR string format: t=20240101T120000&s=1000.00&fn=123456789012&i=1&fp=1234567890
    test_qr = "t=20240101T120000&s=1000.00&fn=9280440300007971&i=141637&fp=4087570038"

    print(f"Testing FNS API with QR: {test_qr}")

    try:
        receipt = await validate_receipt_by_qr(test_qr)
        print("✅ FNS API response:")
        print(f"   Seller: {receipt.seller.name if receipt.seller else 'N/A'}")
        print(f"   INN: {receipt.seller.inn if receipt.seller else 'N/A'}")
        print(f"   Date: {receipt.date_time}")
        print(f"   Total: {receipt.total_sum}")
        print(f"   Items: {len(receipt.items)}")
        for item in receipt.items[:3]:
            print(f"     - {item.name}: {item.price} x {item.quantity} = {item.sum}")
        if len(receipt.items) > 3:
            print(f"     ... and {len(receipt.items) - 3} more items")
    except FNSApiError as e:
        print(f"❌ FNS API Error: {e.message} (code: {e.code})")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")


if __name__ == "__main__":
    asyncio.run(test_fns())
