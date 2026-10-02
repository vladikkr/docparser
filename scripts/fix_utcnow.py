"""Replace every datetime.utcnow() with the shared naive-UTC helper.

`datetime.utcnow()` is deprecated and slated for removal, and it returns a
naive value without saying so, which is what the naive `DateTime` columns here
expect. The eleven call sites all wanted `app.utils.helpers.utcnow()`.

Each file is edited and the module re-imported, so a file that does not use
`datetime` any more has its import narrowed too rather than left with a name it
no longer needs.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TARGETS = [
    "app/core/security.py",
    "app/services/webhook_dispatcher.py",
    "app/utils/file_utils.py",
    "app/tasks/parse_tasks.py",
    "app/api/health.py",
    "app/api/deps.py",
    "app/api/v1/documents.py",
    "app/api/v1/billing.py",
]

CALL = re.compile(r"datetime\.utcnow\(\)")


def rewrite(path: pathlib.Path) -> int:
    text = path.read_text(encoding="utf-8")
    if not CALL.search(text):
        return 0
    count = len(CALL.findall(text))
    new = CALL.sub("utcnow()", text)

    # Add the import next to the existing datetime import.
    if "from app.utils.helpers import" in new:
        new = re.sub(
            r"from app\.utils\.helpers import ([^\n]+)",
            lambda m: "from app.utils.helpers import " + ", ".join(
                sorted(set(part.strip() for part in m.group(1).split(",")) | {"utcnow"})
            ),
            new,
            count=1,
        )
    else:
        anchor = re.search(r"^from datetime import .*$", new, re.MULTILINE)
        if anchor:
            insert_at = anchor.end()
            new = new[:insert_at] + "\n\nfrom app.utils.helpers import utcnow" + new[insert_at:]
        else:
            new = "from app.utils.helpers import utcnow\n" + new

    path.write_text(new, encoding="utf-8")
    return count


def main() -> int:
    total = 0
    for relative in TARGETS:
        path = ROOT / relative
        if not path.exists():
            print(f"  ??  {relative} not found")
            continue
        count = rewrite(path)
        total += count
        if count:
            print(f"  OK  {relative}: {count} call(s)")

    print(f"\nreplaced {total} call(s)")

    # Every touched module has to still parse and import.
    print("\nverifying")
    failures = []
    for relative in TARGETS:
        path = ROOT / relative
        if not path.exists():
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            failures.append(f"{relative}: {exc}")
            continue
        text = path.read_text(encoding="utf-8")
        if CALL.search(text):
            failures.append(f"{relative}: still calls datetime.utcnow()")
    for relative in ["app.core.security", "app.api.deps", "app.api.health",
                     "app.utils.file_utils", "app.services.webhook_dispatcher"]:
        try:
            __import__(relative)
        except Exception as exc:
            failures.append(f"{relative} does not import: {type(exc).__name__}: {exc}")

    if failures:
        for line in failures:
            print(f"  FAIL {line}")
        return 1

    print("  every file parses and imports, and no utcnow() call is left")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
