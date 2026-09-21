"""Игры внутри активного анонимного диалога."""

from __future__ import annotations

import json
import random
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .. import keyboards as K
from .. import texts
from ..actions import Ctx, DeliveryResult, send_to
from ..battle_questions import BattleQuestion, get_question, questions
from ..db import Database
from ..matching import Matchmaker
from ..number_game import NUMBER_REWARDS, NUMBER_ROUNDS, number_reward

router = Router(name="games")


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


def _number_prompt(row: Any) -> str:
    round_index = int(row["question_index"])
    range_max = int(row["range_max"])
    return (
        f"🔢 <b>Числа · раунд {round_index + 1}/{NUMBER_ROUNDS}</b>\n\n"
        f"Выбери число от <b>1</b> до <b>{range_max}</b>.\n"
        "Собеседник увидит его только после своего выбора."
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


async def _send_number_result(ctx: Ctx, row: Any) -> None:
    user_a, user_b = _players(row)
    answer_a = int(row["answer_a"])
    answer_b = int(row["answer_b"])
    diff = abs(answer_a - answer_b)
    reward = number_reward(int(row["range_max"]), answer_a, answer_b)

    if diff == 0:
        body_a = body_b = (
            f"🎯 <b>Точное совпадение!</b>\n"
            f"Вы оба выбрали <b>{answer_a}</b>.\n"
            f"+<b>{reward} ⭐</b> каждому."
        )
    elif diff == 1:
        body_a = (
            f"🔥 <b>Почти совпало!</b>\n"
            f"Ты: <b>{answer_a}</b> · собеседник: <b>{answer_b}</b>\n"
            f"Разница всего <b>1</b> · +<b>{reward} ⭐</b> каждому."
        )
        body_b = (
            f"🔥 <b>Почти совпало!</b>\n"
            f"Ты: <b>{answer_b}</b> · собеседник: <b>{answer_a}</b>\n"
            f"Разница всего <b>1</b> · +<b>{reward} ⭐</b> каждому."
        )
    else:
        body_a = (
            f"🔢 <b>Не совпало</b>\n"
            f"Ты: <b>{answer_a}</b> · собеседник: <b>{answer_b}</b>\n"
            "В этом раунде без награды."
        )
        body_b = (
            f"🔢 <b>Не совпало</b>\n"
            f"Ты: <b>{answer_b}</b> · собеседник: <b>{answer_a}</b>\n"
            "В этом раунде без награды."
        )

    if str(row["status"]) == "finished":
        total_reward = int(row["reward_total"])
        exact = int(row["matches"])
        final = (
            f"🔢 <b>Игра окончена</b>\n"
            f"Сыграно раундов: <b>{NUMBER_ROUNDS}</b>\n"
            f"Точных совпадений: <b>{exact}/{NUMBER_ROUNDS}</b>\n"
            f"Получено за игру: <b>{total_reward} ⭐</b> каждому."
        )
        markup = K.number_end_keyboard()
        body_a = f"{body_a}\n\n{final}"
        body_b = f"{body_b}\n\n{final}"
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
    percent = matches * 100 // total
    if percent == 100:
        verdict = "вы будто читаете мысли 🧠"
    elif percent >= 80:
        verdict = "вы подозрительно похожи 👀"
    elif percent >= 60:
        verdict = "у вас много общего"
    elif percent >= 40:
        verdict = "спорить вам будет интересно"
    else:
        verdict = "противоположности притягиваются"
    reward = "\n🎁 Каждому начислено <b>25 ⭐</b>!" if matches == total else ""
    return (
        f"⚔️ <b>Битва окончена</b>\nСовпадений: <b>{matches}/{total}</b>\n"
        f"<b>{percent}%</b> — {verdict}.{reward}"
    )


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


async def _open_games(ctx: Ctx) -> None:
    if ctx.mm.partner(ctx.user_id) is None:
        await ctx.reply("🎮 Игры доступны только в активном диалоге.", K.menu_keyboard())
        return
    await ctx.reply("🎮 <b>Игры с собеседником</b>\n\nВыбери игру.", K.games_keyboard())


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


@router.callback_query(F.data == K.CB_BATTLE)
async def cb_battle(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    partner = ctx.mm.partner(ctx.user_id)
    if partner is None:
        await ctx.ack("Сначала найди собеседника", alert=True)
        return
    existing = await db.battle_for_pair(ctx.user_id, partner)
    if existing is not None:
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
            "⚔️ Раун завершён. Можно перейти к следующему вопросу.",
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
    game, created = await db.create_battle_invite(ctx.user_id, partner, total)
    if not created:
        await ctx.ack("Игра для этой пары уже создана", alert=True)
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
    await ctx.reply("⚔️ Предложение отправлено. Ждём ответа собеседника…")


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
