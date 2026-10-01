"""Отдельный GeoGuessr📍 для групповых чатов.

Режим не использует анонимный матчмейкер и не начисляет профильные ⭐:
очки существуют только внутри текущего группового матча.
"""

from __future__ import annotations

import asyncio
import html
import secrets
import time
from dataclasses import dataclass, field

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .. import geoquest as GQ
from ..db import Database

router = Router(name="group_geo")

GROUP_TYPES = {"group", "supergroup"}
INVITE_TTL_SECONDS = 600
ROUNDS = GQ.GEO_ROUNDS


@dataclass(slots=True)
class GroupGeoGame:
    id: str
    chat_id: int
    inviter_id: int
    inviter_name: str
    created_at: float = field(default_factory=time.time)
    player_b_id: int | None = None
    player_b_name: str = ""
    place_ids: tuple[int, ...] = ()
    round_index: int = 0
    status: str = "waiting"
    answers: dict[int, tuple[float, float, float, int]] = field(default_factory=dict)
    totals: dict[int, int] = field(default_factory=dict)
    round_started_at: float = 0.0
    timeout_task: asyncio.Task[None] | None = None
    invite_task: asyncio.Task[None] | None = None

    @property
    def players(self) -> tuple[int, int] | None:
        if self.player_b_id is None:
            return None
        return self.inviter_id, int(self.player_b_id)


_games_by_chat: dict[int, GroupGeoGame] = {}
_games_by_id: dict[str, GroupGeoGame] = {}
_state_lock = asyncio.Lock()


def _name(user) -> str:
    value = (getattr(user, "full_name", "") or getattr(user, "first_name", "") or "Игрок").strip()
    return value[:64] or "Игрок"


def _mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={int(user_id)}">{html.escape(name)}</a>'


def _invite_keyboard(game_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Играть", callback_data=f"ggeo:join:{game_id}")],
            [InlineKeyboardButton(text="Отменить", callback_data=f"ggeo:cancel:{game_id}")],
        ]
    )


def _place(game: GroupGeoGame) -> GQ.GeoPlace | None:
    if not game.place_ids or game.round_index < 0 or game.round_index >= len(game.place_ids):
        return None
    return GQ.get_place(game.place_ids[game.round_index])


def _format_answer(game: GroupGeoGame, user_id: int) -> str:
    answer = game.answers.get(int(user_id))
    if answer is None:
        return "⏰ нет ответа · 0 очков"
    _lat, _lon, distance, score = answer
    return f"📏 {GQ.format_distance(distance)} · +{score} очк."


async def _drop_game(game: GroupGeoGame) -> None:
    async with _state_lock:
        if _games_by_chat.get(game.chat_id) is game:
            _games_by_chat.pop(game.chat_id, None)
        if _games_by_id.get(game.id) is game:
            _games_by_id.pop(game.id, None)
        current = asyncio.current_task()
        for task in (game.timeout_task, game.invite_task):
            if task is not None and not task.done() and task is not current:
                task.cancel()
        game.timeout_task = None
        game.invite_task = None


async def _expire_invite(bot, game_id: str) -> None:
    try:
        await asyncio.sleep(INVITE_TTL_SECONDS)
        game = _games_by_id.get(game_id)
        if game is None or game.status != "waiting":
            return
        await _drop_game(game)
        try:
            await bot.send_message(
                game.chat_id,
                "⌛ Вызов GeoGuessr📍 истёк. Чтобы создать новый — /gamegeo",
            )
        except TelegramAPIError:
            pass
    except asyncio.CancelledError:
        raise


async def _send_round(bot, game: GroupGeoGame) -> None:
    if game.status != "active":
        return
    place = _place(game)
    players = game.players
    if place is None or players is None:
        await _drop_game(game)
        return

    game.answers.clear()
    game.round_started_at = time.time()
    a, b = players
    caption = (
        f"🗺 <b>GeoGuessr📍 · РАУНД {game.round_index + 1}/{len(game.place_ids)}</b>\n\n"
        f"👥 {_mention(a, game.inviter_name)} <b>VS</b> {_mention(b, game.player_b_name)}\n"
        f"⏱ На ответ — <b>{GQ.GEO_ROUND_SECONDS // 60} минуты</b>\n\n"
        "📸 <b>Где в Магнитогорске сделано это фото?</b>\n\n"
        "📍 Оба игрока отправляют геопозицию в этот чат.\n"
        "Чтобы бот гарантированно увидел ответ в группе, <b>ответь геопозицией на это фото</b>.\n"
        "Можно отправить <b>любую точку карты</b>, в том числе текущую геопозицию.\n\n"
        "⭐ Чем ближе к месту — тем больше очков за раунд."
    )
    try:
        await bot.send_photo(game.chat_id, place.image_url, caption=caption)
    except TelegramAPIError:
        await bot.send_message(
            game.chat_id,
            f'{caption}\n\n<a href="{html.escape(place.image_url, quote=True)}">Открыть фотографию</a>',
        )

    round_index = game.round_index

    async def timeout() -> None:
        try:
            await asyncio.sleep(GQ.GEO_ROUND_SECONDS)
            await _resolve_round(bot, game, round_index)
        except asyncio.CancelledError:
            raise

    game.timeout_task = asyncio.create_task(timeout())


