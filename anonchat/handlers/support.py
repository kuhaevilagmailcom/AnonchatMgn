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
from ..pack import PROFILE_BADGES

router = Router(name="support")

MIN_STARS = 1
MAX_STARS = 10_000
MIN_RUB = 1
MAX_RUB = 1_000_000_000


class SupportStates(StatesGroup):
    amount = State()


def _plus_active(row) -> bool:
    return bool(row and int(row["premium_until"] or 0) > int(time.time()))


async def show_anon_plus(ctx: Ctx, *, edit: bool = True) -> None:
    row = await ctx.db.get_user(ctx.user_id)
    active = _plus_active(row)
    body = (
        "💎 <b>Анон Plus</b>\n\n"
        + ("<b>Активирован навсегда.</b>\n\n" if active else "")
        + "<b>1. Темы Mini App</b>\n"
          "Меняй оформление приложения под себя.\n\n"
          "<b>2. Расширенная статистика</b>\n"
          "Смотри активность за сегодня и за всё время: сообщения, диалоги, игры и оценки.\n\n"
          "<b>3. Статистика после диалога</b>\n"
          "Длительность разговора, сообщения, игры и заработанные звёзды.\n\n"
          "<b>4. Отображение ника</b>\n"
          "Можно добровольно включить показ своего ника собеседнику. По умолчанию он скрыт.\n\n"
          "<b>5. Без рекламы</b>\n"
          "Рекламные рассылки в боте не будут приходить.\n\n"
        + f"<b>Навсегда · {ctx.cfg.anon_plus_price_rub} ₽ или "
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
        await ctx.ack("Настройка доступна только с Анон Plus", alert=True)
        await show_anon_plus(ctx)
        return
    enabled = not bool(row["anon_plus_show_nick"])
    await db.set_anon_plus_identity(ctx.user_id, show_nick=enabled)
    ctx.me = await db.get_user(ctx.user_id)
    await ctx.ack("Ник будет виден" if enabled else "Ник снова скрыт")
    await show_profile(ctx)


@router.callback_query(F.data == K.CB_ANONPLUS_EMOJI)
async def cb_anon_plus_emoji(
    event: CallbackQuery, ctx: Ctx, db: Database
) -> None:
    row = await db.get_user(ctx.user_id)
    if not _plus_active(row):
        await ctx.ack("Эмодзи доступен только с Анон Plus", alert=True)
        await show_anon_plus(ctx)
        return
    current = str(row["anon_plus_emoji"] or "").strip().lower()
    if not current and (
        int(row["support_stars"] or 0) > 0 or int(row["support_rub"] or 0) > 0
    ):
        current = "diamond"
    await ctx.ack()
    await ctx.edit(
        "✨ <b>Эмодзи рядом с ником</b>\n\n"
        "Выбери один эмодзи. Новый вариант заменит предыдущий — второй значок не добавится.",
        K.anon_plus_emoji_keyboard(current),
    )


@router.callback_query(F.data.startswith(K.CB_ANONPLUS_EMOJI_SET_PREFIX))
async def cb_anon_plus_emoji_set(
    event: CallbackQuery, ctx: Ctx, db: Database
) -> None:
    row = await db.get_user(ctx.user_id)
    if not _plus_active(row):
        await ctx.ack("Эмодзи доступен только с Анон Plus", alert=True)
        await show_anon_plus(ctx)
        return
    key = (event.data or "")[len(K.CB_ANONPLUS_EMOJI_SET_PREFIX):].strip().lower()
    if key not in PROFILE_BADGES:
        await ctx.ack("Неизвестный эмодзи", alert=True)
        return
    await db.set_anon_plus_identity(ctx.user_id, emoji=key)
    ctx.me = await db.get_user(ctx.user_id)
    await ctx.ack(f"Выбран {PROFILE_BADGES[key]}")
    await ctx.edit(
        "✨ <b>Эмодзи рядом с ником</b>\n\n"
        "Выбранный эмодзи уже заменил предыдущий.",
        K.anon_plus_emoji_keyboard(key),
    )


@router.callback_query(F.data == K.CB_ANONPLUS_STARS)
async def cb_anon_plus_stars(
    event: CallbackQuery, ctx: Ctx, cfg: Config, db: Database
) -> None:
    row = await db.get_user(ctx.user_id)
    if _plus_active(row):
        await ctx.ack("Анон Plus уже активирован навсегда", alert=True)
        return
    await ctx.ack()
    payload = (
        f"anonplus:{ctx.user_id}:{int(cfg.anon_plus_price_stars)}:"
        f"0:{secrets.token_hex(8)}"
    )
    await ctx.bot.send_invoice(
        chat_id=ctx.user_id,
        title="Анон Plus",
        description="Анон Plus навсегда: темы, расширенная статистика и дополнительные функции профиля.",
        payload=payload,
        currency="XTR",
        prices=[
            LabeledPrice(
                label="Анон Plus · навсегда",
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
    row = await db.get_user(ctx.user_id)
    if _plus_active(row):
        await ctx.ack("Анон Plus уже активирован навсегда", alert=True)
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
            premium_days=0,
        )
        payment = await create_payment(
            cfg,
            order_id=order_id,
            amount=Decimal(int(cfg.anon_plus_price_rub)),
            description="АНОН МГН · Анон Plus навсегда",
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
        "💳 <b>Анон Plus · СБП</b>\n\n"
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
    await ctx.ack("Анон Plus активирован навсегда")
    await show_anon_plus(ctx)


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
            and days == 0
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
            and days == 0
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
            await ctx.reply("Не удалось активировать Анон Plus. Напиши в поддержку.")
            return

        if not created:
            await ctx.reply(
                "Этот платёж уже учтён.",
                K.menu_keyboard(ctx.mm.status(ctx.user_id)),
            )
            return

        ctx.me = await db.get_user(ctx.user_id)
        await ctx.reply(
            "💎 <b>Анон Plus активирован</b>\n\n"
            "<b>Доступ выдан навсегда.</b>\n\n"
            "Темы и расширенная статистика уже доступны в Mini App.",
            K.menu_keyboard(ctx.mm.status(ctx.user_id)),
        )
        return

    await ctx.reply(texts.SUPPORT_PAYMENT_ERROR)
