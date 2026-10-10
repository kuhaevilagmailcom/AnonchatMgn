"""Synthetic matcher/SQLite smoke test (not a guarantee of Bothost capacity).

Run: python -m tests.load_smoke
"""
from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from anonchat.db import Database
from anonchat.matching import Candidate, Matchmaker


def test_matchmaking_load() -> None:
    for size in (100,300,500,1000):
        mm=Matchmaker(queue_limit=size+10)
        mm._queue={uid:Candidate(user_id=uid,joined_at=float(uid)) for uid in range(10001,10001+size)}
        start=time.perf_counter()
        pairs=mm.sweep()
        elapsed=(time.perf_counter()-start)*1000
        users=[value for pair in pairs for value in pair]
        assert len(users)==size and len(set(users))==size
        assert all(a!=b for a,b in pairs)
        assert mm.queue_size()==0 and mm.online_pairs()==size//2
        restored=Matchmaker()
        restored.restore(mm.snapshot())
        assert restored.online_pairs()==size//2
        print(f"matching: {size} synthetic users, {elapsed:.1f} ms, {len(pairs)} pairs")


def test_1000_active_chat_sessions() -> None:
    """1,000 virtual chatters, 500 isolated pairs and 20,000 chat messages."""
    mm = Matchmaker(queue_limit=1100)
    for uid in range(10001, 11001):
        mm._queue[uid] = Candidate(user_id=uid, joined_at=float(uid))
    start = time.perf_counter()
    assert len(mm.sweep()) == 500
    for _ in range(20):
        for uid in range(10001, 11001):
            result = mm.count_message(uid)
            assert result is not None and result[0] != uid
    snap = mm.snapshot()
    replica = Matchmaker(queue_limit=1100)
    replica.restore(snap)
    assert replica.online_pairs() == 500
    total = sum(replica._pairs[uid].counts.get(uid, 0) for uid in range(10001,11001))
    assert total == 20_000, total
    for uid in range(10001,11001,2):
        partner, summary = replica.release(uid)
        assert partner is not None and sum(summary["counts"].values()) == 40
    assert replica.online_pairs() == 0
    print(f"chat: 1000 users, 500 pairs, 20k virtual messages, {(time.perf_counter()-start)*1000:.1f} ms")


async def test_sqlite_idempotency_load() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db=await Database(Path(tmp)/"load.db").start()
        try:
            await db.ensure_user(700001,"load","Load")
            requests=[
                db.change_xp(
                    700001,1,source="admin_award",reason="Synthetic consistency check",
                    actor_id=999,idempotency_key=f"load-admin-{i:05d}"
                ) for i in range(100)
            ]
            start=time.perf_counter()
            results=await asyncio.gather(*requests)
            elapsed=(time.perf_counter()-start)*1000
            assert sum(1 for _,applied in results if applied)==100
            assert (await db.get_user(700001))["xp"]==100
            count=await db._fetchone(
                "SELECT COUNT(*) count FROM admin_notice_outbox WHERE user_id=?",
                (700001,),
            )
            assert count["count"]==100
            print(f"sqlite: 100 synthetic concurrent balance requests, {elapsed:.1f} ms")
        finally:
            await db.close()


if __name__ == "__main__":
    test_matchmaking_load()
    test_1000_active_chat_sessions()
    asyncio.run(test_sqlite_idempotency_load())
    print("ok synthetic load smoke")
