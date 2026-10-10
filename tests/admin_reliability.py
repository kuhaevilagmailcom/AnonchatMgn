"""Durability regression tests: run with python -m tests.admin_reliability."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace

from anonchat.admin_events import deliver_batch, notice
from anonchat.admin_broadcasts import create_job, job_status, run_once
from anonchat.fsm_storage import SQLiteFSMStorage
from anonchat.backups import maybe_backup
from anonchat.matching import Matchmaker
from aiogram.fsm.storage.base import StorageKey
import time
from anonchat.db import Database, referral_day_start


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[dict] = []
    async def send_message(self, chat_id: int, text: str, **kw):
        self.sent.append({"chat_id":chat_id,"text":text,**kw})
        return SimpleNamespace(message_id=len(self.sent))


async def scenario() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "reliability.db"
        db = await Database(path).start()
        bot = FakeBot()
        try:
            fsm=SQLiteFSMStorage(db)
            fsmkey=StorageKey(bot_id=42,chat_id=801001,user_id=801001)
            await fsm.set_state(fsmkey,"admin:waiting_reason")
            await fsm.set_data(fsmkey,{"target":801002,"action":"mute"})
            await db.ensure_user(801001,"first","First")
            await db.ensure_user(801002,"second","Second")
            await db.set_ban(801002, True, "Спам")
            await db.set_ban(801002, True, "Спам")
            before = await db._fetchone(
                "SELECT COUNT(*) count FROM admin_notice_outbox WHERE user_id=801002 AND kind='ban'")
            assert before["count"]==1,"A repeated unchanged ban cannot create multiple notices"
            ban_event=await db._fetchone(
                "SELECT title,text FROM miniapp_events WHERE user_id=801002 ORDER BY id DESC LIMIT 1")
            assert "заблокированы" in ban_event["title"].lower() and "Спам" in ban_event["text"]
            await db.set_ban(801002,False)
            await db.set_ban(801002,True,"Временная блокировка",minutes=1)
            assert (await db.get_user(801002))["ban_until"]>0
            expired_at=int(time.time())-1
            await db.db.execute("UPDATE users SET ban_until=? WHERE user_id=?",(expired_at,801002))
            await db.db.execute("UPDATE active_ban_expirations SET until_at=? WHERE user_id=?",(expired_at,801002))
            assert await db.expire_bans()==1
            assert (await db.get_user(801002))["banned"]==0
            assert await db.expire_bans()==0
            await db.set_mute(801002,60,reason="Нарушение правил")
            muted=await db.get_user(801002)
            assert muted["mute_until"]>0
            await db.set_mute(801002,0,reason="Досрочно")
            await db.set_mute(801002,1,reason="Тест автоокончания")
            old_stamp=int(time.time())-1
            await db.db.execute("UPDATE users SET mute_until=? WHERE user_id=?",(old_stamp,801002))
            await db.db.execute("UPDATE active_mute_expirations SET until_at=? WHERE user_id=?",(old_stamp,801002))
            assert await db.expire_mutes()==1
            assert (await db.get_user(801002))["mute_until"]==0
            assert await db.expire_mutes()==0
            after,applied=await db.change_xp(
                801002,100,source="admin_award",reason="Компенсация",
                actor_id=801001,idempotency_key="admin-test-reliability-000001")
            assert applied and after>=100
            _after,repeated=await db.change_xp(
                801002,100,source="admin_award",reason="Компенсация",
                actor_id=801001,idempotency_key="admin-test-reliability-000001")
            assert not repeated
            xp_notices=await db._fetchone(
                "SELECT COUNT(*) count FROM admin_notice_outbox WHERE user_id=801002 AND kind='points'")
            assert xp_notices["count"]==1,"Idempotent XP change must produce one notice"
            assert "Компенсация" in notice("points",reason="Компенсация",amount=100,balance=100)[1]

            await db.close()
            db = await Database(path).start()
            restored=SQLiteFSMStorage(db)
            assert await restored.get_state(fsmkey)=="admin:waiting_reason"
            assert await restored.get_data(fsmkey)=={"target":801002,"action":"mute"}
            pending=await db._fetchone("SELECT COUNT(*) count FROM admin_notice_outbox WHERE status='pending'")
            assert pending["count"]>=4,"Unsent notices survive an actual database reopen"
            count=await deliver_batch(bot,db)
            assert count>=4 and len(bot.sent)==count
            assert (await deliver_batch(bot,db))==0

            backup=await maybe_backup(db,Matchmaker(),force=True)
            assert backup and Path(backup).is_file()
            started=await create_job(db,key="test-broadcast-job-001",actor=801001,message="Test message")
            assert started
            assert not await create_job(db,key="test-broadcast-job-001",actor=801001,message="Test message")
            progress=await job_status(db,"test-broadcast-job-001")
            assert progress["total"]==2 and progress["sent"]==0
            assert await run_once(bot,db)
            await db.close()
            db=await Database(path).start()
            assert await run_once(bot,db)
            await run_once(bot,db)
            progress=await job_status(db,"test-broadcast-job-001")
            assert progress["sent"]==2 and progress["status"]=="completed",progress
            assert len([x for x in bot.sent if x["text"]=="Test message"])==2
        finally:
            await db.close()



async def poll_notifications_and_message_statistics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = await Database(Path(tmp) / "poll-notifications.db").start()
        bot = FakeBot()
        try:
            await db.ensure_user(901, "first", "First")
            await db.ensure_user(902, "second", "Second")
            await db.db.execute("UPDATE users SET messages=19 WHERE user_id=901")
            local_today = referral_day_start()
            await db.activity_add(901, timestamp=local_today + 30, messages=4)
            await db.activity_add(901, timestamp=local_today - 86400 + 30, messages=3)
            await db.activity_add(901, timestamp=local_today - 6 * 86400 + 30, messages=5)
            await db.activity_add(901, timestamp=local_today - 7 * 86400 + 30, messages=7)
            summary = await db.stats()
            assert summary["messages_today"] == 4, summary
            assert summary["messages_week"] == 12, summary
            assert summary["messages"] == 19, summary

            poll_id = await db.create_poll(
                "Участвуешь?", "Конечно", "Нет", 901,
                audience="admins", admin_ids=(901, 903),
            )
            key = f"poll:{poll_id}"
            progress = await job_status(db, key)
            assert progress["total"] == 2, progress
            assert await run_once(bot, db)
            sent = bot.sent[-1]
            assert sent["chat_id"] == 901
            assert "Новый опрос" in sent["text"]
            buttons = sent["reply_markup"].inline_keyboard
            assert [b[0].callback_data for b in buttons] == [
                f"poll:vote:{poll_id}:0", f"poll:vote:{poll_id}:1"
            ]
            await run_once(bot, db)
            await run_once(bot, db)
            assert (await job_status(db, key))["status"] == "completed"
            assert len(bot.sent) == 2, bot.sent

            all_poll = await db.create_poll("Второй?", "Да", "Нет", 901)
            all_key = f"poll:{all_poll}"
            assert (await job_status(db, all_key))["total"] == 2
            await run_once(bot, db)
            assert len(bot.sent) == 3
            replacement = await db.create_poll("Третий?", "1", "2", 901)
            assert (await job_status(db, all_key))["status"] == "stopped"
            assert await db.close_active_poll()
            assert (await job_status(db, f"poll:{replacement}"))["status"] == "stopped"
            for _ in range(3):
                await run_once(bot, db)
            assert len(bot.sent) == 3, "Closed/overridden polls must not send"

            with_closed = False
            try:
                await db.create_poll("invalid", "1", "2", 901, audience="unknown")
            except ValueError:
                with_closed = True
            assert with_closed

            admin_job = "test-broadcast-admins-only-001"
            assert await create_job(
                db, key=admin_job, actor=901, message="Only administrators",
                recipient_ids=[901],
            )
            assert (await job_status(db, admin_job))["total"] == 1
            await run_once(bot, db)
            await run_once(bot, db)
            assert bot.sent[-1]["chat_id"] == 901
            assert bot.sent[-1]["text"] == "Only administrators"
        finally:
            await db.close()


def test_poll_notifications() -> None:
    asyncio.run(poll_notifications_and_message_statistics())

def test_reliability() -> None:
    asyncio.run(scenario())


if __name__ == "__main__":
    test_reliability()
    test_poll_notifications()
    print("ok durable moderation notices, poll alerts, message periods and broadcasts")