async def _finish_match(bot, game: GroupGeoGame) -> None:
    players = game.players
    if players is None:
        await _drop_game(game)
        return
    a, b = players
    score_a = int(game.totals.get(a, 0))
    score_b = int(game.totals.get(b, 0))
    if score_a == score_b:
        verdict = "🤝 <b>Ничья!</b>"
    elif score_a > score_b:
        verdict = f"🏆 Победил {_mention(a, game.inviter_name)}"
    else:
        verdict = f"🏆 Победил {_mention(b, game.player_b_name)}"
    await _drop_game(game)
    await bot.send_message(
        game.chat_id,
        "🏁 <b>GeoGuessr📍 завершён</b>\n\n"
        f"{_mention(a, game.inviter_name)} — <b>{score_a}</b> очк.\n"
        f"{_mention(b, game.player_b_name)} — <b>{score_b}</b> очк.\n\n"
        f"{verdict}\n\n"
        "Новая игра: /gamegeo",
    )


async def _resolve_round(bot, game: GroupGeoGame, round_index: int) -> None:
    if (
        game.status != "active"
        or game.round_index != int(round_index)
        or game.round_started_at <= 0
    ):
        return
    # Ставим 0 до первого await: второй ответ и таймер не смогут закрыть раунд дважды.
    game.round_started_at = 0.0
    task = game.timeout_task
    if task is not None and task is not asyncio.current_task() and not task.done():
        task.cancel()
    game.timeout_task = None

    place = _place(game)
    players = game.players
    if place is None or players is None:
        await _drop_game(game)
        return
    a, b = players
    for uid in (a, b):
        answer = game.answers.get(uid)
        if answer is not None:
            game.totals[uid] = int(game.totals.get(uid, 0)) + int(answer[3])

    body = (
        f"🎯 <b>Результат · {game.round_index + 1}/{len(game.place_ids)}</b>\n\n"
        f"📍 <b>{html.escape(place.title)}</b>\n\n"
        f"{_mention(a, game.inviter_name)}\n{_format_answer(game, a)}\n\n"
        f"{_mention(b, game.player_b_name)}\n{_format_answer(game, b)}\n\n"
        f"Счёт: <b>{game.totals.get(a, 0)} : {game.totals.get(b, 0)}</b>"
    )
    await bot.send_message(game.chat_id, body)
    try:
        await bot.send_location(game.chat_id, place.latitude, place.longitude)
    except TelegramAPIError:
        pass

    if game.round_index >= len(game.place_ids) - 1:
        game.status = "finished"
        await _finish_match(bot, game)
        return

    game.round_index += 1
    await asyncio.sleep(1)
    if _games_by_id.get(game.id) is game and game.status == "active":
        await _send_round(bot, game)


@router.message(Command("gamegeo"))
async def cmd_group_geo(message: Message, bot: Bot) -> None:
    if message.chat.type not in GROUP_TYPES or message.from_user is None or message.from_user.is_bot:
        return

    chat_id = int(message.chat.id)
    existing = _games_by_chat.get(chat_id)
    if existing is not None:
        if existing.status == "waiting" and time.time() - existing.created_at > INVITE_TTL_SECONDS:
            await _drop_game(existing)
            existing = None
        elif existing.status == "waiting":
            await message.answer(
                "🗺 В этой группе уже есть открытый вызов GeoGuessr📍. Нажми «Играть» в сообщении выше."
            )
            return
        else:
            players = existing.players
            if players:
                await message.answer(
                    "🎮 Здесь уже идёт GeoGuessr📍: "
                    f"{_mention(players[0], existing.inviter_name)} VS "
                    f"{_mention(players[1], existing.player_b_name)}."
                )
            return

    game_id = secrets.token_hex(4)
    game = GroupGeoGame(
        id=game_id,
        chat_id=chat_id,
        inviter_id=int(message.from_user.id),
        inviter_name=_name(message.from_user),
    )
    async with _state_lock:
        _games_by_chat[chat_id] = game
        _games_by_id[game_id] = game
    await message.answer(
        "🗺 <b>GeoGuessr📍 · ВЫЗОВ</b>\n\n"
        f"{_mention(game.inviter_id, game.inviter_name)} ищет соперника.\n"
        f"🎮 <b>{ROUNDS} раунда</b> · ⏱ <b>2 минуты</b> на каждый.\n\n"
        "Первый, кто нажмёт <b>«Играть»</b>, станет вторым игроком.",
        reply_markup=_invite_keyboard(game.id),
    )
    game.invite_task = asyncio.create_task(_expire_invite(bot, game.id))


