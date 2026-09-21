"""Пересылка сообщений между собеседниками — то, ради чего всё затевалось."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .. import keyboards as K
from .. import texts
from ..actions import (
    Ctx, DeliveryResult, edit_copied_message, send_copy_to,
    send_copy_to_message, send_to, show_menu,
)
from ..config import Config
from ..matching import Matchmaker

router = Router(name="chat")

# Только оперативная память: source(user_id, message_id) -> (partner_id, copied_message_id).
# В БД ничего не пишем; после рестарта старые сообщения просто перестанут синхронизироваться.
_RELAY_COPIES: dict[tuple[int, int], tuple[int, int]] = {}
_RELAY_COPY_LIMIT = 10_000


def _remember_copy(user_id: int, source_message_id: int, partner_id: int, copied_message_id: int) -> None:
    key = (int(user_id), int(source_message_id))
    _RELAY_COPIES[key] = (int(partner_id), int(copied_message_id))
    if len(_RELAY_COPIES) > _RELAY_COPY_LIMIT:
        for old_key in list(_RELAY_COPIES)[:2_000]:
            _RELAY_COPIES.pop(old_key, None)


@router.message(Command("helpcmd", "menu"))
async def cmd_menu(message: Message, ctx: Ctx, state: FSMContext) -> None:
    await state.clear()
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

    result = mm.count_message(ctx.user_id)
    if result is None:
        if mm.status(ctx.user_id) == "queued":
            mm.touch_queue(ctx.user_id)
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

    delivery, copied = await send_copy_to_message(ctx.bot, message, partner)
    if delivery is DeliveryResult.TEMP_ERROR:
        mm.uncount_message(ctx.user_id)
        await ctx.reply(texts.DELIVERY_TEMP_ERROR)
        return
    if delivery is DeliveryResult.UNAVAILABLE:
        mm.uncount_message(ctx.user_id)
        await ctx.db.close_battles_for_users(ctx.user_id, partner)
        mm.forget(ctx.user_id)
        await ctx.reply(
            texts.PARTNER_UNREACHABLE,
            markup=K.menu_keyboard(),
        )
        return
    if copied is not None:
        _remember_copy(ctx.user_id, message.message_id, partner, copied.message_id)
    if message.text:
        mm.record_text(ctx.user_id, message.text)
    await notify_chat_monitors(message, ctx, partner)
    # молча: человек знает, что написал в анонимный чат, подтверждений не просил


@router.edited_message(F.chat.type == "private")
async def relay_edited_message(
    message: Message, ctx: Ctx, cfg: Config, mm: Matchmaker
) -> None:
    """Обновляет уже отправленную анонимную копию после редактирования исходника."""
    if ctx.user_id == 0 or message.from_user is None:
        return

    target = _RELAY_COPIES.get((ctx.user_id, message.message_id))
    if target is None:
        return

    partner_id, copied_message_id = target
    if mm.partner(ctx.user_id) != partner_id:
        # После смены собеседника старые сообщения не трогаем.
        _RELAY_COPIES.pop((ctx.user_id, message.message_id), None)
        return

    body = message.text if message.text is not None else message.caption
    if body is not None and len(body) > cfg.max_message_len:
        await ctx.reply(texts.TOO_LONG.format(limit=cfg.max_message_len))
        return

    delivery = await edit_copied_message(
        ctx.bot, message, partner_id, copied_message_id
    )
    if delivery is DeliveryResult.DELIVERED:
        if message.text:
            mm.record_text(ctx.user_id, message.text)
        return

    if delivery is DeliveryResult.UNAVAILABLE:
        _RELAY_COPIES.pop((ctx.user_id, message.message_id), None)
        return

    # Если Telegram не дал отредактировать конкретный тип, отправляем актуальную
    # версию новым анонимным сообщением и дальше синхронизируем уже её.
    retry, copied = await send_copy_to_message(ctx.bot, message, partner_id)
    if retry is DeliveryResult.DELIVERED and copied is not None:
        _remember_copy(ctx.user_id, message.message_id, partner_id, copied.message_id)
    elif retry is DeliveryResult.TEMP_ERROR:
        await ctx.reply(texts.DELIVERY_TEMP_ERROR)


async def notify_chat_monitors(message: Message, ctx: Ctx, partner_id: int) -> None:
    """Копирует доставленное сообщение владельцам, включившим наблюдение в панели."""
    candidates = await ctx.db.admin_ids_with_permission("monitor", ctx.cfg.admin_ids)
    monitor_ids = [
        admin_id for admin_id in candidates
        if await ctx.db.get_kv(f"chat_monitor:{admin_id}") == "1"
    ]
    if not monitor_ids:
        return

    sender = ctx.me or await ctx.db.get_user(ctx.user_id)
    partner = await ctx.db.get_user(partner_id)

    def identity(row, user_id: int) -> str:
        username = f"@{row['username']}" if row and row["username"] else "без username"
        nickname = row["nickname"] if row and row["nickname"] else f"Аноним-{user_id}"
        return f"{texts.esc(username)} · {texts.esc(nickname)} · <code>{user_id}</code>"

    header = (
        "👁 <b>Сообщение в активном чате</b>\n"
        f"От: {identity(sender, ctx.user_id)}\n"
        f"Собеседник: {identity(partner, partner_id)}"
    )
    for admin_id in monitor_ids:
        if message.text:
            await send_to(
                ctx.bot, admin_id, f"{header}\n\n{texts.esc(message.text)}", None, ctx.pack
            )
        else:
            await send_to(ctx.bot, admin_id, header, None, ctx.pack)
            await send_copy_to(ctx.bot, message, admin_id)
