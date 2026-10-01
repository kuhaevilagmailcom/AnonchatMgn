"""Игры внутри активного анонимного диалога."""

from __future__ import annotations

import json
import random
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .. import keyboards as K
from .. import texts
from ..actions import Ctx, DeliveryResult, send_to
from ..battle_questions import BattleQuestion, get_question, questions
from ..db import Database
from ..matching import Matchmaker
from ..engagement import collect_progress_notifications
from ..number_game import (
    NUMBER_DAILY_REWARD_LIMIT,
    NUMBER_NEAR_DIFFS,
    NUMBER_REWARDS,
    NUMBER_ROUNDS,
    number_reward,
)
from .. import word_game as WG
from .. import geoquest as GQ
from .. import geo_runtime as GR
from .. import live_chat

router = Router(name="games")


async def _notify_progress(ctx: Ctx, user_id: int) -> None:
    for notice in await collect_progress_notifications(ctx.db, user_id):
        await send_to(ctx.bot, user_id, notice, pack=ctx.pack)


def _players(row: Any) -> tuple[int, int]:
    return int(row["user_a"]), int(row["user_b"])


def _current_pair(mm: Matchmaker, row: Any) -> bool:
    user_a, user_b = _players(row)
    return mm.partner(user_a) == user_b and mm.partner(user_b) == user_a


def _question(row: Any) -> BattleQuestion:
    ids = json.loads(str(row["question_ids"] or "[]"))
    return get_question(int(ids[int(row["question_index"])]))


def _total(row: Any) -> int:
    return int(row["total_questions"])


def _game_type(row: Any) -> str:
    try:
        return str(row["game_type"] or "battle")
    except (KeyError, IndexError):
        return "battle"


def _number_answered(row: Any, user_id: int) -> bool:
    column = "answer_a" if int(row["user_a"]) == user_id else "answer_b"
    return row[column] is not None


def _geo_answered(row: Any, user_id: int) -> bool:
    suffix = "a" if int(row["user_a"]) == int(user_id) else "b"
    return row[f"geo_lat_{suffix}"] is not None


def _geo_place(row: Any) -> GQ.GeoPlace | None:
    return GR.place_for(row)


async def _require_current_game(ctx: Ctx, db: Database, game_id: int) -> Any | None:
    row = await db.get_battle(game_id)
    if (
        row is None
        or _game_type(row) != "battle"
        or ctx.user_id not in set(_players(row))
    ):
        await ctx.ack("Игра не найдена", alert=True)
        return None
    if not _current_pair(ctx.mm, row):
        await db.cancel_battle(game_id)
        await ctx.ack("Диалог уже завершён", alert=True)
        return None
    return row


async def _require_current_number(ctx: Ctx, db: Database, game_id: int) -> Any | None:
    row = await db.get_battle(game_id)
    if (
        row is None
        or _game_type(row) != "numbers"
        or ctx.user_id not in set(_players(row))
    ):
        await ctx.ack("Игра не найдена", alert=True)
        return None
    if not _current_pair(ctx.mm, row):
        await db.cancel_battle(game_id)
        await ctx.ack("Диалог уже завершён", alert=True)
        return None
    return row


async def _require_current_geo(ctx: Ctx, db: Database, game_id: int) -> Any | None:
    row = await db.get_battle(game_id)
    if (
        row is None
        or _game_type(row) != "geo"
        or ctx.user_id not in set(_players(row))
    ):
        await ctx.ack("Игра не найдена", alert=True)
        return None
    if not _current_pair(ctx.mm, row):
        await db.cancel_battle(game_id)
        await ctx.ack("Диалог уже завершён", alert=True)
        return None
    return row


async def _send_geo_round(ctx: Ctx, row: Any) -> None:
    if not await GR.send_round(ctx.bot, ctx.pack, row):
        await ctx.db.cancel_battle(int(row["id"]))
        for user_id in _players(row):
            await send_to(
                ctx.bot,
                user_id,
                "🗺 Не получилось открыть место. Игра остановлена.",
                K.chat_keyboard(),
                ctx.pack,
            )
        return
    GR.schedule_timeout(ctx.bot, ctx.db, ctx.mm, ctx.pack, row)


async def _send_geo_result(
    ctx: Ctx, row: Any, reward_a: int, reward_b: int
) -> None:
    await GR.send_result(ctx.bot, ctx.pack, row, reward_a, reward_b)
    await GR.finish_tracking(ctx.bot, ctx.db, ctx.mm, ctx.pack, row)

def _number_prompt(row: Any) -> str:
    round_index = int(row["question_index"])
    range_max = int(row["range_max"])
    reward_note = (
        f"Награды активны · лимит <b>{NUMBER_DAILY_REWARD_LIMIT} ⭐</b> в сутки."
        if int(row["reward_awarded"] or 0)
        else "С этим собеседником награда уже использована — игра идёт без ⭐."
    )
    return (
        f"🔢 <b>Числа · раунд {round_index + 1}/{NUMBER_ROUNDS}</b>\n\n"
        f"Выбери число от <b>1</b> до <b>{range_max}</b>.\n"
        "Собеседник увидит его только после своего выбора.\n"
        f"{reward_note}"
    )


async def _send_number_round(ctx: Ctx, row: Any) -> None:
    body = _number_prompt(row)
    game_id = int(row["id"])
    round_index = int(row["question_index"])
    for user_id in _players(row):
        await send_to(
            ctx.bot,
            user_id,
            body,
            K.number_input_keyboard(game_id, round_index),
            ctx.pack,
        )


