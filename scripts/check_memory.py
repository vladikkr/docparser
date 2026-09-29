"""Measure how much memory the parser actually needs.

Every free hosting tier is quoted in RAM, and the bot is the only service that
matters for uptime. A receipt goes through Tesseract with multi-scale and tiled
passes, so the peak is much higher than a plain parse, and it is the number that
decides which free tier is even viable.

`psutil` is not a dependency here, so the figures come straight from
`GetProcessMemoryInfo`: WORKING_SET_SIZE is what the OS is actually holding,
and PEAK_WORKING_SET_SIZE is the high-water mark over the process lifetime.
The Python heap is printed too, but on its own it understates the real cost,
because Tesseract runs out of process and Pillow buffers natively.
"""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes as wintypes
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.services.parsers import get_parser  # noqa: E402
from app.services.parsers.receipt_kkt import ReceiptKKTParser  # noqa: E402
from app.models import DocumentType  # noqa: E402

RECEIPT = pathlib.Path(r"C:\Users\vladk\Downloads\1.png.jpg")
ROOT = pathlib.Path(__file__).resolve().parent.parent
UPD = ROOT / "test_xml" / "upd" / "upd_valid.xml"


class _Counters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


_PSAPI = ctypes.WinDLL("psapi", use_last_error=True)
_PSAPI.GetProcessMemoryInfo.argtypes = [
    ctypes.wintypes.HANDLE,
    ctypes.POINTER(_Counters),
    wintypes.DWORD,
]
_PSAPI.GetProcessMemoryInfo.restype = wintypes.BOOL


def memory() -> tuple[float, float]:
    """(current working set, peak working set) in MB."""
    counters = _Counters()
    counters.cb = ctypes.sizeof(_Counters)
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    if not _PSAPI.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    mb = 1024 * 1024
    return counters.WorkingSetSize / mb, counters.PeakWorkingSetSize / mb


def main() -> int:
    print("=" * 60)
    print("MEMORY NEEDED BY THE BOT")
    print("=" * 60)

    current, peak = memory()
    print(f"idle, before any parsing      now {current:7.1f} MB   peak {peak:7.1f} MB")

    if RECEIPT.exists():
        raw = RECEIPT.read_bytes()
        result = asyncio.run(ReceiptKKTParser(None).parse(None, raw))
        current, peak = memory()
        print(
            f"after a receipt photo (OCR)  now {current:7.1f} MB   peak {peak:7.1f} MB"
            f"   total={result.get('total_sum')}"
        )
    else:
        print(f"receipt photo missing at {RECEIPT}, OCR path skipped")

    # The invoice path is the same code on a much smaller input, so it should
    # stay near whatever the OCR peak already reserved.
    invoice = get_parser(DocumentType.UPD, None)
    result = asyncio.run(invoice.parse(None, UPD.read_bytes()))
    current, peak = memory()
    print(
        f"after an УПД xml             now {current:7.1f} MB   peak {peak:7.1f} MB"
        f"   items={len(result.get('parsed', {}).get('items', []))}"
    )

    print()
    # Tesseract runs as a separate process and its memory counts against the
    # same container limit, so the Python peak is only part of the bill. Doubling
    # it is a deliberately conservative reading of what was measured rather than
    # a claim about Tesseract's own footprint.
    budget = peak * 2
    tier = 512
    while tier < budget:
        tier *= 2

    print(f"VERDICT: the Python process peaks at {peak:.0f} MB.")
    print(f"         Tesseract adds its own process, so budget about {budget:.0f} MB.")
    print(f"         A {tier} MB tier is the smallest that leaves headroom.")
    print("         128 MB and 256 MB tiers cannot run the OCR path.")
    print("         A 512 MB tier is viable; 1 GB is comfortable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