@router.callback_query(F.data.startswith("ggeo:join:"))
async def cb_group_geo_join(event: CallbackQuery, bot: Bot, db: Database) -> None:
    game_id = (event.data or "").rsplit(":", 1)[-1]
    game = _games_by_id.get(game_id)
    message = event.message
    if (
        game is None
        or game.status != "waiting"
        or message is None
        or getattr(message, "chat", None) is None
        or int(message.chat.id) != game.chat_id
    ):
        await event.answer("Этот вызов уже закрыт", show_alert=True)
        return
    if int(event.from_user.id) == game.inviter_id:
        await event.answer("Ты уже первый игрок — нужен соперник", show_alert=True)
        return

    player_b_id = int(event.from_user.id)
    excluded = await db.recent_geo_place_ids((game.inviter_id, player_b_id))
    place_ids = tuple(GQ.select_place_ids(ROUNDS, excluded=excluded))

    async with _state_lock:
        if game.status != "waiting":
            await event.answer("Кто-то уже принял игру", show_alert=True)
            return
        game.player_b_id = player_b_id
        game.player_b_name = _name(event.from_user)
        game.place_ids = place_ids
        game.totals = {game.inviter_id: 0, game.player_b_id: 0}
        game.round_index = 0
        game.status = "active"
        if game.invite_task is not None and not game.invite_task.done():
            game.invite_task.cancel()
        game.invite_task = None

    await db.remember_geo_places((game.inviter_id, player_b_id), place_ids)

    await event.answer("Игра началась!")
    try:
        await message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass

    await bot.send_message(
        game.chat_id,
        "🔥 <b>ИГРА НАЧАЛАСЬ</b>\n\n"
        f"👤 {_mention(game.inviter_id, game.inviter_name)}\n"
        "<b>VS</b>\n"
        f"👤 {_mention(game.player_b_id, game.player_b_name)}\n\n"
        f"🎮 {ROUNDS} раунда · по {GQ.GEO_ROUND_SECONDS // 60} минуты.",
    )
    await _send_round(bot, game)


@router.callback_query(F.data.startswith("ggeo:cancel:"))
async def cb_group_geo_cancel(event: CallbackQuery) -> None:
    game_id = (event.data or "").rsplit(":", 1)[-1]
    game = _games_by_id.get(game_id)
    if game is None or game.status != "waiting":
        await event.answer("Вызов уже закрыт", show_alert=True)
        return
    if int(event.from_user.id) != game.inviter_id:
        await event.answer("Отменить вызов может только его автор", show_alert=True)
        return
    await _drop_game(game)
    await event.answer("Вызов отменён")
    if event.message is not None:
        try:
            await event.message.edit_text("❌ Вызов GeoGuessr📍 отменён.")
        except TelegramAPIError:
            pass


@router.message(F.location | F.venue)
async def group_geo_location(message: Message, bot: Bot) -> None:
    if message.chat.type not in GROUP_TYPES:
        raise SkipHandler
    if message.from_user is None:
        return
    game = _games_by_chat.get(int(message.chat.id))
    if game is None or game.status != "active" or game.round_started_at <= 0:
        return
    players = game.players
    if players is None or int(message.from_user.id) not in players:
        return

    point = message.location
    if point is None and message.venue is not None:
        point = message.venue.location
    if point is None or not GQ.valid_guess_coordinate(point.latitude, point.longitude):
        return

    uid = int(message.from_user.id)
    if uid in game.answers:
        await message.reply("✅ Твоя метка уже принята в этом раунде.")
        return

    place = _place(game)
    if place is None:
        return
    distance = GQ.distance_meters(
        point.latitude, point.longitude, place.latitude, place.longitude
    )
    score = GQ.geo_reward(distance)
    game.answers[uid] = (
        float(point.latitude),
        float(point.longitude),
        float(distance),
        int(score),
    )

    if len(game.answers) < 2:
        await message.reply(
            f"✅ Метка {_mention(uid, _name(message.from_user))} принята. Ждём второго игрока…"
        )
        return

    await _resolve_round(bot, game, game.round_index)


async def clear_group_geo_state() -> None:
    """Тестовый/служебный сброс памяти групповых матчей."""
    for game in list(_games_by_id.values()):
        await _drop_game(game)
