"""Добровольная поддержка проекта через Telegram Stars."""

from __future__ import annotations

import secrets
import time
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from .. import keyboards as K
from .. import texts
from ..actions import Ctx, show_profile
from ..config import Config
from ..db import Database
from ..payments import RollyPayError, create_payment, get_payment

router = Router(name="support")

MIN_STARS = 1
MAX_STARS = 10_000


class SupportStates(StatesGroup):
    amount = State()


def _plus_active(row) -> bool:
    return bool(row and int(row["premium_until"] or 0) > int(time.time()))


async def show_anon_plus(ctx: Ctx, *, edit: bool = True) -> None:
    row = await ctx.db.get_user(ctx.user_id)
    active = _plus_active(row)
    until = (
        time.strftime("%d.%m.%Y", time.localtime(int(row["premium_until"])))
        if active else ""
    )
    badge = ctx.pack.profile_badge(str(row["anon_plus_emoji"] or "")) if active and row else ""
    body = (
        "💎 <b>Anonymous Plus</b>\n\n"
        + (f"Активен до <b>{until}</b>.\n\n" if active else "")
        + "<b>1. Оформление профиля</b>\n"
          "Выбирай темы Mini App и премиум-эмодзи из NewsEmoji рядом с ником.\n\n"
          "<b>2. Расширенная статистика</b>\n"
          "Диалоги, сообщения, игры и возраст без размытия.\n\n"
          "<b>3. Ник в диалогах</b>\n"
          "По желанию можешь показывать собеседнику свой ник и выбранный эмодзи. "
          "По умолчанию эта функция выключена.\n\n"
        + (f"Твой эмодзи: {badge}\n\n" if badge else "")
        + f"<b>{ctx.cfg.anon_plus_days} дней · "
          f"{ctx.cfg.anon_plus_price_rub} ₽ или "
          f"{ctx.cfg.anon_plus_price_stars} ⭐</b>"
    )
    kb = K.anonymous_plus_keyboard(
        active=active,
        price_stars=ctx.cfg.anon_plus_price_stars,
        price_rub=ctx.cfg.anon_plus_price_rub,
        sbp_enabled=ctx.cfg.rollypay_enabled,
    )
    if edit and await ctx.edit(body, kb):
        return
    await ctx.reply(body, kb)


