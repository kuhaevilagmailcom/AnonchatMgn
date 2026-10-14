"""Fast one-round Telegram animated emoji duels with capped star prizes.

One invitation, one Telegram-generated roll per player. Winners receive modest
in-bot XP/stars through the same 500-star daily cap used by other games.
"""
from __future__ import annotations

import asyncio
import secrets
import time
import weakref
from dataclasses import dataclass, field
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import live_chat

# Emoji, name, maximum Telegram-generated value.
KINDS: dict[str, tuple[str, str, int]] = {
    "dice": ("🎲", "Кости", 6),
    "basket": ("🏀", "Баскетбол", 5),
    "darts": ("🎯", "Дартс", 6),
    "football": ("⚽", "Футбол", 5),
    "bowling": ("🎳", "Боулинг", 6),
    "slots": ("🎰", "Автомат", 64),
}
# Telegram encodes each slot reel in two bits of (dice.value - 1).
_SLOT_SYMBOLS = ("BAR", "🍒", "🍋", "7️⃣")


def display_value(kind: str, value: int) -> str:
    if kind != "slots":
        return str(value)
    bits = value - 1
    return " ".join(_SLOT_SYMBOLS[(bits >> offset) & 3] for offset in (0, 2, 4))


def _score(kind: str, value: int) -> int:
    if kind != "slots":
        return value
    parts = [(value - 1 >> offset) & 3 for offset in (0, 2, 4)]
    if parts == [3, 3, 3]:
        return 4  # 777
    if parts == [0, 0, 0]:
        return 3  # Three BAR
    if len(set(parts)) == 1:
        return 2  # Three cherries or lemons
    if len(set(parts)) == 2:
        return 1  # Pair
    return 0  # No winning combination


def base_prize(kind: str, winning_value: int, losing_value: int) -> int:
    """Base star reward for an actual win, before x2/x3 and the daily cap."""
    mine, other = _score(kind, winning_value), _score(kind, losing_value)
    if mine <= other:
        return 0
    if kind == "basket":
        return 3 if winning_value >= 4 else 0  # Ball reached the basket
    if kind == "football":
        return 2 if winning_value >= 3 else 0  # Scored a goal
    if kind == "slots":
        return {0: 0, 1: 5, 2: 7, 3: 10, 4: 15}[mine]
    # Darts, dice, bowling: 3 stars for a perfect maximum, otherwise 2.
    return 3 if winning_value == KINDS[kind][2] else 2


def reward_rules(kind: str) -> str:
    return {
        "basket": "За победное попадание: +3 ⭐.",
        "football": "За победный гол: +2 ⭐.",
        "slots": "Пара — 5 ⭐; три 🍒/🍋 — 7 ⭐; три BAR — 10 ⭐; 777 — 15 ⭐.",
        "darts": "Победителю 2 ⭐, за яблочко 3 ⭐.",
        "dice": "Победителю 2 ⭐, за шестёрку 3 ⭐.",
        "bowling": "Победителю 2 ⭐, за страйк 3 ⭐.",
    }[kind]


TTL = 10 * 60
# Keep result/replay buttons usable during the active anonymous conversation.
RESULT_TTL = 6 * 60 * 60
# Telegram visually animates the dice even after Bot API has returned its value.
# Avoid announcing a winner before the second animation finishes.
REVEAL_DELAY_SECONDS = 4.0


class DuelError(ValueError):
    pass


@dataclass(slots=True)
class Duel:
    id: int
    pair: tuple[int, int]
    inviter: int
    kind: str
    session: int
    created_at: float
    status: str = "invited"
    rolls: dict[int, int] = field(default_factory=dict)
    rewards: dict[int, int] = field(default_factory=dict)
    finished_at: float = 0

    @property
    def emoji(self) -> str:
        return KINDS[self.kind][0]


