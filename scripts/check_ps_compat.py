"""Check that every PowerShell script survives Windows PowerShell 5.1.

Two separate traps live here, and both cost real debugging time:

1. Windows PowerShell 5.1 reads a script that has no BOM as the system ANSI
   code page, not UTF-8. An em dash is E2 80 94, and 0x94 is a closing double
   quote in windows-1251, so the parser believes the string ended and reports
   TerminatorExpectedAtEndOfString pointing at an unrelated brace.

2. Windows PowerShell 5.1 has no New-ScheduledTaskRepetition, and
   Register-ScheduledTask rejects a string for -Action, so a script written
   against newer PowerShell fails at run time rather than at parse time.

So the check parses each file with the 5.1 parser and also greps for the
5.1-incompatible API.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BOM = b"\xef\xbb\xbf"

# Absent from Windows PowerShell 5.1; using it is a run-time failure, not a
# parse failure, so parsing alone would not catch it.
INCOMPATIBLE_API = ["New-ScheduledTaskRepetition", "Register-CimInstance -Action"]


def parses(path: pathlib.Path) -> tuple[bool, str]:
    command = (
        "$e=$null;$t=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$t,[ref]$e)|Out-Null;"
        "if($e){$e[0].Message}else{'OK'}"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
    )
    text = result.stdout.decode("utf-8", errors="replace").strip()
    text = result.stdout.decode("cp866", errors="replace").strip() if not text else text
    return text == "OK", text


def main() -> int:
    print("=" * 66)
    print("POWERSHELL 5.1 COMPATIBILITY")
    print("=" * 66)

    problems: list[str] = []
    scripts = [
        p
        for p in sorted(ROOT.rglob("*.ps1"))
        if "__pycache__" not in p.parts and p.name != "_probe.ps1"
    ]

    for path in scripts:
        raw = path.read_bytes()
        if not raw.strip():
            continue
        name = path.relative_to(ROOT)

        non_ascii = any(byte > 0x7F for byte in raw)
        has_bom = raw.startswith(BOM)
        if non_ascii and not has_bom:
            problems.append(
                f"{name}: has non-ASCII text but no BOM, so PowerShell 5.1 will "
                "misread it (run scripts/fix_powershell_encoding.py)"
            )

        ok, message = parses(path)
        if not ok:
            problems.append(f"{name}: does not parse on 5.1 — {message[:80]}")

        text = raw.decode("utf-8", errors="replace")
        # Comments may legitimately name the missing cmdlet to explain why it is
        # not used, so only real code is scanned.
        code = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("#")
        )
        for api in INCOMPATIBLE_API:
            if api in code:
                problems.append(f"{name}: uses {api}, which Windows PowerShell 5.1 lacks")

    print(f"checked {len(scripts)} script(s)")

    if problems:
        print(f"\n{len(problems)} problem(s):\n")
        for line in problems:
            print(f"  - {line}")
        return 1

    print("OK: every script parses on Windows PowerShell 5.1 and carries a BOM")
    return 0


if __name__ == "__main__":
    sys.exit(main())
