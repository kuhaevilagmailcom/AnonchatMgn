"""Игра «Объясни слово»: состояние живёт только в RAM, награды ограничивает БД."""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field

WORD_ROUNDS = 5
WORD_REWARD = 3
WORD_PAIR_DAILY_REWARD_LIMIT = 6
WORD_DAILY_REWARD_LIMIT = 9

WORDS: tuple[str, ...] = (
    "самокат", "наушники", "рюкзак", "мороженое", "зонт", "автобус",
    "лифт", "подушка", "зеркало", "фонарь", "ноутбук", "будильник",
    "зарядка", "пицца", "арбуз", "велосипед", "снеговик", "кинотеатр",
    "магазин", "светофор", "кастрюля", "пылесос", "микрофон", "клавиатура",
    "гитара", "футбол", "шоколад", "чайник", "холодильник", "чемодан",
    "ракета", "облако", "фотография", "такси", "остановка", "бассейн",
    "подарок", "шарик", "кроссовки", "кепка", "кошелёк", "батарея",
    "окно", "лестница", "диван", "плед", "мышка", "колонка",
    "парикмахер", "врач", "учитель", "художник", "повар", "поезд",
    "самолёт", "корабль", "мост", "парк", "дождь", "молния", "радуга",
    "снег", "солнце", "кошка", "собака", "хомяк", "попугай", "жираф",
    "панда", "крокодил", "апельсин", "банан", "лимон", "огурец",
    "помидор", "бургер", "роллы", "компас", "термос", "скейтборд",
)


@dataclass(slots=True)
class WordGame:
    id: int
    user_a: int
    user_b: int
    inviter_id: int
    status: str = "invited"
    round_index: int = 0
    explainer_id: int = 0
    guesser_id: int = 0
    word: str = ""
    used_words: set[str] = field(default_factory=set)
    correct: dict[int, int] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass(slots=True, frozen=True)
class GuessResult:
    game_id: int
    round_index: int
    total_rounds: int
    word: str
    explainer_id: int
    guesser_id: int
    finished: bool
    correct_total: int


_games: dict[tuple[int, int], WordGame] = {}
_by_id: dict[int, WordGame] = {}
_next_id = 1


def _pair_key(user_a: int, user_b: int) -> tuple[int, int]:
    a, b = sorted((int(user_a), int(user_b)))
    return a, b


def _normalize(value: str) -> str:
    value = str(value or "").casefold().replace("ё", "е")
    return " ".join(re.findall(r"[0-9a-zа-я]+", value))


def _contains_word(text: str, word: str) -> bool:
    normalized = _normalize(text)
    target = _normalize(word)
    if not normalized or not target:
        return False
    return target in normalized.split()


def get_for_pair(user_a: int, user_b: int) -> WordGame | None:
    return _games.get(_pair_key(user_a, user_b))


def get_by_id(game_id: int) -> WordGame | None:
    return _by_id.get(int(game_id))


def create_invite(inviter_id: int, partner_id: int) -> tuple[WordGame, bool]:
    global _next_id
    key = _pair_key(inviter_id, partner_id)
    existing = _games.get(key)
    if existing is not None:
        return existing, False
    game = WordGame(
        id=_next_id,
        user_a=int(inviter_id),
        user_b=int(partner_id),
        inviter_id=int(inviter_id),
    )
    _next_id += 1
    _games[key] = game
    _by_id[game.id] = game
    return game, True


def _choose_word(game: WordGame) -> str:
    pool = [word for word in WORDS if word not in game.used_words]
    if not pool:
        game.used_words.clear()
        pool = list(WORDS)
    word = random.choice(pool)
    game.used_words.add(word)
    return word


def _start_round(game: WordGame) -> WordGame:
    first = game.inviter_id
    second = game.user_b if game.user_a == first else game.user_a
    game.explainer_id = first if game.round_index % 2 == 0 else second
    game.guesser_id = second if game.explainer_id == first else first
    game.word = _choose_word(game)
    game.status = "active"
    game.updated_at = time.time()
    return game


def accept(game_id: int, user_id: int) -> WordGame | None:
    game = get_by_id(game_id)
    if (
        game is None
        or game.status != "invited"
        or int(user_id) not in {game.user_a, game.user_b}
        or int(user_id) == game.inviter_id
    ):
        return None
    return _start_round(game)


def decline(game_id: int, user_id: int) -> WordGame | None:
    game = get_by_id(game_id)
    if (
        game is None
        or game.status != "invited"
        or int(user_id) not in {game.user_a, game.user_b}
        or int(user_id) == game.inviter_id
    ):
        return None
    remove(game_id)
    return game


def explainer_used_secret(user_id: int, partner_id: int, text: str) -> bool:
    game = get_for_pair(user_id, partner_id)
    return bool(
        game
        and game.status == "active"
        and game.explainer_id == int(user_id)
        and _contains_word(text, game.word)
    )


def resolve_guess(user_id: int, partner_id: int, text: str) -> GuessResult | None:
    game = get_for_pair(user_id, partner_id)
    if (
        game is None
        or game.status != "active"
        or game.guesser_id != int(user_id)
        or not _contains_word(text, game.word)
    ):
        return None

    game.correct[user_id] = game.correct.get(user_id, 0) + 1
    finished = game.round_index >= WORD_ROUNDS - 1
    game.status = "finished" if finished else "round_done"
    game.updated_at = time.time()
    return GuessResult(
        game_id=game.id,
        round_index=game.round_index,
        total_rounds=WORD_ROUNDS,
        word=game.word,
        explainer_id=game.explainer_id,
        guesser_id=game.guesser_id,
        finished=finished,
        correct_total=sum(game.correct.values()),
    )


def advance(game_id: int, user_id: int, round_index: int) -> WordGame | None:
    game = get_by_id(game_id)
    if (
        game is None
        or game.status != "round_done"
        or int(user_id) not in {game.user_a, game.user_b}
        or game.round_index != int(round_index)
    ):
        return None
    game.round_index += 1
    if game.round_index >= WORD_ROUNDS:
        game.status = "finished"
        return game
    return _start_round(game)


def remove(game_id: int) -> WordGame | None:
    game = _by_id.pop(int(game_id), None)
    if game is None:
        return None
    _games.pop(_pair_key(game.user_a, game.user_b), None)
    return game


def clear_pair(user_a: int, user_b: int) -> None:
    game = get_for_pair(user_a, user_b)
    if game is not None:
        remove(game.id)


def active_for_pair(user_a: int, user_b: int) -> bool:
    game = get_for_pair(user_a, user_b)
    return bool(game and game.status in {"invited", "active", "round_done"})


def role_text(game: WordGame, user_id: int) -> str:
    n = game.round_index + 1
    if game.status == "invited":
        return "Предложение отправлено."
    if game.status == "round_done":
        return f"Раунд {n}/{WORD_ROUNDS} завершён."
    if game.status != "active":
        return "Игра завершена."
    if int(user_id) == game.explainer_id:
        return (
            f"🗣 <b>Объясни слово · {n}/{WORD_ROUNDS}</b>\n\n"
            f"Твоё слово: <b>{game.word}</b>\n\n"
            "Объясняй его своими словами, но не пиши само слово."
        )
    return (
        f"🧩 <b>Угадай слово · {n}/{WORD_ROUNDS}</b>\n\n"
        "Собеседник получил слово и будет его объяснять. "
        "Пиши варианты прямо в чат."
    )
