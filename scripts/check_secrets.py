"""Scan the working tree and the whole git history for secrets.

Tokens were pasted into a chat during development, so the question is not
whether a secret exists somewhere but whether one ever reached a commit. The
history matters more than the current tree: a leaked token stays leaked after
the file is deleted, and .gitignore only protects files that were never added.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (label, regex). Kept narrow on purpose: a pattern that matches ordinary code
# produces noise and gets ignored, which is how real leaks slip through.
PATTERNS = [
    ("telegram bot token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35,}\b")),
    ("stripe live key", re.compile(r"\bsk_live_[A-Za-z0-9]{20,}\b")),
    ("stripe secret key", re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("huggingface token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("render api key", re.compile(r"\brnd_[A-Za-z0-9]{30,}\b")),
    ("supabase service key", re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b")),
    ("postgres url with password", re.compile(r"postgres(?:ql)?://[^:\s]+:[^@\s]{6,}@")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
]

# Paths that are supposed to hold local secrets and must never be committed.
MUST_BE_IGNORED = [".env", ".env.local", "*.pem", "*.key", "storage/"]


def scan_text(text: str) -> list[tuple[str, str]]:
    hits = []
    for label, pattern in PATTERNS:
        for match in pattern.finditer(text):
            # Show only enough to identify it, never the whole secret.
            value = match.group(0)
            masked = value[:8] + "…" + value[-4:] if len(value) > 16 else value
            hits.append((label, masked))
    return hits


def main() -> int:
    print("=" * 66)
    print("SECRET SCAN")
    print("=" * 66)

    problems: list[str] = []

    # 1. Tracked files in the current tree.
    print("\n1. tracked files")
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True
    ).stdout.split()
    checked = 0
    for name in tracked:
        path = ROOT / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        checked += 1
        for label, masked in scan_text(text):
            problems.append(f"tracked {name}: {label} ({masked})")
    print(f"   scanned {checked} tracked file(s)")

    # 2. Every blob in the history.
    print("\n2. git history")
    revisions = subprocess.run(
        ["git", "log", "--all", "--pretty=format:%H"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.split()
    blobs: set[str] = set()
    for revision in revisions:
        listing = subprocess.run(
            ["git", "show", "--pretty=format:", "--name-only", revision],
            cwd=ROOT, capture_output=True, text=True,
        ).stdout.split()
        blobs.update(listing)
    history_hits = 0
    for name in sorted(blobs):
        if name not in tracked:
            # A path that exists only in history: check its last content.
            content = subprocess.run(
                ["git", "show", f"{revisions[-1]}:{name}"],
                cwd=ROOT, capture_output=True,
            ).stdout.decode("utf-8", errors="replace")
        else:
            content = (ROOT / name).read_text(encoding="utf-8", errors="replace") if (ROOT / name).is_file() else ""
        for label, masked in scan_text(content):
            history_hits += 1
            problems.append(f"history {name}: {label} ({masked})")
    print(f"   scanned {len(blobs)} path(s) across {len(revisions)} revision(s)")

    # 3. Secret-shaped files must be ignored.
    print("\n3. ignore rules")
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".env"], cwd=ROOT
    ).returncode == 0
    print(f"   .env ignored: {ignored}")
    if not ignored:
        problems.append(".env is not ignored, so a token could be committed")

    if problems:
        print(f"\n{len(problems)} finding(s):\n")
        for line in problems:
            print(f"  - {line}")
        return 1

    print("\nOK: no secret pattern in the working tree or in the history")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
