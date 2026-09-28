"""Telegram bot package.

The bot lets a client send a photo straight into the chat and get the parsed
result back, so nothing has to be forwarded by hand. It talks to the same
parsers as the HTTP API and runs on our own machine over long polling, which
means no public HTTPS endpoint and no paid hosting.
"""

from app.bot.main import main

__all__ = ["main"]
