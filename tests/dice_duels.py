"""Native Telegram dice duels: fair, one roll each, retries and pair isolation."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory

from anonchat.db import Database

from anonchat import dice_duels as DD


class FakeMM:
    def __init__(self):
        self.pairs = {101: 202, 202: 101}
        self.started = 1000

    def partner(self, uid):
        return self.pairs.get(uid)

    def dialog_stats(self, uid):
        return {"started_at": self.started}


class FakeLedger:
    def __init__(self, multiplier=1, used=0):
        self.multiplier = multiplier
        self.used = {101: used}
        self.payouts = []

    async def award_game_xp(self, uid, amount, *, source, **kwargs):
        assert source == "emoji_dice"
        paid = min(amount * self.multiplier, max(0, 500 - self.used.get(uid, 0)))
        self.used[uid] = self.used.get(uid, 0) + paid
        self.payouts.append((uid, amount, paid, kwargs))
        return paid


class FakeBot:
    def __init__(self):
        self.messages = []
        self.dice = []
        self.copied = []
        self.values = [4, 2]
        self.next_id = 100
        self.fail_copy = False

    async def send_message(self, uid, text, **kw):
        self.messages.append((uid, text, kw))
        self.next_id += 1
        return SimpleNamespace(message_id=self.next_id)

    async def send_dice(self, *, chat_id, emoji):
        value = self.values.pop(0)
        self.dice.append((chat_id, emoji, value))
        self.next_id += 1
        return SimpleNamespace(message_id=self.next_id,
                               dice=SimpleNamespace(value=value, emoji=emoji))

    async def copy_message(self, *, chat_id, from_chat_id, message_id):
        if self.fail_copy:
            raise RuntimeError("Copy failed")
        self.copied.append((chat_id, from_chat_id, message_id))
        return SimpleNamespace(message_id=message_id+1000)


async def scenario():
    mm, bot = FakeMM(), FakeBot()
    ledger = FakeLedger()
    DD.reset()
    # Keep ordinary regression runs fast; a separate test verifies the reveal delay.
    DD.REVEAL_DELAY_SECONDS = 0
    assert DD.display_value("slots", 1) == "BAR BAR BAR"
    assert DD.display_value("slots", 64) == "7️⃣ 7️⃣ 7️⃣"
    assert DD._score("slots", 1) == 3
    assert DD._score("slots", 22) == 2
    assert DD._score("slots", 43) == 2
    assert DD._score("slots", 64) == 4
    assert DD._score("slots", 1) > DD._score("slots", 22)
    assert DD.base_prize("slots", 2, 20) == 5
    assert DD.base_prize("slots", 22, 20) == 7
    assert DD.base_prize("slots", 1, 20) == 10
    assert DD.base_prize("slots", 64, 1) == 15
    assert DD.base_prize("slots", 20, 2) == 0
    assert DD.base_prize("slots", 1, 1) == 0
    assert DD.base_prize("basket", 5, 1) == 3
    assert DD.base_prize("basket", 3, 1) == 0
    assert DD.base_prize("football", 5, 1) == 2
    assert DD.base_prize("football", 2, 1) == 0
    for kind in ("darts", "dice", "bowling"):
        assert DD.base_prize(kind, 6, 1) == 3
        assert DD.base_prize(kind, 5, 1) == 2
        assert DD.base_prize(kind, 4, 4) == 0

    for key, (emoji, title, max_value) in DD.KINDS.items():
        assert 1 <= max_value <= 64
        bot.values = [max_value, 1]
        duel = await DD.invite(mm, bot, 101, 202, key)
        assert duel.emoji == emoji
        assert DD.state_for(mm, 101, 202)["status"] == "invited"
        assert bot.messages[-1][0] == 202
        assert bot.messages[-1][2]["reply_markup"].inline_keyboard[0][0].callback_data.endswith(str(duel.id))

        try:
            await DD.invite(mm, bot, 101, 202, key)
        except DD.DuelError:
            pass
        else:
            raise AssertionError("Duplicate invite accepted")

        try:
            await DD.respond(mm, bot, 101, 202, duel.id, True)
        except DD.DuelError:
            pass
        else:
            raise AssertionError("Inviter can accept own invitation")

        await DD.respond(mm, bot, 202, 101, duel.id, True)
        assert DD.state_for(mm, 202, 101)["status"] == "active"
        state, first = await DD.roll(mm, bot, 101, 202, duel.id, db=ledger)
        assert first == max_value
        assert state.rolls == {101: max_value}
        assert bot.copied[-1][0:2] == (202, 101)
        assert DD.state_for(mm, 101, 202)["answered"] is True
        assert DD.state_for(mm, 101, 202)["partner_roll"] is None
        assert DD.state_for(mm, 101, 202)["finished"] is False
        assert duel.rewards == {}
        assert not any("Победа!" in msg or "победил" in msg.lower() for _, msg, _ in bot.messages[-1:])

        try:
            await DD.roll(mm, bot, 101, 202, duel.id, db=ledger)
        except DD.DuelError:
            pass
        else:
            raise AssertionError("Repeat roll accepted")
        _, second = await DD.roll(mm, bot, 202, 101, duel.id, db=ledger)
        assert second == 1
        assert DD.state_for(mm, 101, 202)["finished"]
        expected = DD.base_prize(key, max_value, 1)
        assert DD.state_for(mm, 101, 202)["reward_total"] == expected
        assert ledger.payouts[-1][0:3] == (101, expected, expected)
        assert bot.messages[-1][0] in (101, 202)
        assert any("Победа" in msg for _, msg, _ in bot.messages[-2:]) or max_value == 1
        # Under each result a Telegram inline button repeats this exact game.
        for _, result_text, kwargs in bot.messages[-2:]:
            assert "reply_markup" in kwargs
            button = kwargs["reply_markup"].inline_keyboard[0][0]
            assert "Ещё раз" in button.text
            assert button.callback_data == f"game:dice:again:{duel.id}"

    # One-tap replay keeps the same game kind and requires acceptance again.
    DD.reset()
    bot.values = [5, 1]
    basketball = await DD.invite(mm, bot, 101, 202, "basket")
    await DD.respond(mm, bot, 202, 101, basketball.id, True)
    await DD.roll(mm, bot, 101, 202, basketball.id, db=ledger)
    await DD.roll(mm, bot, 202, 101, basketball.id, db=ledger)
    again = await DD.replay(mm, bot, 202, 101, basketball.id)
    assert again.kind == "basket" and again.emoji == "🏀" and again.id != basketball.id
    assert again.status == "invited" and again.inviter == 202
    assert bot.messages[-1][0] == 101
    try:
        await DD.replay(mm, bot, 101, 202, basketball.id)
    except DD.DuelError:
        pass
    else:
        raise AssertionError("A completed round can only be replayed once")

    # A real second roll should show 'resolving' during Telegram's animation.
    DD.reset()
    bot.values = [5, 1]
    DD.REVEAL_DELAY_SECONDS = 0.08
    pending = await DD.invite(mm, bot, 101, 202, "basket")
    await DD.respond(mm, bot, 202, 101, pending.id, True)
    await DD.roll(mm, bot, 101, 202, pending.id, db=ledger)
    assert pending.status == "active" and pending.rewards == {}
    outcomes_before = sum("Победа!" in text for _, text, _ in bot.messages)
    second_task = asyncio.create_task(DD.roll(mm, bot, 202, 101, pending.id, db=ledger))
    await asyncio.sleep(0.02)
    assert pending.status == "resolving" and len(pending.rolls) == 2
    assert DD.state_for(mm, 101, 202)["finished"] is False
    assert pending.rewards == {}
    assert sum("Победа!" in text for _, text, _ in bot.messages) == outcomes_before
    try:
        await DD.replay(mm, bot, 101, 202, pending.id)
    except DD.DuelError:
        pass
    else:
        raise AssertionError("Replay must wait for the second dice animation")
    await second_task
    assert pending.status == "finished"
    assert DD.state_for(mm, 101, 202)["finished"] is True
    assert len(pending.rolls) == 2
    DD.REVEAL_DELAY_SECONDS = 0

    # Manual real Telegram dice rolled by the user must be relayed unchanged.
    DD.reset()
    duel = await DD.invite(mm, bot, 101, 202, "basket")
    await DD.respond(mm, bot, 202, 101, duel.id, True)
    msg = SimpleNamespace(message_id=777, dice=SimpleNamespace(value=5, emoji="🏀"))
    assert await DD.try_manual_roll(mm, bot, 101, msg, db=ledger)
    assert bot.copied[-1] == (202, 101, 777)
    assert duel.rolls[101] == 5
    # Wrong game emoji remains a regular chat message, not a game move.
    bad = SimpleNamespace(message_id=778, dice=SimpleNamespace(value=6, emoji="🎲"))
    assert not await DD.try_manual_roll(mm, bot, 202, bad, db=ledger)

    # Failed copy does not consume a turn.
    bot.fail_copy = True
    bot.values = [4]
    try:
        await DD.roll(mm, bot, 202, 101, duel.id, db=ledger)
    except DD.DuelError:
        pass
    else:
        raise AssertionError("Failed delivery counted as a turn")
    assert 202 not in duel.rolls
    bot.fail_copy = False
    bot.values = [3]
    await DD.roll(mm, bot, 202, 101, duel.id, db=ledger)

    # Concurrent duplicate presses resolve to one valid turn.
    DD.reset()
    bot.values = [3, 2]
    duel = await DD.invite(mm, bot, 101, 202, "dice")
    await DD.respond(mm, bot, 202, 101, duel.id, True)
    replies = await asyncio.gather(
        DD.roll(mm, bot, 101, 202, duel.id, db=ledger),
        DD.roll(mm, bot, 101, 202, duel.id, db=ledger),
        return_exceptions=True,
    )
    assert sum(isinstance(x, tuple) for x in replies) == 1
    assert sum(isinstance(x, DD.DuelError) for x in replies) == 1

    # Different pairs roll in parallel, without waiting for each other's network sends.
    class SlowBot(FakeBot):
        def __init__(self):
            super().__init__()
            self.active_sends = 0
            self.max_sends = 0

        async def send_dice(self, *, chat_id, emoji):
            self.active_sends += 1
            self.max_sends = max(self.max_sends, self.active_sends)
            try:
                await asyncio.sleep(0.03)
                return await super().send_dice(chat_id=chat_id, emoji=emoji)
            finally:
                self.active_sends -= 1

    DD.reset()
    mm.pairs.update({303: 404, 404: 303})
    slow = SlowBot()
    slow.values = [5, 3]
    first = await DD.invite(mm, slow, 101, 202, "basket")
    second = await DD.invite(mm, slow, 303, 404, "darts")
    await DD.respond(mm, slow, 202, 101, first.id, True)
    await DD.respond(mm, slow, 404, 303, second.id, True)
    await asyncio.gather(
        DD.roll(mm, slow, 101, 202, first.id, db=ledger),
        DD.roll(mm, slow, 303, 404, second.id, db=ledger),
    )
    assert slow.max_sends == 2, "Unrelated conversations blocked each other's dice rolls"

    # Scheduled multiplier applies before the shared 500-star cap.
    DD.reset()
    limited = FakeLedger(multiplier=2, used=498)
    bot.values = [5, 1]
    duel = await DD.invite(mm, bot, 101, 202, "basket")
    await DD.respond(mm, bot, 202, 101, duel.id, True)
    await DD.roll(mm, bot, 101, 202, duel.id, db=limited)
    await DD.roll(mm, bot, 202, 101, duel.id, db=limited)
    assert duel.rewards == {101: 2}
    assert limited.used[101] == 500

    # Verify real SQLite ledger, daily quota, and the source category.
    with TemporaryDirectory() as temp:
        db = await Database(Path(temp) / "duels.sqlite").start()
        try:
            await db.ensure_user(101, "tester", "One")
            before = await db.game_xp_today(101)
            credited = await db.award_game_xp(
                101, 3, source="emoji_dice", reason="Тест дуэли",
                reference_type="dice_duel", reference_id="123",
            )
            assert credited == 3 * await db.xp_multiplier()
            assert await db.game_xp_today(101) == before + credited
            assert int((await db.get_user(101))["xp"]) == credited
            journal = await db._fetchone(
                "SELECT source, amount FROM xp_transactions WHERE user_id=? ORDER BY id DESC LIMIT 1",
                (101,),
            )
            assert journal["source"] == "emoji_dice"
            assert int(journal["amount"]) == credited
        finally:
            await db.close()

    # Re-matching the same two IDs invalidates callbacks from their old session.
    mm.started += 100
    assert DD.state_for(mm, 101, 202) is None
    assert not DD.active_for_pair(mm, 101, 202)
    DD.reset()
    print("Telegram dice duels passed (all 6 modes, real values, concurrent rolls, privacy)")


if __name__ == "__main__":
    asyncio.run(scenario())
