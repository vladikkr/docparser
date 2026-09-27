"""Verify every third-party import is declared in requirements.txt.

Run: python scripts/check_requirements.py
Exits non-zero when an import is missing, so CI catches it before deploy.
"""

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"
APP_DIR = ROOT / "app"

ALIASES = {
    "yaml": "pyyaml",
    "PIL": "pillow",
    "cv2": "opencv-python-headless",
    "jwt": "python-jose",
    "jose": "python-jose",
    "Crypto": "pycryptodome",
    "dotenv": "python-dotenv",
}

# Imports intentionally optional: guarded by try/except or lazy loaders.
OPTIONAL = {"magic", "PIL", "cv2", "pytesseract", "pdf2image", "numpy", "sentry_sdk"}


def declared_packages() -> set[str]:
    packages = set()
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[<>=!~\[; ]", line)[0]
        packages.add(name.lower().replace("_", "-"))
    return packages


def third_party_imports() -> set[tuple[str, str, int]]:
    local = {"app", "alembic", "tests", "scripts"}
    found: set[tuple[str, str, int]] = set()

    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:  # top level only
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.add((alias.name.split(".")[0], str(path), node.lineno))
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add((node.module.split(".")[0], str(path), node.lineno))

    return {(m, p, ln) for m, p, ln in found if m not in sys.stdlib_module_names and m not in local}


def main() -> int:
    declared = declared_packages()
    missing: list[str] = []

    for module, path, lineno in sorted(third_party_imports()):
        key = ALIASES.get(module, module).lower().replace("_", "-")
        if key in declared or module.lower() in declared:
            continue
        if module in OPTIONAL:
            continue
        missing.append(f"{module} ({path}:{lineno}) -> add '{key}' to requirements.txt")

    if missing:
        print("Missing dependencies:\n")
        for line in missing:
            print(f"  {line}")
        return 1

    print(f"OK: all {len(third_party_imports())} third-party imports are declared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
