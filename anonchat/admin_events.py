"""Durable administrative notices, recorded alongside the corresponding mutation.

The Mini App event and Telegram delivery outbox share a transaction. The Telegram
sender runs independently so provider outages never roll back a moderation action.
"""
from __future__ import annotations

import asyncio
import html
import logging
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter

log = logging.getLogger(__name__)
LOCAL_TZ = ZoneInfo("Asia/Yekaterinburg")


def _time_local(ts: int) -> str:
    return datetime.fromtimestamp(ts, LOCAL_TZ).strftime("%d.%m.%Y, %H:%M (МГН)")


def _duration(minutes: int) -> str:
    n = max(1, int(minutes))
    for unit, size, words in (
        ("day", 1440, ("день", "дня", "дней")),
        ("hour", 60, ("час", "часа", "часов")),
        ("minute", 1, ("минута", "минуты", "минут")),
    ):
        if n % size == 0 or size == 1:
            value = n // size
            word = words[2] if value % 100 in (11, 12, 13, 14) or value % 10 in (0, 5, 6, 7, 8, 9) else words[0] if value % 10 == 1 else words[1]
            return f"{value} {word}"
    return f"{n} минут"


def notice(kind: str, *, reason: str = "", minutes: int = 0,
           until: int = 0, amount: int = 0, balance: int = 0) -> tuple[str, str]:
    why = (str(reason).strip() or "Решение модерации")[:500]
    if kind == "ban":
        return "🚫 Вы заблокированы в АНОН МГН", f"Причина: {why}\nСрок: Бессрочно.\nЕсли решение ошибочно, обратитесь в поддержку."
    if kind == "unban":
        return "✅ Блокировка снята", f"Причина: {why}\nВы снова можете пользоваться АНОН МГН."
    if kind == "mute":
        return "🔇 Вам ограничили общение", f"Причина: {why}\nСрок: {_duration(minutes)}.\nДо: {_time_local(until)}."
    if kind == "unmute":
        return "🔊 Ограничение общения снято", f"Причина: {why}\nВы снова можете общаться."
    if kind == "points":
        sign = "+" if amount > 0 else "−"
        title = "⭐ Вам начислены очки" if amount > 0 else "➖ С вашего баланса списаны очки"
        return title, f"Изменение: {sign}{abs(amount):,} ⭐\nПричина: {why}\nВаш баланс: {balance:,} ⭐".replace(",", " ")
    raise ValueError(f"Unknown administrative event: {kind}")


async def enqueue(conn, user_id: int, kind: str, *, reason: str = "",
                  minutes: int = 0, until: int = 0, amount: int = 0,
                  balance: int = 0, event_key: str = "") -> str:
    """Call inside the SAME BEGIN IMMEDIATE transaction as the actual action."""
    key = event_key or f"admin:{uuid.uuid4().hex}"
    title, body = notice(kind, reason=reason, minutes=minutes, until=until,
                         amount=amount, balance=balance)
    stamp = int(time.time())
    query = await conn.execute(
        """INSERT OR IGNORE INTO admin_notice_outbox
           (event_key,user_id,kind,title,body,status,created_at,next_attempt_at)
           VALUES (?,?,?,?,?,'pending',?,?)""",
        (key, int(user_id), kind, title, body, stamp, stamp),
    )
    if query.rowcount:
        await conn.execute(
            """INSERT INTO miniapp_events(user_id,type,icon,title,text,action,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (int(user_id), "moderation" if kind != "points" else "admin_points",
             "bell", title[:120], body[:500], "", stamp),
        )
    return key


async def deliver_batch(bot, db, *, limit: int = 30) -> int:
    """Deliver a bounded batch; never log full private notification text."""
    stamp = int(time.time())
    rows = await db._fetchall(
        """SELECT * FROM admin_notice_outbox
           WHERE status='pending' AND next_attempt_at<=?
           ORDER BY created_at,event_key LIMIT ?""",
        (stamp, max(1, min(int(limit), 100))),
    )
    done = 0
    for row in rows:
        key = str(row["event_key"])
        update = await db.db.execute(
            "UPDATE admin_notice_outbox SET status='sending',attempts=attempts+1 WHERE event_key=? AND status='pending'",
            (key,),
        )
        if not update.rowcount:
            continue
        try:
            title = html.escape(str(row["title"]))
            body = html.escape(str(row["body"]))
            result = await bot.send_message(int(row["user_id"]), f"<b>{title}</b>\n\n{body}")
        except TelegramForbiddenError:
            await db.db.execute(
                "UPDATE admin_notice_outbox SET status='undeliverable',last_error='bot_blocked' WHERE event_key=?",
                (key,),
            )
        except TelegramRetryAfter as exc:
            retry = max(1, min(3600, int(exc.retry_after) + 1))
            await db.db.execute(
                "UPDATE admin_notice_outbox SET status='pending',next_attempt_at=?,last_error='rate_limit' WHERE event_key=?",
                (int(time.time()) + retry, key),
            )
        except TelegramAPIError as exc:
            attempts = int(row["attempts"] or 0) + 1
            retry = min(3600, 2 ** min(attempts, 10))
            await db.db.execute(
                "UPDATE admin_notice_outbox SET status=?,next_attempt_at=?,last_error=? WHERE event_key=?",
                ("pending" if attempts < 8 else "failed", int(time.time()) + retry,
                 type(exc).__name__[:100], key),
            )
        except Exception:
            log.exception("Admin notice sender failed for event %s", key)
            await db.db.execute(
                "UPDATE admin_notice_outbox SET status='pending',next_attempt_at=?,last_error='unexpected' WHERE event_key=?",
                (int(time.time()) + 30, key),
            )
        else:
            await db.db.execute(
                "UPDATE admin_notice_outbox SET status='sent',sent_at=?,telegram_message_id=?,last_error='' WHERE event_key=?",
                (int(time.time()), int(getattr(result, "message_id", 0) or 0), key),
            )
            done += 1
    return done


async def run_worker(bot, db) -> None:
    """Startup recovery + bounded polling; pending events survive process death."""
    await db.db.execute(
        "UPDATE admin_notice_outbox SET status='pending',next_attempt_at=? WHERE status='sending'",
        (int(time.time()) + 10,),
    )
    while True:
        try:
            await deliver_batch(bot, db)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Administrative delivery loop failed")
        await asyncio.sleep(2)
