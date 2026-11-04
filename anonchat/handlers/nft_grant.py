"""Owner-only manual NFT ticket grants, recorded independently of SBP payments.

A grant is a separate, auditable, explicitly confirmed transaction.
It never changes or fakes a RollyPay payment and cannot run after the draw.
"""
from __future__ import annotations

import html
import re
import secrets
import time

import aiosqlite
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..actions import Ctx
from ..db import Database
from .nft_giveaway import Giveaway, _active, _init

router = Router(name="nft_grant")
GRANT_LIMIT = 99
GRANT_CONFIRM_TTL = 10 * 60
_ID_RE = re.compile(r"[1-9][0-9]{0,18}\Z")
_TOKEN_RE = re.compile(r"[0-9a-f]{16}\Z")


async def _init_grants(path) -> None:
    async with aiosqlite.connect(path, timeout=15.0) as con:
        await con.execute("PRAGMA busy_timeout=10000")
        await con.execute("""
            CREATE TABLE IF NOT EXISTS nft_ticket_grants (
                token TEXT PRIMARY KEY,
                campaign TEXT NOT NULL,
                actor_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                confirmed_at INTEGER NOT NULL DEFAULT 0,
                first_number INTEGER NOT NULL DEFAULT 0
            )
        """)
        await con.commit()


def _parse_grant(text: str) -> tuple[int, int] | None:
    args = (text or "").strip().split()
    if len(args) != 3:
        return None
    user_id, qty = args[1:]
    if not _ID_RE.fullmatch(user_id) or not re.fullmatch(r"[1-9][0-9]?\Z", qty):
        return None
    uid, quantity = int(user_id), int(qty)
    if uid > 2**63 - 1 or not 1 <= quantity <= GRANT_LIMIT:
        return None
    return uid, quantity


async def _create_grant(
    path, *, campaign: str, actor_id: int, user_id: int, quantity: int,
) -> str:
    await _init_grants(path)
    token = secrets.token_hex(8)
    async with aiosqlite.connect(path, timeout=15.0) as con:
        await con.execute(
            "INSERT INTO nft_ticket_grants "
            "(token,campaign,actor_id,user_id,quantity,status,created_at) "
            "VALUES (?,?,?,?,?,'pending',?)",
            (token, campaign, actor_id, user_id, quantity, int(time.time())),
        )
        await con.commit()
    return token


async def _finish_grant(
    path, *, token: str, actor_id: int, current: Giveaway | None,
    approve: bool,
) -> tuple[str, int, int, int]:
    """Atomically confirm/cancel a grant; returns (status, user_id, qty, first).

    The unique token acts as an idempotency key. Rows are inserted into the
    original ticket table so the published statistics and random draw use them.
    """
    if not _TOKEN_RE.fullmatch(token):
        return "invalid", 0, 0, 0
    await _init(path)
    await _init_grants(path)
    async with aiosqlite.connect(path, timeout=15.0) as con:
        await con.execute("PRAGMA busy_timeout=10000")
        await con.execute("BEGIN IMMEDIATE")
        row = await (await con.execute(
            "SELECT campaign,actor_id,user_id,quantity,status,created_at,first_number "
            "FROM nft_ticket_grants WHERE token=?",
            (token,),
        )).fetchone()
        if not row or int(row[1]) != actor_id:
            await con.rollback()
            return "invalid", 0, 0, 0
        campaign, _, user_id, qty, status, created_at, first_number = row
        user_id, qty, first_number = int(user_id), int(qty), int(first_number)
        if status != "pending":
            await con.commit()
            return ("already_issued" if status == "issued" else str(status)), user_id, qty, first_number
        if not approve:
            await con.execute(
                "UPDATE nft_ticket_grants SET status='cancelled' WHERE token=?",
                (token,),
            )
            await con.commit()
            return "cancelled", user_id, qty, 0

        now = int(time.time())
        latest = await (await con.execute(
            "SELECT campaign,close_at FROM nft_giveaway_campaigns "
            "ORDER BY created_at DESC,campaign DESC LIMIT 1"
        )).fetchone()
        allowed = bool(
            current is not None and current.campaign == campaign
            and current.close_at > now
            and (latest is None or (
                latest[0] == campaign and int(latest[1]) > now
            ))
        )
        if now - int(created_at) > GRANT_CONFIRM_TTL or not allowed:
            await con.execute(
                "UPDATE nft_ticket_grants SET status='expired' WHERE token=?",
                (token,),
            )
            await con.commit()
            return "expired", user_id, qty, 0

        winner = await (await con.execute(
            "SELECT 1 FROM nft_giveaway_winners WHERE campaign=?", (campaign,)
        )).fetchone()
        if winner:
            await con.execute(
                "UPDATE nft_ticket_grants SET status='expired' WHERE token=?",
                (token,),
            )
            await con.commit()
            return "expired", user_id, qty, 0
        user = await (await con.execute(
            "SELECT 1 FROM users WHERE user_id=?", (user_id,),
        )).fetchone()
        if not user:
            await con.rollback()
            return "missing_user", user_id, qty, 0

        first = int((await (await con.execute(
            "SELECT COUNT(*) FROM nft_giveaway_tickets WHERE campaign=?",
            (campaign,),
        )).fetchone())[0]) + 1
        for i in range(1, qty + 1):
            await con.execute(
                "INSERT INTO nft_giveaway_tickets "
                "(campaign,user_id,payment_id,joined_at) VALUES (?,?,?,?)",
                (campaign, user_id, f"admin:{token}:{i}", now),
            )
        await con.execute(
            "UPDATE nft_ticket_grants SET status='issued',confirmed_at=?,first_number=? "
            "WHERE token=? AND status='pending'",
            (now, first, token),
        )
        await con.commit()
        return "issued", user_id, qty, first


