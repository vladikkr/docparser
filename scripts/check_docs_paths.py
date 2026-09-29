"""Check that every command and file named in the hand-off actually exists.

`next_steps.md` and `deploy_bot_render.md` are the two documents a person reads
instead of a person who can run the code, so a path or script name that has
drifted makes them actively misleading. This reads them back and resolves
every command and file they mention.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = [ROOT / "docs" / "next_steps.md", ROOT / "docs" / "deploy_bot_render.md"]

COMMAND_RE = re.compile(r"(?:python|powershell)(?:\s+-[\w-]+)*\s+([\w./\\-]+\.(?:py|ps1))")
# A leading slash is excluded on purpose: `/app/storage/...` is a path inside
# the container, not a file in the repository, and must not be resolved here.
PATH_RE = re.compile(r"(?<![/\w])((?:docs|scripts|app|docker|test_xml|site)/[\w./-]+)")


def main() -> int:
    problems: list[str] = []
    referenced = 0

    for doc in DOCS:
        if not doc.exists():
            problems.append(f"{doc.name} is missing")
            continue
        text = doc.read_text(encoding="utf-8")

        for match in COMMAND_RE.finditer(text):
            referenced += 1
            target = ROOT / match.group(1).replace("\\", "/")
            if not target.exists():
                problems.append(f"{doc.name}: runs {match.group(1)}, which does not exist")

        for match in PATH_RE.finditer(text):
            referenced += 1
            target = ROOT / match.group(1)
            if not target.exists():
                problems.append(f"{doc.name}: points at {match.group(1)}, which does not exist")

    print(f"checked {referenced} reference(s) in {len(DOCS)} document(s)")

    if problems:
        print(f"\n{len(problems)} broken reference(s):")
        for line in sorted(set(problems)):
            print(f"  - {line}")
        return 1

    print("OK: every command and file in the hand-off exists")
    return 0


if __name__ == "__main__":
    sys.exit(main())
