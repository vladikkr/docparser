"""Telegram bot package.

The bot lets a client send a photo straight into the chat and get the parsed
result back, so nothing has to be forwarded by hand. It talks to the same
parsers as the HTTP API and runs on our own machine over long polling, which
means no public HTTPS endpoint and no paid hosting.

Run it with `python -m app.bot`. The entry point deliberately does not re-export
`main` here: doing so shadowed the `app.bot.main` module, so `from app.bot
import main` handed back the function instead of the module.
"""

from app.bot.detect import Detection, detect
from app.bot.render import render, render_receipt
from app.bot.service import Outcome, process
from app.bot.store import BotUser, UserStore

__all__ = [
    "BotUser",
    "Detection",
    "Outcome",
    "UserStore",
    "detect",
    "process",
    "render",
    "render_receipt",
]
