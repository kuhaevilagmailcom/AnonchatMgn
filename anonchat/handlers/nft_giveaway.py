"""NFT-розыгрыш с билетами по 35 RUB через RollyPay."""
from __future__ import annotations

import asyncio
import html
import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlsplit

import aiosqlite
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..actions import Ctx
from ..admin_broadcasts import create_job
from ..db import Database
from ..payments import RollyPayError, create_payment, get_payment

router = Router(name="nft_giveaway")
TICKET_PRICE_RUB = 35
NFT_CHECK_PREFIX = "nft:check:"


@dataclass(frozen=True)
class Giveaway:
    campaign: str
    nft_url: str
    close_at: int
    deadline: str


def valid_nft_url(url: str) -> bool:
    if not url or len(url) > 1000 or any(ch.isspace() for ch in url):
        return False
    try:
        parsed = urlsplit(url)
        return bool(
            parsed.scheme == "https" and parsed.hostname
            and not parsed.username and not parsed.password
        )
    except ValueError:
        return False


def _configured() -> Giveaway | None:
    """Ссылка на NFT и срок — единственные обязательные настройки."""
    campaign = os.getenv("NFT_GIVEAWAY_ID", "nft-2026").strip().lower()
    nft_url = os.getenv("NFT_GIVEAWAY_URL", "").strip()
    deadline = os.getenv("NFT_GIVEAWAY_CLOSE_AT", "").strip()
    if not re.fullmatch(r"[a-z0-9_-]{1,32}", campaign) or not valid_nft_url(nft_url):
        return None
    try:
        dt = datetime.fromisoformat(deadline)
        if dt.tzinfo is None:
            return None
        close_at = int(dt.timestamp())
    except (TypeError, ValueError, OverflowError):
        return None
    return Giveaway(campaign, nft_url, close_at, dt.astimezone(timezone(timedelta(hours=5))).strftime("%d.%m.%Y %H:%M МГН"))


def _message(g: Giveaway) -> str:
    if time.time() >= g.close_at:
        return (
            "🎁 Розыгрыш NFT\n\n"
            f"NFT: {g.nft_url}\n\n"
            "Приём новых заявок завершён.\n"
            "Проверь свои билеты кнопкой ниже."
        )
    return (
        "🎁 Розыгрыш NFT\n\n"
        f"NFT: {g.nft_url}\n\n"
        f"Стоимость одного билета: {TICKET_PRICE_RUB} ₽. Можно купить несколько.\n"
        f"Приём заявок до {g.deadline}.\n\n"
        "Билет выдаётся только после подтверждения оплаты."
    )


