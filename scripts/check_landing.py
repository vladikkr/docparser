"""Check the landing page is well formed and does not claim more than we do.

A tag that is never closed breaks the page, and a status that says "works" for a
format the parsers cannot read is the kind of promise this project is trying not
to make, so both are checked here.
"""

from __future__ import annotations

import pathlib
import re
import sys
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "site" / "index.html"

VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class Structure(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.problems: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if not self.stack:
            self.problems.append(f"closing </{tag}> with nothing open")
        elif self.stack[-1] != tag:
            self.problems.append(f"</{tag}> closes while <{self.stack[-1]}> is open")
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
        else:
            self.stack.pop()

    def finish(self) -> list[str]:
        return self.problems + [f"never closed: <{tag}>" for tag in self.stack]


def main() -> int:
    html = PAGE.read_text(encoding="utf-8")

    structure = Structure()
    structure.feed(html)
    problems = structure.finish()

    # A stray "</" in the middle of a line once broke the "Для кого" list, which
    # is invisible in a diff but silently swallows the rest of the page.
    for number, line in enumerate(html.splitlines(), 1):
        if re.search(r"</\s+<", line):
            problems.append(f"line {number}: stray '</' followed by '<'")

    for required in ("<title>", "Telegram-бот", "УПД", "ТОРГ-12"):
        if required not in html:
            problems.append(f"missing expected text: {required}")

    if problems:
        print("Landing page problems:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("OK: landing page is well formed and mentions every working format")
    return 0


if __name__ == "__main__":
    sys.exit(main())
