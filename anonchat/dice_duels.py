"""Tiny, non-monetary duels with Telegram's *real* animated dice.

One invitation, one roll per person. Telegram supplies the random value.
Matches exist only for the current anonymous chat, not in permanent history.
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
    if len(set(parts)) == 1:
        return 3  # Three matching symbols
    if len(set(parts)) == 2:
        return 2  # Pair
    return 1  # No match


TTL = 10 * 60
RESULT_TTL = 30


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
        if now - game.created_at > TTL or (game.finished_at and now - game.finished_at > RESULT_TTL):
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
        or now - game.created_at > TTL
        or (game.finished_at and now - game.finished_at > RESULT_TTL)
    ):
        _GAMES.pop(key, None)
        return None
    return game


def active_for_pair(mm: Any, uid: int, partner: int) -> bool:
    game = _current(mm, uid, partner)
    return game is not None and game.status in ("invited", "active")


def state_for(mm: Any, uid: int, partner: int | None) -> dict | None:
    if partner is None:
        return None
    game = _current(mm, uid, partner)
    if game is None:
        return None
    return {
        "type": "dice", "id": game.id, "emoji": game.emoji,
        "title": KINDS[game.kind][1], "status": game.status,
        "inviter": game.inviter == uid,
        "answered": uid in game.rolls,
        "my_roll": game.rolls.get(uid),
        "partner_roll": game.rolls.get(partner),
        "my_display": display_value(game.kind, game.rolls[uid]) if uid in game.rolls else "",
        "partner_display": display_value(game.kind, game.rolls[partner]) if partner in game.rolls else "",
        "my_score": _score(game.kind, game.rolls[uid]) if uid in game.rolls else None,
        "partner_score": _score(game.kind, game.rolls[partner]) if partner in game.rolls else None,
        "total": 1, "round": 1, "finished": game.status == "finished",
    }


def invite_markup(game: Duel) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Играть", callback_data=f"game:dice:yes:{game.id}"),
        InlineKeyboardButton(text="Не сейчас", callback_data=f"game:dice:no:{game.id}"),
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
    rule = ("Три одинаковых символа сильнее пары, 777 — лучше всех."
            if kind == "slots" else
            "Каждый делает один бросок. Чей результат выше — тот победил.")
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


async def roll(mm: Any, bot: Any, uid: int, partner: int, game_id: int,
               *, original: Any = None) -> tuple[Duel, int]:
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
        finished = len(game.rolls) == 2
        if finished:
            game.status = "finished"
            game.finished_at = time.monotonic()
    display = display_value(game.kind, value)
    live_chat.private(uid, f"{game.emoji} Твой бросок: {display}", kind="game_round")
    live_chat.private(partner, f"{game.emoji} Бросок собеседника: {display}", kind="game_round")
    if finished:
        for player in game.pair:
            other = partner if player == uid else uid
            mine = game.rolls[player]
            theirs = game.rolls[other]
            mine_score, their_score = _score(game.kind, mine), _score(game.kind, theirs)
            outcome = ("🤝 Ничья!" if mine_score == their_score
                       else "🏆 Победа!" if mine_score > their_score else "Собеседник победил.")
            text = (f"{game.emoji} <b>{outcome}</b>\n"
                    f"Ты: <b>{display_value(game.kind, mine)}</b> · "
                    f"Собеседник: <b>{display_value(game.kind, theirs)}</b>\n"
                    "Ещё раз? Игры → выбери эмодзи.")
            try:
                await bot.send_message(player, text, parse_mode="HTML")
            except Exception:
                pass
            live_chat.private(player, text, kind="game_round")
        live_chat.game_status(set(game.pair), "dice", game.id, "finished", "Раунд завершён")
    return game, value


async def try_manual_roll(mm: Any, bot: Any, uid: int, message: Any) -> bool:
    partner = mm.partner(uid)
    if partner is None:
        return False
    game = _current(mm, uid, partner)
    if game is None or game.status != "active":
        return False
    if message.dice is None or message.dice.emoji != game.emoji:
        return False
    try:
        await roll(mm, bot, uid, partner, game.id, original=message)
    except DuelError as exc:
        try:
            await bot.send_message(uid, str(exc))
        except Exception:
            pass
    return True


def reset() -> None:
    """Test isolation and optional graceful reset on restart."""
    _GAMES.clear()
