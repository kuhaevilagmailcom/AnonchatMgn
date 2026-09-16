"""Пересылка сообщений между собеседниками — то, ради чего всё затевалось."""

from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from .. import keyboards as K
from .. import texts
from ..actions import Ctx, send_copy_to, send_to, show_menu
from ..config import Config
from ..db import Database
from ..matching import Matchmaker
from ..pack import EmojiPack
from ..safety import contains_contact

router = Router(name="chat")

# что разрешено переправлять собеседнику
ALLOWED_TYPES = frozenset(
    {
        "text",
        "photo",
        "video",
        "audio",
        "sticker",
        "animation",
        "voice",
        "video_note",
        "poll",
        "dice",
    }
)


@router.message(Command("helpcmd", "menu"))
async def cmd_menu(message: Message, ctx: Ctx) -> None:
    await show_menu(ctx, edit=False)


@router.message(Command("send", "user"))
async def cmd_send_contact(message: Message, ctx: Ctx, cfg: Config, mm: Matchmaker) -> None:
    """Явно отправляет собеседнику username/ссылку, не пересылая саму команду."""
    if await ctx.restricted():
        return
    partner = mm.partner(ctx.user_id)
    if partner is None:
        await ctx.reply(texts.NO_DIALOG, markup=K.menu_keyboard(mm.status(ctx.user_id)))
        return
    value = (message.text or "").partition(" ")[2].strip()
    if not value:
        await ctx.reply(texts.SEND_EMPTY)
        return
    if len(value) > cfg.max_message_len:
        await ctx.reply(texts.TOO_LONG.format(limit=cfg.max_message_len))
        return
    if not await send_to(ctx.bot, partner, value, None, ctx.pack):
        mm.forget(ctx.user_id)
        await ctx.reply(texts.PARTNER_UNREACHABLE, markup=K.menu_keyboard())
        return
    mm.record_text(ctx.user_id, value)


@router.message(F.chat.type == "private")
async def relay_to_partner(
    message: Message, ctx: Ctx, cfg: Config, db: Database, mm: Matchmaker, pack: EmojiPack
) -> None:
    """Ловим ВСЁ остальное в личке: если есть пара — отправляем копию собеседнику."""
    if ctx.user_id == 0 or message.from_user is None:
        return

    # пользователь прислал эмодзи из пака — запоминаем id, чтобы бот тоже мог им пользоваться
    if pack.harvest(message):
        await db.set_kv("emoji_ids", json.dumps(pack.as_pairs(), ensure_ascii=False))

    if message.text and message.text.startswith("/"):
        await ctx.reply(
            texts.UNKNOWN_COMMAND,
            markup=K.menu_keyboard(mm.status(ctx.user_id)),
        )
        return

    if await ctx.restricted():
        return

    if message.content_type not in ALLOWED_TYPES:
        await ctx.reply(texts.UNKNOWN_TYPE)
        return

    payload_text = (message.text or message.caption or "").strip()
    if payload_text and contains_contact(payload_text):
        await ctx.reply(texts.CONTACT_BLOCKED)
        return

    result = mm.count_message(ctx.user_id)
    if result is None:
        await ctx.reply(
            texts.NO_DIALOG,
            markup=K.menu_keyboard(mm.status(ctx.user_id)),
        )
        return

    partner, _sent = result

    if len(message.text or "") > cfg.max_message_len:
        await ctx.reply(texts.TOO_LONG.format(limit=cfg.max_message_len))
        mm.uncount_message(ctx.user_id)
        return

    if not await send_copy_to(ctx.bot, message, partner):
        # собеседник заблокировал бота / аккаунт удалён — расцепляем пару
        mm.uncount_message(ctx.user_id)
        mm.forget(ctx.user_id)
        await ctx.reply(
            texts.PARTNER_UNREACHABLE,
            markup=K.menu_keyboard(),
        )
        return
    if message.text:
        mm.record_text(ctx.user_id, message.text)
    # молча: человек знает, что написал в анонимный чат, подтверждений не просил
