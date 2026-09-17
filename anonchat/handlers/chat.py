"""Пересылка сообщений между собеседниками — то, ради чего всё затевалось."""

from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import keyboards as K
from .. import texts
from ..actions import Ctx, DeliveryResult, send_copy_to, send_to, show_menu
from ..config import Config
from ..matching import Matchmaker
from ..safety import contains_contact

router = Router(name="chat")

CONTACT_RE = re.compile(r"^(?:@[A-Za-z0-9_]{5,32}|https?://(?:t\.me|telegram\.me)/[A-Za-z0-9_/?=&-]+|(?:t\.me|telegram\.me)/[A-Za-z0-9_/?=&-]+)$", re.I)
CONTACT_IN_TEXT_RE = re.compile(r"(?:@[A-Za-z0-9_]{5,32}|(?:https?://)?(?:t\.me|telegram\.me)/\S+)", re.I)


class ContactStates(StatesGroup):
    confirm = State()

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
async def cmd_menu(message: Message, ctx: Ctx, state: FSMContext) -> None:
    await state.clear()
    await show_menu(ctx)


@router.message(Command("send", "user"))
async def cmd_send_contact(
    message: Message, ctx: Ctx, mm: Matchmaker, state: FSMContext
) -> None:
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
    if not CONTACT_RE.fullmatch(value):
        await ctx.reply("Можно отправить только @username или ссылку t.me/…")
        return
    await state.set_state(ContactStates.confirm)
    await state.set_data({"value": value, "partner": partner})
    await ctx.reply(
        "Ты собираешься поделиться контактом.\n\nПосле этого собеседник сможет написать тебе вне бота.",
        K.contact_confirm_keyboard(),
    )


@router.callback_query(ContactStates.confirm, F.data == "contact:send")
async def cb_send_contact(
    event: CallbackQuery, ctx: Ctx, mm: Matchmaker, state: FSMContext
) -> None:
    data = await state.get_data()
    value = str(data.get("value", ""))
    partner = int(data.get("partner", 0))
    await state.clear()
    if not value or not mm.is_paired_with(ctx.user_id, partner):
        await ctx.ack("Диалог уже завершён", alert=True)
        return
    result = await send_to(ctx.bot, partner, texts.esc(value), None, ctx.pack)
    if result is DeliveryResult.TEMP_ERROR:
        await ctx.reply(texts.DELIVERY_TEMP_ERROR)
        return
    if result is DeliveryResult.UNAVAILABLE:
        mm.forget(ctx.user_id)
        await ctx.reply(texts.PARTNER_UNREACHABLE, markup=K.menu_keyboard())
        return
    mm.record_text(ctx.user_id, value)
    await ctx.ack("Отправлено")


@router.callback_query(ContactStates.confirm, F.data == "contact:cancel")
async def cb_cancel_contact(event: CallbackQuery, ctx: Ctx, state: FSMContext) -> None:
    await state.clear()
    await ctx.ack("Отменено")
    await show_menu(ctx)


@router.message(F.chat.type == "private")
async def relay_to_partner(
    message: Message, ctx: Ctx, cfg: Config, mm: Matchmaker
) -> None:
    """Ловим ВСЁ остальное в личке: если есть пара — отправляем копию собеседнику."""
    if ctx.user_id == 0 or message.from_user is None:
        return

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
    if payload_text and (contains_contact(payload_text) or CONTACT_IN_TEXT_RE.search(payload_text)):
        await ctx.reply(texts.CONTACT_BLOCKED)
        return

    result = mm.count_message(ctx.user_id)
    if result is None:
        if mm.status(ctx.user_id) == "queued":
            await ctx.reply(texts.QUEUED_MESSAGE, markup=K.menu_keyboard("queued"))
            return
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

    delivery = await send_copy_to(ctx.bot, message, partner)
    if delivery is DeliveryResult.TEMP_ERROR:
        mm.uncount_message(ctx.user_id)
        await ctx.reply(texts.DELIVERY_TEMP_ERROR)
        return
    if delivery is DeliveryResult.UNAVAILABLE:
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
