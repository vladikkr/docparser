"""Summarise ruff findings by rule code, and name the ones worth acting on.

A flat list of 300 style complaints hides the two that matter: an undefined
name and an unused import are bugs, while a modern-syntax suggestion is not.
The severity map below says which is which, and the report leads with the bugs.
"""

from __future__ import annotations

import collections
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Rules that indicate a real defect rather than a style preference.
BUGS = {
    "F821": "undefined name",
    "F811": "redefinition of unused name",
    "F401": "unused import",
    "F841": "local variable assigned but never used",
    "F632": "use of == to compare literals",
    "F702": "syntax error",
    "F706": "return outside function",
    "B008": "call in default argument",
    "B006": "mutable default argument",
    "E999": "syntax error",
}
WORTH_A_LOOK = {
    "B904": "raise without from inside except",
    "B023": "function definition does not bind loop variable",
    "SIM105": "contextlib.suppress instead of try/except/pass",
    "SIM117": "nested with statements could be combined",
    "S": "bandit-style security warning",
}


def main() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "app", "tests", "scripts", "--output-format", "json"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        findings = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("could not read ruff output")
        print(result.stdout[:500])
        return 1

    by_code = collections.Counter(f["code"] for f in findings)

    print("=" * 64)
    print(f"RUFF: {len(findings)} finding(s)")
    print("=" * 64)

    print("\nDEFECTS (fix these):")
    defects = 0
    for code, count in by_code.most_common():
        if code in BUGS:
            defects += count
            print(f"  {count:4}  {code:6} {BUGS[code]}")
    if not defects:
        print("  none")

    print("\nWORTH A LOOK:")
    for code, count in by_code.most_common():
        if code in WORTH_A_LOOK:
            print(f"  {count:4}  {code:6} {WORTH_A_LOOK[code]}")

    print("\nSTYLE (bulk-fixable):")
    style = sum(n for c, n in by_code.items() if c not in BUGS and c not in WORTH_A_LOOK)
    print(f"  {style:4}  across {len([c for c in by_code if c not in BUGS and c not in WORTH_A_LOOK])} rule(s)")

    if defects:
        print("\nDETAIL OF EVERY DEFECT:")
        for finding in findings:
            if finding["code"] in BUGS:
                location = pathlib.Path(finding["filename"]).relative_to(ROOT)
                print(f"  {location}:{finding['location']['row']}  {finding['code']}  {finding['message']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