def _keyboard(payment_enabled: bool = True) -> InlineKeyboardMarkup:
    rows = []
    if payment_enabled:
        rows.append([InlineKeyboardButton(
            text=f"Купить билет · {TICKET_PRICE_RUB} ₽", callback_data="nft:buy"
        )])
    rows.append([InlineKeyboardButton(text="Мои билеты", callback_data="nft:status")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _payment_keyboard(payment_id: str, pay_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Оплатить {TICKET_PRICE_RUB} ₽", url=pay_url)],
        [InlineKeyboardButton(
            text="Проверить оплату", callback_data=NFT_CHECK_PREFIX + payment_id
        )],
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
        await con.execute("""
            CREATE TABLE IF NOT EXISTS nft_giveaway_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                payment_id TEXT NOT NULL UNIQUE,
                joined_at INTEGER NOT NULL
            )
        """)
        await con.execute(
            "CREATE INDEX IF NOT EXISTS idx_nft_tickets_campaign "
            "ON nft_giveaway_tickets(campaign,id)"
        )
        await con.execute(
            "CREATE INDEX IF NOT EXISTS idx_nft_tickets_user "
            "ON nft_giveaway_tickets(campaign,user_id,id)"
        )
        # Preserve tickets created by the former free-entry implementation.
        await con.execute("""
            INSERT OR IGNORE INTO nft_giveaway_tickets
                (id,campaign,user_id,payment_id,joined_at)
            SELECT id,campaign,user_id,'legacy:' || campaign || ':' || user_id,joined_at
              FROM nft_giveaway_entries
        """)
        await con.commit()


async def _active(db: Database) -> Giveaway | None:
    await _init(db.path)
    row = await db._fetchone(
        "SELECT campaign,prize,close_at,deadline FROM nft_giveaway_campaigns "
        "ORDER BY created_at DESC,campaign DESC LIMIT 1"
    )
    if row:
        return Giveaway(
            str(row["campaign"]), str(row["prize"]), int(row["close_at"]),
            str(row["deadline"]),
        )
    return _configured()


async def _save_campaign(db: Database, nft_url: str, close_at: int,
                         deadline: str) -> Giveaway:
    if not valid_nft_url(nft_url):
        raise ValueError("Нужна ссылка HTTPS на NFT.")
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
            (campaign, nft_url, close_at, deadline, "", int(time.time())),
        )
        await con.commit()
    return Giveaway(campaign, nft_url, close_at, deadline)


async def _ticket_number(con: aiosqlite.Connection, campaign: str, entry_id: int) -> int:
    # Stable sequence starting at 1 in each campaign, even when old global IDs are large.
    row = await (await con.execute(
        "SELECT COUNT(*) FROM nft_giveaway_tickets WHERE campaign=? AND id<=?",
        (campaign, entry_id),
    )).fetchone()
    return int(row[0])


async def _ticket_numbers(path, campaign: str, user_id: int) -> list[int]:
    await _init(path)
    async with aiosqlite.connect(path, timeout=15.0) as con:
        rows = await (await con.execute(
            "SELECT id FROM nft_giveaway_tickets WHERE campaign=? AND user_id=? ORDER BY id",
            (campaign, user_id),
        )).fetchall()
        return [await _ticket_number(con, campaign, int(row[0])) for row in rows]


async def _issue_paid_ticket(path, payment_id: str) -> tuple[int, bool]:
    """Atomically mark a verified RollyPay payment paid and issue one ticket."""
    await _init(path)
    async with aiosqlite.connect(path, timeout=15.0) as con:
        con.row_factory = aiosqlite.Row
        await con.execute("PRAGMA busy_timeout=10000")
        await con.execute("BEGIN IMMEDIATE")
        payment = await (await con.execute(
            "SELECT * FROM sbp_payments WHERE payment_id=?", (str(payment_id),)
        )).fetchone()
        if payment is None:
            await con.rollback()
            raise ValueError("Payment not found")
        kind = str(payment["kind"] or "")
        if not kind.startswith("nft_ticket:") or int(payment["amount_rub"]) != TICKET_PRICE_RUB:
            await con.rollback()
            raise ValueError("Payment is not an NFT ticket order")
        campaign = kind.split(":", 1)[1]
        existing = await (await con.execute(
            "SELECT id FROM nft_giveaway_tickets WHERE payment_id=?", (str(payment_id),)
        )).fetchone()
        if existing:
            number = await _ticket_number(con, campaign, int(existing[0]))
            await con.commit()
            return number, False
        winner = await (await con.execute(
            "SELECT 1 FROM nft_giveaway_winners WHERE campaign=?", (campaign,)
        )).fetchone()
        if winner:
            await con.rollback()
            raise ValueError("Giveaway already drawn")
        cur = await con.execute(
            "INSERT INTO nft_giveaway_tickets(campaign,user_id,payment_id,joined_at) "
            "VALUES (?,?,?,?)",
            (campaign, int(payment["user_id"]), str(payment_id), int(time.time())),
        )
        await con.execute(
            "UPDATE sbp_payments SET status='paid',paid_at=? WHERE payment_id=?",
            (int(time.time()), str(payment_id)),
        )
        number = await _ticket_number(con, campaign, int(cur.lastrowid))
        await con.commit()
        return number, True


async def _count(path, campaign: str) -> int:
    await _init(path)
    async with aiosqlite.connect(path) as con:
        row = await (await con.execute(
            "SELECT COUNT(*) FROM nft_giveaway_tickets WHERE campaign=?",
            (campaign,),
        )).fetchone()
        return int(row[0])


async def _pending_nft_orders(path, campaign: str) -> int:
    """Invoices that may still be paid and must be reconciled before a draw."""
    await _init(path)
    async with aiosqlite.connect(path, timeout=15.0) as con:
        row = await (await con.execute(
            "SELECT COUNT(*) FROM sbp_payments WHERE kind=? "
            "AND status IN ('creating','awaiting_payment','pending','processing','created')",
            (f"nft_ticket:{campaign}",),
        )).fetchone()
        return int(row[0])


async def _reconcile_pending_nft_orders(db: Database, cfg, campaign: str) -> None:
    """Best-effort provider verification before an early draw.

    Only provider receipts with matching order, payment ID, RUB amount and
    paid status may mint a ticket. Uncertain orders remain pending and block
    winner selection. Limit the batch so a Telegram callback is responsive.
    """
    await _init(db.path)
    rows = await db._fetchall(
        "SELECT payment_id,order_id,amount_rub FROM sbp_payments "
        "WHERE kind=? AND status IN "
        "('awaiting_payment','pending','processing','created') "
        "AND payment_id NOT LIKE 'creating:%' "
        "ORDER BY created_at LIMIT 12",
        (f"nft_ticket:{campaign}",),
    )
    if not rows or not cfg.rollypay_enabled:
        return
    limit = asyncio.Semaphore(4)

    async def check(row) -> None:
        async with limit:
            payment_id = str(row["payment_id"])
            try:
                remote = await get_payment(cfg, payment_id)
                value = Decimal(str(remote.get("amount", remote.get("payment_amount"))))
                valid = (
                    str(remote.get("payment_id") or "") == payment_id
                    and str(remote.get("order_id") or "") == str(row["order_id"])
                    and str(remote.get("currency") or remote.get("payment_currency") or "").upper() == "RUB"
                    and value.is_finite() and value == Decimal(TICKET_PRICE_RUB)
                    and int(row["amount_rub"]) == TICKET_PRICE_RUB
                )
                if not valid:
                    return
                status = str(remote.get("status") or "").lower()
                if status == "paid":
                    await _issue_paid_ticket(db.path, payment_id)
                elif status in {"failed", "canceled", "cancelled", "expired"}:
                    await db.set_sbp_status(payment_id, status)
            except (RollyPayError, ValueError, ArithmeticError, TypeError):
                # Never treat an unverified provider response as a paid ticket.
                return

    await asyncio.gather(*(check(row) for row in rows))


async def _finish_now(path, g: Giveaway) -> tuple[str, tuple[int, int, int] | None, int]:
    """Owner-only finalization: close intake, then draw once no unsettled SBP orders remain.

    Closing and winner selection share one IMMEDIATE transaction. An existing
    winner is returned unchanged. Existing payment links must be reconciled
    before selecting anyone, so confirmed buyers cannot be excluded silently.
    """
    await _init(path)
    closed_at = int(time.time()) - 1
    deadline = datetime.fromtimestamp(
        closed_at, timezone(timedelta(hours=5))
    ).strftime("%d.%m.%Y %H:%M МГН")
    async with aiosqlite.connect(path, timeout=15.0) as con:
        await con.execute("PRAGMA busy_timeout=10000")
        await con.execute("BEGIN IMMEDIATE")
        prior = await (await con.execute(
            "SELECT user_id, entry_id, entries_count FROM nft_giveaway_winners "
            "WHERE campaign=?", (g.campaign,),
        )).fetchone()
        if prior:
            ticket = await _ticket_number(con, g.campaign, int(prior[1]))
            await con.commit()
            return "already_drawn", (int(prior[0]), ticket, int(prior[2])), 0

        await con.execute(
            "INSERT INTO nft_giveaway_campaigns "
            "(campaign, prize, close_at, deadline, rules_url, created_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(campaign) DO UPDATE SET "
            "close_at=MIN(close_at, excluded.close_at), "
            "deadline=excluded.deadline",
            (g.campaign, g.nft_url, closed_at, deadline, "", closed_at),
        )
        pending = int((await (await con.execute(
            "SELECT COUNT(*) FROM sbp_payments WHERE kind=? "
            "AND status IN ('creating','awaiting_payment','pending','processing','created')",
            (f"nft_ticket:{g.campaign}",),
        )).fetchone())[0])
        if pending:
            await con.commit()
            return "pending", None, pending

        total = int((await (await con.execute(
            "SELECT COUNT(*) FROM nft_giveaway_tickets WHERE campaign=?",
            (g.campaign,),
        )).fetchone())[0])
        if not total:
            await con.commit()
            return "empty", None, 0

        picked = await (await con.execute(
            "SELECT user_id,id FROM nft_giveaway_tickets WHERE campaign=? "
            "ORDER BY id LIMIT 1 OFFSET ?",
            (g.campaign, secrets.randbelow(total)),
        )).fetchone()
        user_id, entry_id = int(picked[0]), int(picked[1])
        await con.execute(
            "INSERT INTO nft_giveaway_winners "
            "(campaign,user_id,entry_id,entries_count,drawn_at) VALUES (?,?,?,?,?)",
            (g.campaign, user_id, entry_id, total, int(time.time())),
        )
        ticket = await _ticket_number(con, g.campaign, entry_id)
        await con.commit()
        return "drawn", (user_id, ticket, total), 0


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
            return (int(prior[0]),
                    await _ticket_number(con, g.campaign, int(prior[1])),
                    int(prior[2]))
        if time.time() < g.close_at:
            await con.commit()
            return None
        pending = int((await (await con.execute(
            "SELECT COUNT(*) FROM sbp_payments WHERE kind=? "
            "AND status IN ('creating','awaiting_payment','pending','processing','created')",
            (f"nft_ticket:{g.campaign}",),
        )).fetchone())[0])
        if pending:
            await con.commit()
            return None
        total = int((await (await con.execute(
            "SELECT COUNT(*) FROM nft_giveaway_tickets WHERE campaign=?", (g.campaign,)
        )).fetchone())[0])
        if not total:
            await con.commit()
            return None
        picked = await (await con.execute(
            "SELECT user_id,id FROM nft_giveaway_tickets WHERE campaign=? ORDER BY id LIMIT 1 OFFSET ?",
            (g.campaign, secrets.randbelow(total)),
        )).fetchone()
        user_id, entry_id = int(picked[0]), int(picked[1])
        await con.execute(
            "INSERT INTO nft_giveaway_winners(campaign,user_id,entry_id,entries_count,drawn_at) "
            "VALUES (?,?,?,?,?)",
            (g.campaign, user_id, entry_id, total, int(time.time())),
        )
        ticket = await _ticket_number(con, g.campaign, entry_id)
        await con.commit()
        return user_id, ticket, total


@router.message(CommandStart(), F.text.regexp(r"^/start(?:@\w+)? nft$"))
async def nft_from_channel(message: Message, ctx: Ctx, db: Database) -> None:
    """Direct link from a Telegram channel opens the giveaway, not the main menu."""
    g = await _active(db)
    if not g:
        await ctx.reply("NFT-розыгрыш пока не открыт.")
        return
    await ctx.reply(html.escape(_message(g)), _keyboard(
        ctx.cfg.rollypay_enabled and time.time() < g.close_at
    ))


@router.message(Command("nft"))
async def nft_open(message: Message, ctx: Ctx, db: Database) -> None:
    g = await _active(db)
    if not g:
        await ctx.reply("NFT-розыгрыш пока не открыт.")
        return
    await ctx.reply(html.escape(_message(g)), _keyboard(
        ctx.cfg.rollypay_enabled and time.time() < g.close_at
    ))


async def _start_ticket_purchase(ctx: Ctx, db: Database) -> None:
    g = await _active(db)
    if not g:
        await ctx.reply("Розыгрыш пока не открыт.")
        return
    if await ctx.restricted():
        await ctx.reply("Участие недоступно.")
        return
    if time.time() >= g.close_at:
        await ctx.reply("Продажа билетов завершена.")
        return
    if not ctx.cfg.rollypay_enabled:
        await ctx.reply("Оплата рублями временно недоступна.")
        return
    order_id = f"nft-{g.campaign}-{ctx.user_id}-{secrets.token_hex(5)}"
    local_id = ""
    try:
        local_id = await db.create_sbp_order(
            order_id=order_id, user_id=ctx.user_id,
            kind=f"nft_ticket:{g.campaign}", amount_rub=TICKET_PRICE_RUB,
        )
        # An owner may close the campaign while the buyer is opening checkout.
        # Do not create an external payment if intake closed meanwhile.
        current = await _active(db)
        if current is None or current.campaign != g.campaign or time.time() >= current.close_at:
            await db.set_sbp_status(local_id, "cancelled")
            await ctx.reply("Приём новых билетов завершён.")
            return
        payment = await create_payment(
            ctx.cfg, order_id=order_id, amount=Decimal(TICKET_PRICE_RUB),
            description="АНОН МГН · Билет NFT-розыгрыша", user_id=ctx.user_id,
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
        await ctx.reply("Не удалось создать платёж. Попробуй немного позже.")
        return
    await ctx.reply(
        "🎟 <b>Билет NFT-розыгрыша</b>\n\n"
        f"К оплате: <b>{TICKET_PRICE_RUB} ₽</b>.\n"
        "После оплаты обязательно нажми «Проверить оплату».\n"
        "Каждый подтверждённый платёж выдаёт один новый билет.",
        _payment_keyboard(payment_id, pay_url),
    )


@router.callback_query(F.data.in_({"nft:buy", "nft:join"}))
async def nft_buy(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    await ctx.ack()
    await _start_ticket_purchase(ctx, db)


@router.callback_query(F.data.startswith(NFT_CHECK_PREFIX))
async def nft_check_payment(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    payment_id = str(event.data or "")[len(NFT_CHECK_PREFIX):]
    local = await db.get_sbp_payment(payment_id)
    if (
        not local or int(local["user_id"]) != ctx.user_id
        or not str(local["kind"] or "").startswith("nft_ticket:")
        or int(local["amount_rub"]) != TICKET_PRICE_RUB
    ):
        await ctx.ack("Платёж не найден", alert=True)
        return
    if str(local["status"] or "").lower() != "paid":
        try:
            remote = await get_payment(ctx.cfg, payment_id)
        except RollyPayError:
            await ctx.ack("Не удалось проверить оплату. Попробуй позже.", alert=True)
            return
        amount = remote.get("amount", remote.get("payment_amount"))
        currency = remote.get("currency", remote.get("payment_currency"))
        matches = (
            str(remote.get("payment_id") or "") == payment_id
            and str(remote.get("order_id") or "") == str(local["order_id"])
            and str(currency or "").upper() == "RUB"
        )
        try:
            matches = matches and Decimal(str(amount)) == Decimal(TICKET_PRICE_RUB)
        except Exception:
            matches = False
        if not matches:
            await ctx.ack("Данные платежа не совпали", alert=True)
            return
        status = str(remote.get("status") or "").lower()
        if status != "paid":
            if status in {
                "created", "pending", "processing", "awaiting_payment",
                "failed", "cancelled", "canceled", "expired",
            }:
                await db.set_sbp_status(payment_id, status)
            await ctx.ack("Оплата ещё не поступила", alert=True)
            return
    try:
        ticket, fresh = await _issue_paid_ticket(db.path, payment_id)
    except ValueError:
        await ctx.ack("Не удалось выдать билет. Обратись в поддержку.", alert=True)
        return
    await ctx.ack("Билет выдан!" if fresh else "Этот платёж уже учтён")
    await ctx.reply(
        f"🎟 <b>Билет №{ticket}</b>\n\n"
        "Оплата подтверждена. Билет участвует в NFT-розыгрыше."
    )


@router.callback_query(F.data == "nft:status")
async def nft_status(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    g = await _active(db)
    if not g:
        await ctx.ack("Розыгрыш пока не открыт.", alert=True)
        return
    tickets = await _ticket_numbers(db.path, g.campaign, ctx.user_id)
    await ctx.ack()
    if tickets:
        numbers = ", ".join(f"№{number}" for number in tickets)
        await ctx.reply(
            f"🎟 Твои билеты: <b>{html.escape(numbers)}</b>.\n"
            f"Всего: <b>{len(tickets)}</b>. Все участвуют в розыгрыше.",
            _keyboard(ctx.cfg.rollypay_enabled) if time.time() < g.close_at else None,
        )
    elif time.time() >= g.close_at:
        await ctx.reply("Продажа билетов завершена.")
    else:
        await ctx.reply("У тебя пока нет билетов.", _keyboard(ctx.cfg.rollypay_enabled))


@router.message(Command("nft_broadcast"))
async def nft_broadcast_preview(message: Message, ctx: Ctx, db: Database) -> None:
    if not (ctx.is_owner or ctx.can("broadcast")):
        return
    g = await _active(db)
    if not g:
        await ctx.reply(
            "Сначала создай розыгрыш через /nft_setup: "
            "нужна только ссылка на NFT и дата окончания."
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
    preview_id = int(event.message.message_id) if event.message else 0
    key = f"nft-giveaway-{g.campaign}-{ctx.user_id}-{preview_id}"
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
    await ctx.reply(f"NFT-розыгрыш · продано билетов: <b>{total}</b>.\n"
                    f"Закрытие: {html.escape(g.deadline)}.")


@router.message(Command("nft_finish"))
async def nft_finish_preview(message: Message, ctx: Ctx, db: Database) -> None:
    """Give the owner an explicit confirmation before ending a public campaign."""
    if not ctx.is_owner or message.chat.type != "private":
        return
    g = await _active(db)
    if g is None:
        await ctx.reply("Нет активного NFT-розыгрыша.")
        return
    count = await _count(db.path, g.campaign)
    pending = await _pending_nft_orders(db.path, g.campaign)
    body = (
        "🏁 <b>Досрочно подвести итоги NFT?</b>\n\n"
        f"Билетов: <b>{count}</b>\n"
        f"Непроверенных СБП-заказов: <b>{pending}</b>\n\n"
        "После подтверждения приём новых билетов закроется. "
        "Победитель будет выбран случайно и сохранён навсегда.\n\n"
        "Важно: в опубликованном посте была другая дата. "
        "Объяви исправление подписчикам."
    )
    if pending:
        body += (
            "\n\nЕсли есть неоплаченные или неподтверждённые счета, "
            "бот сначала остановит приём билетов и не выберет победителя, "
            "пока платежи не будут проверены."
        )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Завершить и подвести итоги",
            callback_data=f"nft:finish:{g.campaign}",
        )],
        [InlineKeyboardButton(text="Отмена", callback_data="nft:finish_cancel")],
    ])
    await ctx.reply(body, keyboard)


@router.callback_query(F.data == "nft:finish_cancel")
async def nft_finish_cancel(event: CallbackQuery, ctx: Ctx) -> None:
    if not ctx.is_owner:
        await ctx.ack("Недостаточно прав", alert=True)
        return
    await ctx.ack("Отменено")
    await ctx.edit("Досрочное завершение отменено.")


@router.callback_query(F.data.startswith("nft:finish:"))
async def nft_finish_confirm(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    if not ctx.is_owner or not event.message or event.message.chat.type != "private":
        await ctx.ack("Недостаточно прав", alert=True)
        return
    g = await _active(db)
    campaign = (event.data or "").removeprefix("nft:finish:")
    if not g or campaign != g.campaign:
        await ctx.ack("Предпросмотр устарел. Вызови /nft_finish заново.", alert=True)
        return
    # Existing invoices may have been paid even if the customer did not
    # press the verification button. Reconcile them before choosing a winner.
    await ctx.ack()
    await _reconcile_pending_nft_orders(db, ctx.cfg, g.campaign)
    status, result, pending = await _finish_now(db.path, g)
    if status == "pending":
        await ctx.reply(
            "⛔ <b>Приём новых билетов остановлен.</b>\n\n"
            f"Осталось непроверенных заказов СБП: <b>{pending}</b>.\n"
            "Попроси покупателей проверить оплату кнопкой в боте. "
            "Когда все счета будут разрешены, снова введи /nft_finish."
        )
        return
    if status == "empty":
        await ctx.reply(
            "Приём закрыт, но оплаченных билетов нет. "
            "Победителя выбирать не из кого."
        )
        return
    if result is None:
        await ctx.reply("Не удалось подвести итоги. Проверь состояние розыгрыша.")
        return
    user_id, ticket, total = result
    await ctx.reply(
        ("🏆 <b>Итоги уже подведены</b>\n\n" if status == "already_drawn"
         else "🏆 <b>Розыгрыш завершён досрочно!</b>\n\n")
        + f"Победитель: ID <code>{user_id}</code>\n"
        f"Билет: <b>№{ticket}</b>\n"
        f"Всего билетов: <b>{total}</b>\n\n"
        "Результат сохранён. Опубликуй его в канале и уведомь победителя."
    )


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
        await ctx.reply(
            "Итоги пока недоступны: розыгрыш не закрыт, нет билетов "
            "или есть незавершённые платежи СБП. "
            "Для досрочного завершения используй /nft_finish."
        )
        return
    user_id, ticket, total = result
    await ctx.reply(
        f"Победитель: ID <code>{user_id}</code>, билет <b>№{ticket}</b>. "
        f"Всего заявок: <b>{total}</b>. Результат сохранён."
    )
