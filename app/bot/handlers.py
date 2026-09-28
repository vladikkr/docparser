"""Telegram handlers: the client sends a photo, the bot answers in the same chat."""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app.bot.render import render
from app.bot.service import Outcome, process
from app.bot.store import UserStore
from app.config import settings

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "📷 <b>Как работает</b>\n\n"
    "1. Сфотографируй чек так, чтобы были видны все строки и итог.\n"
    "2. Отправь фото сюда одной кнопкой — можно без подписи.\n"
    "3. Я верну разобранные данные: продавец, позиции, итог.\n\n"
    "📎 Можно прислать файлом: PDF, JPG, PNG.\n\n"
    "⚠️ Если итог не сошёлся с позициями, я честно об этом напишу, "
    "а не выдам случайное число."
)


def _store(context: ContextTypes.DEFAULT_TYPE) -> UserStore:
    if "user_store" not in context.application.bot_data:
        context.application.bot_data["user_store"] = UserStore()
    return context.application.bot_data["user_store"]


def _greeting(user) -> str:
    name = user.first_name or "клиент"
    return f"Привет, {name}!"


def _status_line(user) -> str:
    if user.approved:
        return "♾️ Доступ открыт, без ограничений."
    left = user.trial_left
    if left <= 0:
        return "⛔ Пробный лимит исчерпан."
    plural = "документ" if left == 1 else "документа" if left < 5 else "документов"
    return f"🎁 Осталось пробных: {left} {plural} из {user.trial_limit}."


async def _register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    store = _store(context)
    user = store.get(tg_user.id)
    return store.touch(user, tg_user.username, tg_user.first_name)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _register(update, context)
    await update.message.reply_text(
        f"{_greeting(user)}\n\n{_status_line(user)}\n\n{HELP_TEXT}",
        parse_mode="HTML",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _register(update, context)
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _register(update, context)
    usage = f"Обработано документов: {user.documents_used}"
    await update.message.reply_text(
        f"{_status_line(user)}\n{usage}",
        parse_mode="HTML",
    )


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _register(update, context)
    await update.message.reply_text(
        f"Твой Telegram ID: <code>{user.user_id}</code>\n"
        f"Имя: {user.first_name or '—'}"
        + (f"\nЮзернейм: @{user.username}" if user.username else ""),
        parse_mode="HTML",
    )


async def _notify_admin(context: ContextTypes.DEFAULT_TYPE, user, outcome_note: str) -> None:
    """Ask the owner to hand over paid access."""
    if not settings.telegram_admin_configured:
        logger.warning("telegram_admin_not_configured user=%s", user.user_id)
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Выдать доступ", callback_data=f"approve:{user.user_id}"),
                InlineKeyboardButton("✖️ Отказать", callback_data=f"deny:{user.user_id}"),
            ]
        ]
    )
    who = f"@{user.username}" if user.username else user.first_name or str(user.user_id)
    try:
        await context.bot.send_message(
            chat_id=settings.TELEGRAM_ADMIN_ID,
            text=(
                "🔔 <b>Клиент исчерпал пробный лимит</b>\n\n"
                f"ID: <code>{user.user_id}</code>\n"
                f"Кто: {who}\n"
                f"Обработано: {user.documents_used}\n\n"
                f"{outcome_note}"
            ),
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    except TelegramError as exc:
        logger.error("admin_notify_failed error=%s", exc)


async def _handle_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE, file_bytes: bytes, name: str | None) -> None:
    user = await _register(update, context)
    store = _store(context)

    if not user.has_access:
        store.mark_payment_requested(user.user_id)
        await update.message.reply_text(
            "⛔ Пробный лимит исчерпан.\n\n"
            "Разбор платный. Напишите, пожалуйста, @vladikskr — согласуем оплату, "
            "и я включу доступ.",
            parse_mode="HTML",
        )
        await _notify_admin(context, user, "Клиент ждёт решения по оплате.")
        return

    await update.effective_chat.send_action(ChatAction.TYPING)
    outcome: Outcome = await process(file_bytes, name)

    if outcome.ok:
        store.consume_document(user.user_id)
        user = store.get(user.user_id)
        tail = "" if user.approved else f"\n\n{_status_line(user)}"
        await update.message.reply_text(render(outcome) + tail, parse_mode="HTML")
        if not user.approved and user.trial_left == 0:
            await _notify_admin(
                context,
                user,
                f"Последний бесплатный документ: <b>{outcome.label}</b>.",
            )
        return

    await update.message.reply_text(render(outcome), parse_mode="HTML")


def _too_big(update: Update) -> None:
    limit = settings.TELEGRAM_MAX_FILE_MB
    update.message.reply_text(
        f"⚠️ Файл больше {limit} МБ. Пришли фото покрупнее, но без перегруза — "
        "или сожми его.",
    )


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Telegram keeps several sizes per photo; the last one is the largest.
    photo = update.message.photo[-1]
    if photo.file_size and photo.file_size > settings.TELEGRAM_MAX_FILE_MB * 1024 * 1024:
        _too_big(update)
        return

    telegram_file = await context.bot.get_file(photo.file_id)
    file_bytes = bytes(await telegram_file.download_as_bytearray())
    await _handle_incoming(update, context, file_bytes, "photo.jpg")


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document
    limit = settings.TELEGRAM_MAX_FILE_MB * 1024 * 1024
    if document.file_size and document.file_size > limit:
        _too_big(update)
        return

    telegram_file = await context.bot.get_file(document.file_id)
    file_bytes = bytes(await telegram_file.download_as_bytearray())
    await _handle_incoming(update, context, file_bytes, document.file_name)


async def on_anything_else(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Пришли фото чека или PDF с документом — разберу и верну результат.\n"
        "Команда /help — подробнее.",
    )


async def on_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner grants or refuses paid access."""
    query = update.callback_query
    if update.effective_user.id != settings.TELEGRAM_ADMIN_ID:
        await query.answer("Это не для тебя.", show_alert=True)
        return

    action, _, raw_id = (query.data or "").partition(":")
    if not raw_id.isdigit():
        await query.answer()
        return
    client_id = int(raw_id)

    store = _store(context)
    client = store.get(client_id)

    if action == "approve":
        store.approve(client_id, True)
        await query.answer("Доступ выдан.")
        await query.edit_message_text(f"✅ Доступ выдан клиенту <code>{client_id}</code>.")
        try:
            await context.bot.send_message(
                chat_id=client_id,
                text="✅ Доступ открыт. Присылайте документы, разберу их.",
            )
        except TelegramError as exc:
            logger.warning("client_notify_failed client=%s error=%s", client_id, exc)
    else:
        store.approve(client_id, False)
        await query.answer("Отказано.")
        await query.edit_message_text(f"✖️ Отказано клиенту <code>{client_id}</code>.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("bot_error", exc_info=context.error)
