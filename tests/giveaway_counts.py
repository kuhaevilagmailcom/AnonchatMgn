"""Raffle regression tests: run with python -m tests.giveaway_counts."""
from __future__ import annotations

import asyncio
import hashlib
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from anonchat.db import Database
from anonchat.miniapp_api import MiniAppServer


def stamp(day: int, hour: int = 12) -> int:
    return int(datetime(2026, 10, day, hour, tzinfo=ZoneInfo("Asia/Yekaterinburg")).timestamp())


async def test_new_messages_and_cutoff() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = await Database(Path(tmp) / "contest.db").start()
        try:
            await db.ensure_user(101, "alice", "Alice")
            t = stamp(22)
            with patch("anonchat.db.now", return_value=t):
                assert await db.record_giveaway_message(101, 1, "привет")
                assert not await db.record_giveaway_message(101, 2, "ПРИВЕТ")
                assert await db.record_giveaway_message(101, 3, "photo:unique1")
                assert await db.record_giveaway_message(101, 4, "photo:unique2")
                assert not await db.record_giveaway_message(101, 3, "photo:unique1")
            with patch("anonchat.db.now", return_value=t + 4):
                assert await db.record_giveaway_message(101, 5, "привет")
            # Up to 60 accepted messages in a rolling minute.
            with patch("anonchat.db.now", return_value=t + 10):
                for number in range(6, 62):
                    assert await db.record_giveaway_message(101, number, f"message {number}")
                assert not await db.record_giveaway_message(101, 62, "over the limit")
            with patch("anonchat.db.now", return_value=stamp(23, 0)):
                assert not await db.record_giveaway_message(101, 100, "too late")
            counts = await db._fetchone(
                "SELECT SUM(accepted) accepted,COUNT(*) total FROM giveaway_message_events WHERE user_id=101"
            )
            assert counts["accepted"] == 60, dict(counts)
        finally:
            await db.close()


async def test_recovery_and_miniapp_ids() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = await Database(Path(tmp) / "contest.db").start()
        try:
            for uid in (201, 202, 203):
                await db.ensure_user(uid, f"u{uid}", f"U{uid}")
            start = stamp(20)
            await db.db.execute(
                """INSERT INTO matches(started_at,ended_at,user_a,user_b,msg_a,msg_b)
                   VALUES(?,?,?,?,?,?)""",
                (start, start + 300, 201, 202, 10, 4),
            )
            with patch("anonchat.db.now", return_value=start + 100):
                for mid in range(1, 4):
                    assert await db.record_giveaway_message(201, mid, f"normal {mid}")
                assert not await db.record_giveaway_message(201, 4, "normal 3")
                # Same recipient message ID in different Telegram chats: unique Mini App events.
                await MiniAppServer._count_miniapp_giveaway(
                    SimpleNamespace(db=db), 203, 201, 10, "mini first"
                )
                await MiniAppServer._count_miniapp_giveaway(
                    SimpleNamespace(db=db), 203, 201, 10, "mini first"
                )
                await MiniAppServer._count_miniapp_giveaway(
                    SimpleNamespace(db=db), 203, 202, 10, "mini second"
                )
            result = await db.giveaway_leaderboard()
            ranks = {int(x["user_id"]): x for x in result["rows"]}
            assert ranks[201]["accepted"] == 9, ranks
            assert ranks[201]["recovered"] == 6, ranks
            assert ranks[202]["accepted"] == 4, ranks
            assert ranks[203]["accepted"] == 2, ranks
            assert result["total"]["recovered"] == 10, result
            assert result["total"]["rejected"] == 1, result
            # Events and completed match counts must not double count.
            assert result["total"]["accepted"] == 15, result
        finally:
            await db.close()


async def test_legacy_recount_survives_restart() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "contest.db"
        db = await Database(path).start()
        try:
            await db.ensure_user(301, "u301", "U301")
            t = stamp(19)
            digest = hashlib.sha256("old repeated text".encode()).hexdigest()
            await db.db.executemany(
                """INSERT INTO giveaway_message_events
                   (user_id,message_id,created_at,content_hash,accepted,reason)
                   VALUES(?,?,?,?,?,?)""",
                [
                    (301, mid, t + mid * 4, digest, 1 if mid == 1 else 0,
                     "" if mid == 1 else "duplicate")
                    for mid in range(1, 11)
                ],
            )
            await db.db.execute("DELETE FROM kv WHERE key='giveaway_2026_recount_v2'")
        finally:
            await db.close()
        db = await Database(path).start()
        try:
            counts = await db._fetchone(
                "SELECT SUM(accepted) accepted FROM giveaway_message_events WHERE user_id=301"
            )
            assert counts["accepted"] == 10, dict(counts)
            assert (await db.giveaway_leaderboard())["rows"][0]["accepted"] == 10
        finally:
            await db.close()


async def scenario() -> None:
    await test_new_messages_and_cutoff()
    await test_recovery_and_miniapp_ids()
    await test_legacy_recount_survives_restart()
    print("ok giveaway: duplicates, rate, Mini App, history recovery, recount, cutoff")


if __name__ == "__main__":
    asyncio.run(scenario())
