r"""Catch annotations that only work on this machine's Python.

Locally we run 3.14, where PEP 649 makes annotations lazy, so a function
signature may name something that was never imported and nothing complains.
The container runs 3.12, where annotations are evaluated at definition time, and
the same module raises `NameError` on import and the whole worker fails to
start.

This is not hypothetical: `invoice.py` once annotated a return type as
`Dict[str, Any]` with no `typing` import, which passed every test here and
would have killed the deploy.
"""

from __future__ import annotations

import ast
import builtins
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGETS = ["app", "scripts", "tests"]

# Names that are always available in an annotation.
BUILTIN_NAMES = set(dir(builtins)) | {"Self", "Any", "Optional"}


def module_symbols(tree: ast.Module) -> set[str]:
    """Every name a module binds, so a reference can be resolved."""
    names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    names.update(BUILTIN_NAMES)
                    continue
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            for decorator in node.decorator_list:
                names |= {n.id for n in ast.walk(decorator) if isinstance(n, ast.Name)}
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names |= {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.If, ast.Try)):
            # Names bound inside a `if TYPE_CHECKING:` or a try/except import
            # still count, since the guard decides what the annotation sees.
            for sub in ast.walk(node):
                if isinstance(sub, ast.ImportFrom):
                    for alias in sub.names:
                        names.add(alias.asname or alias.name.split(".")[0])
                elif isinstance(sub, ast.Assign):
                    for target in sub.targets:
                        names |= {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}
    return names


def annotation_names(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _display(path: pathlib.Path) -> str:
    """Repo-relative when possible, so output stays short for outside paths."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def check_file(path: pathlib.Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"{path}: syntax error: {exc}"]

    bound = module_symbols(tree) | BUILTIN_NAMES
    # A `from __future__ import annotations` file is safe on 3.12 too, because
    # it turns the eager evaluation off explicitly.
    lazy = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(a.name == "annotations" for a in node.names)
        for node in tree.body
    )
    if lazy:
        return []

    problems: list[str] = []
    for node in ast.walk(tree):
        annotations = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations = [a.annotation for a in node.args.args + node.args.kwonlyargs]
            annotations += [node.returns]
        elif isinstance(node, ast.AnnAssign):
            annotations = [node.annotation]

        for annotation in annotations:
            for name in annotation_names(annotation) - bound:
                problems.append(
                    f"{_display(path)}:{node.lineno}: annotation uses "
                    f"'{name}', which is neither imported nor built in"
                )
    return problems


def main() -> int:
    print("=" * 66)
    print("ANNOTATIONS THAT WOULD ONLY BREAK ON PYTHON 3.12")
    print("=" * 66)

    problems: list[str] = []
    checked = 0
    for target in TARGETS:
        for path in sorted((ROOT / target).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            checked += 1
            problems += check_file(path)

    if problems:
        print(f"\n{len(problems)} problem(s) in {checked} files:\n")
        for line in problems:
            print(f"  {line}")
        print(
            "\nThese pass on 3.14 because annotations are lazy, and would raise "
            "NameError on import under the container's 3.12."
        )
        return 1

    print(f"OK: all {checked} files import cleanly on Python 3.12")
    return 0


if __name__ == "__main__":
    sys.exit(main())
