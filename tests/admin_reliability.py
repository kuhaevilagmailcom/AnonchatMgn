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
    async def send_photo(self, chat_id: int, photo: str, **kw):
        self.sent.append({"chat_id":chat_id,"photo":photo,**kw})
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

            media_job = "test-broadcast-media-queue-001"
            assert await create_job(
                db, key=media_job, actor=901, message="Photo caption",
                photo_file_id="telegram-file-id", button_action="profile",
                recipient_ids=[901],
            )
            assert await run_once(bot, db)
            await run_once(bot, db)
            assert (await job_status(db, media_job))["status"] == "completed"
            assert bot.sent[-1]["photo"] == "telegram-file-id"
            assert bot.sent[-1]["caption"] == "Photo caption"
            assert bot.sent[-1]["reply_markup"] is not None
        finally:
            await db.close()


async def historical_month_archive() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp) / "archive.db"
        db=await Database(path).start()
        try:
            await db.ensure_user(901,"first","First")
            await db.ensure_user(902,"second","Second")
            now_day=referral_day_start()
            await db.log_dialog(901,902,3,5,now_day+100,None)
            await db.bump(901,"messages",3)
            await db.bump(902,"messages",5)
            current=await db.message_activity_days(7)
            assert current[-1]["messages"]==8,current
            await db.cleanup_daily_activity(retention_days=2)
            assert (await db.message_activity_days(7))[-1]["messages"]==8
            # Simulate completed matches from an older version before archiving.
            old_end=now_day-29*86400+3600
            await db.db.execute(
                """INSERT INTO matches(started_at,ended_at,user_a,user_b,msg_a,msg_b)
                   VALUES(?,?,?,?,?,?)""",
                (old_end-100,old_end,901,902,4,6),
            )
            await db.db.execute(
                "DELETE FROM kv WHERE key='message_daily_totals_matches_v1'"
            )
        finally:
            await db.close()
        db=await Database(path).start()
        try:
            old_day=referral_day_start(old_end)
            historical=await db.message_activity_range(old_day,old_day)
            assert historical[0]["messages"]==10,historical
            assert (await db.message_activity_days(7))[-1]["messages"]==8
            months=await db.message_activity_months()
            assert months
        finally:
            await db.close()
        db=await Database(path).start()
        try:
            assert (await db.message_activity_range(old_day,old_day))[0]["messages"]==10
            assert (await db.message_activity_days(7))[-1]["messages"]==8
        finally:
            await db.close()


def test_monthly_message_archive() -> None:
    asyncio.run(historical_month_archive())


async def historical_star_balance_regression() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db=await Database(Path(tmp)/"star-timeline.db").start()
        try:
            await db.ensure_user(912,"timeline","Timeline")
            baseline=int(time.time())-7200
            await db.db.execute(
                "UPDATE users SET created_at=? WHERE user_id=?", (baseline-100,912)
            )
            for amount, balance, timestamp in (
                (150,150,baseline), (25,175,baseline+900),
                (-55,120,baseline+900), (8,128,baseline+3600),
            ):
                await db.db.execute(
                    """INSERT INTO xp_transactions(user_id,amount,balance_after,source,created_at)
                       VALUES(?,?,?,?,?)""",
                    (912,amount,balance,
                     "opening_balance" if timestamp==baseline else "test",timestamp),
                )
            before=await db.xp_balance_at(912,baseline-1)
            assert before["status"]=="unavailable" and before["balance"] is None
            assert (await db.xp_balance_at(912,baseline))["balance"]==150
            assert (await db.xp_balance_at(912,baseline+899))["balance"]==150
            assert (await db.xp_balance_at(912,baseline+900))["balance"]==120
            assert (await db.xp_balance_at(912,baseline+3600))["balance"]==128
            from anonchat.monitoring import _chat_header
            header=_chat_header(None,{"username":"one","nickname":"First","xp":175},912,
                                {"username":"two","nickname":"Second","xp":120},913)
            assert "175 ⭐" in header and "120 ⭐" in header,header
        finally:
            await db.close()


def test_historical_star_balance() -> None:
    asyncio.run(historical_star_balance_regression())


async def giveaway_freeze_regression() -> None:
    # Fixed October 2026 draw: use historical local dates, not the host clock.
    start=1791140400
    sunday=1791658800
    cutoff=1791730800
    with tempfile.TemporaryDirectory() as tmp:
        db=await Database(Path(tmp)/"giveaway.db").start()
        try:
            for uid in (311,312,313,314):
                await db.ensure_user(uid,f"giveaway{uid}",f"Player {uid}")
                await db.db.execute(
                    "UPDATE users SET created_at=? WHERE user_id=?",(start-86400,uid)
                )
            for uid,monday,sun,messages in (
                (311,500,200,60),(312,500,100,70),
                (313,400,80,80),(314,100,0,90),
            ):
                await db.activity_add(uid,timestamp=start+100,
                                      xp_earned=monday,messages=messages,dialogs=1)
                if sun:
                    await db.activity_add(uid,timestamp=sunday+100,
                                          xp_earned=sun,messages=12,dialogs=1)
            # The XP ledger was already active when the draw ended.
            await db.db.execute(
                """INSERT INTO xp_transactions(user_id,amount,balance_after,source,created_at)
                   VALUES(311,1,1,'test',?)""",(start+200,)
            )
            # Post-deadline credits must not change winners.
            await db.db.execute(
                """INSERT INTO xp_transactions(user_id,amount,balance_after,source,created_at)
                   VALUES(311,250,250,'test',?)""",(cutoff+60,)
            )
            # Debit while the raffle is still open reduces weekly points.
            await db.db.execute(
                """INSERT INTO xp_transactions(user_id,amount,balance_after,source,created_at)
                   VALUES(312,-50,550,'test',?)""",(cutoff-60,)
            )
            # Late completed conversation: exclude those messages and the dialog.
            await db.db.execute(
                """INSERT INTO matches(started_at,ended_at,user_a,user_b,msg_a,msg_b)
                   VALUES(?,?,?,?,?,?)""",
                (cutoff-100,cutoff+300,311,312,6,6),
            )
            result=await db.giveaway_results_2026_10_11()
            assert result["status"]=="confirmed",result
            assert [(x["user_id"],x["stars"]) for x in result["items"]]==[
                (312,550),(313,480),(311,450)
            ],result
            # Later activity can never rewrite the archived prize ordering.
            await db.activity_add(314,timestamp=sunday+100,xp_earned=999999)
            again=await db.giveaway_results_2026_10_11()
            assert again==result
            await db.close()
            db=await Database(Path(tmp)/"giveaway.db").start()
            assert await db.giveaway_results_2026_10_11()==result
        finally:
            await db.close()


def test_giveaway_freeze() -> None:
    asyncio.run(giveaway_freeze_regression())


def test_poll_notifications() -> None:
    asyncio.run(poll_notifications_and_message_statistics())

def test_reliability() -> None:
    asyncio.run(scenario())


if __name__ == "__main__":
    test_reliability()
    test_poll_notifications()
    test_monthly_message_archive()
    test_historical_star_balance()
    test_giveaway_freeze()
    print("ok durable moderation notices, poll alerts, calendar archive, XP and raffle snapshots")
