"""Owner-only manual NFT result announcement in the owner's chat."""
from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..actions import Ctx
from ..db import Database

router = Router(name="nft_win")


class NFTManualResult(StatesGroup):
    user_id = State()
    tickets = State()


def format_manual_win(user_id: int, tickets: int) -> str:
    return (
        "🏆 <b>Розыгрыш завершён!</b>\n\n"
        f"Победитель: ID <code>{int(user_id)}</code>\n"
        f"Билетов у победителя: <b>{int(tickets)}</b>\n\n"
        "<i>Ручной итог администратора.</i>"
    )


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Подтвердить итог", callback_data="nft:manual:confirm",
        )],
        [InlineKeyboardButton(text="Отмена", callback_data="nft:manual:cancel")],
    ])


@router.callback_query(F.data == "nft:admin:manual_result")
async def nft_manual_start(
    event: CallbackQuery, ctx: Ctx, state: FSMContext,
) -> None:
    if not ctx.is_owner or not event.message or event.message.chat.type != "private":
        await ctx.ack("Нет доступа", alert=True)
        return
    await state.set_state(NFTManualResult.user_id)
    await ctx.ack()
    await ctx.reply("<b>Ручной итог</b>\n\nОтправь Telegram ID победителя.")


@router.message(NFTManualResult.user_id, F.text, ~F.text.startswith("/"))
async def nft_manual_user_id(
    message: Message, ctx: Ctx, state: FSMContext, db: Database,
) -> None:
    value = (message.text or "").strip()
    if not ctx.is_owner or not re.fullmatch(r"[1-9][0-9]{0,18}", value):
        await ctx.reply("Отправь корректный Telegram ID цифрами.")
        return
    if not await db.get_user(int(value)):
        await ctx.reply("Пользователь с таким ID не найден в базе бота.")
        return
    await state.update_data(user_id=int(value))
    await state.set_state(NFTManualResult.tickets)
    await ctx.reply("Сколько билетов было у победителя? Отправь число от 1 до 999999.")


@router.message(NFTManualResult.tickets, F.text, ~F.text.startswith("/"))
async def nft_manual_tickets(message: Message, ctx: Ctx, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not ctx.is_owner or not re.fullmatch(r"[1-9][0-9]{0,5}", value):
        await ctx.reply("Отправь количество билетов числом от 1 до 999999.")
        return
    await state.update_data(tickets=int(value))
    data = await state.get_data()
    await ctx.reply(
        "<b>Проверь итог перед подтверждением</b>\n\n"
        + format_manual_win(int(data["user_id"]), int(value)),
        _confirm_keyboard(),
    )


@router.callback_query(F.data.in_({"nft:manual:confirm", "nft:manual:cancel"}))
async def nft_manual_action(
    event: CallbackQuery, ctx: Ctx, state: FSMContext,
) -> None:
    if not ctx.is_owner:
        await ctx.ack("Нет доступа", alert=True)
        return
    if event.data == "nft:manual:cancel":
        await state.clear()
        await ctx.ack("Отменено")
        await ctx.edit("Ручной итог отменён.")
        return
    data = await state.get_data()
    user_id, tickets = int(data.get("user_id", 0)), int(data.get("tickets", 0))
    if user_id <= 0 or tickets <= 0:
        await state.clear()
        await ctx.ack("Данные устарели. Начни заново.", alert=True)
        return
    await state.clear()
    await ctx.ack("Итог готов")
    await ctx.edit(format_manual_win(user_id, tickets))


@router.message(Command("win"))
async def nft_manual_win(message: Message, ctx: Ctx) -> None:
    if not ctx.is_owner or message.chat.type != "private":
        return
    raw = (message.text or "").strip().split()
    if (
        len(raw) != 3
        or not re.fullmatch(r"[1-9][0-9]{0,18}", raw[1])
        or not re.fullmatch(r"[1-9][0-9]{0,5}", raw[2])
    ):
        await ctx.reply(
            "Укажи ID и количество билетов. Пример: <code>/win 123456789 5</code>"
        )
        return
    await ctx.reply(format_manual_win(int(raw[1]), int(raw[2])))
