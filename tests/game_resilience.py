"""Game regression scenarios without hitting Telegram or production hosting.

Run: python -m tests.game_resilience
"""
from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from anonchat.db import Database
from anonchat.matching import Matchmaker
from anonchat import geo_runtime as GR
from anonchat import word_game as WG


async def scenario() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "game-resilience.db"
        db = await Database(path).start()
        try:
            for uid in (991001, 991002):
                await db.ensure_user(uid, f"test{uid}", "Test")

            # Battle: duplicate invite/answers and concurrent two-person input.
            invite, created = await db.create_battle_invite(991001, 991002, 5)
            assert created
            same, created = await db.create_battle_invite(991002, 991001, 5)
            assert not created and int(same["id"]) == int(invite["id"])
            battle = int(invite["id"])
            assert await db.accept_battle(battle, 991002, [1, 2, 3, 4, 5])
            assert await db.accept_battle(battle, 991002, [1, 2, 3, 4, 5]) is None
            for turn in range(5):
                first = await asyncio.gather(
                    db.answer_battle(battle, 991001, turn, 0),
                    db.answer_battle(battle, 991001, turn, 0),
                )
                assert sorted(v[0] for v in first) == ["already", "waiting"], first
                result, game = await db.answer_battle(battle, 991002, turn, 0)
                assert result == "resolved" and game is not None
                if turn < 4:
                    assert await db.advance_battle(battle, 991001, turn)
                    assert await db.advance_battle(battle, 991002, turn) is None
                else:
                    assert game["status"] == "finished"
            assert (await db.answer_battle(battle, 991001, 4, 0))[0] == "missing"
            battle_reward = 25 * await db.xp_multiplier()
            assert int((await db.get_user(991001))["xp"]) == battle_reward

            # Mid-game /next: clear live game, disallow stale answers or rewards.
            invite, created = await db.create_battle_invite(991001, 991002, 5)
            assert created
            battle = int(invite["id"])
            assert await db.accept_battle(battle, 991002, [1, 2, 3, 4, 5])
            assert await db.close_battles_for_users(991001, 991002) == 1
            assert (await db.answer_battle(battle, 991001, 0, 0))[0] == "missing"
            assert int((await db.get_user(991001))["xp"]) == battle_reward

            # GeoGuessr: timeout is resolved once, with no phantom rewards.
            invite, created = await db.create_geo_invite(991001, 991002, [11, 22, 33])
            assert created
            geo_id = int(invite["id"])
            assert await db.accept_geo(geo_id, 991002)
            assert (await db.answer_geo(
                geo_id, 991001, 0, 53.4, 58.98, 53.4, 58.98
            ))[0] == "waiting"
            assert (await db.answer_geo(
                geo_id, 991001, 0, 53.4, 58.98, 53.4, 58.98
            ))[0] == "already"
            await db.db.execute(
                "UPDATE battle_games SET geo_round_started_at=? WHERE id=?",
                (int(time.time()) - 125, geo_id),
            )
            states = await asyncio.gather(
                db.expire_geo_round(geo_id, 0), db.expire_geo_round(geo_id, 0)
            )
            assert sorted(item[0] for item in states) == ["closed", "resolved"], states

            game = await db.advance_geo(geo_id, 991001, 0)
            assert game is not None
            # Save/restore an active round; do not extend its 120s deadline.
            await db.close()
            db = await Database(path).start()
            mm = Matchmaker()
            assert mm.connect(991001)[0] == "queued"
            assert mm.connect(991002)[0] == "paired"
            real_schedule = GR.schedule_timeout
            resumed = []
            try:
                GR.schedule_timeout = lambda bot, store, matchmaking, pack, row: resumed.append(
                    (int(row["id"]), int(row["question_index"]))
                )
                assert await GR.restore_timeouts(None, db, mm, None) == 1
                assert resumed == [(geo_id, 1)], resumed
            finally:
                GR.schedule_timeout = real_schedule
            assert await db.close_battles_for_users(991001, 991002) == 1
            assert (await db.expire_geo_round(geo_id, 1))[0] == "closed"

            # Cooldown refresh: already-waiting partners can meet after 2 minutes.
            await db.log_dialog(991001, 991002, 0, 0, int(time.time()) - 10, 991001)
            mm = Matchmaker()
            await db.db.execute(
                "UPDATE matches SET ended_at=? WHERE user_a=? AND user_b=?",
                (int(time.time()) - 60, 991001, 991002),
            )
            assert mm.connect(991001, excluded={991002})[0] == "queued"
            assert mm.connect(991002, excluded={991001})[0] == "queued"
            active = await db.queue_recent_exclusions(mm.queued_user_ids(), 120)
            assert active[991001] == {991002}
            mm.refresh_queued_exclusions(active)
            assert mm.sweep() == []
            await db.db.execute(
                "UPDATE matches SET ended_at=? WHERE user_a=? AND user_b=?",
                (int(time.time()) - 125, 991001, 991002),
            )
            expired = await db.queue_recent_exclusions(mm.queued_user_ids(), 120)
            mm.refresh_queued_exclusions(expired)
            assert len(mm.sweep()) == 1
            assert mm.online_pairs() == 1

            # Explain a word: idempotent guesses, role switching, process reload.
            WG.bind_database(db)
            WG.clear_pair(991001, 991002)
            invite, created = WG.create_invite(991001, 991002)
            assert created
            words_id = invite.id
            assert WG.create_invite(991002, 991001)[1] is False
            active = WG.accept(words_id, 991002)
            assert active is not None and active.status == "active"
            assert WG.accept(words_id, 991002) is None
            assert WG.resolve_guess(active.guesser_id, active.explainer_id, active.word)
            assert WG.resolve_guess(active.guesser_id, active.explainer_id, active.word) is None
            assert WG.advance(words_id, 991001, 0) is not None
            assert WG.advance(words_id, 991002, 0) is None
            await WG.flush()
            await db.close()
            db = await Database(path).start()
            WG.bind_database(db)
            assert await WG.restore(db) >= 1
            restored = WG.get_by_id(words_id)
            assert restored is not None and restored.round_index == 1
            for index in range(1, WG.WORD_ROUNDS):
                guessed = WG.resolve_guess(
                    restored.guesser_id, restored.explainer_id, restored.word
                )
                assert guessed is not None
                assert guessed.finished is (index == WG.WORD_ROUNDS - 1)
                assert WG.resolve_guess(
                    restored.guesser_id, restored.explainer_id, restored.word
                ) is None
                if index < WG.WORD_ROUNDS - 1:
                    restored = WG.advance(words_id, 991001, index)
                    assert restored is not None
                else:
                    assert WG.get_by_id(words_id).status == "finished"
            WG.clear_pair(991001, 991002)
            assert WG.get_by_id(words_id) is None
            replay, created = WG.create_invite(991002, 991001)
            assert created and replay.id != words_id
            WG.clear_pair(991001, 991002)
            await WG.flush()
        finally:
            await db.close()


if __name__ == "__main__":
    asyncio.run(scenario())
    print("ok battle/word/geo scenarios, double taps, restart, timeout and next")
