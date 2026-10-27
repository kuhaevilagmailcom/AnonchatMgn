"""Настройка бесплатного NFT-розыгрыша владельцем через личные сообщения боту."""
from __future__ import annotations

import html
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from ..actions import Ctx
from ..db import Database
from .nft_giveaway import _active, _keyboard, _message, _save_campaign

router = Router(name="nft_setup")


class NFTSetup(StatesGroup):
    prize = State()
    deadline = State()
    rules = State()


@router.message(Command("nft_setup"))
async def nft_admin_setup(message: Message, ctx: Ctx, state: FSMContext, db: Database) -> None:
    if not ctx.is_owner:
        return
    current = await _active(db)
    if current and current.close_at > time.time():
        await ctx.reply("Розыгрыш уже идёт. Следующий можно создать после завершения текущего.")
        return
    await state.set_state(NFTSetup.prize)
    await ctx.reply(
        "🎁 <b>Новый NFT-розыгрыш</b>\n\n"
        "Напиши название NFT, который разыгрываем.\n"
        "Отмена: /nft_cancel"
    )


@router.message(Command("nft_cancel"))
async def nft_admin_cancel(message: Message, ctx: Ctx, state: FSMContext) -> None:
    if not ctx.is_owner:
        return
    await state.clear()
    await ctx.reply("Настройка розыгрыша отменена.")


@router.message(NFTSetup.prize, F.text, ~F.text.startswith("/"))
async def nft_setup_prize(message: Message, ctx: Ctx, state: FSMContext) -> None:
    if not ctx.is_owner:
        return
    prize = (message.text or "").strip()
    if not 3 <= len(prize) <= 160:
        await ctx.reply("Название NFT должно содержать от 3 до 160 символов.")
        return
    await state.update_data(nft_prize=prize)
    await state.set_state(NFTSetup.deadline)
    await ctx.reply(
        "Когда заканчивается приём заявок?\n"
        "Отправь дату по Магнитогорску: <b>01.11.2026 20:00</b>"
    )


@router.message(NFTSetup.deadline, F.text, ~F.text.startswith("/"))
async def nft_setup_deadline(message: Message, ctx: Ctx, state: FSMContext) -> None:
    if not ctx.is_owner:
        return
    try:
        date = datetime.strptime((message.text or "").strip(), "%d.%m.%Y %H:%M")
        date = date.replace(tzinfo=timezone(timedelta(hours=5)))
        if date.timestamp() <= time.time():
            raise ValueError("Past date")
    except ValueError:
        await ctx.reply("Нужна будущая дата: <b>01.11.2026 20:00</b> (время МГН).")
        return
    await state.update_data(
        nft_close_at=int(date.timestamp()),
        nft_deadline=date.strftime("%d.%m.%Y %H:%M МГН"),
    )
    await state.set_state(NFTSetup.rules)
    await ctx.reply(
        "Пришли ссылку HTTPS на правила розыгрыша. "
        "В правилах укажи NFT, сроки, выбор победителя и получение приза."
    )


@router.message(NFTSetup.rules, F.text, ~F.text.startswith("/"))
async def nft_setup_rules(message: Message, ctx: Ctx, state: FSMContext, db: Database) -> None:
    if not ctx.is_owner:
        return
    url = (message.text or "").strip()
    parsed = urlsplit(url)
    if (len(url) > 1000 or parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password):
        await ctx.reply("Нужна ссылка с https:// на публичные правила.")
        return
    data = await state.get_data()
    try:
        g = await _save_campaign(
            db, str(data["nft_prize"]), int(data["nft_close_at"]),
            str(data["nft_deadline"]), url,
        )
    except (KeyError, ValueError) as exc:
        await state.clear()
        await ctx.reply("Не получилось создать розыгрыш: " + html.escape(str(exc)))
        return
    await state.clear()
    await ctx.reply(
        "<b>Розыгрыш создан</b>\n\n" + html.escape(_message(g))
        + "\n\nТеперь введи /nft_broadcast, посмотри рассылку и подтверди отправку.",
        _keyboard(),
    )
