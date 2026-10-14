"""Native Telegram dice duels: fair, one roll each, retries and pair isolation."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from anonchat import dice_duels as DD


class FakeMM:
    def __init__(self):
        self.pairs = {101: 202, 202: 101}
        self.started = 1000

    def partner(self, uid):
        return self.pairs.get(uid)

    def dialog_stats(self, uid):
        return {"started_at": self.started}


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
    DD.reset()
    assert DD.display_value("slots", 1) == "BAR BAR BAR"
    assert DD.display_value("slots", 64) == "7️⃣ 7️⃣ 7️⃣"
    assert DD._score("slots", 1) == 3
    assert DD._score("slots", 22) == 3
    assert DD._score("slots", 43) == 3
    assert DD._score("slots", 64) == 4
    assert DD._score("slots", 1) > DD._score("slots", 20)

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
        state, first = await DD.roll(mm, bot, 101, 202, duel.id)
        assert first == max_value
        assert state.rolls == {101: max_value}
        assert bot.copied[-1][0:2] == (202, 101)
        assert DD.state_for(mm, 101, 202)["answered"] is True

        try:
            await DD.roll(mm, bot, 101, 202, duel.id)
        except DD.DuelError:
            pass
        else:
            raise AssertionError("Repeat roll accepted")
        _, second = await DD.roll(mm, bot, 202, 101, duel.id)
        assert second == 1
        assert DD.state_for(mm, 101, 202)["finished"]
        assert bot.messages[-1][0] in (101, 202)
        assert any("Победа" in msg for _, msg, _ in bot.messages[-2:]) or max_value == 1

    # Manual real Telegram dice rolled by the user must be relayed unchanged.
    DD.reset()
    duel = await DD.invite(mm, bot, 101, 202, "basket")
    await DD.respond(mm, bot, 202, 101, duel.id, True)
    msg = SimpleNamespace(message_id=777, dice=SimpleNamespace(value=5, emoji="🏀"))
    assert await DD.try_manual_roll(mm, bot, 101, msg)
    assert bot.copied[-1] == (202, 101, 777)
    assert duel.rolls[101] == 5
    # Wrong game emoji remains a regular chat message, not a game move.
    bad = SimpleNamespace(message_id=778, dice=SimpleNamespace(value=6, emoji="🎲"))
    assert not await DD.try_manual_roll(mm, bot, 202, bad)

    # Failed copy does not consume a turn.
    bot.fail_copy = True
    bot.values = [4]
    try:
        await DD.roll(mm, bot, 202, 101, duel.id)
    except DD.DuelError:
        pass
    else:
        raise AssertionError("Failed delivery counted as a turn")
    assert 202 not in duel.rolls
    bot.fail_copy = False
    bot.values = [3]
    await DD.roll(mm, bot, 202, 101, duel.id)

    # Concurrent duplicate presses resolve to one valid turn.
    DD.reset()
    bot.values = [3, 2]
    duel = await DD.invite(mm, bot, 101, 202, "dice")
    await DD.respond(mm, bot, 202, 101, duel.id, True)
    replies = await asyncio.gather(
        DD.roll(mm, bot, 101, 202, duel.id),
        DD.roll(mm, bot, 101, 202, duel.id),
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
        DD.roll(mm, slow, 101, 202, first.id),
        DD.roll(mm, slow, 303, 404, second.id),
    )
    assert slow.max_sends == 2, "Unrelated conversations blocked each other's dice rolls"

    # Re-matching the same two IDs invalidates callbacks from their old session.
    mm.started += 100
    assert DD.state_for(mm, 101, 202) is None
    assert not DD.active_for_pair(mm, 101, 202)
    DD.reset()
    print("Telegram dice duels passed (all 6 modes, real values, concurrent rolls, privacy)")


if __name__ == "__main__":
    asyncio.run(scenario())
