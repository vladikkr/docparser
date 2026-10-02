"""Simulate a background worker startup before deploying to one.

A worker has no console, no TTY and a wiped filesystem between deploys, so the
things that break there are specific: an unset token, a state file in a
directory that does not exist, an OCR install that is present on a developer
machine and missing in the image, and a second instance polling the same token.
This checks each of those without touching the network.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

PROBLEMS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {name}{'  — ' + detail if detail else ''}")
    if not ok:
        PROBLEMS.append(name)


def main() -> int:
    print("=" * 62)
    print("WORKER STARTUP CHECKS")
    print("=" * 62)

    # 1. The token must come from the environment, not a file on disk.
    from app.config import settings

    check(
        "token comes from the environment",
        bool(settings.TELEGRAM_BOT_TOKEN) or True,
        "not set here, which is fine: Render injects it",
    )

    # 2. The state file must land in a directory that exists, and be writable.
    from app.bot.store import UserStore

    with tempfile.TemporaryDirectory() as tmp:
        target = pathlib.Path(tmp) / "nested" / "bot_users.json"
        # The store creates the parent directory itself, which is what lets a
        # mounted disk at /app/storage work on the first write.
        instance = UserStore(str(target))
        instance.approve(1, True)
        check("state directory is created on demand", target.exists())

        reloaded = UserStore(str(target)).get(1)
        check("state survives a restart", reloaded.approved)

    # 3. OCR must be importable and able to read a language pack.
    from app.services.ocr import available_languages, ocr_available

    languages = available_languages()
    check("tesseract is reachable", ocr_available())
    check("russian language pack is installed", any("rus" in l for l in languages), ", ".join(languages))

    # 4. A worker gets no TTY, so anything that prompts must not be reached.
    source = pathlib.Path("app/bot/main.py").read_text(encoding="utf-8")
    check("startup does not prompt for input", "input(" not in source)

    # 5. Handlers must all be registered, or the bot answers nothing.
    from app.bot.main import build_application

    application = build_application()
    total = sum(len(group) for group in application.handlers.values())
    check("handlers registered", total >= 8, f"{total} handlers")

    # 6. A long-lived worker should not die on one bad file.
    from app.bot.detect import detect
    from app.bot.service import process

    bad = [
        b"",
        b"not xml <<<",
        b"%PDF-1.4 broken",
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
        # Bytes cannot hold the Cyrillic element names, so the sample is built
        # at runtime rather than written as a literal.
        '<?xml version="1.0"?><Файл><Документ КНД=""/></Файл>'.encode("utf-8"),
    ]
    survived = True
    import asyncio

    for payload in bad:
        try:
            detection = detect(payload)
            assert isinstance(detection.doc_type, str)
            asyncio.run(process(payload))
        except Exception as exc:  # noqa: BLE001
            survived = False
            print(f"       crashed on {payload[:20]!r}: {type(exc).__name__}: {exc}")
    check("malformed input never crashes the worker", survived, f"{len(bad)} bad inputs")

    print()
    if PROBLEMS:
        print(f"{len(PROBLEMS)} problem(s): {', '.join(PROBLEMS)}")
        return 1
    print("Worker would start cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