async def _send_number_result(
    ctx: Ctx, row: Any, reward_a: int, reward_b: int
) -> None:
    user_a, user_b = _players(row)
    answer_a = int(row["answer_a"])
    answer_b = int(row["answer_b"])
    diff = abs(answer_a - answer_b)
    raw_reward = number_reward(int(row["range_max"]), answer_a, answer_b)
    reward_enabled = bool(int(row["reward_awarded"] or 0))

    def reward_line(actual: int) -> str:
        if raw_reward <= 0:
            return "В этом раунде без награды."
        if not reward_enabled:
            return "С этой парой награда уже использована · +<b>0 ⭐</b>."
        if actual <= 0:
            return (
                f"Дневной лимит <b>{NUMBER_DAILY_REWARD_LIMIT} ⭐</b> достигнут · "
                "+<b>0 ⭐</b>."
            )
        if actual < raw_reward:
            return (
                f"+<b>{actual} ⭐</b> · сработал дневной лимит "
                f"{NUMBER_DAILY_REWARD_LIMIT} ⭐."
            )
        return f"+<b>{actual} ⭐</b>."

    if diff == 0:
        head_a = head_b = (
            f"🎯 <b>Точное совпадение!</b>\n"
            f"Вы оба выбрали <b>{answer_a}</b>.\n"
        )
    elif 1 <= diff <= NUMBER_NEAR_DIFFS.get(int(row["range_max"]), 0):
        head_a = (
            f"🔥 <b>Почти совпало!</b>\n"
            f"Ты: <b>{answer_a}</b> · собеседник: <b>{answer_b}</b>\n"
            f"Разница <b>{diff}</b>.\n"
        )
        head_b = (
            f"🔥 <b>Почти совпало!</b>\n"
            f"Ты: <b>{answer_b}</b> · собеседник: <b>{answer_a}</b>\n"
            f"Разница <b>{diff}</b>.\n"
        )
    else:
        head_a = (
            f"🔢 <b>Не совпало</b>\n"
            f"Ты: <b>{answer_a}</b> · собеседник: <b>{answer_b}</b>\n"
        )
        head_b = (
            f"🔢 <b>Не совпало</b>\n"
            f"Ты: <b>{answer_b}</b> · собеседник: <b>{answer_a}</b>\n"
        )

    body_a = f"{head_a}{reward_line(reward_a)}"
    body_b = f"{head_b}{reward_line(reward_b)}"

    if str(row["status"]) == "finished":
        total_a = int(row["reward_total_a"] or 0)
        total_b = int(row["reward_total_b"] or 0)
        exact = int(row["matches"])
        final_a = (
            f"🔢 <b>Игра окончена</b>\n"
            f"Сыграно раундов: <b>{NUMBER_ROUNDS}</b>\n"
            f"Точных совпадений: <b>{exact}/{NUMBER_ROUNDS}</b>\n"
            f"Ты получил за игру: <b>{total_a} ⭐</b>."
        )
        final_b = (
            f"🔢 <b>Игра окончена</b>\n"
            f"Сыграно раундов: <b>{NUMBER_ROUNDS}</b>\n"
            f"Точных совпадений: <b>{exact}/{NUMBER_ROUNDS}</b>\n"
            f"Ты получил за игру: <b>{total_b} ⭐</b>."
        )
        markup = K.number_end_keyboard()
        body_a = f"{body_a}\n\n{final_a}"
        body_b = f"{body_b}\n\n{final_b}"
    else:
        markup = K.number_next_keyboard(int(row["id"]), int(row["question_index"]))

    await send_to(ctx.bot, user_a, body_a, markup, ctx.pack)
    await send_to(ctx.bot, user_b, body_b, markup, ctx.pack)


async def _send_question(ctx: Ctx, row: Any) -> None:
    question = _question(row)
    index = int(row["question_index"])
    body = f"⚔️ <b>{index + 1}/{_total(row)}</b>\n\n{texts.esc(question.text)}"
    markup = K.battle_answer_keyboard(row["id"], index, question.first, question.second)
    for user_id in _players(row):
        await send_to(ctx.bot, user_id, body, markup, ctx.pack)


def _final_text(matches: int, total: int) -> str:
    reward = "\n🎁 Каждому начислено <b>25 ⭐</b>." if matches == total else ""
    return f"⚔️ <b>Битва окончена</b>\nСовпадений: <b>{matches}/{total}</b>.{reward}"


async def _send_round_result(ctx: Ctx, row: Any) -> None:
    question = _question(row)
    user_a, user_b = _players(row)
    answer_a = int(row["answer_a"])
    answer_b = int(row["answer_b"])
    index = int(row["question_index"])
    if answer_a == answer_b:
        body_a = body_b = (
            f"🤝 <b>Совпало!</b>\nВы оба выбрали: "
            f"<b>{texts.esc(question.option(answer_a))}</b>"
        )
    else:
        body_a = (
            f"💥 <b>Разошлись</b>\n"
            f"Ты: <b>{texts.esc(question.option(answer_a))}</b>\n"
            f"Собеседник: <b>{texts.esc(question.option(answer_b))}</b>"
        )
        body_b = (
            f"💥 <b>Разошлись</b>\n"
            f"Ты: <b>{texts.esc(question.option(answer_b))}</b>\n"
            f"Собеседник: <b>{texts.esc(question.option(answer_a))}</b>"
        )
    if row["status"] == "finished":
        final = _final_text(int(row["matches"]), _total(row))
        markup = K.battle_end_keyboard()
        body_a = f"{body_a}\n\n{final}"
        body_b = f"{body_b}\n\n{final}"
    else:
        markup = K.battle_next_keyboard(int(row["id"]), index)
    await send_to(ctx.bot, user_a, body_a, markup, ctx.pack)
    await send_to(ctx.bot, user_b, body_b, markup, ctx.pack)