_GAMES: dict[tuple[int, int], Duel] = {}
# Separate locks ensure a slow Telegram API request for one couple never blocks
# other couples. Weak references automatically discard unused pair locks.
_LOCKS: weakref.WeakValueDictionary[tuple[int, int], asyncio.Lock] = weakref.WeakValueDictionary()


def _lock_for(uid: int, partner: int) -> asyncio.Lock:
    key = _key(uid, partner)
    lock = _LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[key] = lock
    return lock


def _prune_expired() -> None:
    now = time.monotonic()
    for key, game in list(_GAMES.items()):
        if ((game.status not in ("finished", "restarting") and now - game.created_at > TTL)
                or (game.finished_at and now - game.finished_at > RESULT_TTL)):
            _GAMES.pop(key, None)


def _key(a: int, b: int) -> tuple[int, int]:
    return tuple(sorted((int(a), int(b))))


def _session(mm: Any, uid: int) -> int:
    stats = mm.dialog_stats(uid) or {}
    return int(float(stats.get("started_at") or 0))


def _current(mm: Any, uid: int, partner: int) -> Duel | None:
    key = _key(uid, partner)
    game = _GAMES.get(key)
    if game is None:
        return None
    now = time.monotonic()
    if (
        mm.partner(uid) != partner or mm.partner(partner) != uid
        or game.session != _session(mm, uid)
        or (game.status not in ("finished", "restarting") and now - game.created_at > TTL)
        or (game.finished_at and now - game.finished_at > RESULT_TTL)
    ):
        _GAMES.pop(key, None)
        return None
    return game


def active_for_pair(mm: Any, uid: int, partner: int) -> bool:
    game = _current(mm, uid, partner)
    return game is not None and game.status in ("invited", "active", "resolving", "restarting")


def state_for(mm: Any, uid: int, partner: int | None) -> dict | None:
    if partner is None:
        return None
    game = _current(mm, uid, partner)
    if game is None:
        return None
    return {
        "type": "dice", "id": game.id, "emoji": game.emoji,
        "title": KINDS[game.kind][1], "status": game.status,
        "kind": game.kind,
        "inviter": game.inviter == uid,
        "answered": uid in game.rolls,
        "my_roll": game.rolls.get(uid),
        "partner_roll": game.rolls.get(partner),
        "my_display": display_value(game.kind, game.rolls[uid]) if uid in game.rolls else "",
        "partner_display": display_value(game.kind, game.rolls[partner]) if partner in game.rolls else "",
        "my_score": _score(game.kind, game.rolls[uid]) if uid in game.rolls else None,
        "partner_score": _score(game.kind, game.rolls[partner]) if partner in game.rolls else None,
        "reward_total": game.rewards.get(uid, 0),
        "total": 1, "round": 1, "finished": game.status == "finished",
    }


def invite_markup(game: Duel) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Играть", callback_data=f"game:dice:yes:{game.id}"),
        InlineKeyboardButton(text="Не сейчас", callback_data=f"game:dice:no:{game.id}"),
    ]])


def replay_markup(game: Duel) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=f"🔄 Ещё раз · {game.emoji}",
            callback_data=f"game:dice:again:{game.id}",
        ),
    ]])


def roll_markup(game: Duel) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"{game.emoji} Бросить", callback_data=f"game:dice:roll:{game.id}"),
    ]])


