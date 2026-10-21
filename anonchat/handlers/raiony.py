"""Bot-side callbacks for RАЙОНЫ warehouse invitations and verified XTR pets."""
from __future__ import annotations
import sqlite3
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery
from aiogram.exceptions import TelegramAPIError
from ..db import Database
from ..config import Config
from .. import city_progression as progression
from .. import city_warehouses as warehouses

router=Router(name="raiony")

async def _allowed(db, cfg, uid):
    import os
    if os.getenv("CITY_GAME_TEST_ADMINS_ONLY","1")=="0":return True
    return uid in await db.all_admin_ids(cfg.admin_ids)

@router.callback_query(F.data.startswith("rdi:"))
async def on_invite(callback:CallbackQuery,db:Database,cfg:Config):
    if not await _allowed(db,cfg,callback.from_user.id):
        await callback.answer("Игра пока для администраторов",show_alert=True);return
    try:
        _prefix,token,mode=(callback.data or "").split(":")
        if mode not in ("y","n"):raise ValueError("Ошибка приглашения")
        with sqlite3.connect(db.path,timeout=10,isolation_level=None) as conn:
            warehouses.init_db(conn)
            result=warehouses.respond(conn,callback.from_user.id,int(token),mode=="y")
        await callback.answer("Ты принят!" if result["accepted"] else "Отклонено")
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(
                "📦 Ты вступил на склад!" if result["accepted"] else "Приглашение отклонено.")
    except (ValueError,sqlite3.Error):
        await callback.answer("Приглашение недоступно или устарело",show_alert=True)

@router.pre_checkout_query(F.invoice_payload.startswith("raiony:"))
async def on_pre_checkout(query:PreCheckoutQuery,db:Database,cfg:Config):
    if not await _allowed(db,cfg,query.from_user.id):
        await query.answer(ok=False,error_message="Игра пока недоступна");return
    try:
        payload=(query.invoice_payload or "").removeprefix("raiony:")
        with sqlite3.connect(db.path,timeout=10) as conn:
            progression.init_db(conn)
            valid=progression.validate_precheckout(
                conn,query.from_user.id,payload,query.currency,query.total_amount)
        if valid:
            await query.answer(ok=True)
        else:
            await query.answer(ok=False,error_message="Этот счёт недействителен")
    except (sqlite3.Error,ValueError):
        await query.answer(ok=False,error_message="Не удалось проверить счёт")

@router.message(F.successful_payment, F.successful_payment.invoice_payload.startswith("raiony:"))
async def on_paid(message:Message,db:Database,cfg:Config):
    pay=message.successful_payment
    if not pay:return
    try:
        with sqlite3.connect(db.path,timeout=10,isolation_level=None) as conn:
            progression.init_db(conn)
            result=progression.confirm_paid(
                conn,message.from_user.id,
                pay.invoice_payload.removeprefix("raiony:"),
                pay.currency,pay.total_amount,pay.telegram_payment_charge_id)
        if result.get("replayed"):
            await message.answer("Покупка уже записана в инвентаре РАЙОНОВ.")
        else:
            item=progression.PREMIUM[result["kind"]]
            await message.answer(
                f"✅ Получен питомец {item['emoji']} {item['name']}!\n"
                "Он уже в инвентаре игры «РАЙОНЫ».")
    except (ValueError,sqlite3.Error):
        # Persisted successful_payment can be replayed by Telegram. Never
        # grant via fallback or trust message text: manual reconciliation.
        import logging
        logging.getLogger("raiony.payments").exception("Payment reconciliation needed")
        await message.answer("Оплата получена. Если питомец не появился, напиши в поддержку.")

@router.message(Command("raiony_refund"))
async def refund_stars(message:Message,db:Database,cfg:Config):
    """Admin-only support command: /raiony_refund <user_id> <telegram_charge_id>."""
    if message.from_user.id not in await db.all_admin_ids(cfg.admin_ids):
        await message.answer("Эта команда только для администрации.");return
    parts=(message.text or "").split()
    if len(parts)!=3 or not parts[1].isdigit() or not parts[2].strip():
        await message.answer("Использование: /raiony_refund user_id telegram_payment_charge_id")
        return
    uid=int(parts[1]);charge=parts[2].strip()
    if uid<1 or len(charge)>255:
        await message.answer("Некорректные реквизиты");return
    try:
        with sqlite3.connect(db.path,timeout=10) as conn:
            progression.init_db(conn)
            order=conn.execute("""SELECT pet_id,refunded_at FROM city_premium_orders
                WHERE user_id=? AND charge_id=? AND fulfilled_at>0""",(uid,charge)).fetchone()
        if not order:
            await message.answer("Подтверждённый платёж не найден");return
        if order[1]:
            await message.answer("Этот платёж уже возвращён");return
        try:
            # Only Telegram can actually return XTR. Local DB is not authoritative.
            await message.bot.refund_star_payment(
                user_id=uid,telegram_payment_charge_id=charge)
        except TelegramAPIError as error:
            # On an interrupted prior refund, Telegram may already have
            # returned the Stars; finish local reconciliation idempotently.
            if "CHARGE_ALREADY_REFUNDED" not in str(error).upper():
                await message.answer("Telegram не подтвердил возврат. Ничего не списано.")
                return
        with sqlite3.connect(db.path,timeout=10,isolation_level=None) as conn:
            progression.init_db(conn)
            result=progression.mark_refunded(conn,uid,charge)
        await message.answer(
            "✅ Telegram Stars возвращены. Платный питомец отозван из РАЙОНОВ."
            if result.get("refunded") else "Возврат уже учтён")
    except (ValueError,sqlite3.Error):
        await message.answer("Не удалось завершить возврат. Проверь лог транзакции.")
