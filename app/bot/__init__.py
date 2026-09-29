"""Telegram bot package.

The bot lets a client send a photo straight into the chat and get the parsed
result back, so nothing has to be forwarded by hand. It talks to the same
parsers as the HTTP API and runs as a background worker over long polling,
which means no public HTTPS endpoint and no paid hosting.

Run it with `python -m app.bot`.

This module deliberately re-exports nothing. Re-exporting `main`, `detect` or
`process` shadows the submodules of the same name, so `from app.bot import
detect` hands back the function while the module is still reachable by its
attribute, and which one you get depends on the import style. That cost an hour
of debugging twice, so imports are explicit: `from app.bot.detect import detect`.
"""