async def invite(mm: Any, bot: Any, uid: int, partner: int, kind: str) -> Duel:
    if kind not in KINDS:
        raise DuelError("Неизвестная игра")
    async with _lock_for(uid, partner):
        _prune_expired()
        old = _current(mm, uid, partner)
        if old is not None and old.status != "finished":
            raise DuelError("У вас уже есть приглашение или активная дуэль")
        game = Duel(
            id=secrets.randbelow(1_000_000_000) + 1,
            pair=_key(uid, partner), inviter=uid,
            kind=kind, session=_session(mm, uid),
            created_at=time.monotonic(),
        )
        _GAMES[game.pair] = game
    emoji, name, _ = KINDS[kind]
    rule = "Один раунд: каждый делает по одному броску. " + reward_rules(kind) + "\n" \
           "x2/x3 и дневной лимит 500 ⭐ действуют как в остальных играх."
    try:
        await bot.send_message(
            partner, f"{emoji} <b>Собеседник зовёт в «{name}»</b>\n"
            + rule,
            parse_mode="HTML", reply_markup=invite_markup(game),
        )
    except Exception:
        async with _lock_for(uid, partner):
            if _GAMES.get(game.pair) is game:
                _GAMES.pop(game.pair, None)
        raise DuelError("Не удалось отправить приглашение") from None
    live_chat.game_invite(uid, partner, "dice", game.id, f"{emoji} {name}", "По одному броску")
    return game


async def respond(mm: Any, bot: Any, uid: int, partner: int, game_id: int, accept: bool) -> Duel:
    async with _lock_for(uid, partner):
        game = _current(mm, uid, partner)
        if game is None or game.id != game_id or game.status != "invited":
            raise DuelError("Приглашение уже недоступно")
        if uid == game.inviter:
            raise DuelError("На приглашение отвечает собеседник")
        game.status = "active" if accept else "declined"
        if not accept:
            _GAMES.pop(game.pair, None)
    if accept:
        for player in game.pair:
            try:
                await bot.send_message(
                    player,
                    f"{game.emoji} <b>{KINDS[game.kind][1]}</b>\n"
                    "Нажми «Бросить» или отправь этот игровой эмодзи в чат с ботом.",
                    parse_mode="HTML", reply_markup=roll_markup(game),
                )
            except Exception:
                pass
    else:
        try:
            await bot.send_message(game.inviter, f"{game.emoji} Собеседник отказался от игры.")
        except Exception:
            pass
    live_chat.game_status(set(game.pair), "dice", game.id,
                          "accepted" if accept else "declined",
                          "Игра началась" if accept else "Предложение отклонено")
    return game


async def replay(mm: Any, bot: Any, uid: int, partner: int, game_id: int) -> Duel:
    """Repeat the completed game type without returning to the game picker."""
    async with _lock_for(uid, partner):
        old = _current(mm, uid, partner)
        if old is None or old.id != game_id or old.status != "finished":
            raise DuelError("Эта игра уже повторена или завершена")
        kind = old.kind
        # Claim the replay exactly once, even if both players tap together.
        old.status = "restarting"
        _GAMES.pop(old.pair, None)
    return await invite(mm, bot, uid, partner, kind)


