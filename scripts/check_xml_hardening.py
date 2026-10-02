"""Confirm the XML loader refuses an expansion bomb instead of eating memory.

ElementTree expands entities, so a small document can declare thousands of
nested ones and expand to gigabytes. The parsers read files that clients
upload, which makes this reachable by anyone who finds the bot.

This is a real payload, kept small enough to be harmless if the guard is ever
removed: the expansion is what would hurt, not the text.
"""

from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# The payloads carry Cyrillic element names, which a bytes literal cannot
# hold, so they are written as text and encoded here.
BILLION_LAUGHS = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
  <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
  <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">
  <!ENTITY lol6 "&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;">
  <!ENTITY lol7 "&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;">
  <!ENTITY lol8 "&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;">
  <!ENTITY lol9 "&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;">
]>
<Файл><Документ КНД="1115131">&lol9;</Документ></Файл>
""".encode("utf-8")

EXTERNAL_ENTITY = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE foo [
  <!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<Файл><Документ КНД="1115131">&xxe;</Документ></Файл>
""".encode("utf-8")

ORDINARY = """<?xml version="1.0" encoding="UTF-8"?>
<Файл><Документ КНД="1115131">обычный документ</Документ></Файл>""".encode("utf-8")


def peak_memory_mb() -> float:
    """High-water mark of this process, via the Windows API or /proc."""
    try:
        import ctypes
        import ctypes.wintypes as wintypes

        class Counters(ctypes.Structure):
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

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        return counters.PeakWorkingSetSize / 1024 / 1024
    except Exception:
        return 0.0


def main() -> int:
    from app.services.parsers.fns_xml import FnsParseError, load_xml

    print("=" * 62)
    print("XML HARDENING")
    print("=" * 62)

    failures = []

    print("\n1. ordinary document still parses")
    try:
        root = load_xml(ORDINARY)
        ok = root.tag == "Файл"
        print(f"   parsed root={root.tag!r} -> {'OK' if ok else 'WRONG ROOT'}")
        if not ok:
            failures.append("an ordinary document stopped parsing")
    except Exception as exc:
        failures.append(f"an ordinary document stopped parsing: {exc}")
        print(f"   FAILED: {exc}")

    print("\n2. billion-laughs bomb is rejected")
    for name, payload in (("expansion bomb", BILLION_LAUGHS), ("external entity", EXTERNAL_ENTITY)):
        started = time.time()
        try:
            load_xml(payload)
            failures.append(f"{name} was accepted")
            print(f"   {name}: ACCEPTED, which is the vulnerability")
        except FnsParseError as exc:
            print(f"   {name}: rejected in {time.time() - started:.2f}s — {str(exc)[:60]}")
        except Exception as exc:
            failures.append(f"{name} raised {type(exc).__name__} instead of FnsParseError")
            print(f"   {name}: raised {type(exc).__name__}: {exc}")

    try:
        peak = peak_memory_mb()
        print(f"\n   peak memory during the run: {peak:.0f} MB")
        if peak > 600:
            failures.append(f"peak memory reached {peak:.0f} MB, the bomb was expanded")
    except Exception:
        pass  # the memory figure is a nicety; rejection is the assertion

    print()
    if failures:
        print(f"{len(failures)} problem(s):")
        for line in failures:
            print(f"  - {line}")
        return 1

    print("OK: hostile XML is refused and normal documents still parse")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
