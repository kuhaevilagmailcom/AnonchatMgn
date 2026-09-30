"""Общая Telegram/UI-логика игры «Геогусер»."""

from __future__ import annotations

import asyncio
import html
import json
import time
from typing import Any

from aiogram.exceptions import TelegramAPIError
from aiogram.types import ReplyKeyboardRemove

from . import geoquest as GQ
from . import keyboards as K
from .actions import send_to
from .engagement import collect_progress_notifications


_timeout_tasks: dict[tuple[int, int], asyncio.Task[None]] = {}


def players(row: Any) -> tuple[int, int]:
    return int(row["user_a"]), int(row["user_b"])


def place_for(row: Any) -> GQ.GeoPlace | None:
    try:
        ids = json.loads(str(row["question_ids"] or "[]"))
        return GQ.get_place(int(ids[int(row["question_index"])]))
    except (IndexError, TypeError, ValueError, json.JSONDecodeError):
        return None


def round_deadline(row: Any) -> int:
    started = int(row["geo_round_started_at"] or row["updated_at"] or 0)
    return started + GQ.GEO_ROUND_SECONDS if started else int(time.time()) + GQ.GEO_ROUND_SECONDS


def _source_line(place: GQ.GeoPlace) -> str:
    source = html.escape(place.source_url, quote=True)
    license_url = html.escape(place.license_url or place.source_url, quote=True)
    license_name = html.escape(place.license or "лицензия")
    return (
        f'ℹ️ <a href="{source}">Источник фото</a> · '
        f'<a href="{license_url}">{license_name}</a>'
    )


def round_caption(row: Any, place: GQ.GeoPlace) -> str:
    index = int(row["question_index"])
    total = max(1, int(row["total_questions"] or GQ.GEO_ROUNDS))
    reward_enabled = bool(int(row["reward_awarded"] or 0))
    reward_line = (
        f"⭐ <b>За точность — до 10 ⭐</b> · дневной лимит {GQ.GEO_DAILY_REWARD_LIMIT} ⭐"
        if reward_enabled
        else "⭐ Сегодня с этим собеседником раунд идёт без начисления ⭐"
    )
    return (
        f"🗺 <b>ГЕОГУСЕР · РАУНД {index + 1}/{total}</b>\n"
        f"⏱ <b>Время: 2 минуты</b>\n\n"
        "📸 <b>Где в Магнитогорске сделано это фото?</b>\n\n"
        "📍 <b>Как отправить ответ:</b>\n"
        "1. Нажми <b>скрепку 📎</b> в Telegram\n"
        "2. Выбери <b>«Геопозиция»</b>\n"
        "3. Передвинь карту и <b>выбери точку в Магнитогорске</b>\n"
        "4. Отправь выбранную точку боту\n\n"
        "⚠️ <b>Не отправляй «свою текущую геопозицию».</b> "
        "Для игры нужна именно выбранная тобой точка на карте.\n\n"
        f"{reward_line}\n"
        "🎯 Чем ближе метка к настоящему месту — тем больше ⭐.\n\n"
        f"<i>Фото: {html.escape(place.credit)}</i>"
    )


async def send_round(bot, pack, row: Any) -> bool:
    """Отправить фото обоим игрокам и убрать старую request_location-клавиатуру."""
    place = place_for(row)
    if place is None:
        return False
    caption = round_caption(row, place)
    for user_id in players(row):
        try:
            await bot.send_photo(
                user_id,
                place.image_url,
                caption=pack.wrap(caption),
                reply_markup=ReplyKeyboardRemove(),
            )
        except TelegramAPIError:
            await send_to(
                bot,
                user_id,
                f'{caption}\n\n<a href="{html.escape(place.image_url, quote=True)}">Открыть фотографию</a>',
                ReplyKeyboardRemove(),
                pack,
            )
    return True


def _accuracy_line(distance: float | None, answered: bool, reward: int) -> str:
    if not answered or distance is None:
        return "⏰ <b>Метка не отправлена вовремя</b> · +<b>0 ⭐</b>"
    return (
        f"📏 Ошибка — <b>{GQ.format_distance(distance)}</b>\n"
        f"⭐ За точность — <b>+{int(reward)} ⭐</b>"
    )


