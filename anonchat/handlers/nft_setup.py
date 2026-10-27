"""Управление NFT-розыгрышем с платными билетами из чата владельца."""
from __future__ import annotations

import html
import time
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from ..actions import Ctx
from ..db import Database
from .nft_giveaway import _active, _keyboard, _message, _save_campaign, valid_nft_url

router = Router(name="nft_setup")


class NFTSetup(StatesGroup):
    link = State()
    deadline = State()


@router.message(Command("nft_setup"))
async def nft_admin_setup(message: Message, ctx: Ctx, state: FSMContext, db: Database) -> None:
    if not ctx.is_owner:
        return
    current = await _active(db)
    if current and current.close_at > time.time():
        await ctx.reply("Розыгрыш уже идёт. Следующий можно создать после окончания.")
        return
    await state.set_state(NFTSetup.link)
    await ctx.reply(
        "🎁 <b>Розыгрыш NFT</b>\n\n"
        "Пришли ссылку на NFT (https://...).\n"
        "Для отмены: /nft_cancel"
    )


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
        "<b>Розыгрыш создан!</b>\n\n" + html.escape(_message(giveaway))
        + "\n\nДля рассылки введи /nft_broadcast и подтверди отправку.",
        _keyboard(ctx.cfg.rollypay_enabled),
    )
