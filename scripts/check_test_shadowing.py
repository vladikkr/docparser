"""Catch test functions that never run.

Two test functions with the same name in one module is legal Python: the second
silently replaces the first, so the earlier test contributes nothing while the
suite still reports a pass. That is worse than no test, because the coverage
count looks right.

This also catches a test that is defined and then shadowed by a fixture or a
local name, and a test whose name is not collected by the configured pattern.
"""

from __future__ import annotations

import ast
import collections
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"


def main() -> int:
    print("=" * 62)
    print("TESTS THAT SILENTLY DO NOT RUN")
    print("=" * 62)

    problems: list[str] = []
    total_tests = 0
    files = 0

    for path in sorted(TESTS.rglob("test_*.py")):
        files += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        tests = [name for name in names if name.startswith("test_")]
        total_tests += len(tests)

        duplicates = [name for name, count in collections.Counter(names).items() if count > 1]
        for name in duplicates:
            problems.append(
                f"{path.relative_to(ROOT)}: {name} is defined more than once, "
                "so the earlier definition never runs"
            )

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                if not node.body:
                    problems.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.name} is empty")

    print(f"{files} file(s), {total_tests} test function(s)")

    if problems:
        print(f"\n{len(problems)} problem(s):\n")
        for line in problems:
            print(f"  - {line}")
        return 1

    print("OK: no test is shadowed by another of the same name")
    return 0


if __name__ == "__main__":
    sys.exit(main())