def result_body(
    row: Any,
    place: GQ.GeoPlace,
    user_id: int,
    reward_a: int,
    reward_b: int,
) -> str:
    user_a, user_b = players(row)
    mine_a = int(user_id) == user_a
    mine_answered = row["geo_lat_a"] is not None if mine_a else row["geo_lat_b"] is not None
    other_answered = row["geo_lat_b"] is not None if mine_a else row["geo_lat_a"] is not None
    mine_distance = (
        float(row["geo_distance_a"]) if mine_a and row["geo_distance_a"] is not None
        else float(row["geo_distance_b"]) if not mine_a and row["geo_distance_b"] is not None
        else None
    )
    other_distance = (
        float(row["geo_distance_b"]) if mine_a and row["geo_distance_b"] is not None
        else float(row["geo_distance_a"]) if not mine_a and row["geo_distance_a"] is not None
        else None
    )
    mine_reward = int(reward_a if mine_a else reward_b)
    other_reward = int(reward_b if mine_a else reward_a)

    if mine_answered and other_answered and mine_distance is not None and other_distance is not None:
        delta = abs(mine_distance - other_distance)
        if delta <= GQ.GEO_TIE_METERS:
            verdict = "🤝 <b>Практически одинаковая точность!</b>"
        elif mine_distance < other_distance:
            verdict = f"🏆 <b>Ты оказался ближе на {GQ.format_distance(delta)}!</b>"
        else:
            verdict = f"👤 <b>Собеседник оказался ближе на {GQ.format_distance(delta)}.</b>"
    elif mine_answered and not other_answered:
        verdict = "🏆 <b>Собеседник не успел — твоя метка засчитана.</b>"
    elif not mine_answered and other_answered:
        verdict = "⏰ <b>Время вышло. Собеседник успел отправить метку.</b>"
    else:
        verdict = "⏰ <b>Время вышло — никто не успел отправить метку.</b>"

    index = int(row["question_index"])
    total = max(1, int(row["total_questions"] or GQ.GEO_ROUNDS))
    finished = str(row["status"]) == "finished"
    mine_total = int((row["reward_total_a"] if mine_a else row["reward_total_b"]) or 0)

    body = (
        f"🗺 <b>РЕЗУЛЬТАТ · {index + 1}/{total}</b>\n\n"
        f"📍 <b>{html.escape(place.title)}</b>\n\n"
        "🎯 <b>Твоя точность</b>\n"
        f"{_accuracy_line(mine_distance, mine_answered, mine_reward)}\n\n"
        "👤 <b>Собеседник</b>\n"
        f"{_accuracy_line(other_distance, other_answered, other_reward)}\n\n"
        f"{verdict}\n\n"
        f"✨ За игру сейчас: <b>{mine_total} ⭐</b>"
    )
    if finished:
        body += (
            "\n\n━━━━━━━━━━━━━━\n"
            "🏁 <b>ГЕОГУСЕР ЗАВЕРШЁН</b>\n"
            f"🎮 Раундов сыграно: <b>{total}</b>\n"
            f"⭐ Получено за игру: <b>{mine_total} ⭐</b>\n"
            "━━━━━━━━━━━━━━"
        )
    else:
        body += "\n\n⏭ <i>Следующее место откроется по кнопке ниже.</i>"

    return f"{body}\n\n{_source_line(place)}"


async def send_result(bot, pack, row: Any, reward_a: int, reward_b: int) -> None:
    place = place_for(row)
    if place is None:
        return
    user_a, user_b = players(row)
    finished = str(row["status"]) == "finished"
    markup = (
        K.geo_end_keyboard()
        if finished
        else K.geo_next_keyboard(int(row["id"]), int(row["question_index"]))
    )
    for user_id in (user_a, user_b):
        await send_to(
            bot,
            user_id,
            result_body(row, place, user_id, reward_a, reward_b),
            markup,
            pack,
        )
        try:
            await bot.send_location(user_id, place.latitude, place.longitude)
        except TelegramAPIError:
            pass


async def finish_tracking(bot, db, mm, pack, row: Any) -> None:
    if str(row["status"]) != "finished":
        return
    user_a, user_b = players(row)
    total = max(1, int(row["total_questions"] or GQ.GEO_ROUNDS))
    mm.record_game(user_a, "geo", 0, total)
    for user_id in (user_a, user_b):
        await db.record_game_engagement(user_id, "geo", total=total)
        for notice in await collect_progress_notifications(db, user_id):
            await send_to(bot, user_id, notice, pack=pack)


def cancel_timeout(game_id: int, round_index: int) -> None:
    task = _timeout_tasks.pop((int(game_id), int(round_index)), None)
    if task is not None and not task.done() and task is not asyncio.current_task():
        task.cancel()


def schedule_timeout(bot, db, mm, pack, row: Any) -> None:
    game_id = int(row["id"])
    round_index = int(row["question_index"])
    key = (game_id, round_index)
    existing = _timeout_tasks.get(key)
    if existing is not None and not existing.done():
        return
    deadline = round_deadline(row)

    async def runner() -> None:
        try:
            await asyncio.sleep(max(0.0, deadline - time.time()))
            state, game, reward_a, reward_b = await db.expire_geo_round(
                game_id, round_index
            )
            if state != "resolved" or game is None:
                return
            await send_result(bot, pack, game, reward_a, reward_b)
            await finish_tracking(bot, db, mm, pack, game)
        except asyncio.CancelledError:
            raise
        finally:
            _timeout_tasks.pop(key, None)

    _timeout_tasks[key] = asyncio.create_task(runner())
