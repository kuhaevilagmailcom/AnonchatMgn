"""Бесплатный NFT-розыгрыш: билеты, рассылка, закрытие и выбор победителя.

Платная лотерея/покупка билетов через СБП здесь намеренно не реализована.
Одна заявка на человека, проверяемая и сохраняемая на сервере.
"""
from __future__ import annotations

import html
import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

import aiosqlite
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..actions import Ctx
from ..admin_broadcasts import create_job
from ..db import Database

router = Router(name="nft_giveaway")


@dataclass(frozen=True)
class Giveaway:
    campaign: str
    prize: str
    close_at: int
    deadline: str
    rules_url: str


def _configured() -> Giveaway | None:
    """Отправка и сбор участников недоступны без приза, срока и правил."""
    campaign = os.getenv("NFT_GIVEAWAY_ID", "nft-2026").strip().lower()
    prize = os.getenv("NFT_GIVEAWAY_PRIZE", "").strip()
    deadline = os.getenv("NFT_GIVEAWAY_CLOSE_AT", "").strip()
    rules_url = os.getenv("NFT_GIVEAWAY_RULES_URL", "").strip()
    if not re.fullmatch(r"[a-z0-9_-]{1,32}", campaign) or not prize or len(prize) > 160:
        return None
    parsed = urlsplit(rules_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    try:
        dt = datetime.fromisoformat(deadline)
        if dt.tzinfo is None:
            return None
        close_at = int(dt.timestamp())
    except (TypeError, ValueError, OverflowError):
        return None
    return Giveaway(campaign, prize, close_at, dt.strftime("%d.%m.%Y %H:%M %Z"), rules_url)


def _message(g: Giveaway) -> str:
    return (
        "🎁 Розыгрыш NFT\n\n"
        "Для участия нужен 1 билет. Он бесплатный.\n"
        "Нажми кнопку ниже, чтобы получить билет.\n\n"
        f"Приз: {g.prize}\n"
        f"Участвовать до: {g.deadline}\n"
        f"Правила: {g.rules_url}"
    )


def _keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Получить билет", callback_data="nft:join")],
        [InlineKeyboardButton(text="Мой билет", callback_data="nft:status")],
    ])


