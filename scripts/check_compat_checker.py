"""Prove the 3.12 annotation checker actually catches the bug it claims to.

A check that passes everything is indistinguishable from a check that is
broken, so the file from the original `invoice.py` defect is fed through it and
the bad one is required to be reported.
"""

import importlib.util
import pathlib
import sys
import tempfile

spec = importlib.util.spec_from_file_location(
    "compat", pathlib.Path(__file__).resolve().parent / "check_py312_compat.py"
)
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)

CASES = [
    (
        "missing typing import",
        "from typing import Any\n\n"
        "class A:\n"
        "    async def parse(self) -> Dict[str, Any]:\n"
        "        return {}\n",
        True,
    ),
    (
        "variable annotation without import",
        "value: Unknown = 3\n",
        True,
    ),
    (
        "future import makes it safe",
        "from __future__ import annotations\n"
        "from typing import Any\n\n"
        "def f() -> Dict[str, Any]:\n"
        "    return {}\n",
        False,
    ),
    (
        "properly imported",
        "from typing import Any, Dict\n\n"
        "def f() -> Dict[str, Any]:\n"
        "    return {}\n",
        False,
    ),
    (
        "builtin and own names are fine",
        "def f() -> int:\n"
        "    class Inner:\n"
        "        pass\n"
        "    return 1\n",
        False,
    ),
]

failures = []
with tempfile.TemporaryDirectory() as tmp:
    for name, source, should_report in CASES:
        path = pathlib.Path(tmp) / "sample.py"
        path.write_text(source, encoding="utf-8")
        problems = compat.check_file(path)
        reported = bool(problems)
        ok = reported == should_report
        print(f"  {'OK  ' if ok else 'FAIL'} {name}: reported={reported} expected={should_report}")
        if not ok:
            failures.append(f"{name}: {problems}")

if failures:
    print("\nThe checker does not behave as documented:")
    for line in failures:
        print(f"  {line}")
    raise SystemExit(1)

print("\nThe checker catches a missing import and stays quiet on valid code.")
