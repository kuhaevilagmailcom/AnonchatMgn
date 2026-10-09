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
from anonchat.db import Database


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


def test_reliability() -> None:
    asyncio.run(scenario())


if __name__ == "__main__":
    test_reliability()
    print("ok durable moderation notices and broadcasts across restart")
