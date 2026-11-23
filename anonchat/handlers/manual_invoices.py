"""Ручные счета СБП: создание владельцем, отправка и проверка через RollyPay."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import keyboards as K, texts
from ..actions import Ctx
from ..config import Config
from ..db import Database
from ..payments import RollyPayError, create_payment, get_payment

router = Router(name="manual_invoices")
log = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Yekaterinburg")
MAX_AMOUNT_RUB = 100_000
PAGE_SIZE = 6


class InvoiceStates(StatesGroup):
    recipient = State()
    amount = State()
    description = State()
    confirmation = State()


def _kb(*buttons: tuple[str, str]) -> object:
    b = InlineKeyboardBuilder()
    for label, callback in buttons:
        b.button(text=label, callback_data=callback)
    b.adjust(1)
    return b.as_markup()


def _invoice_kb(invoice: dict, *, owner: bool) -> object:
    b = InlineKeyboardBuilder()
    if invoice["pay_url"] and invoice["status"] != "paid":
        b.button(text="💳 Перейти к оплате", url=invoice["pay_url"])
    if invoice["payment_id"]:
        b.button(text="🔄 Проверить оплату", callback_data=f"bill:check:{invoice['id']}")
    if owner:
        b.button(text="📋 Все счета", callback_data="bill:list:all:0")
        b.button(text="➕ Создать ещё", callback_data="bill:new")
    b.adjust(1)
    return b.as_markup()


def _status(status: str) -> str:
    return {
        "creating": "Создаётся",
        "awaiting_payment": "Ожидает оплаты",
        "pending": "Ожидает оплаты",
        "created": "Ожидает оплаты",
        "new": "Ожидает оплаты",
        "processing": "Обрабатывается",
        "paid": "Оплачен",
        "expired": "Истёк",
        "failed": "Ошибка оплаты",
        "create_failed": "Ошибка создания",
        "cancelled": "Отменён",
        "canceled": "Отменён",
        "refunded": "Возвращён",
    }.get(status, "Ожидает оплаты")


def _card(invoice: dict, *, owner: bool = True) -> str:
    issued = datetime.fromtimestamp(int(invoice["created_at"]), TZ).strftime("%d.%m.%Y %H:%M")
    return (
        f"💳 <b>Счёт №{invoice['id']}</b>\n\n"
        f"Сумма: <b>{invoice['amount_rub']} ₽</b>\n"
        f"Назначение: {texts.esc(invoice['description'])}\n"
        f"Статус: <b>{_status(invoice['status'])}</b>\n"
        f"Создан: {issued} (МГН)\n"
        + (f"Получатель: <code>{invoice['user_id']}</code>\n" if owner else "")
        + (f"Доставка в Telegram: {'да' if invoice['delivered_at'] else 'нет'}"
           if owner and invoice["pay_url"] else "")
    ).strip()


async def _screen(ctx: Ctx, body: str, markup: object) -> None:
    if await ctx.edit(body, markup):
        return
    await ctx.reply(body, markup)


async def _home(ctx: Ctx, db: Database) -> None:
    stats = await db.manual_invoice_stats()
    b = _kb(
        ("➕ Создать счёт", "bill:new"),
        ("📋 Все счета", "bill:list:all:0"),
        ("⌛ Неоплаченные", "bill:list:unpaid:0"),
        ("✅ Оплаченные", "bill:list:paid:0"),
        ("↩️ В админку", K.CB_PANEL_BACK),
    )
    await _screen(
        ctx,
        "💳 <b>Счета на оплату · СБП</b>\n\n"
        f"Всего: <b>{stats['total']}</b>\n"
        f"Оплачено: <b>{stats['paid']}</b>\n"
        f"Не оплачено: <b>{stats['unpaid']}</b>\n"
        f"Получено по подтверждённым счетам: <b>{stats['paid_rub']} ₽</b>\n\n"
        "Каждый платёж подтверждается только через RollyPay.",
        b,
    )


async def _list(ctx: Ctx, db: Database, status: str, page: int) -> None:
    if status not in {"all", "unpaid", "paid"}:
        status = "all"
    page = max(0, min(page, 10000))
    rows = await db.list_manual_invoices(status=status, limit=PAGE_SIZE + 1, offset=page * PAGE_SIZE)
    visible = rows[:PAGE_SIZE]
    headings = {"all": "Все", "unpaid": "Неоплаченные", "paid": "Оплаченные"}
    body = f"💳 <b>{headings[status]} счета</b> · страница {page + 1}\n\n"
    body += "\n".join(
        f"№{r['id']} · <b>{r['amount_rub']} ₽</b> · {_status(r['status'])}"
        for r in visible
    ) if visible else "Счетов пока нет."
    b = InlineKeyboardBuilder()
    for r in visible:
        b.button(text=f"Открыть №{r['id']}", callback_data=f"bill:view:{r['id']}")
    if page > 0:
        b.button(text="← Назад", callback_data=f"bill:list:{status}:{page-1}")
    if len(rows) > PAGE_SIZE:
        b.button(text="Вперёд →", callback_data=f"bill:list:{status}:{page+1}")
    b.button(text="➕ Создать", callback_data="bill:new")
    b.button(text="↩️ К счетам", callback_data="bill:home")
    b.adjust(1)
    await _screen(ctx, body, b.as_markup())


async def _detail(ctx: Ctx, db: Database, invoice_id: int) -> None:
    invoice = await db.get_manual_invoice(invoice_id)
    if not invoice:
        await ctx.ack("Счёт не найден", alert=True)
        return
    await _screen(ctx, _card(invoice), _invoice_kb(invoice, owner=True))


async def verify_manual_invoice(cfg: Config, db: Database, invoice: dict) -> tuple[str, bool]:
    """Сверяет сумму, валюту, IDs; paid не выставляется по нажатию кнопки."""
    if invoice["status"] == "paid":
        return "paid", False
    if not invoice["payment_id"]:
        raise RollyPayError("Счёт ещё не создан")
    remote = await get_payment(cfg, str(invoice["payment_id"]))
    try:
        amount = Decimal(str(remote.get("amount")))
    except (InvalidOperation, ValueError):
        amount = Decimal("-1")
    if not (
        str(remote.get("payment_id") or "") == str(invoice["payment_id"])
        and str(remote.get("order_id") or "") == str(invoice["order_id"])
        and str(remote.get("currency") or remote.get("payment_currency") or "").upper() == "RUB"
        and amount.is_finite()
        and amount == Decimal(int(invoice["amount_rub"]))
    ):
        raise RollyPayError("Данные платежа не совпадают с выставленным счётом")
    remote_status = str(remote.get("status") or "").strip().lower()
    allowed = {
        "paid", "pending", "awaiting_payment", "processing", "created", "new",
        "failed", "expired", "cancelled", "canceled", "refunded",
    }
    status = remote_status if remote_status in allowed else "pending"
    fresh = await db.set_manual_invoice_status(int(invoice["id"]), status)
    return status, fresh


async def _notify_paid(bot: object, invoice: dict, skip_user_id: int = 0) -> None:
    body_admin = (
        f"✅ <b>Оплачен счёт №{invoice['id']}</b>\n"
        f"Сумма: <b>{invoice['amount_rub']} ₽</b>\n"
        f"Плательщик: <code>{invoice['user_id']}</code>\n"
        f"Назначение: {texts.esc(invoice['description'])}"
    )
    body_user = (
        f"✅ <b>Счёт №{invoice['id']} оплачен!</b>\n"
        f"Получено: <b>{invoice['amount_rub']} ₽</b>.\n"
        f"Назначение: {texts.esc(invoice['description'])}"
    )
    for uid, body in (
        (int(invoice["created_by"]), body_admin),
        (int(invoice["user_id"]), body_user),
    ):
        if uid == skip_user_id:
            continue
        try:
            await bot.send_message(uid, body)
        except TelegramAPIError:
            log.info("Manual invoice %s: notification to %s not delivered", invoice["id"], uid)


async def sync_pending_manual_invoices(bot: object, cfg: Config, db: Database) -> int:
    """Регулярно сверяем свежие СБП-счета без необходимости нажимать кнопку."""
    if not cfg.rollypay_enabled:
        return 0
    paid = 0
    for invoice in await db.list_pending_manual_invoices(limit=12):
        try:
            status, fresh = await verify_manual_invoice(cfg, db, invoice)
        except RollyPayError:
            log.warning("Manual invoice %s: provider reconciliation failed", invoice["id"])
            continue
        if status == "paid" and fresh:
            paid += 1
            await _notify_paid(bot, invoice)
    return paid


@router.message(Command("invoice", "счёт", "счет"))
async def cmd_invoice(message: Message, ctx: Ctx, db: Database) -> None:
    if not ctx.is_owner:
        await ctx.reply("Создавать счета может только владелец.")
        return
    if not ctx.cfg.rollypay_enabled:
        await ctx.reply("СБП не настроена: укажи ROLLYPAY_API_KEY в окружении.")
        return
    await _home(ctx, db)


@router.callback_query(F.data.startswith("bill:"))
async def callback_invoice(event: CallbackQuery, ctx: Ctx, db: Database, cfg: Config,
                           state: FSMContext) -> None:
    data = event.data or ""
    if data.startswith("bill:check:"):
        try:
            invoice_id = int(data.rsplit(":", 1)[1])
        except ValueError:
            await ctx.ack("Некорректный номер счёта", alert=True)
            return
        invoice = await db.get_manual_invoice(invoice_id)
        if not invoice or not (ctx.is_owner or invoice["user_id"] == ctx.user_id):
            await ctx.ack("Счёт недоступен", alert=True)
            return
        try:
            status, fresh = await verify_manual_invoice(cfg, db, invoice)
        except RollyPayError as exc:
            await ctx.ack(str(exc), alert=True)
            return
        await ctx.ack("Оплата подтверждена" if status == "paid" else "Платёж пока не оплачен", alert=status != "paid")
        if fresh:
            await _notify_paid(ctx.bot, invoice, skip_user_id=ctx.user_id)
        if ctx.is_owner:
            await _detail(ctx, db, invoice_id)
        elif status == "paid":
            await _screen(ctx, f"✅ <b>Счёт №{invoice_id} успешно оплачен.</b>", None)
        return

    if not ctx.is_owner:
        await ctx.ack("Создание счетов доступно только владельцу", alert=True)
        return
    if data in {"bill:home", "bill:cancel"}:
        await state.clear()
        await ctx.ack()
        await _home(ctx, db)
        return
    if data.startswith("bill:list:"):
        try:
            _, _, status, page_raw = data.split(":")
            page = int(page_raw)
        except ValueError:
            await ctx.ack("Некорректная страница", alert=True)
            return
        await ctx.ack()
        await _list(ctx, db, status, page)
        return
    if data.startswith("bill:view:"):
        try:
            invoice_id = int(data.rsplit(":", 1)[1])
        except ValueError:
            await ctx.ack("Некорректный номер", alert=True)
            return
        await ctx.ack()
        await _detail(ctx, db, invoice_id)
        return
    if data == "bill:new":
        if not cfg.rollypay_enabled:
            await ctx.ack("СБП не настроена", alert=True)
            return
        await state.clear()
        await state.set_state(InvoiceStates.recipient)
        await ctx.ack()
        await _screen(
            ctx,
            "💳 <b>Новый счёт · шаг 1/3</b>\n\n"
            "Пришли Telegram ID пользователя, которому выставляем счёт.\n"
            "Если он не запускал бота, ссылку можно будет отправить вручную.",
            _kb(("Отмена", "bill:cancel")),
        )
        return
    if data == "bill:create":
        if await state.get_state() != InvoiceStates.confirmation.state:
            await ctx.ack("Черновик устарел — создай счёт заново", alert=True)
            return
        draft = await state.get_data()
        await state.clear()  # блокируем повторное создание при двойном нажатии
        try:
            user_id = int(draft["bill_user_id"])
            amount = int(draft["bill_amount"])
            description = str(draft["bill_description"])
            if user_id < 1 or user_id >= 2**63 or not 1 <= amount <= MAX_AMOUNT_RUB:
                raise ValueError("Некорректные данные")
        except (KeyError, TypeError, ValueError):
            await ctx.ack("Черновик повреждён — начни сначала", alert=True)
            return
        if not cfg.rollypay_enabled:
            await ctx.ack("СБП не настроена", alert=True)
            return
        await ctx.ack("Создаём счёт")
        order_id = f"manual-{ctx.user_id}-{secrets.token_hex(8)}"
        invoice_id = 0
        try:
            invoice_id = await db.create_manual_invoice(
                order_id=order_id, created_by=ctx.user_id, user_id=user_id,
                amount_rub=amount, description=description,
            )
            result = await create_payment(
                cfg, order_id=order_id, amount=Decimal(amount),
                description=description, user_id=user_id,
            )
            await db.attach_manual_invoice(
                invoice_id, str(result["payment_id"]), str(result["pay_url"]),
            )
        except Exception:
            log.exception("Manual invoice creation failed (order=%s)", order_id)
            if invoice_id:
                try:
                    await db.set_manual_invoice_status(invoice_id, "create_failed")
                except Exception:
                    log.exception("Failed to flag invoice %s", invoice_id)
            await _screen(
                ctx, "Не получилось создать платёж в СБП. Деньги не списаны ботом; "
                "проверь подключение RollyPay и попробуй ещё раз.",
                _kb(("Создать снова", "bill:new"), ("К счетам", "bill:home")),
            )
            return
        invoice = await db.get_manual_invoice(invoice_id)
        assert invoice is not None
        delivered = False
        try:
            await ctx.bot.send_message(
                user_id,
                "💳 <b>Вам выставлен счёт в АНОН МГН.</b>\n\n"
                + _card(invoice, owner=False),
                reply_markup=_invoice_kb(invoice, owner=False),
            )
            await db.mark_manual_invoice_delivered(invoice_id)
            delivered = True
        except TelegramAPIError:
            log.info("Manual invoice %s could not be sent to %s", invoice_id, user_id)
        await _screen(
            ctx,
            _card(await db.get_manual_invoice(invoice_id))
            + ("\n\n✅ Счёт отправлен пользователю." if delivered else
               "\n\n⚠️ Пользователю не удалось отправить сообщение. "
               "Отправь ему ссылку по кнопке ниже вручную."),
            _invoice_kb(invoice, owner=True),
        )
        return
    await ctx.ack("Кнопка не найдена", alert=True)


def _plain(message: Message) -> str:
    return (message.text or "").strip()


async def _cancel_text(message: Message, ctx: Ctx, state: FSMContext) -> bool:
    if _plain(message).lower() in {"/cancel", "/admin", "отмена"}:
        await state.clear()
        await ctx.reply("Создание счёта отменено. Открой /admin, чтобы вернуться в панель.")
        return True
    return False


@router.message(InvoiceStates.recipient)
async def recipient_input(message: Message, ctx: Ctx, state: FSMContext) -> None:
    if not ctx.is_owner or await _cancel_text(message, ctx, state):
        return
    raw = _plain(message)
    if not raw.isdecimal() or not 1 <= int(raw) < 2**63:
        await ctx.reply("Нужен числовой Telegram ID пользователя.", _kb(("Отмена", "bill:cancel")))
        return
    await state.update_data(bill_user_id=int(raw))
    await state.set_state(InvoiceStates.amount)
    await ctx.reply(
        "💳 <b>Новый счёт · шаг 2/3</b>\n\n"
        f"Получатель: <code>{raw}</code>\n"
        f"Введи сумму в рублях от 1 до {MAX_AMOUNT_RUB:,} (целое число).",
        _kb(("Отмена", "bill:cancel")),
    )


@router.message(InvoiceStates.amount)
async def amount_input(message: Message, ctx: Ctx, state: FSMContext) -> None:
    if not ctx.is_owner or await _cancel_text(message, ctx, state):
        return
    raw = _plain(message)
    if not raw.isdecimal() or not 1 <= int(raw) <= MAX_AMOUNT_RUB:
        await ctx.reply(f"Введи целую сумму от 1 до {MAX_AMOUNT_RUB} ₽.", _kb(("Отмена", "bill:cancel")))
        return
    await state.update_data(bill_amount=int(raw))
    await state.set_state(InvoiceStates.description)
    await ctx.reply(
        "💳 <b>Новый счёт · шаг 3/3</b>\n\n"
        "Пришли назначение платежа (от 3 до 200 символов).",
        _kb(("Отмена", "bill:cancel")),
    )


@router.message(InvoiceStates.description)
async def description_input(message: Message, ctx: Ctx, state: FSMContext) -> None:
    if not ctx.is_owner or await _cancel_text(message, ctx, state):
        return
    description = _plain(message)
    if not 3 <= len(description) <= 200:
        await ctx.reply("Назначение должно содержать 3–200 символов.", _kb(("Отмена", "bill:cancel")))
        return
    await state.update_data(bill_description=description)
    await state.set_state(InvoiceStates.confirmation)
    data = await state.get_data()
    await ctx.reply(
        "💳 <b>Подтверди создание счёта</b>\n\n"
        f"Пользователь: <code>{data['bill_user_id']}</code>\n"
        f"Сумма: <b>{data['bill_amount']} ₽</b>\n"
        f"Назначение: {texts.esc(description)}\n\n"
        "После подтверждения RollyPay создаст ссылку на оплату.",
        _kb(("✅ Создать счёт", "bill:create"), ("Отмена", "bill:cancel")),
    )


@router.message(InvoiceStates.confirmation)
async def confirmation_input(message: Message, ctx: Ctx, state: FSMContext) -> None:
    if not ctx.is_owner or await _cancel_text(message, ctx, state):
        return
    await ctx.reply("Подтверди счёт кнопкой выше или нажми «Отмена».")