@router.callback_query(F.data == K.CB_ANONPLUS)
async def cb_anon_plus(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack()
    await show_anon_plus(ctx)


@router.callback_query(F.data == K.CB_ANONPLUS_SHOW_NICK)
async def cb_anon_plus_show_nick(
    event: CallbackQuery, ctx: Ctx, db: Database
) -> None:
    row = await db.get_user(ctx.user_id)
    if not _plus_active(row):
        await ctx.ack("Настройка доступна только с Anonymous Plus", alert=True)
        await show_anon_plus(ctx)
        return
    enabled = not bool(row["anon_plus_show_nick"])
    await db.set_anon_plus_identity(ctx.user_id, show_nick=enabled)
    ctx.me = await db.get_user(ctx.user_id)
    await ctx.ack("Ник будет виден" if enabled else "Ник снова скрыт")
    await show_profile(ctx)


@router.callback_query(F.data == K.CB_ANONPLUS_STARS)
async def cb_anon_plus_stars(
    event: CallbackQuery, ctx: Ctx, cfg: Config
) -> None:
    await ctx.ack()
    payload = (
        f"anonplus:{ctx.user_id}:{int(cfg.anon_plus_price_stars)}:"
        f"{int(cfg.anon_plus_days)}:{secrets.token_hex(8)}"
    )
    await ctx.bot.send_invoice(
        chat_id=ctx.user_id,
        title="Anonymous Plus",
        description=(
            f"Anonymous Plus на {cfg.anon_plus_days} дней: "
            "темы, премиум-эмодзи и расширенная статистика"
        ),
        payload=payload,
        currency="XTR",
        prices=[
            LabeledPrice(
                label=f"Anonymous Plus · {cfg.anon_plus_days} дней",
                amount=int(cfg.anon_plus_price_stars),
            )
        ],
        provider_token="",
    )


@router.callback_query(F.data == K.CB_ANONPLUS_SBP)
async def cb_anon_plus_sbp(
    event: CallbackQuery, ctx: Ctx, cfg: Config, db: Database
) -> None:
    if not cfg.rollypay_enabled:
        await ctx.ack("СБП временно недоступна", alert=True)
        return
    await ctx.ack("Создаю платёж…")
    order_id = f"anonplus-bot-{ctx.user_id}-{secrets.token_hex(6)}"
    local_id = ""
    try:
        local_id = await db.create_sbp_order(
            order_id=order_id,
            user_id=ctx.user_id,
            kind="anonplus",
            amount_rub=int(cfg.anon_plus_price_rub),
            premium_days=int(cfg.anon_plus_days),
        )
        payment = await create_payment(
            cfg,
            order_id=order_id,
            amount=Decimal(int(cfg.anon_plus_price_rub)),
            description=f"АНОН МГН · Anonymous Plus на {cfg.anon_plus_days} дней",
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

    row = await db.get_user(ctx.user_id)
    await ctx.edit(
        "💳 <b>Anonymous Plus · СБП</b>\n\n"
        f"К оплате: <b>{cfg.anon_plus_price_rub} ₽</b>\n"
        "После оплаты нажми «Проверить оплату».",
        K.anonymous_plus_keyboard(
            active=_plus_active(row),
            price_stars=cfg.anon_plus_price_stars,
            price_rub=cfg.anon_plus_price_rub,
            sbp_enabled=True,
            payment_id=payment_id,
            pay_url=pay_url,
        ),
    )


@router.callback_query(F.data.startswith(K.CB_ANONPLUS_SBP_CHECK_PREFIX))
async def cb_anon_plus_sbp_check(
    event: CallbackQuery, ctx: Ctx, cfg: Config, db: Database
) -> None:
    payment_id = (event.data or "")[len(K.CB_ANONPLUS_SBP_CHECK_PREFIX):]
    local = await db.get_sbp_payment(payment_id)
    if not local or int(local["user_id"]) != ctx.user_id:
        await ctx.ack("Платёж не найден", alert=True)
        return
    if str(local["status"] or "").lower() == "paid":
        ctx.me = await db.get_user(ctx.user_id)
        await ctx.ack("Оплата уже подтверждена")
        await show_anon_plus(ctx)
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
    await ctx.ack("Anonymous Plus активирован")
    await show_anon_plus(ctx)


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


def _valid_payload(
    query: PreCheckoutQuery, cfg: Config | None = None
) -> bool:
    parts = (query.invoice_payload or "").split(":")
    if not parts:
        return False

    if parts[0] == "support":
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

    if parts[0] == "anonplus":
        if cfg is None:
            return False
        if len(parts) != 5 or not parts[4]:
            return False
        try:
            user_id, value, days = int(parts[1]), int(parts[2]), int(parts[3])
        except ValueError:
            return False
        return (
            user_id == query.from_user.id
            and query.currency == "XTR"
            and value == int(cfg.anon_plus_price_stars)
            and days == int(cfg.anon_plus_days)
            and query.total_amount == value
        )

    return False

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
    if not parts:
        await ctx.reply(texts.SUPPORT_PAYMENT_ERROR)
        return

    if parts[0] == "support":
        if len(parts) != 4 or not parts[3]:
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
        return

    if parts[0] == "anonplus":
        if len(parts) != 5 or not parts[4]:
            await ctx.reply(texts.SUPPORT_PAYMENT_ERROR)
            return
        try:
            payload_user = int(parts[1])
            value = int(parts[2])
            days = int(parts[3])
        except ValueError:
            await ctx.reply(texts.SUPPORT_PAYMENT_ERROR)
            return
        if not (
            payload_user == ctx.user_id
            and value == payment.total_amount == int(cfg.anon_plus_price_stars)
            and days == int(cfg.anon_plus_days)
        ):
            await ctx.reply(texts.SUPPORT_PAYMENT_ERROR)
            return

        try:
            created, premium_until = await db.record_anon_plus_payment(
                ctx.user_id,
                payment.total_amount,
                payment.telegram_payment_charge_id,
                payment.provider_payment_charge_id,
                payment.invoice_payload,
                days,
            )
        except ValueError:
            await ctx.reply("Не удалось активировать Anon+. Напиши в поддержку.")
            return

        if not created:
            await ctx.reply(
                "Этот платёж уже учтён.",
                K.menu_keyboard(ctx.mm.status(ctx.user_id)),
            )
            return

        ctx.me = await db.get_user(ctx.user_id)
        until = time.strftime("%d.%m.%Y", time.localtime(premium_until))
        await ctx.reply(
            "💎 <b>Anon+ активирован</b>\n\n"
            f"Доступ открыт на <b>{days} дней</b>.\n"
            f"Активен до <b>{until}</b>.\n\n"
            "Темы и расширенная статистика уже доступны в Mini App.",
            K.menu_keyboard(ctx.mm.status(ctx.user_id)),
        )
        return

    await ctx.reply(texts.SUPPORT_PAYMENT_ERROR)