async def _init(path) -> None:
    async with aiosqlite.connect(path, timeout=15.0) as con:
        await con.execute("PRAGMA busy_timeout=10000")
        await con.execute("""
            CREATE TABLE IF NOT EXISTS nft_giveaway_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at INTEGER NOT NULL,
                UNIQUE (campaign, user_id)
            )
        """)
        await con.execute("""
            CREATE TABLE IF NOT EXISTS nft_giveaway_winners (
                campaign TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                entry_id INTEGER NOT NULL,
                entries_count INTEGER NOT NULL,
                drawn_at INTEGER NOT NULL
            )
        """)
        await con.execute("""
            CREATE TABLE IF NOT EXISTS nft_giveaway_campaigns (
                campaign TEXT PRIMARY KEY,
                prize TEXT NOT NULL,
                close_at INTEGER NOT NULL,
                deadline TEXT NOT NULL,
                rules_url TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        await con.commit()


async def _active(db: Database) -> Giveaway | None:
    await _init(db.path)
    row = await db._fetchone(
        "SELECT campaign,prize,close_at,deadline,rules_url FROM nft_giveaway_campaigns "
        "ORDER BY created_at DESC,campaign DESC LIMIT 1"
    )
    if row:
        return Giveaway(
            str(row["campaign"]), str(row["prize"]), int(row["close_at"]),
            str(row["deadline"]), str(row["rules_url"]),
        )
    return _configured()


async def _save_campaign(db: Database, prize: str, close_at: int,
                         deadline: str, rules_url: str) -> Giveaway:
    await _init(db.path)
    campaign = "nft-" + secrets.token_hex(8)
    async with aiosqlite.connect(db.path, timeout=15.0) as con:
        await con.execute("PRAGMA busy_timeout=10000")
        await con.execute("BEGIN IMMEDIATE")
        row = await (await con.execute(
            "SELECT close_at FROM nft_giveaway_campaigns "
            "ORDER BY created_at DESC,campaign DESC LIMIT 1"
        )).fetchone()
        if row and int(row[0]) > time.time():
            await con.rollback()
            raise ValueError("Сначала дождись завершения текущего розыгрыша.")
        await con.execute(
            "INSERT INTO nft_giveaway_campaigns("
            "campaign,prize,close_at,deadline,rules_url,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (campaign, prize, close_at, deadline, rules_url, int(time.time())),
        )
        await con.commit()
    return Giveaway(campaign, prize, close_at, deadline, rules_url)


async def _ticket(path, campaign: str, user_id: int) -> int | None:
    await _init(path)
    async with aiosqlite.connect(path, timeout=15.0) as con:
        cur = await con.execute(
            "SELECT id FROM nft_giveaway_entries WHERE campaign=? AND user_id=?",
            (campaign, user_id),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else None


async def _join(path, g: Giveaway, user_id: int) -> tuple[int | None, bool]:
    await _init(path)
    async with aiosqlite.connect(path, timeout=15.0) as con:
        await con.execute("PRAGMA busy_timeout=10000")
        await con.execute("BEGIN IMMEDIATE")
        row = await (await con.execute(
            "SELECT id FROM nft_giveaway_entries WHERE campaign=? AND user_id=?",
            (g.campaign, user_id),
        )).fetchone()
        if row:
            await con.commit()
            return int(row[0]), False
        winner = await (await con.execute(
            "SELECT 1 FROM nft_giveaway_winners WHERE campaign=?", (g.campaign,)
        )).fetchone()
        if winner or time.time() >= g.close_at:
            await con.commit()
            return None, False
        cur = await con.execute(
            "INSERT INTO nft_giveaway_entries(campaign,user_id,joined_at) VALUES (?,?,?)",
            (g.campaign, user_id, int(time.time())),
        )
        await con.commit()
        return int(cur.lastrowid), True


async def _count(path, campaign: str) -> int:
    await _init(path)
    async with aiosqlite.connect(path) as con:
        row = await (await con.execute(
            "SELECT COUNT(*) FROM nft_giveaway_entries WHERE campaign=?",
            (campaign,),
        )).fetchone()
        return int(row[0])


async def _draw(path, g: Giveaway) -> tuple[int, int, int] | None:
    """Результат фиксируется один раз атомарно; повторный вызов его не меняет."""
    await _init(path)
    async with aiosqlite.connect(path, timeout=15.0) as con:
        await con.execute("PRAGMA busy_timeout=10000")
        await con.execute("BEGIN IMMEDIATE")
        prior = await (await con.execute(
            "SELECT user_id,entry_id,entries_count FROM nft_giveaway_winners WHERE campaign=?",
            (g.campaign,),
        )).fetchone()
        if prior:
            await con.commit()
            return int(prior[0]), int(prior[1]), int(prior[2])
        if time.time() < g.close_at:
            await con.commit()
            return None
        total = int((await (await con.execute(
            "SELECT COUNT(*) FROM nft_giveaway_entries WHERE campaign=?", (g.campaign,)
        )).fetchone())[0])
        if not total:
            await con.commit()
            return None
        picked = await (await con.execute(
            "SELECT user_id,id FROM nft_giveaway_entries WHERE campaign=? ORDER BY id LIMIT 1 OFFSET ?",
            (g.campaign, secrets.randbelow(total)),
        )).fetchone()
        user_id, entry_id = int(picked[0]), int(picked[1])
        await con.execute(
            "INSERT INTO nft_giveaway_winners(campaign,user_id,entry_id,entries_count,drawn_at) "
            "VALUES (?,?,?,?,?)",
            (g.campaign, user_id, entry_id, total, int(time.time())),
        )
        await con.commit()
        return user_id, entry_id, total


@router.message(Command("nft"))
async def nft_open(message: Message, ctx: Ctx, db: Database) -> None:
    g = await _active(db)
    if not g:
        await ctx.reply("NFT-розыгрыш пока не открыт.")
        return
    await ctx.reply(html.escape(_message(g)), _keyboard())


@router.callback_query(F.data == "nft:join")
async def nft_join(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    g = await _active(db)
    if not g:
        await ctx.ack("Розыгрыш пока не открыт.", alert=True)
        return
    if await ctx.restricted():
        await ctx.ack("Участие недоступно.", alert=True)
        return
    ticket, created = await _join(db.path, g, ctx.user_id)
    if ticket is None:
        await ctx.ack("Приём заявок завершён.", alert=True)
        return
    await ctx.ack("Билет получен!" if created else "Билет у тебя уже есть.")
    await ctx.reply(
        f"🎟 <b>Твой билет №{ticket}</b>\n\n"
        "Ты участвуешь в розыгрыше NFT. Повторно записываться не нужно."
    )


@router.callback_query(F.data == "nft:status")
async def nft_status(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    g = await _active(db)
    if not g:
        await ctx.ack("Розыгрыш пока не открыт.", alert=True)
        return
    ticket = await _ticket(db.path, g.campaign, ctx.user_id)
    await ctx.ack()
    if ticket:
        await ctx.reply(f"🎟 Твой билет №{ticket}. Он участвует в розыгрыше.")
    elif time.time() >= g.close_at:
        await ctx.reply("Приём заявок завершён.")
    else:
        await ctx.reply("У тебя пока нет билета.", _keyboard())


@router.message(Command("nft_broadcast"))
async def nft_broadcast_preview(message: Message, ctx: Ctx, db: Database) -> None:
    if not (ctx.is_owner or ctx.can("broadcast")):
        return
    g = await _active(db)
    if not g:
        await ctx.reply(
            "Для NFT-розыгрыша укажи в окружении NFT_GIVEAWAY_PRIZE, "
            "NFT_GIVEAWAY_CLOSE_AT и NFT_GIVEAWAY_RULES_URL. "
            "Без приза, даты и правил рассылку запускать нельзя."
        )
        return
    if time.time() >= g.close_at:
        await ctx.reply("Дата окончания розыгрыша уже прошла.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Разослать всем", callback_data="nft:send")],
        [InlineKeyboardButton(text="Отмена", callback_data="nft:cancel")],
    ])
    await ctx.reply(
        "<b>Предпросмотр NFT-рассылки</b>\n\n" + html.escape(_message(g)),
        kb,
    )


@router.callback_query(F.data == "nft:cancel")
async def nft_cancel(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack("Отменено")


@router.callback_query(F.data == "nft:send")
async def nft_send(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    if not (ctx.is_owner or ctx.can("broadcast")):
        await ctx.ack("Нет доступа", alert=True)
        return
    g = await _active(db)
    if not g or time.time() >= g.close_at:
        await ctx.ack("Розыгрыш не настроен или уже завершился", alert=True)
        return
    ids = await db.broadcast_ids()
    key = f"nft-giveaway-{g.campaign}"
    created = await create_job(
        db, key=key, actor=ctx.user_id, message=_message(g),
        button_action="nft", recipient_ids=ids,
    )
    await ctx.ack("Рассылка добавлена в очередь" if created else "Рассылка уже запускалась")
    await ctx.reply(
        f"Рассылка NFT: {len(ids)} получателей в очереди."
        if created else "Рассылка по этому NFT-розыгрышу уже существует."
    )


@router.message(Command("nft_stats"))
async def nft_admin_stats(message: Message, ctx: Ctx, db: Database) -> None:
    if not (ctx.is_owner or ctx.can("stats")):
        return
    g = await _active(db)
    if not g:
        await ctx.reply("NFT-розыгрыш пока не настроен.")
        return
    total = await _count(db.path, g.campaign)
    await ctx.reply(f"NFT-розыгрыш · участников: <b>{total}</b>.\n"
                    f"Закрытие: {html.escape(g.deadline)}.")


@router.message(Command("nft_draw"))
async def nft_admin_draw(message: Message, ctx: Ctx, db: Database) -> None:
    if not ctx.is_owner:
        return
    g = await _active(db)
    if not g:
        await ctx.reply("NFT-розыгрыш пока не настроен.")
        return
    result = await _draw(db.path, g)
    if result is None:
        await ctx.reply("Выбрать победителя можно после закрытия приёма заявок, "
                        "если есть участники.")
        return
    user_id, ticket, total = result
    await ctx.reply(
        f"Победитель: ID <code>{user_id}</code>, билет <b>№{ticket}</b>. "
        f"Всего заявок: <b>{total}</b>. Результат сохранён."
    )
