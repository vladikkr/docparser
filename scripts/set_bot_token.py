#!/usr/bin/env python3
"""Write the Telegram settings into .env without typing the token into a chat.

The bot token is a full control of the bot: anyone holding it can read every
message the bot receives. So it is typed straight into this prompt, which keeps
it out of chat history and out of the shell history file.

Run:  python scripts/set_bot_token.py
"""

from __future__ import annotations

import getpass
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"

FIELDS = {
    "TELEGRAM_BOT_TOKEN": "BotFather token",
    "TELEGRAM_ADMIN_ID": "your numeric Telegram id (0 skips the admin buttons)",
    "TELEGRAM_TRIAL_LIMIT": "free documents before asking for payment (3)",
}


def upsert(text: str, key: str, value: str) -> str:
    """Set a key in .env text, keeping the rest of the file as it is."""
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=.*$", re.MULTILINE)
    line = f"{key}={value}"
    if pattern.search(text):
        return pattern.sub(line, text)
    separator = "" if text.endswith("\n") or not text else "\n"
    return f"{text}{separator}{line}\n"


def main() -> int:
    if not ENV.exists():
        print(f"{ENV} not found. Copy .env.example to .env first.")
        return 1

    text = ENV.read_text(encoding="utf-8")
    values: dict[str, str] = {}

    token = getpass.getpass("BotFather token (input stays hidden): ").strip()
    if not re.fullmatch(r"\d{6,}:[A-Za-z0-9_-]{30,}", token):
        print("That does not look like a BotFather token (expected 123456789:AA...).")
        print("Nothing was written.")
        return 1
    values["TELEGRAM_BOT_TOKEN"] = token

    admin = input("Your numeric Telegram id (send /id to the bot, 0 to skip): ").strip() or "0"
    if not admin.isdigit():
        print("The id must be digits only. Nothing was written.")
        return 1
    values["TELEGRAM_ADMIN_ID"] = admin

    trial = input(f"Free documents before payment [{FIELDS['TELEGRAM_TRIAL_LIMIT']}]: ").strip()
    if trial.isdigit():
        values["TELEGRAM_TRIAL_LIMIT"] = trial

    for key, value in values.items():
        text = upsert(text, key, value)

    ENV.write_text(text, encoding="utf-8")
    # .env is gitignored, but a stray readable copy in the repo would be a leak.
    try:
        ENV.chmod(0o600)
    except OSError:
        pass  # Windows without POSIX permissions; the file is gitignored anyway

    print("\nSaved to .env:")
    for key in values:
        shown = "<hidden>" if key.endswith("TOKEN") else values[key]
        print(f"  {key} = {shown}")
    print("\nNext:  python -m app.bot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
