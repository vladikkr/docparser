"""Write every .ps1 in the repo as UTF-8 *with* a BOM.

Windows PowerShell 5.1 reads a script without a BOM as the system ANSI
code page, so multi-byte UTF-8 is misread. The bytes of an em dash (E2 80 94)
end in 0x94, which is a closing double quote in windows-1251, so the parser
thinks the string ended and reports TerminatorExpectedAtEndOfString pointing at
an unrelated line. One character broke the whole bot service script and the
error named a brace a hundred lines away.

    python scripts/fix_powershell_encoding.py
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BOM = b"\xef\xbb\xbf"


def main() -> int:
    fixed, already = [], []
    for path in sorted(ROOT.rglob("*.ps1")):
        if "__pycache__" in path.parts:
            continue
        raw = path.read_bytes()
        if not raw.strip():
            continue
        has_non_ascii = any(byte > 0x7F for byte in raw)
        if not has_non_ascii:
            already.append(path.name)
            continue
        if raw.startswith(BOM):
            already.append(path.name)
            continue
        path.write_bytes(BOM + raw)
        fixed.append(path.name)

    print(f"rewrote with a BOM: {len(fixed)}")
    for name in fixed:
        print(f"  {name}")
    if not fixed:
        print("all scripts with non-ASCII text already carry a BOM")
    return 0


if __name__ == "__main__":
    sys.exit(main())
