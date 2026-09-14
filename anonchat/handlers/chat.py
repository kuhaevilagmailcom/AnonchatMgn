"""Пересылка сообщений между собеседниками — то, ради чего всё затевалось."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from .. import keyboards as K
from .. import texts
from ..actions import Ctx, send_copy_to, show_menu
from ..config import Config
from ..db import Database
from ..matching import Matchmaker

router = Router(name="chat")

# что разрешено переправлять собеседнику
ALLOWED_TYPES = frozenset(
    {
        "text",
        "photo",
        "video",
        "audio",
        "document",
        "sticker",
        "animation",
        "voice",
        "video_note",
        "location",
        "poll",
        "dice",
    }
)


@router.message(Command("helpcmd", "menu"))
async def cmd_menu(message: Message, ctx: Ctx) -> None:
    await show_menu(ctx, edit=False)


@router.message(F.chat.type == "private")
async def relay_to_partner(message: Message, ctx: Ctx, cfg: Config, db: Database, mm: Matchmaker) -> None:
    """Ловим ВСЁ остальное в личке: если есть пара — отправляем копию собеседнику."""
    if ctx.user_id == 0 or message.from_user is None:
        return

    if message.text and message.text.startswith("/"):
        await ctx.reply(
            "🤖 Не знаю такой команды. Меню — <code>/start</code>, помощь — <code>/help</code>.",
            markup=K.menu_keyboard(cfg.emoji_pack_url, mm.status(ctx.user_id)),
        )
        return

    if await ctx.restricted():
        return

    if message.content_type not in ALLOWED_TYPES:
        await ctx.reply(
            "🚫 Такой тип сообщений анонимный чат не пересылает (контакты, ссылки-запросы и прочее "
            "могут выдать личность). Отправь текстом 🙂"
        )
        return

    result = mm.count_message(ctx.user_id)
    if result is None:
        await ctx.reply(
            texts.NO_DIALOG,
            markup=K.menu_keyboard(cfg.emoji_pack_url, mm.status(ctx.user_id)),
        )
        return

    partner, sent_count = result

    if len(message.text or "") > cfg.max_message_len:
        await ctx.reply(
            f"📏 Слишком длинно — больше {cfg.max_message_len} символов не отправляем. "
            "Разбей на пару сообщений, собеседнику так только легче."
        )
        mm.uncount_message(ctx.user_id)
        return

    if not await send_copy_to(ctx.bot, message, partner):
        # собеседник заблокировал бота / аккаунт удалён — расцепляем пару
        mm.uncount_message(ctx.user_id)
        mm.forget(ctx.user_id)
        await ctx.reply(
            "👋 Собеседник недоступен — диалог закрыт. Нажми <b>🔎 Поиск собеседника</b>, чтобы найти нового.",
            markup=K.menu_keyboard(cfg.emoji_pack_url),
        )
        return

    if sent_count == 1:
        await ctx.reply("🤫 Первое сообщение ушло анонимно: никто не видит ни ник, ни аватарку.")
