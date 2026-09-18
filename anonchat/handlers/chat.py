"""Пересылка сообщений между собеседниками — то, ради чего всё затевалось."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .. import keyboards as K
from .. import texts
from ..actions import Ctx, DeliveryResult, send_copy_to, send_to, show_menu
from ..config import Config
from ..matching import Matchmaker
from ..message_styles import transform_message_style

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
        "contact",
    }
)


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

    if message.content_type not in ALLOWED_TYPES:
        await ctx.reply(texts.UNKNOWN_TYPE)
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

    source_text = message.text if message.text is not None else message.caption
    if len(source_text or "") > cfg.max_message_len:
        await ctx.reply(texts.TOO_LONG.format(limit=cfg.max_message_len))
        mm.uncount_message(ctx.user_id)
        return

    final_text = (
        await transform_message_style(
            ctx.db,
            ctx.user_id,
            source_text,
            max_length=4096 if message.text is not None else 1024,
        )
        if source_text is not None else None
    )
    delivery = await send_copy_to(ctx.bot, message, partner, final_text)
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
    if final_text:
        mm.record_text(ctx.user_id, final_text)
    await notify_chat_monitors(message, ctx, partner, final_text)
    # молча: человек знает, что написал в анонимный чат, подтверждений не просил


async def notify_chat_monitors(
    message: Message, ctx: Ctx, partner_id: int, delivered_text: str | None = None
) -> None:
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
        if message.text is not None:
            await send_to(
                ctx.bot, admin_id, f"{header}\n\n{texts.esc(delivered_text or message.text)}", None, ctx.pack
            )
        else:
            await send_to(ctx.bot, admin_id, header, None, ctx.pack)
            await send_copy_to(ctx.bot, message, admin_id, delivered_text)
