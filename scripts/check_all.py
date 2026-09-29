#!/usr/bin/env python3
"""Run every check in the project and report one verdict.

The individual scripts exist because each answers a different question, and
running them by hand meant someone forgot one of them. Several guards only
matter on a deploy machine rather than here: annotations that break on the
container's Python, a worker with no console, a landing page that has drifted
from what the parsers actually do.

    python scripts/check_all.py
    python scripts/check_all.py --quick   # skip the slow OCR passes
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (name, script, slow?)
CHECKS: list[tuple[str, str, bool]] = [
    ("unit tests", "-m pytest -q -p no:cacheprovider", False),
    ("imports declared", "scripts/check_requirements.py", False),
    ("python 3.12 compatibility", "scripts/check_py312_compat.py", False),
    ("powershell 5.1 compatibility", "scripts/check_ps_compat.py", False),
    ("landing page", "scripts/check_landing.py", False),
    ("prices agree across docs", "scripts/check_prices.py", False),
    ("button labels in docs", "scripts/check_button_labels.py", False),
    ("document parsers", "scripts/validate_all.py", False),
    ("worker startup", "scripts/check_worker_startup.py", True),
    ("memory footprint", "scripts/check_memory.py", True),
    ("receipt layouts", "scripts/check_photo_pipeline.py", True),
    ("receipt wording", "scripts/check_wording.py", False),
    ("self-employed receipts", "scripts/check_selfemployed.py", True),
]


def run(command: str) -> tuple[bool, str]:
    result = subprocess.run(
        f"{sys.executable} {command}",
        cwd=ROOT,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode == 0, (result.stdout or "") + (result.stderr or "")


def tail(output: str, lines: int = 2) -> str:
    kept = [line.strip() for line in output.strip().splitlines() if line.strip()]
    return " | ".join(kept[-lines:])[:120]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="skip OCR-heavy checks")
    args = parser.parse_args()

    print("=" * 70)
    print("FULL CHECK")
    print("=" * 70)

    failures: list[tuple[str, str]] = []
    total_started = time.time()

    for name, command, slow in CHECKS:
        if args.quick and slow:
            print(f"  SKIP {name} (slow)")
            continue

        started = time.time()
        ok, output = run(command)
        elapsed = time.time() - started

        print(f"  {'OK  ' if ok else 'FAIL'} {name:28} {elapsed:5.1f}s   {tail(output)}")
        if not ok:
            failures.append((name, output))

    print()
    print("-" * 70)
    if failures:
        print(f"{len(failures)} check(s) FAILED:\n")
        for name, output in failures:
            print(f"### {name}")
            for line in output.strip().splitlines()[-15:]:
                print(f"    {line}")
            print()
        return 1

    print(f"All {len(CHECKS)} checks passed in {time.time() - total_started:.1f}s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
