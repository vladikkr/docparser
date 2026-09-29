"""Entry point: python -m app.bot

Runs the bot over long polling from this machine. Long polling needs no public
HTTPS address, so the bot works without any paid hosting, and it is the only
option while Render routes nowhere and the HF space has no quota.

Only one process may poll a single token at a time: a second one makes Telegram
return 409 and both copies go deaf.
"""

from __future__ import annotations

import logging
import sys

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.bot import handlers
from app.config import settings

logging.basicConfig(
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger("docparser.bot")


async def post_init(application: Application) -> None:
    """Print who we are, from inside the polling loop.

    `get_me` is a coroutine, so it has to be awaited on the loop that
    `run_polling` owns. Calling it from `main` without awaiting raised
    "'coroutine' object has no attribute 'username'", which killed the bot on
    startup and made it look silent.
    """
    me = await application.bot.get_me()
    logger.info("bot_started username=%s id=%s", me.username, me.id)
    print(f"Bot @{me.username} ({me.first_name}) is running. Press Ctrl+C to stop.")
    print(f"Open https://t.me/{me.username} and send it a photo.")


def build_application() -> Application:
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", handlers.cmd_start))
    app.add_handler(CommandHandler("help", handlers.cmd_help))
    app.add_handler(CommandHandler("status", handlers.cmd_status))
    app.add_handler(CommandHandler("id", handlers.cmd_id))

    app.add_handler(MessageHandler(filters.PHOTO, handlers.on_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handlers.on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_anything_else))

    app.add_handler(CallbackQueryHandler(handlers.on_approve))
    app.add_error_handler(handlers.on_error)

    app.bot_data["user_store"] = handlers.UserStore()
    return app


def _preflight() -> None:
    from app.services.ocr import available_languages, ocr_available

    if not settings.telegram_configured:
        print("TELEGRAM_BOT_TOKEN is not set. Add it to .env (see .env.example).")
        sys.exit(1)

    if not settings.telegram_admin_configured:
        print("WARNING: TELEGRAM_ADMIN_ID is 0 — nobody can approve paid access.")
        print("         Send /id to the bot, then set TELEGRAM_ADMIN_ID to that number.")

    if not ocr_available():
        print("WARNING: Tesseract is not reachable — photo parsing will fail.")
    else:
        print(f"OCR languages available: {', '.join(available_languages())}")


def main() -> None:
    _preflight()

    app = build_application()
    # The identity is printed by post_init, once the polling loop owns the bot.
    app.run_polling(drop_pending_updates=True, close_loop=False)


if __name__ == "__main__":
    main()
