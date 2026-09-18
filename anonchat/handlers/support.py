"""Добровольная поддержка проекта через Telegram Stars."""

from __future__ import annotations

import secrets
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from .. import keyboards as K
from .. import texts
from ..actions import Ctx
from ..config import Config
from ..db import Database

router = Router(name="support")

MIN_STARS = 1
MAX_STARS = 10_000


class SupportStates(StatesGroup):
    amount = State()


async def ask_amount(ctx: Ctx, state: FSMContext, *, edit: bool) -> None:
    await state.set_state(SupportStates.amount)
    body = texts.SUPPORT_PROMPT.format(min_stars=MIN_STARS, max_stars=MAX_STARS)
    if edit and await ctx.edit(body, K.back_menu_keyboard()):
        return
    await ctx.reply(body, K.back_menu_keyboard())


@router.message(Command("support", "donate"))
async def cmd_support(message: Message, ctx: Ctx, state: FSMContext) -> None:
    await ask_amount(ctx, state, edit=False)


@router.callback_query(F.data == K.CB_SUPPORT)
async def cb_support(event: CallbackQuery, ctx: Ctx, state: FSMContext) -> None:
    await ask_amount(ctx, state, edit=True)
    await ctx.ack()


async def show_premium(ctx: Ctx, cfg: Config) -> None:
    row = await ctx.db.get_user(ctx.user_id)
    premium_until = int(row["premium_until"] or 0) if row else 0
    active = premium_until > int(time.time())
    status = (
        f"\n\nПодписка активна до <b>{time.strftime('%d.%m.%Y', time.localtime(premium_until))}</b>."
        if active else ""
    )
    body = (
        "<b>Подписка Holy Gram</b>\n\n"
        "✦ Стили общения в диалогах\n"
        "✦ Дополнительные возможности профиля\n"
        "✦ Поддержка проекта\n\n"
        f"<b>{cfg.premium_price_stars} ⭐ · {cfg.premium_days} дней</b>{status}"
    )
    if not await ctx.edit(body, K.premium_keyboard(active, cfg.premium_price_stars)):
        await ctx.reply(body, K.premium_keyboard(active, cfg.premium_price_stars))


@router.message(Command("premium", "plus"))
async def cmd_premium(message: Message, ctx: Ctx, cfg: Config) -> None:
    await show_premium(ctx, cfg)


@router.callback_query(F.data == K.CB_PREMIUM)
async def cb_premium(event: CallbackQuery, ctx: Ctx, cfg: Config) -> None:
    await show_premium(ctx, cfg)
    await ctx.ack()


@router.callback_query(F.data == "premium:buy")
async def cb_buy_premium(event: CallbackQuery, ctx: Ctx, cfg: Config) -> None:
    target = event.message
    if target is None:
        return
    await target.answer_invoice(
        title=f"Holy Gram · {cfg.premium_days} дней",
        description="Подписка Holy Gram со стилями общения.",
        payload=f"premium:{ctx.user_id}:{cfg.premium_days}:{secrets.token_hex(8)}",
        currency="XTR",
        prices=[LabeledPrice(label="Holy Gram", amount=cfg.premium_price_stars)],
        provider_token="",
    )
    await ctx.ack()


@router.message(SupportStates.amount, F.text, ~F.text.startswith("/"))
async def support_amount(message: Message, ctx: Ctx, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or not MIN_STARS <= int(raw) <= MAX_STARS:
        await ctx.reply(
            texts.SUPPORT_BAD_AMOUNT.format(min_stars=MIN_STARS, max_stars=MAX_STARS),
            K.back_menu_keyboard(),
        )
        return

    stars = int(raw)
    payload = f"support:{ctx.user_id}:{stars}:{secrets.token_hex(8)}"
    await state.clear()
    await message.answer_invoice(
        title=texts.SUPPORT_INVOICE_TITLE,
        description=texts.SUPPORT_INVOICE_DESCRIPTION,
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label="Поддержка проекта", amount=stars)],
        provider_token="",
    )


def _valid_payload(query: PreCheckoutQuery, cfg: Config | None = None) -> bool:
    parts = (query.invoice_payload or "").split(":")
    if len(parts) != 4 or parts[0] not in {"support", "premium"} or not parts[3]:
        return False
    try:
        user_id, value = int(parts[1]), int(parts[2])
    except ValueError:
        return False
    if user_id != query.from_user.id or query.currency != "XTR":
        return False
    if parts[0] == "support":
        return MIN_STARS <= value <= MAX_STARS and query.total_amount == value
    return bool(
        cfg and value == cfg.premium_days and query.total_amount == cfg.premium_price_stars
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, cfg: Config) -> None:
    if _valid_payload(query, cfg):
        await query.answer(ok=True)
        return
    await query.answer(ok=False, error_message="Счёт устарел. Создай новый в меню бота.")


@router.message(F.successful_payment)
async def successful_payment(message: Message, ctx: Ctx, cfg: Config, db: Database) -> None:
    payment = message.successful_payment
    if payment is None or payment.currency != "XTR" or not payment.telegram_payment_charge_id:
        await ctx.reply(texts.SUPPORT_PAYMENT_ERROR)
        return
    parts = (payment.invoice_payload or "").split(":")
    if len(parts) != 4 or parts[0] not in {"support", "premium"} or not parts[3]:
        await ctx.reply(texts.SUPPORT_PAYMENT_ERROR)
        return
    try:
        payload_user = int(parts[1])
        value = int(parts[2])
    except ValueError:
        await ctx.reply(texts.SUPPORT_PAYMENT_ERROR)
        return
    kind = parts[0]
    valid = payload_user == ctx.user_id and (
        (kind == "support" and value == payment.total_amount and MIN_STARS <= value <= MAX_STARS)
        or (
            kind == "premium"
            and value == cfg.premium_days
            and payment.total_amount == cfg.premium_price_stars
        )
    )
    if not valid:
        await ctx.reply(texts.SUPPORT_PAYMENT_ERROR)
        return
    created, result = await db.record_payment(
        ctx.user_id,
        kind,
        payment.total_amount,
        payment.telegram_payment_charge_id,
        payment.provider_payment_charge_id,
        payment.invoice_payload,
        cfg.premium_days if kind == "premium" else 0,
    )
    if not created:
        await ctx.reply("Этот платёж уже учтён.", K.menu_keyboard(ctx.mm.status(ctx.user_id)))
        return
    ctx.me = await db.get_user(ctx.user_id)
    if kind == "premium":
        until = time.strftime("%d.%m.%Y", time.localtime(result))
        await ctx.reply(f"Подписка Holy Gram активна до <b>{until}</b>.", K.menu_keyboard())
    else:
        await ctx.reply(
            texts.SUPPORT_THANKS.format(stars=payment.total_amount, total=result),
            K.menu_keyboard(ctx.mm.status(ctx.user_id)),
        )
