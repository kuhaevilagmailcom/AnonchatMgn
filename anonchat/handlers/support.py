"""Добровольная поддержка проекта через Telegram Stars."""

from __future__ import annotations

import secrets
from decimal import Decimal, InvalidOperation

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
from ..payments import RollyPayError, create_payment, get_payment

router = Router(name="support")

MIN_STARS = 1
MAX_STARS = 10_000
MIN_RUB = 1
MAX_RUB = 1_000_000_000


class SupportStates(StatesGroup):
    amount = State()


async def show_support_methods(ctx: Ctx, state: FSMContext, *, edit: bool) -> None:
    await state.clear()
    body = (
        "💖 <b>Поддержать проект</b>\n\n"
        "Выбери способ поддержки. После этого введёшь сумму."
    )
    kb = K.support_method_keyboard(sbp_enabled=ctx.cfg.rollypay_enabled)
    if edit and await ctx.edit(body, kb):
        return
    await ctx.reply(body, kb)


async def ask_support_amount(
    ctx: Ctx, state: FSMContext, *, method: str, edit: bool
) -> None:
    await state.set_state(SupportStates.amount)
    await state.update_data(method=method)
    if method == "rub":
        body = (
            "💳 <b>Поддержать рублями</b>\n\n"
            "Введи сумму от <b>1 ₽</b>. Например: <code>100</code>."
        )
    else:
        body = (
            "⭐ <b>Поддержать Stars</b>\n\n"
            f"Введи количество звёзд от <b>{MIN_STARS}</b> до <b>{MAX_STARS}</b>."
        )
    if edit and await ctx.edit(body, K.back_menu_keyboard()):
        return
    await ctx.reply(body, K.back_menu_keyboard())


@router.message(Command("support", "donate"))
async def cmd_support(message: Message, ctx: Ctx, state: FSMContext) -> None:
    await show_support_methods(ctx, state, edit=False)


@router.callback_query(F.data == K.CB_SUPPORT)
async def cb_support(event: CallbackQuery, ctx: Ctx, state: FSMContext) -> None:
    await ctx.ack()
    await show_support_methods(ctx, state, edit=True)


@router.callback_query(F.data == K.CB_SUPPORT_STARS)
async def cb_support_stars(event: CallbackQuery, ctx: Ctx, state: FSMContext) -> None:
    await ctx.ack()
    await ask_support_amount(ctx, state, method="stars", edit=True)


@router.callback_query(F.data == K.CB_SUPPORT_RUB)
async def cb_support_rub(event: CallbackQuery, ctx: Ctx, state: FSMContext) -> None:
    if not ctx.cfg.rollypay_enabled:
        await ctx.ack("СБП временно недоступна", alert=True)
        return
    await ctx.ack()
    await ask_support_amount(ctx, state, method="rub", edit=True)


@router.message(SupportStates.amount, F.text, ~F.text.startswith("/"))
async def support_amount(
    message: Message, ctx: Ctx, state: FSMContext, db: Database
) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await ctx.reply("Введи сумму целым числом.", K.back_menu_keyboard())
        return

    amount = int(raw)
    data = await state.get_data()
    method = str(data.get("method") or "stars")

    if method == "stars":
        if not MIN_STARS <= amount <= MAX_STARS:
            await ctx.reply(
                texts.SUPPORT_BAD_AMOUNT.format(
                    min_stars=MIN_STARS, max_stars=MAX_STARS
                ),
                K.back_menu_keyboard(),
            )
            return
        payload = f"support:{ctx.user_id}:{amount}:{secrets.token_hex(8)}"
        await state.clear()
        await message.answer_invoice(
            title=texts.SUPPORT_INVOICE_TITLE,
            description=texts.SUPPORT_INVOICE_DESCRIPTION,
            payload=payload,
            currency="XTR",
            prices=[LabeledPrice(label="Поддержка проекта", amount=amount)],
            provider_token="",
        )
        return

    if amount < MIN_RUB or amount > MAX_RUB:
        await ctx.reply("Минимальная сумма — 1 ₽.", K.back_menu_keyboard())
        return
    if not ctx.cfg.rollypay_enabled:
        await state.clear()
        await ctx.reply("СБП временно недоступна.")
        return

    order_id = f"support-bot-{ctx.user_id}-{secrets.token_hex(6)}"
    local_id = ""
    try:
        local_id = await db.create_sbp_order(
            order_id=order_id,
            user_id=ctx.user_id,
            kind="support",
            amount_rub=amount,
            premium_days=0,
        )
        payment = await create_payment(
            ctx.cfg,
            order_id=order_id,
            amount=Decimal(amount),
            description="АНОН МГН · Поддержка проекта",
            user_id=ctx.user_id,
        )
        payment_id = str(payment["payment_id"])
        pay_url = str(payment["pay_url"])
        await db.attach_sbp_provider_payment(local_id, payment_id, pay_url)
    except (RollyPayError, KeyError, ValueError):
        if local_id:
            try:
                await db.set_sbp_status(local_id, "create_failed")
            except Exception:
                pass
        await ctx.reply("Не удалось создать платёж СБП. Попробуй позже.")
        return

    await state.clear()
    await ctx.reply(
        "💳 <b>Поддержка проекта</b>\n\n"
        f"К оплате: <b>{amount} ₽</b>.",
        K.support_sbp_keyboard(payment_id, pay_url, amount),
    )


