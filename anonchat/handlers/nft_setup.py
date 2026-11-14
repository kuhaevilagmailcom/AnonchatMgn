"""Управление NFT-розыгрышем с платными билетами из чата владельца."""
from __future__ import annotations

import html
import time
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import keyboards as K
from ..actions import Ctx
from ..db import Database
from .nft_giveaway import _active, _card, _keyboard, _save_campaign, valid_nft_url

router = Router(name="nft_setup")


class NFTSetup(StatesGroup):
    link = State()
    deadline = State()


async def _begin_setup(ctx: Ctx, state: FSMContext, db: Database) -> None:
    current = await _active(db)
    if current and current.close_at > time.time():
        await ctx.reply(
            "Розыгрыш уже идёт. Заверши его перед созданием нового.",
            K.admin_raffle_keyboard(),
        )
        return
    await state.set_state(NFTSetup.link)
    await ctx.reply(
        "<b>Новый розыгрыш</b>\n\nОтправь ссылку на NFT.",
        K.panel_cancel_keyboard(),
    )


@router.message(Command("nft_setup"))
async def nft_admin_setup(message: Message, ctx: Ctx, state: FSMContext, db: Database) -> None:
    if not ctx.is_owner:
        return
    await _begin_setup(ctx, state, db)


@router.callback_query(F.data == K.CB_ADMIN_RAFFLE)
async def nft_admin_hub(event: CallbackQuery, ctx: Ctx) -> None:
    if not ctx.is_owner:
        await ctx.ack("Нет доступа", alert=True)
        return
    await ctx.ack()
    body = "<b>NFT-розыгрыш</b>\n\nСоздание, публикация и итоги — в одном месте."
    if not await ctx.edit(body, K.admin_raffle_keyboard()):
        await ctx.reply(body, K.admin_raffle_keyboard())


@router.callback_query(F.data == "nft:admin:create")
async def nft_admin_create(
    event: CallbackQuery, ctx: Ctx, state: FSMContext, db: Database,
) -> None:
    if not ctx.is_owner:
        await ctx.ack("Нет доступа", alert=True)
        return
    await ctx.ack()
    await _begin_setup(ctx, state, db)


@router.callback_query(F.data.in_({
    "nft:admin:broadcast", "nft:admin:post", "nft:admin:stats", "nft:admin:finish",
}))
async def nft_admin_action(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    if not ctx.is_owner or event.message is None:
        await ctx.ack("Нет доступа", alert=True)
        return
    await ctx.ack()
    action = event.data or ""
    if action == "nft:admin:post":
        from .nft_channel import nft_post_preview
        await nft_post_preview(event.message, ctx, db)
    elif action == "nft:admin:broadcast":
        from .nft_giveaway import nft_broadcast_preview
        await nft_broadcast_preview(event.message, ctx, db)
    elif action == "nft:admin:stats":
        from .nft_giveaway import nft_admin_stats
        await nft_admin_stats(event.message, ctx, db)
    else:
        from .nft_giveaway import nft_finish_preview
        await nft_finish_preview(event.message, ctx, db)


@router.message(Command("nft_cancel"))
async def nft_admin_cancel(message: Message, ctx: Ctx, state: FSMContext) -> None:
    if not ctx.is_owner:
        return
    await state.clear()
    await ctx.reply("Настройка отменена.")


@router.message(NFTSetup.link, F.text, ~F.text.startswith("/"))
async def nft_setup_link(message: Message, ctx: Ctx, state: FSMContext) -> None:
    if not ctx.is_owner:
        return
    url = (message.text or "").strip()
    if not valid_nft_url(url):
        await ctx.reply("Отправь корректную ссылку на NFT, начинающуюся с https://")
        return
    await state.update_data(nft_url=url)
    await state.set_state(NFTSetup.deadline)
    await ctx.reply(
        "До какого числа можно участвовать?\n"
        "Например: <b>01.11.2026 20:00</b> (время Магнитогорска)."
    )


@router.message(NFTSetup.deadline, F.text, ~F.text.startswith("/"))
async def nft_setup_deadline(message: Message, ctx: Ctx, state: FSMContext, db: Database) -> None:
    if not ctx.is_owner:
        return
    try:
        date = datetime.strptime((message.text or "").strip(), "%d.%m.%Y %H:%M")
        date = date.replace(tzinfo=timezone(timedelta(hours=5)))
        if date.timestamp() <= time.time():
            raise ValueError("Past date")
    except ValueError:
        await ctx.reply("Введи будущую дату, например <b>01.11.2026 20:00</b> (МГН).")
        return
    data = await state.get_data()
    try:
        giveaway = await _save_campaign(
            db, str(data["nft_url"]),
            int(date.timestamp()), date.strftime("%d.%m.%Y %H:%M МГН"),
        )
    except (KeyError, ValueError) as exc:
        await state.clear()
        await ctx.reply("Не получилось создать розыгрыш: " + html.escape(str(exc)))
        return
    await state.clear()
    await ctx.reply(
        "<b>Розыгрыш создан!</b>\n\n" + await _card(ctx, db, giveaway)
        + "\n\nРассылку и публикацию запускай кнопками в NFT-разделе.",
        _keyboard(ctx.cfg.rollypay_enabled),
    )
