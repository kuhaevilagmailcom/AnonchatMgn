"""Persistent, single-process Telegram broadcasts with recipient-level delivery state.

An uncertain Telegram response is NOT automatically resent: this prevents
accidental duplicate messages after a crash between send and acknowledgement.
"""
from __future__ import annotations

import asyncio
import logging
import time

import aiosqlite
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter, TelegramNetworkError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

log = logging.getLogger(__name__)


async def create_job(db, *, key: str, actor: int, message: str, button_text: str = "",
                     button_url: str = "", recipient_ids: list[int] | None = None) -> bool:
    async with aiosqlite.connect(db.path, isolation_level=None) as con:
        await con.execute("PRAGMA busy_timeout=10000")
        await con.execute("BEGIN IMMEDIATE")
        try:
            stamp = int(time.time())
            created = await con.execute(
                """INSERT OR IGNORE INTO admin_action_log
                   (action_key,actor_id,target_id,action,reason,created_at)
                   VALUES (?,?,0,'broadcast',?,?)""",
                (key, int(actor), f"Broadcast ({len(message)} chars)", stamp),
            )
            if not created.rowcount:
                await con.rollback()
                return False
            await con.execute(
                """INSERT INTO admin_broadcast_jobs
                   (job_key,actor_id,message,button_text,button_url,status,created_at)
                   VALUES (?,?,?,?,?,'running',?)""",
                (key, int(actor), message, button_text, button_url, stamp),
            )
            if recipient_ids is None:
                await con.execute(
                    """INSERT INTO admin_broadcast_targets(job_key,user_id)
                       SELECT ?,user_id FROM users WHERE banned=0""",
                    (key,),
                )
            else:
                await con.executemany(
                    "INSERT OR IGNORE INTO admin_broadcast_targets(job_key,user_id) VALUES (?,?)",
                    [(key, uid) for uid in sorted(set(int(x) for x in recipient_ids if int(x)>0))],
                )
            await con.commit()
            return True
        except BaseException:
            await con.rollback()
            raise


async def job_status(db, key: str) -> dict:
    job = await db._fetchone(
        "SELECT status,created_at,finished_at FROM admin_broadcast_jobs WHERE job_key=?",
        (key,),
    )
    if not job:
        return {"status": "unknown", "sent": 0, "failed": 0, "pending": 0, "uncertain": 0}
    rows = await db._fetchall(
        "SELECT status,COUNT(*) count FROM admin_broadcast_targets WHERE job_key=? GROUP BY status",
        (key,),
    )
    counts = {str(row["status"]): int(row["count"]) for row in rows}
    return {
        "status": str(job["status"]),
        "sent": counts.get("sent", 0),
        "failed": counts.get("failed", 0),
        "pending": counts.get("pending", 0) + counts.get("sending", 0),
        "uncertain": counts.get("uncertain", 0),
        "total": sum(counts.values()),
        "created_at": int(job["created_at"]),
        "finished_at": int(job["finished_at"]),
    }


async def run_once(bot, db) -> bool:
    job = await db._fetchone(
        "SELECT * FROM admin_broadcast_jobs WHERE status='running' ORDER BY created_at,job_key LIMIT 1"
    )
    if not job:
        return False
    key = str(job["job_key"])
    recipient = await db._fetchone(
        """SELECT user_id,attempts FROM admin_broadcast_targets
           WHERE job_key=? AND status='pending' AND next_retry_at<=?
           ORDER BY user_id LIMIT 1""",
        (key, int(time.time())),
    )
    if not recipient:
        row = await db._fetchone(
            "SELECT COUNT(*) count FROM admin_broadcast_targets WHERE job_key=? AND status='pending'", (key,)
        )
        if not int(row["count"]):
            unresolved=await db._fetchone(
                "SELECT COUNT(*) count FROM admin_broadcast_targets WHERE job_key=? AND status='uncertain'",
                (key,),
            )
            final_status="review" if int(unresolved["count"] or 0) else "completed"
            await db.db.execute(
                "UPDATE admin_broadcast_jobs SET status=?,finished_at=? WHERE job_key=? AND status='running'",
                (final_status,int(time.time()),key),
            )
        return False

    uid = int(recipient["user_id"])
    changed = await db.db.execute(
        """UPDATE admin_broadcast_targets
           SET status='sending',attempts=attempts+1
           WHERE job_key=? AND user_id=? AND status='pending'""",
        (key, uid),
    )
    if not changed.rowcount:
        return False
    # Poll notification buttons vote directly, without exposing another user's ID.
    # A new/closed poll invalidates any unsent old notification.
    poll_url = str(job["button_url"] or "")
    if poll_url.startswith("poll:") and poll_url[5:].isdigit():
        poll_id = int(poll_url[5:])
        active = await db._fetchone(
            "SELECT active,option_a,option_b FROM polls WHERE id=?", (poll_id,)
        )
        if active is None or not int(active["active"]):
            await db.db.execute(
                "UPDATE admin_broadcast_jobs SET status='stopped',finished_at=? WHERE job_key=?",
                (int(time.time()), key),
            )
            await db.db.execute(
                "UPDATE admin_broadcast_targets SET status='failed',last_error='poll_closed' "
                "WHERE job_key=? AND user_id=? AND status='sending'", (key,uid)
            )
            return False
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"1️⃣ {str(active['option_a'])[:48]}",callback_data=f"poll:vote:{poll_id}:0")],
            [InlineKeyboardButton(text=f"2️⃣ {str(active['option_b'])[:48]}",callback_data=f"poll:vote:{poll_id}:1")],
        ])
    else:
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=job["button_text"],url=job["button_url"])
        ]]) if job["button_url"] else None
    try:
        result = await bot.send_message(
            uid, str(job["message"]), parse_mode=None,reply_markup=markup,
            disable_web_page_preview=True,
        )
    except TelegramForbiddenError:
        state, error, retry_at = "failed", "blocked", 0
    except TelegramRetryAfter as exc:
        state, error, retry_at = "pending", "retry_after", int(time.time()) + min(3600,max(1,int(exc.retry_after)+1))
    except TelegramNetworkError:
        state, error, retry_at = "uncertain", "network_unknown_delivery", 0
    except TelegramAPIError as exc:
        state, error, retry_at = "failed", type(exc).__name__[:80], 0
    except Exception:
        log.exception("Broadcast delivery error, job %s",key)
        state, error, retry_at = "uncertain", "unexpected_unknown_delivery", 0
    else:
        state, error, retry_at = "sent", "", 0
    await db.db.execute(
        """UPDATE admin_broadcast_targets
           SET status=?,last_error=?,next_retry_at=?,telegram_message_id=?
           WHERE job_key=? AND user_id=?""",
        (state,error,retry_at,int(getattr(result, "message_id", 0) or 0) if state=="sent" else 0,key,uid),
    )
    return True


async def run_worker(bot, db) -> None:
    # Any 'sending' recipient during a crash might have received the message.
    # Surface this for manual review rather than automatically resending.
    await db.db.execute(
        "UPDATE admin_broadcast_targets SET status='uncertain',last_error='interrupted_restart' WHERE status='sending'"
    )
    while True:
        try:
            busy = await run_once(bot, db)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Broadcast worker failed")
            busy = False
        await asyncio.sleep(0.08 if busy else 2)