@router.callback_query(F.data.startswith(K.CB_SUPPORT_SBP_CHECK_PREFIX))
async def cb_support_sbp_check(
    event: CallbackQuery, ctx: Ctx, cfg: Config, db: Database
) -> None:
    payment_id = (event.data or "")[len(K.CB_SUPPORT_SBP_CHECK_PREFIX):]
    local = await db.get_sbp_payment(payment_id)
    if not local or int(local["user_id"]) != ctx.user_id or str(local["kind"]) != "support":
        await ctx.ack("Платёж не найден", alert=True)
        return
    if str(local["status"] or "").lower() == "paid":
        await ctx.ack("Платёж уже учтён")
        return

    try:
        remote = await get_payment(cfg, payment_id)
    except RollyPayError:
        await ctx.ack("Не удалось проверить платёж", alert=True)
        return

    try:
        remote_amount = Decimal(str(remote.get("amount")))
    except (InvalidOperation, ValueError):
        remote_amount = Decimal("-1")
    matches = (
        str(remote.get("payment_id") or "") == payment_id
        and str(remote.get("order_id") or "") == str(local["order_id"])
        and str(remote.get("currency") or remote.get("payment_currency") or "").upper() == "RUB"
        and remote_amount.is_finite()
        and remote_amount == Decimal(int(local["amount_rub"]))
    )
    if not matches:
        await ctx.ack("Данные платежа не совпали", alert=True)
        return

    status = str(remote.get("status") or "").lower()
    if status != "paid":
        await db.set_sbp_status(payment_id, status or "pending")
        await ctx.ack("Платёж пока не подтверждён", alert=True)
        return

    await db.settle_sbp_payment(payment_id)
    ctx.me = await db.get_user(ctx.user_id)
    await ctx.ack("Спасибо за поддержку!")
    await ctx.reply(
        "💖 <b>Спасибо за поддержку АНОН МГН!</b>\n\n"
        f"Получено: <b>{int(local['amount_rub'])} ₽</b>.",
        K.menu_keyboard(ctx.mm.status(ctx.user_id)),
    )


def _valid_payload(query: PreCheckoutQuery, cfg: Config | None = None) -> bool:
    parts = (query.invoice_payload or "").split(":")
    if not parts or parts[0] != "support":
        return False
    if len(parts) != 4 or not parts[3]:
        return False
    try:
        user_id, value = int(parts[1]), int(parts[2])
    except ValueError:
        return False
    return (
        user_id == query.from_user.id
        and query.currency == "XTR"
        and MIN_STARS <= value <= MAX_STARS
        and query.total_amount == value
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, cfg: Config) -> None:
    if _valid_payload(query, cfg):
        await query.answer(ok=True)
        return
    await query.answer(ok=False, error_message="Счёт устарел. Создай новый в меню бота.")


@router.message(F.successful_payment)
async def successful_payment(
    message: Message, ctx: Ctx, db: Database, cfg: Config
) -> None:
    payment = message.successful_payment
    if (
        payment is None
        or payment.currency != "XTR"
        or not payment.telegram_payment_charge_id
    ):
        await ctx.reply(texts.SUPPORT_PAYMENT_ERROR)
        return

    parts = (payment.invoice_payload or "").split(":")
    if len(parts) != 4 or parts[0] != "support" or not parts[3]:
        await ctx.reply(texts.SUPPORT_PAYMENT_ERROR)
        return

    try:
        payload_user = int(parts[1])
        value = int(parts[2])
    except ValueError:
        await ctx.reply(texts.SUPPORT_PAYMENT_ERROR)
        return

    if not (
        payload_user == ctx.user_id
        and value == payment.total_amount
        and MIN_STARS <= value <= MAX_STARS
    ):
        await ctx.reply(texts.SUPPORT_PAYMENT_ERROR)
        return

    created, support_total = await db.record_payment(
        ctx.user_id,
        "support",
        payment.total_amount,
        payment.telegram_payment_charge_id,
        payment.provider_payment_charge_id,
        payment.invoice_payload,
    )
    if not created:
        await ctx.reply(
            "Этот платёж уже учтён.",
            K.menu_keyboard(ctx.mm.status(ctx.user_id)),
        )
        return

    ctx.me = await db.get_user(ctx.user_id)
    await ctx.reply(
        texts.SUPPORT_THANKS.format(
            stars=payment.total_amount, total=support_total
        ),
        K.menu_keyboard(ctx.mm.status(ctx.user_id)),
    )