async def roll(mm: Any, bot: Any, uid: int, partner: int, game_id: int,
               *, db: Any, original: Any = None) -> tuple[Duel, int]:
    # Network sends stay under the pair's turn lock so parallel button taps
    # cannot get two valid throws. This is intentionally a very short duel.
    async with _lock_for(uid, partner):
        game = _current(mm, uid, partner)
        if game is None or game.id != game_id or game.status != "active":
            raise DuelError("Дуэль уже закончилась")
        if uid in game.rolls:
            raise DuelError("Ты уже бросил. Ждём собеседника")
        try:
            if original is None:
                sent = await bot.send_dice(chat_id=uid, emoji=game.emoji)
                if sent.dice is None or sent.dice.emoji != game.emoji:
                    raise DuelError("Telegram не вернул результат броска")
                value = int(sent.dice.value)
                await bot.copy_message(chat_id=partner, from_chat_id=uid,
                                       message_id=sent.message_id)
            else:
                if original.dice is None or original.dice.emoji != game.emoji:
                    raise DuelError("Отправь эмодзи выбранной игры")
                value = int(original.dice.value)
                await bot.copy_message(chat_id=partner, from_chat_id=uid,
                                       message_id=original.message_id)
        except DuelError:
            raise
        except Exception:
            raise DuelError("Не удалось показать бросок собеседнику. Попробуй ещё раз") from None
        if not 1 <= value <= KINDS[game.kind][2]:
            raise DuelError("Некорректный результат Telegram")
        game.rolls[uid] = value
        second_roll = len(game.rolls) == 2
        if second_roll:
            game.status = "resolving"
    display = display_value(game.kind, value)
    live_chat.private(uid, f"{game.emoji} Твой бросок: {display}", kind="game_round")
    live_chat.private(partner, f"{game.emoji} Бросок собеседника: {display}", kind="game_round")
    if not second_roll:
        # The first roll never creates a winner or any star payout.
        live_chat.private(uid, "⏳ Ждём бросок собеседника…", kind="game_round")
        try:
            await bot.send_message(uid, "⏳ Ждём бросок собеседника…")
        except Exception:
            pass
        return game, value

    live_chat.game_status(set(game.pair), "dice", game.id, "resolving",
                          "Оба броска приняты · смотрим анимацию…")
    if REVEAL_DELAY_SECONDS > 0:
        await asyncio.sleep(REVEAL_DELAY_SECONDS)

    async with _lock_for(uid, partner):
        # Someone may have ended their chat while Telegram showed the dice.
        if _current(mm, uid, partner) is not game or game.status != "resolving":
            return game, value
        # Both actual Telegram dice values are required, not only one.
        if len(game.rolls) != 2 or set(game.rolls) != set(game.pair):
            raise DuelError("Ожидаем бросок второго игрока")
        first, second = game.pair
        first_prize = base_prize(game.kind, game.rolls[first], game.rolls[second])
        second_prize = base_prize(game.kind, game.rolls[second], game.rolls[first])
        winner = first if first_prize else second if second_prize else None
        amount = first_prize or second_prize
        if winner is not None:
            game.rewards[winner] = await db.award_game_xp(
                winner, amount, source="emoji_dice",
                reason=f"{game.emoji} Победа в эмодзи-дуэли «{KINDS[game.kind][1]}»",
                reference_type="dice_duel", reference_id=str(game.id),
            )
        game.status = "finished"
        game.finished_at = time.monotonic()
    if game.status == "finished":
        for player in game.pair:
            other = partner if player == uid else uid
            mine = game.rolls[player]
            theirs = game.rolls[other]
            mine_score, their_score = _score(game.kind, mine), _score(game.kind, theirs)
            outcome = ("🤝 Ничья!" if mine_score == their_score
                       else "🏆 Победа!" if mine_score > their_score else "Собеседник победил.")
            actual_reward = game.rewards.get(player, 0)
            reward_line = f"\n+{actual_reward} ⭐" if actual_reward else ""
            text = (f"{game.emoji} <b>{outcome}</b>\n"
                    f"Ты: <b>{display_value(game.kind, mine)}</b> · "
                    f"Собеседник: <b>{display_value(game.kind, theirs)}</b>"
                    f"{reward_line}")
            try:
                await bot.send_message(
                    player, text, parse_mode="HTML",
                    reply_markup=replay_markup(game),
                )
            except Exception:
                pass
            live_chat.private(player, text, kind="game_round")
        live_chat.game_status(set(game.pair), "dice", game.id, "finished", "Раунд завершён")
    return game, value


async def try_manual_roll(mm: Any, bot: Any, uid: int, message: Any, *, db: Any) -> bool:
    partner = mm.partner(uid)
    if partner is None:
        return False
    game = _current(mm, uid, partner)
    if game is None or game.status != "active":
        return False
    if message.dice is None or message.dice.emoji != game.emoji:
        return False
    try:
        await roll(mm, bot, uid, partner, game.id, db=db, original=message)
    except DuelError as exc:
        try:
            await bot.send_message(uid, str(exc))
        except Exception:
            pass
    return True


def reset() -> None:
    """Test isolation and optional graceful reset on restart."""
    _GAMES.clear()