async def _send_word_round(ctx: Ctx, game: WG.WordGame) -> None:
    for user_id in (game.user_a, game.user_b):
        role = WG.role_text(game, user_id)
        await send_to(
            ctx.bot,
            user_id,
            role,
            K.chat_keyboard(),
            ctx.pack,
        )
        live_chat.private(
            user_id,
            role,
            kind="game_round",
            data={"game_type": "words", "game_id": int(game.id)},
        )


async def _open_games(ctx: Ctx) -> None:
    if ctx.mm.partner(ctx.user_id) is None:
        await ctx.reply("🎮 Игры доступны только в активном диалоге.", K.menu_keyboard())
        return
    await ctx.reply(
        "🎮 <b>Игры с собеседником</b>\n\nВыбери игру.",
        K.games_keyboard(admin=ctx.is_admin),
    )


@router.message(Command("game", "games"))
async def cmd_game(message: Message, ctx: Ctx) -> None:
    await _open_games(ctx)


@router.callback_query(F.data == K.CB_GAMES)
async def cb_games(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack()
    await _open_games(ctx)


@router.callback_query(F.data == "game:return")
async def cb_return(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack("Вернулись в чат")
    await ctx.reply("💬 Можно продолжать общение.", K.chat_keyboard())


@router.callback_query(F.data == K.CB_NUMBERS)
async def cb_numbers(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    partner = ctx.mm.partner(ctx.user_id)
    if partner is None:
        await ctx.ack("Сначала найди собеседника", alert=True)
        return
    if WG.active_for_pair(ctx.user_id, partner):
        await ctx.ack("Сначала заверши игру «Объясни слово»", alert=True)
        return

    existing = await db.game_for_pair(ctx.user_id, partner)
    if existing is not None:
        if _game_type(existing) != "numbers":
            await ctx.ack("Сначала заверши текущую игру", alert=True)
            return
        status = str(existing["status"])
        game_id = int(existing["id"])
        range_max = int(existing["range_max"])
        if status == "invited":
            if int(existing["inviter_id"]) == ctx.user_id:
                await ctx.ack("Предложение уже отправлено", alert=True)
            else:
                await ctx.reply(
                    f"🔢 Собеседник предлагает сыграть в Числа · 1–{range_max}.",
                    K.number_invite_keyboard(game_id),
                )
            return
        if status == "active":
            await ctx.ack("Игра уже идёт")
            if _number_answered(existing, ctx.user_id):
                await ctx.reply("🔢 Число принято. Ждём выбор собеседника…")
            else:
                await ctx.reply(
                    _number_prompt(existing),
                    K.number_input_keyboard(game_id, int(existing["question_index"])),
                )
            return
        await ctx.reply(
            "🔢 Раунд завершён. Можно перейти дальше.",
            K.number_next_keyboard(game_id, int(existing["question_index"])),
        )
        return

    await ctx.ack()
    await ctx.reply(
        "🔢 <b>Числа · 3 раунда</b>\n\n"
        "Выбери диапазон. Чем он больше, тем выше награда за совпадение.",
        K.number_range_keyboard(),
    )


@router.callback_query(F.data.startswith("game:numbers:range:"))
async def cb_number_range(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    try:
        range_max = int((event.data or "").rsplit(":", 1)[1])
    except (TypeError, ValueError):
        await ctx.ack("Неверный диапазон", alert=True)
        return
    if range_max not in NUMBER_REWARDS:
        await ctx.ack("Можно выбрать 1–10, 1–100 или 1–1000", alert=True)
        return

    partner = ctx.mm.partner(ctx.user_id)
    if partner is None:
        await ctx.ack("Сначала найди собеседника", alert=True)
        return
    if WG.active_for_pair(ctx.user_id, partner):
        await ctx.ack("Сначала заверши игру «Объясни слово»", alert=True)
        return

    reward_available = await db.number_pair_reward_available(ctx.user_id, partner)
    game, created = await db.create_number_invite(ctx.user_id, partner, range_max)
    if not created:
        await ctx.ack("У вас уже есть активная игра", alert=True)
        return

    base = NUMBER_REWARDS[range_max]
    near = base // 2
    near_diff = NUMBER_NEAR_DIFFS[range_max]
    result = await send_to(
        ctx.bot,
        partner,
        f"🔢 <b>Собеседник предлагает сыграть в Числа</b>\n"
        f"Диапазон: <b>1–{range_max}</b> · раундов: <b>{NUMBER_ROUNDS}</b>\n"
        f"Точное совпадение: <b>{base} ⭐</b> · "
        f"разница до {near_diff}: <b>{near} ⭐</b>\n"
        + (
            f"Награды доступны · дневной лимит {NUMBER_DAILY_REWARD_LIMIT} ⭐."
            if reward_available
            else "Вы уже играли вместе — эта игра будет без награды."
        ),
        K.number_invite_keyboard(int(game["id"])),
        ctx.pack,
    )
    if result is DeliveryResult.UNAVAILABLE:
        await db.cancel_battle(int(game["id"]))
        await ctx.reply("Не получилось отправить предложение.")
        return
    live_chat.game_invite(
        ctx.user_id,
        partner,
        "numbers",
        int(game["id"]),
        "🔢 Числа",
        f"Диапазон 1–{range_max} · {NUMBER_ROUNDS} раунда",
    )
    event_id = await db.add_miniapp_event(
        partner, "games", "Приглашение в «Числа»",
        f"Диапазон 1–{range_max} · {NUMBER_ROUNDS} раунда",
        icon="gamepad-2", action="chat",
    )
    live_chat.signal({partner}, "events_changed", event_id=event_id)
    await ctx.ack()
    await ctx.reply("🔢 Предложение отправлено.")


@router.callback_query(F.data.startswith("game:num:yes:"))
async def cb_number_accept(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    try:
        game_id = int((event.data or "").rsplit(":", 1)[1])
    except (TypeError, ValueError):
        await ctx.ack("Игра не найдена", alert=True)
        return
    row = await _require_current_number(ctx, db, game_id)
    if row is None:
        return
    game = await db.accept_number(game_id, ctx.user_id)
    if game is None:
        await ctx.ack("На это предложение уже ответили", alert=True)
        return
    live_chat.game_status(
        set(_players(game)), "numbers", game_id, "accepted", "Игра началась"
    )
    await ctx.ack("Игра началась")
    await _send_number_round(ctx, game)


@router.callback_query(F.data.startswith("game:num:no:"))
async def cb_number_decline(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    try:
        game_id = int((event.data or "").rsplit(":", 1)[1])
    except (TypeError, ValueError):
        await ctx.ack("Игра не найдена", alert=True)
        return
    row = await _require_current_number(ctx, db, game_id)
    if row is None:
        return
    declined = await db.decline_number(game_id, ctx.user_id)
    if declined is None:
        await ctx.ack("Предложение уже закрыто", alert=True)
        return
    live_chat.game_status(
        set(_players(declined)), "numbers", game_id, "declined", "Предложение отклонено"
    )
    await ctx.ack("Не сейчас")
    await send_to(
        ctx.bot,
        int(declined["inviter_id"]),
        "Собеседник пока не хочет играть в Числа.",
        K.chat_keyboard(),
        ctx.pack,
    )


@router.callback_query(F.data == "game:num:noop")
async def cb_number_noop(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack()


@router.callback_query(F.data.startswith("game:num:set:"))
async def cb_number_set(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    try:
        _, _, _, raw_game, raw_round, raw_value = (event.data or "").split(":")
        game_id, round_index = int(raw_game), int(raw_round)
    except (TypeError, ValueError):
        await ctx.ack("Не получилось выбрать число", alert=True)
        return

    row = await _require_current_number(ctx, db, game_id)
    if row is None:
        return
    if str(row["status"]) != "active" or int(row["question_index"]) != round_index:
        await ctx.ack("Этот раунд уже закрыт", alert=True)
        return
    if _number_answered(row, ctx.user_id):
        await ctx.ack("Ты уже выбрал число", alert=True)
        return

    current = "" if raw_value == "x" else raw_value
    if current:
        if not current.isdigit():
            await ctx.ack("Неверное число", alert=True)
            return
        value = int(current)
        range_max = int(row["range_max"])
        if value < 1:
            await ctx.ack(f"Выбери число от 1 до {range_max}", alert=True)
            return
        if value > range_max:
            await ctx.ack(f"Максимум {range_max}", alert=True)
            return

    await ctx.ack()
    if event.message is not None:
        try:
            await event.message.edit_reply_markup(
                reply_markup=K.number_input_keyboard(game_id, round_index, current)
            )
        except TelegramAPIError:
            pass


@router.callback_query(F.data.startswith("game:num:submit:"))
async def cb_number_submit(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    try:
        _, _, _, raw_game, raw_round, raw_value = (event.data or "").split(":")
        game_id, round_index = int(raw_game), int(raw_round)
        value = 0 if raw_value == "x" else int(raw_value)
    except (TypeError, ValueError):
        await ctx.ack("Не получилось выбрать число", alert=True)
        return

    row = await _require_current_number(ctx, db, game_id)
    if row is None:
        return
    range_max = int(row["range_max"])
    if not 1 <= value <= range_max:
        await ctx.ack(f"Выбери число от 1 до {range_max}", alert=True)
        return

    result, game, reward_a, reward_b = await db.answer_number(
        game_id, ctx.user_id, round_index, value
    )
    if result == "waiting":
        await ctx.ack("Число принято")
        await ctx.reply("🔢 Число принято. Ждём выбор собеседника…")
        return
    if result == "resolved" and game is not None:
        await ctx.ack("Число принято")
        await _send_number_result(ctx, game, reward_a, reward_b)
        if str(game["status"]) == "finished":
            user_a, user_b = _players(game)
            exact = int(game["matches"] or 0)
            total = int(game["total_questions"] or NUMBER_ROUNDS)
            range_max = int(game["range_max"] or 0)
            ctx.mm.record_game(user_a, "numbers", exact, total)
            for uid in (user_a, user_b):
                await db.record_game_engagement(
                    uid, "numbers", matches=exact, total=total,
                    number_exact=exact, range_max=range_max,
                )
                await _notify_progress(ctx, uid)
        return
    if result == "already":
        await ctx.ack("Ты уже выбрал число", alert=True)
        return
    if result == "invalid":
        await ctx.ack(f"Число должно быть от 1 до {range_max}", alert=True)
        return
    await ctx.ack("Этот раунд уже закрыт", alert=True)


@router.callback_query(F.data.startswith("game:num:next:"))
async def cb_number_next(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    try:
        _, _, _, raw_game, raw_round = (event.data or "").split(":")
        game_id, round_index = int(raw_game), int(raw_round)
    except (TypeError, ValueError):
        await ctx.ack("Раунд уже закрыт", alert=True)
        return

    row = await _require_current_number(ctx, db, game_id)
    if row is None:
        return
    game = await db.advance_number(game_id, ctx.user_id, round_index)
    if game is None:
        await ctx.ack("Собеседник уже перешёл дальше", alert=True)
        return
    await ctx.ack()
    await _send_number_round(ctx, game)


@router.callback_query(F.data == K.CB_GEO)
async def cb_geo(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    partner = ctx.mm.partner(ctx.user_id)
    if partner is None:
        await ctx.ack("Сначала найди собеседника", alert=True)
        return
    if WG.active_for_pair(ctx.user_id, partner):
        await ctx.ack("Сначала заверши игру «Объясни слово»", alert=True)
        return

    existing = await db.game_for_pair(ctx.user_id, partner)
    if existing is not None:
        if _game_type(existing) != "geo":
            await ctx.ack("Сначала заверши текущую игру", alert=True)
            return
        status = str(existing["status"])
        game_id = int(existing["id"])
        if status == "invited":
            if int(existing["inviter_id"]) == ctx.user_id:
                await ctx.ack("Предложение уже отправлено", alert=True)
            else:
                await ctx.reply(
                    "🗺 <b>Собеседник предлагает сыграть в GeoGuessr📍</b>\n\n"
                    f"🎮 Раундов: <b>{int(existing['total_questions'])}</b> · "
                    "⏱ по <b>2 минуты</b> на место.",
                    K.geo_invite_keyboard(game_id),
                )
            return
        if status == "active":
            await ctx.ack("Игра уже идёт")
            if _geo_answered(existing, ctx.user_id):
                await ctx.reply(
                    "✅ <b>Метка принята</b>\n\nЖдём ответ собеседника…"
                )
            else:
                await _send_geo_round(ctx, existing)
            return
        await ctx.ack()
        await ctx.reply(
            "✅ <b>Раунд завершён</b>\n\nМожно открыть следующее место.",
            K.geo_next_keyboard(game_id, int(existing["question_index"])),
        )
        return

    await ctx.ack()
    await ctx.reply(
        "🗺 <b>GeoGuessr📍 · МАГНИТОГОРСК</b>\n\n"
        "📸 Бот показывает фотографию места, а вы с собеседником угадываете, "
        "где оно находится.\n\n"
        "⭐ <b>Чем ближе метка — тем больше звёзд.</b>\n"
        "⏱ На каждый раунд — <b>2 минуты</b>.\n\n"
        "📍 Ответ отправляется через Telegram:\n"
        "<b>📎 Скрепка → Геопозиция → выбрать любую точку на карте → отправить.</b>\n\n"
        "🌍 Можно поставить метку где угодно — расстояние посчитается автоматически.\n\n"
        "🎮 <b>Сколько раундов сыграть?</b>",
        K.geo_rounds_keyboard(),
    )


@router.callback_query(F.data.startswith("game:geo:rounds:"))
async def cb_geo_rounds(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    try:
        total = int((event.data or "").rsplit(":", 1)[1])
    except (TypeError, ValueError):
        await ctx.ack("Неверное количество раундов", alert=True)
        return
    if total not in GQ.GEO_ROUND_OPTIONS:
        await ctx.ack("Можно выбрать 3, 5 или 10 раундов", alert=True)
        return
    partner = ctx.mm.partner(ctx.user_id)
    if partner is None:
        await ctx.ack("Диалог уже завершён", alert=True)
        return
    if WG.active_for_pair(ctx.user_id, partner):
        await ctx.ack("Сначала заверши игру «Объясни слово»", alert=True)
        return
    if await db.game_for_pair(ctx.user_id, partner) is not None:
        await ctx.ack("У вас уже есть активная игра", alert=True)
        return

    try:
        excluded = await db.recent_geo_place_ids((ctx.user_id, partner))
        place_ids = GQ.select_place_ids(total, excluded=excluded)
    except RuntimeError:
        await ctx.ack("Для такого количества раундов пока не хватает мест", alert=True)
        return
    game, created = await db.create_geo_invite(ctx.user_id, partner, place_ids)
    if not created:
        await ctx.ack("У вас уже есть активная игра", alert=True)
        return

    reward_available = await db.geo_pair_reward_available(ctx.user_id, partner)
    reward_text = (
        "⭐ Чем точнее метка, тем больше награда — <b>до 10 ⭐ за раунд</b>."
        if reward_available
        else "⭐ Сегодня с этой парой награда уже использована — игра будет без начисления ⭐."
    )
    result = await send_to(
        ctx.bot,
        partner,
        "🗺 <b>ТЕБЯ ЗОВУТ В GeoGuessr📍</b>\n\n"
        f"🎮 Раундов: <b>{total}</b>\n"
        "⏱ На каждый раунд: <b>2 минуты</b>\n"
        f"{reward_text}\n\n"
        "📍 Чтобы ответить: <b>📎 Скрепка → Геопозиция → выбери любую точку "
        "на карте → отправь.</b>\n"
        "🌍 Подойдёт любая корректная точка на карте.",
        K.geo_invite_keyboard(int(game["id"])),
        ctx.pack,
    )
    if result is DeliveryResult.UNAVAILABLE:
        await db.cancel_battle(int(game["id"]))
        await ctx.reply("Не получилось отправить предложение.")
        return

    live_chat.game_invite(
        ctx.user_id,
        partner,
        "geo",
        int(game["id"]),
        "GeoGuessr📍",
        f"{total} раундов · 2 минуты на раунд",
    )
    event_id = await db.add_miniapp_event(
        partner,
        "games",
        "Приглашение в «GeoGuessr📍»",
        f"{total} раундов · по 2 минуты",
        icon="geo",
        action="chat",
    )
    live_chat.signal({partner}, "events_changed", event_id=event_id)
    await ctx.ack("Предложение отправлено")
    await ctx.reply(
        "✅ <b>Предложение отправлено</b>\n"
        f"GeoGuessr📍 · {total} раундов · по 2 минуты."
    )


@router.callback_query(F.data.startswith("game:geo:yes:"))
async def cb_geo_accept(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    try:
        game_id = int((event.data or "").rsplit(":", 1)[1])
    except (TypeError, ValueError):
        await ctx.ack("Игра не найдена", alert=True)
        return
    row = await _require_current_geo(ctx, db, game_id)
    if row is None:
        return
    game = await db.accept_geo(game_id, ctx.user_id)
    if game is None:
        await ctx.ack("На это предложение уже ответили", alert=True)
        return
    live_chat.game_status(
        set(_players(game)), "geo", game_id, "accepted", "GeoGuessr📍 начался"
    )
    await ctx.ack("Игра началась")
    await _send_geo_round(ctx, game)


@router.callback_query(F.data.startswith("game:geo:no:"))
async def cb_geo_decline(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    try:
        game_id = int((event.data or "").rsplit(":", 1)[1])
    except (TypeError, ValueError):
        await ctx.ack("Игра не найдена", alert=True)
        return
    row = await _require_current_geo(ctx, db, game_id)
    if row is None:
        return
    declined = await db.decline_geo(game_id, ctx.user_id)
    if declined is None:
        await ctx.ack("Предложение уже закрыто", alert=True)
        return
    live_chat.game_status(
        set(_players(declined)), "geo", game_id, "declined", "Предложение отклонено"
    )
    await ctx.ack("Не сейчас")
    await send_to(
        ctx.bot,
        int(declined["inviter_id"]),
        "🗺 Собеседник пока не хочет играть в GeoGuessr📍.",
        K.chat_keyboard(),
        ctx.pack,
    )


@router.callback_query(F.data.startswith("game:geo:next:"))
async def cb_geo_next(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    try:
        _, _, _, raw_game, raw_round = (event.data or "").split(":")
        game_id, round_index = int(raw_game), int(raw_round)
    except (TypeError, ValueError):
        await ctx.ack("Раунд уже закрыт", alert=True)
        return
    row = await _require_current_geo(ctx, db, game_id)
    if row is None:
        return
    game = await db.advance_geo(game_id, ctx.user_id, round_index)
    if game is None:
        await ctx.ack("Собеседник уже перешёл дальше", alert=True)
        return
    await ctx.ack()
    await _send_geo_round(ctx, game)


@router.message(F.location | F.venue)
async def geo_location(message: Message, ctx: Ctx, db: Database) -> None:
    partner = ctx.mm.partner(ctx.user_id)
    if partner is None:
        raise SkipHandler
    geo_game = await db.geo_for_pair(ctx.user_id, partner)
    if geo_game is None or str(geo_game["status"]) != "active":
        # Вне GeoGuessr точная геолокация по-прежнему блокируется обычным релеем.
        raise SkipHandler
    if not _current_pair(ctx.mm, geo_game):
        await db.cancel_battle(int(geo_game["id"]))
        await ctx.reply("Диалог уже завершён.", K.menu_keyboard())
        return

    place = _geo_place(geo_game)
    point = message.location
    if point is None and message.venue is not None:
        point = message.venue.location
    if place is None or point is None:
        await db.cancel_battle(int(geo_game["id"]))
        await ctx.reply("Место недоступно. Игра остановлена.", K.chat_keyboard())
        return

    game_id = int(geo_game["id"])
    round_index = int(geo_game["question_index"])
    result, game, reward_a, reward_b = await db.answer_geo(
        game_id,
        ctx.user_id,
        round_index,
        point.latitude,
        point.longitude,
        place.latitude,
        place.longitude,
    )

    if result == "waiting":
        await ctx.reply(
            "✅ <b>Метка принята!</b>\n\n"
            "📍 Ответ сохранён. Теперь ждём собеседника…"
        )
        return
    if result == "resolved" and game is not None:
        GR.cancel_timeout(game_id, round_index)
        await _send_geo_result(ctx, game, reward_a, reward_b)
        return
    if result == "expired":
        state, expired_game, reward_a, reward_b = await db.expire_geo_round(
            game_id, round_index
        )
        if state == "resolved" and expired_game is not None:
            GR.cancel_timeout(game_id, round_index)
            await _send_geo_result(ctx, expired_game, reward_a, reward_b)
        else:
            await ctx.reply("⏰ Время этого раунда уже вышло.")
        return
    if result == "already":
        await ctx.reply(
            "✅ Ты уже отправил метку. Ждём собеседника…"
        )
        return
    if result == "invalid":
        await ctx.reply(
            "Не получилось прочитать координаты. Выбери точку на карте ещё раз."
        )
        return
    await ctx.reply("Этот раунд уже закрыт.")


@router.callback_query(F.data == K.CB_BATTLE)
async def cb_battle(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    partner = ctx.mm.partner(ctx.user_id)
    if partner is None:
        await ctx.ack("Сначала найди собеседника", alert=True)
        return
    if WG.active_for_pair(ctx.user_id, partner):
        await ctx.ack("Сначала заверши игру «Объясни слово»", alert=True)
        return
    existing = await db.game_for_pair(ctx.user_id, partner)
    if existing is not None:
        if _game_type(existing) != "battle":
            await ctx.ack("Сначала заверши текущую игру", alert=True)
            return
        status = str(existing["status"])
        if status == "invited":
            if int(existing["inviter_id"]) == ctx.user_id:
                await ctx.ack("Предложение уже отправлено", alert=True)
            else:
                await ctx.reply(
                    "⚔️ Собеседник предлагает сыграть в Битву мнений.",
                    K.battle_invite_keyboard(int(existing["id"])),
                )
            return
        if status == "active":
            await ctx.ack("Игра уже идёт")
            question = _question(existing)
            await ctx.reply(
                f"⚔️ <b>{int(existing['question_index']) + 1}/{_total(existing)}</b>\n\n{texts.esc(question.text)}",
                K.battle_answer_keyboard(
                    int(existing["id"]), int(existing["question_index"]),
                    question.first, question.second,
                ),
            )
            return
        await ctx.reply(
            "⚔️ Раунд завершён. Можно перейти к следующему вопросу.",
            K.battle_next_keyboard(int(existing["id"]), int(existing["question_index"])),
        )
        return
    await ctx.ack()
    await ctx.reply("⚔️ <b>Сколько вопросов сыграть?</b>", K.battle_length_keyboard())


@router.callback_query(F.data.startswith("game:battle:"))
async def cb_battle_length(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    try:
        total = int((event.data or "").rsplit(":", 1)[1])
    except (TypeError, ValueError):
        await ctx.ack("Неверное количество вопросов", alert=True)
        return
    if total not in {5, 10}:
        await ctx.ack("Можно выбрать только 5 или 10 вопросов", alert=True)
        return
    partner = ctx.mm.partner(ctx.user_id)
    if partner is None:
        await ctx.ack("Сначала найди собеседника", alert=True)
        return
    if WG.active_for_pair(ctx.user_id, partner):
        await ctx.ack("Сначала заверши игру «Объясни слово»", alert=True)
        return
    game, created = await db.create_battle_invite(ctx.user_id, partner, total)
    if not created:
        await ctx.ack("У вас уже есть активная игра", alert=True)
        return
    result = await send_to(
        ctx.bot,
        partner,
        f"⚔️ <b>Собеседник предлагает сыграть в Битву мнений</b>\nВопросов: <b>{total}</b>",
        K.battle_invite_keyboard(int(game["id"])),
        ctx.pack,
    )
    if result is DeliveryResult.UNAVAILABLE:
        await db.cancel_battle(int(game["id"]))
        await ctx.reply("Не получилось отправить предложение.")
        return
    live_chat.game_invite(
        ctx.user_id,
        partner,
        "battle",
        int(game["id"]),
        "⚔️ Битва мнений",
        f"{total} вопросов",
    )
    event_id = await db.add_miniapp_event(
        partner, "games", "Приглашение в «Битву мнений»",
        f"{total} вопросов",
        icon="gamepad-2", action="chat",
    )
    live_chat.signal({partner}, "events_changed", event_id=event_id)
    await ctx.reply("⚔️ Предложение отправлено.")


@router.callback_query(F.data.startswith("game:yes:"))
async def cb_accept(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    game_id = int((event.data or "").rsplit(":", 1)[1])
    row = await _require_current_game(ctx, db, game_id)
    if row is None:
        return
    selected = random.sample(list(questions()), _total(row))
    game = await db.accept_battle(game_id, ctx.user_id, selected)
    if game is None:
        await ctx.ack("На это предложение уже ответили", alert=True)
        return
    live_chat.game_status(
        set(_players(game)), "battle", game_id, "accepted", "Игра началась"
    )
    await ctx.ack("Игра началась")
    await _send_question(ctx, game)


@router.callback_query(F.data.startswith("game:no:"))
async def cb_decline(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    game_id = int((event.data or "").rsplit(":", 1)[1])
    row = await _require_current_game(ctx, db, game_id)
    if row is None:
        return
    declined = await db.decline_battle(game_id, ctx.user_id)
    if declined is None:
        await ctx.ack("Предложение уже закрыто", alert=True)
        return
    live_chat.game_status(
        set(_players(declined)), "battle", game_id, "declined", "Предложение отклонено"
    )
    await ctx.ack("Не сейчас")
    await send_to(ctx.bot, int(declined["inviter_id"]), "Собеседник пока не хочет играть.", K.chat_keyboard(), ctx.pack)


@router.callback_query(F.data.startswith("game:answer:"))
async def cb_answer(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    try:
        _, _, raw_game, raw_index, raw_choice = (event.data or "").split(":")
        game_id, index, choice = int(raw_game), int(raw_index), int(raw_choice)
    except (TypeError, ValueError):
        await ctx.ack("Неверный ответ", alert=True)
        return
    row = await _require_current_game(ctx, db, game_id)
    if row is None:
        return
    result, game = await db.answer_battle(game_id, ctx.user_id, index, choice)
    if result == "waiting":
        await ctx.ack("Ответ принят")
        await ctx.reply("Ответ принят. Ждём собеседника…")
        return
    if result == "resolved" and game is not None:
        await ctx.ack("Ответ принят")
        await _send_round_result(ctx, game)
        if str(game["status"]) == "finished":
            user_a, user_b = _players(game)
            matches = int(game["matches"] or 0)
            total = int(game["total_questions"] or 0)
            ctx.mm.record_game(user_a, "battle", matches, total)
            for uid in (user_a, user_b):
                await db.record_game_engagement(
                    uid, "battle", matches=matches, total=total
                )
                await _notify_progress(ctx, uid)
        return
    await ctx.ack("Ответ уже принят или вопрос закрыт", alert=True)


@router.callback_query(F.data.startswith("game:next:"))
async def cb_next_question(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    try:
        _, _, raw_game, raw_index = (event.data or "").split(":")
        game_id, index = int(raw_game), int(raw_index)
    except (TypeError, ValueError):
        await ctx.ack("Вопрос уже закрыт", alert=True)
        return
    row = await _require_current_game(ctx, db, game_id)
    if row is None:
        return
    game = await db.advance_battle(game_id, ctx.user_id, index)
    if game is None:
        await ctx.ack("Собеседник уже перешёл дальше", alert=True)
        return
    await ctx.ack()
    await _send_question(ctx, game)


@router.callback_query(F.data == "game:again")
async def cb_again(event: CallbackQuery, ctx: Ctx) -> None:
    if ctx.mm.partner(ctx.user_id) is None:
        await ctx.ack("Диалог уже завершён", alert=True)
        return
    await ctx.ack()
    await ctx.reply("⚔️ <b>Сколько вопросов сыграть?</b>", K.battle_length_keyboard())



@router.callback_query(F.data == K.CB_WORDS)
async def cb_words(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    partner = ctx.mm.partner(ctx.user_id)
    if partner is None:
        await ctx.ack("Сначала найди собеседника", alert=True)
        return

    if await db.game_for_pair(ctx.user_id, partner) is not None:
        await ctx.ack("Сначала заверши текущую игру", alert=True)
        return

    game = WG.get_for_pair(ctx.user_id, partner)
    if game is not None:
        if game.status == "invited":
            if game.inviter_id == ctx.user_id:
                await ctx.ack("Предложение уже отправлено", alert=True)
            else:
                await ctx.ack()
                await ctx.reply(
                    "🗣 Собеседник предлагает сыграть в «Объясни слово».",
                    K.word_invite_keyboard(game.id),
                )
            return
        if game.status == "active":
            await ctx.ack("Игра уже идёт")
            await ctx.reply(WG.role_text(game, ctx.user_id), K.chat_keyboard())
            return
        if game.status == "round_done":
            await ctx.ack()
            await ctx.reply(
                WG.role_text(game, ctx.user_id),
                K.word_next_keyboard(game.id, game.round_index),
            )
            return
        WG.remove(game.id)

    game, created = WG.create_invite(ctx.user_id, partner)
    if not created:
        await ctx.ack("У вас уже есть активная игра", alert=True)
        return

    result = await send_to(
        ctx.bot,
        partner,
        "🗣 <b>Собеседник предлагает сыграть в «Объясни слово»</b>\n\n"
        f"Раундов: <b>{WG.WORD_ROUNDS}</b>. Один объясняет слово, второй угадывает. "
        f"За правильное угадывание — до <b>{WG.WORD_REWARD} ⭐</b>.",
        K.word_invite_keyboard(game.id),
        ctx.pack,
    )
    if result is DeliveryResult.UNAVAILABLE:
        WG.remove(game.id)
        await ctx.reply("Не получилось отправить предложение.")
        return
    live_chat.game_invite(
        ctx.user_id,
        partner,
        "words",
        int(game.id),
        "🗣 Объясни слово",
        f"{WG.WORD_ROUNDS} слов · до {WG.WORD_REWARD} ⭐ за угадывание",
    )
    event_id = await ctx.db.add_miniapp_event(
        partner, "games", "Приглашение в «Объясни слово»",
        f"{WG.WORD_ROUNDS} слов · до {WG.WORD_REWARD} ⭐",
        icon="gamepad-2", action="chat",
    )
    live_chat.signal({partner}, "events_changed", event_id=event_id)
    await ctx.ack()
    await ctx.reply("🗣 Предложение отправлено.")


@router.callback_query(F.data.startswith("game:word:yes:"))
async def cb_word_accept(event: CallbackQuery, ctx: Ctx) -> None:
    try:
        game_id = int((event.data or "").rsplit(":", 1)[1])
    except (TypeError, ValueError):
        await ctx.ack("Игра не найдена", alert=True)
        return
    game = WG.get_by_id(game_id)
    partner = ctx.mm.partner(ctx.user_id)
    if game is None or partner is None or partner not in {game.user_a, game.user_b}:
        await ctx.ack("Диалог уже завершён", alert=True)
        return
    game = WG.accept(game_id, ctx.user_id)
    if game is None:
        await ctx.ack("На это предложение уже ответили", alert=True)
        return
    live_chat.game_status(
        {game.user_a, game.user_b}, "words", game_id, "accepted", "Игра началась"
    )
    await ctx.ack("Игра началась")
    await _send_word_round(ctx, game)


@router.callback_query(F.data.startswith("game:word:no:"))
async def cb_word_decline(event: CallbackQuery, ctx: Ctx) -> None:
    try:
        game_id = int((event.data or "").rsplit(":", 1)[1])
    except (TypeError, ValueError):
        await ctx.ack("Игра не найдена", alert=True)
        return
    game = WG.decline(game_id, ctx.user_id)
    if game is None:
        await ctx.ack("Предложение уже закрыто", alert=True)
        return
    live_chat.game_status(
        {game.user_a, game.user_b}, "words", game_id, "declined", "Предложение отклонено"
    )
    await ctx.ack("Не сейчас")
    await send_to(
        ctx.bot,
        game.inviter_id,
        "Собеседник пока не хочет играть в «Объясни слово».",
        K.chat_keyboard(),
        ctx.pack,
    )


@router.callback_query(F.data.startswith("game:word:next:"))
async def cb_word_next(event: CallbackQuery, ctx: Ctx) -> None:
    try:
        _, _, _, raw_game, raw_round = (event.data or "").split(":")
        game_id, round_index = int(raw_game), int(raw_round)
    except (TypeError, ValueError):
        await ctx.ack("Раунд уже закрыт", alert=True)
        return
    current = WG.get_by_id(game_id)
    partner = ctx.mm.partner(ctx.user_id)
    if current is None or partner is None or partner not in {current.user_a, current.user_b}:
        await ctx.ack("Диалог уже завершён", alert=True)
        return
    game = WG.advance(game_id, ctx.user_id, round_index)
    if game is None:
        await ctx.ack("Собеседник уже перешёл дальше", alert=True)
        return
    await ctx.ack()
    await _send_word_round(ctx, game)