@router.message(Command("nft_give"))
async def nft_grant_preview(message: Message, ctx: Ctx, db: Database) -> None:
    if not ctx.is_owner or message.chat.type != "private":
        return
    parsed = _parse_grant(message.text or "")
    if not parsed:
        await ctx.reply(
            "Укажи Telegram ID и количество билетов от 1 до 99.\n"
            "Пример: <code>/nft_give 123456789 5</code>"
        )
        return
    uid, qty = parsed
    g = await _active(db)
    if not g or time.time() >= g.close_at:
        await ctx.reply("Сейчас нет активного NFT-розыгрыша.")
        return
    if not await db.get_user(uid):
        await ctx.reply(
            f"Пользователь <code>{uid}</code> не найден в базе. "
            "Он должен сначала запустить бота через /start."
        )
        return
    token = await _create_grant(
        db.path, campaign=g.campaign,
        actor_id=ctx.user_id, user_id=uid, quantity=qty,
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"✅ Выдать {qty} билет(ов)",
            callback_data=f"nft:grant:confirm:{token}",
        )],
        [InlineKeyboardButton(
            text="Отмена", callback_data=f"nft:grant:cancel:{token}",
        )],
    ])
    await ctx.reply(
        "<b>Подтверди выдачу NFT-билетов</b>\n\n"
        f"Telegram ID: <code>{uid}</code>\n"
        f"Количество: <b>{qty}</b>\n"
        "Стоимость: <b>0 ₽ (выдача администратором)</b>\n\n"
        "Билеты попадут в общий розыгрыш. "
        "Нажми «Выдать» для подтверждения.",
        keyboard,
    )


@router.callback_query(F.data.startswith("nft:grant:confirm:"))
@router.callback_query(F.data.startswith("nft:grant:cancel:"))
async def nft_grant_action(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    if not ctx.is_owner or not event.message or event.message.chat.type != "private":
        await ctx.ack("Нет доступа", alert=True)
        return
    data = event.data or ""
    approve = data.startswith("nft:grant:confirm:")
    token = data.rsplit(":", 1)[-1]
    g = await _active(db)
    status, user_id, qty, first = await _finish_grant(
        db.path, token=token, actor_id=ctx.user_id,
        current=g, approve=approve,
    )
    if status == "invalid":
        await ctx.ack("Запрос не найден или доступ запрещён", alert=True)
        return
    if status == "issued":
        await ctx.ack("Билеты выданы")
        label = f"№{first}" if qty == 1 else f"№{first}–№{first + qty - 1}"
        try:
            await ctx.bot.send_message(
                chat_id=user_id,
                text="🎟 <b>Вам начислены NFT-билеты!</b>\n\n"
                     f"Количество: <b>{qty}</b>\n"
                     f"Номера: <b>{label}</b>\n\n"
                     "Посмотреть их можно в /nft → «Мои билеты».",
            )
        except TelegramAPIError:
            await ctx.reply(
                "Билеты начислены, но отправить уведомление пользователю не удалось."
            )
        await ctx.reply(
            "✅ <b>Билеты выданы</b>\n\n"
            f"Telegram ID: <code>{user_id}</code>\n"
            f"Количество: <b>{qty}</b>\n"
            f"Номера: <b>{html.escape(label)}</b>\n"
            "Выдача сохранена в журнале."
        )
        return
    if status == "cancelled":
        await ctx.ack("Отменено")
        await ctx.reply("Выдача билетов отменена.")
    elif status == "expired":
        await ctx.ack("Запрос устарел", alert=True)
        await ctx.reply("Розыгрыш завершён или подтверждение устарело. Создай новый запрос.")
    elif status == "missing_user":
        await ctx.ack("Пользователь не найден", alert=True)
    else:
        await ctx.ack("Этот запрос уже обработан", alert=True)
