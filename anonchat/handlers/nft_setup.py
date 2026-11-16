"""Управление NFT-розыгрышем с платными билетами из чата владельца."""
from __future__ import annotations

import html
import re
import time
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .. import keyboards as K
from ..actions import Ctx
from ..db import Database
from .nft_giveaway import (
    _active, _card, _keyboard, _save_campaign, _update_active_campaign,
    valid_nft_url,
)

router = Router(name="nft_setup")


class NFTSetup(StatesGroup):
    link = State()
    deadline = State()


class NFTEdit(StatesGroup):
    price = State()
    deadline = State()


def _parse_mgn_date(text: str) -> tuple[int, str]:
    try:
        date = datetime.strptime(text.strip(), "%d.%m.%Y %H:%M")
        date = date.replace(tzinfo=timezone(timedelta(hours=5)))
        if date.timestamp() <= time.time():
            raise ValueError("Past date")
    except ValueError:
        raise ValueError("Нужна будущая дата в формате ДД.ММ.ГГГГ ЧЧ:ММ (МГН).")
    return int(date.timestamp()), date.strftime("%d.%m.%Y %H:%M МГН")


def _command_arg(message: Message) -> str:
    parts = (message.text or "").strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


async def _notify_changed(ctx: Ctx, db: Database, what: str) -> None:
    g = await _active(db)
    await ctx.reply(
        f"<b>{html.escape(what)}</b>\n\n"
        + f"Цена: <b>{g.price_rub} ₽</b>\n"
        + f"Окончание: <b>{html.escape(g.deadline)}</b>\n\n"
        + "Ранее выставленные счета сохраняют свою сумму.",
        K.admin_raffle_keyboard(),
    )
    # Refresh already published messages now; the normal worker retries later.
    try:
        from ..nft_channel_live import refresh_campaign_posts
        await refresh_campaign_posts(ctx.bot, db)
    except Exception:
        pass


async def _apply_price(ctx: Ctx, db: Database, raw: str) -> bool:
    if not re.fullmatch(r"[0-9]{1,5}", raw.strip()):
        await ctx.reply("Введи цену целым числом от 1 до 10000 ₽.")
        return False
    try:
        price = int(raw.strip())
        await _update_active_campaign(db, price_rub=price)
    except ValueError as exc:
        await ctx.reply(html.escape(str(exc)))
        return False
    await _notify_changed(ctx, db, "Цена билета изменена")
    return True


async def _apply_deadline(ctx: Ctx, db: Database, raw: str) -> bool:
    try:
        close_at, deadline = _parse_mgn_date(raw)
        await _update_active_campaign(db, close_at=close_at, deadline=deadline)
    except ValueError as exc:
        await ctx.reply(html.escape(str(exc)))
        return False
    await _notify_changed(ctx, db, "Дата окончания изменена")
    return True


async def _begin_setup(ctx: Ctx, state: FSMContext, db: Database) -> None:
    current = await _active(db)
    if current and current.close_at > time.time():
        await ctx.reply(
            "Розыгрыш уже идёт. Цена и дата меняются в NFT-панели; "
            "для создания нового сначала заверши текущий.",
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
async def nft_admin_hub(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    if not ctx.is_owner:
        await ctx.ack("Нет доступа", alert=True)
        return
    await ctx.ack()
    body = "<b>NFT-розыгрыш</b>\n\nСоздание, публикация и итоги — в одном месте."
    g = await _active(db)
    if g and g.close_at > time.time():
        body += (f"\n\nБилет: <b>{g.price_rub} ₽</b>"
                 f"\nОкончание: <b>{html.escape(g.deadline)}</b>")
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



@router.callback_query(F.data.in_({"nft:admin:price", "nft:admin:date"}))
async def nft_admin_edit_prompt(
    event: CallbackQuery, ctx: Ctx, state: FSMContext, db: Database,
) -> None:
    if not ctx.is_owner:
        await ctx.ack("Нет доступа", alert=True)
        return
    await ctx.ack()
    g = await _active(db)
    if not g or g.close_at <= time.time():
        await ctx.reply("Нет активного розыгрыша для изменения.")
        return
    if event.data == "nft:admin:price":
        await state.set_state(NFTEdit.price)
        prompt = (f"<b>Новая цена билета</b>\n\nСейчас: {g.price_rub} ₽. "
                  "Отправь целое число от 1 до 10000.")
    else:
        await state.set_state(NFTEdit.deadline)
        prompt = (f"<b>Новая дата окончания</b>\n\nСейчас: "
                  f"{html.escape(g.deadline)}.\n"
                  "Отправь дату, например <b>30.11.2026 20:00</b> (МГН).")
    await ctx.reply(prompt, InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Отмена", callback_data="nft:admin:edit_cancel")
    ]]))


@router.callback_query(F.data == "nft:admin:edit_cancel")
async def nft_admin_edit_cancel(
    event: CallbackQuery, ctx: Ctx, state: FSMContext,
) -> None:
    if not ctx.is_owner:
        await ctx.ack("Нет доступа", alert=True)
        return
    await state.clear()
    await ctx.ack("Отменено")
    await ctx.reply("Изменение отменено.", K.admin_raffle_keyboard())


@router.message(Command("nft_price"))
async def nft_admin_price_command(
    message: Message, ctx: Ctx, state: FSMContext, db: Database,
) -> None:
    if not ctx.is_owner:
        return
    raw = _command_arg(message)
    if raw:
        if await _apply_price(ctx, db, raw):
            await state.clear()
    else:
        g = await _active(db)
        if not g or g.close_at <= time.time():
            await ctx.reply("Нет активного розыгрыша для изменения.")
            return
        await state.set_state(NFTEdit.price)
        await ctx.reply(f"Цена сейчас {g.price_rub} ₽. Отправь новую сумму от 1 до 10000.")


@router.message(Command("nft_date"))
async def nft_admin_date_command(
    message: Message, ctx: Ctx, state: FSMContext, db: Database,
) -> None:
    if not ctx.is_owner:
        return
    raw = _command_arg(message)
    if raw:
        if await _apply_deadline(ctx, db, raw):
            await state.clear()
    else:
        g = await _active(db)
        if not g or g.close_at <= time.time():
            await ctx.reply("Нет активного розыгрыша для изменения.")
            return
        await state.set_state(NFTEdit.deadline)
        await ctx.reply(
            f"Окончание сейчас {html.escape(g.deadline)}. "
            "Отправь новую дату ДД.ММ.ГГГГ ЧЧ:ММ по Магнитогорску."
        )


@router.message(NFTEdit.price, F.text, ~F.text.startswith("/"))
async def nft_admin_price_value(
    message: Message, ctx: Ctx, state: FSMContext, db: Database,
) -> None:
    if ctx.is_owner and await _apply_price(ctx, db, message.text or ""):
        await state.clear()


@router.message(NFTEdit.deadline, F.text, ~F.text.startswith("/"))
async def nft_admin_date_value(
    message: Message, ctx: Ctx, state: FSMContext, db: Database,
) -> None:
    if ctx.is_owner and await _apply_deadline(ctx, db, message.text or ""):
        await state.clear()
