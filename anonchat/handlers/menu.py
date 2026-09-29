"""Меню, команды-дубликаты кнопок и оценка диалога."""

from __future__ import annotations

import time

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import keyboards as K
from .. import texts
from ..actions import (
    Ctx,
    act_connect,
    act_next,
    act_stop,
    apply_rating,
    send_to,
    show_help,
    show_menu,
    show_rules,
    show_top,
    show_welcome,
    show_referral,
    show_activity,
    show_streak,
    show_quests,
)
from ..commands import ensure_for_admin
from ..config import Config, decode_anon_question_token
from ..db import Database, REFERRAL_DAILY_LIMIT
from ..monitoring import enqueue_anonymous_monitor

router = Router(name="menu")
REFERRAL_XP = 50


class AnonymousQuestionStates(StatesGroup):
    question = State()
    answer = State()


def _anonymous_body(title: str, body: str = "", *, media: bool = False) -> str:
    """Заголовок + содержимое с корректным лимитом Telegram."""
    clean = texts.esc((body or "").strip())
    if not clean:
        return title
    # Caption ограничен сильнее обычного текста. Оставляем запас под заголовок.
    limit = 900 if media else 3900
    return f"{title}\n\n{clean[:limit]}"


async def _deliver_anonymous_copy(
    message: Message,
    ctx: Ctx,
    target_id: int,
    title: str,
    reply_markup=None,
) -> bool:
    """Доставляет вопрос/ответ одним сообщением без раскрытия отправителя."""
    try:
        if message.text is not None:
            await ctx.bot.send_message(
                target_id,
                _anonymous_body(title, message.text),
                reply_markup=reply_markup,
            )
            return True

        caption = _anonymous_body(title, message.caption or "", media=True)

        if message.photo:
            await ctx.bot.send_photo(
                target_id,
                message.photo[-1].file_id,
                caption=caption,
                reply_markup=reply_markup,
                has_spoiler=bool(getattr(message, "has_media_spoiler", False)),
            )
            return True

        if message.animation:
            await ctx.bot.send_animation(
                target_id,
                message.animation.file_id,
                caption=caption,
                reply_markup=reply_markup,
                has_spoiler=bool(getattr(message, "has_media_spoiler", False)),
            )
            return True

        if message.video:
            await ctx.bot.send_video(
                target_id,
                message.video.file_id,
                caption=caption,
                reply_markup=reply_markup,
                has_spoiler=bool(getattr(message, "has_media_spoiler", False)),
            )
            return True

        if message.audio:
            await ctx.bot.send_audio(
                target_id,
                message.audio.file_id,
                caption=caption,
                reply_markup=reply_markup,
            )
            return True

        if message.voice:
            await ctx.bot.send_voice(
                target_id,
                message.voice.file_id,
                caption=caption,
                reply_markup=reply_markup,
            )
            return True

        if message.document:
            await ctx.bot.send_document(
                target_id,
                message.document.file_id,
                caption=caption,
                reply_markup=reply_markup,
            )
            return True

        # У стикеров и кружков Bot API не поддерживает caption.
        # Всё равно доставляем их одним сообщением с кнопкой ответа.
        if message.sticker:
            await ctx.bot.send_sticker(
                target_id,
                message.sticker.file_id,
                reply_markup=reply_markup,
            )
            return True

        if message.video_note:
            await ctx.bot.send_video_note(
                target_id,
                message.video_note.file_id,
                reply_markup=reply_markup,
            )
            return True

        # Прочие поддерживаемые Telegram-типы (контакт, гео и т.п.)
        # копируем как одно сообщение. Заголовок к ним API тоже не прикрепляет.
        await message.send_copy(chat_id=target_id, reply_markup=reply_markup)
        return True
    except TelegramAPIError:
        return False


# ---------------------------------------------------------------------------------- анонимные вопросы
@router.message(CommandStart(), F.text.startswith("/start ask_") | F.text.startswith("/start q_"))
async def cmd_anonymous_question(
    message: Message, ctx: Ctx, cfg: Config, state: FSMContext
) -> None:
    await state.clear()
    if await ctx.restricted():
        return

    parts = (message.text or "").split(maxsplit=1)
    payload = parts[1].strip() if len(parts) == 2 else ""
    if payload.startswith("q_"):
        target_id = await ctx.db.anonymous_question_user(payload.removeprefix("q_"))
    else:
        target_id = decode_anon_question_token(
            payload.removeprefix("ask_"), cfg.bot_token
        )
    if not target_id:
        await ctx.reply(
            "Эта ссылка на анонимные вопросы не работает.",
            K.back_menu_keyboard(),
        )
        return
    if ctx.mm.status(ctx.user_id) in {"paired", "queued"}:
        await ctx.reply(
            "Сначала заверши текущий диалог или останови поиск, затем открой ссылку ещё раз.",
            K.back_menu_keyboard(),
        )
        return

    await state.set_state(AnonymousQuestionStates.question)
    await state.update_data(anonymous_question_target=int(target_id))
    await ctx.reply(
        "💌 <b>Анонимный вопрос</b>\n\n"
        "Отправь сообщение. Можно текст, фото, GIF, стикер, "
        "голосовое или другое медиа."
    )


@router.message(AnonymousQuestionStates.question)
async def send_anonymous_question(
    message: Message, ctx: Ctx, cfg: Config, state: FSMContext
) -> None:
    if message.text and message.text.startswith("/"):
        await state.clear()
        await show_menu(ctx)
        return
    if await ctx.restricted():
        await state.clear()
        return

    data = await state.get_data()
    target_id = int(data.get("anonymous_question_target") or 0)
    if not target_id:
        await state.clear()
        await show_menu(ctx)
        return

    sender_token = await ctx.db.anonymous_question_token(ctx.user_id)
    delivered = await _deliver_anonymous_copy(
        message,
        ctx,
        target_id,
        "💌 <b>Новый анонимный вопрос</b>",
        K.anonymous_reply_keyboard(sender_token),
    )
    if delivered:
        await enqueue_anonymous_monitor(
            message, ctx, target_id, kind="question"
        )
    await state.clear()

    if delivered:
        await ctx.reply(
            "✅ Анонимный вопрос отправлен.",
            K.back_menu_keyboard(),
        )
    else:
        await ctx.reply(
            "Не получилось доставить анонимный вопрос.",
            K.back_menu_keyboard(),
        )


@router.callback_query(F.data.startswith("anonq:reply:"))
async def cb_anonymous_reply(
    event: CallbackQuery, ctx: Ctx, cfg: Config, state: FSMContext
) -> None:
    token = (event.data or "").removeprefix("anonq:reply:")
    target_id = await ctx.db.anonymous_question_user(token)
    if not target_id:
        # Старые длинные кнопки продолжают работать после перехода на короткие ссылки.
        target_id = decode_anon_question_token(token, cfg.bot_token)
    if not target_id:
        await ctx.ack("Этот вопрос уже недоступен", alert=True)
        return
    if ctx.mm.status(ctx.user_id) in {"paired", "queued"}:
        await ctx.ack("Сначала заверши текущий диалог или останови поиск", alert=True)
        return
    if await ctx.restricted():
        await state.clear()
        return

    await state.clear()
    await state.set_state(AnonymousQuestionStates.answer)
    await state.update_data(anonymous_answer_target=int(target_id))
    await ctx.ack()
    await ctx.reply(
        "💌 <b>Ответ на анонимный вопрос</b>\n\n"
        "Отправь сообщение. Можно текст, фото, GIF, стикер, "
        "голосовое или другое медиа."
    )


@router.message(AnonymousQuestionStates.answer)
async def send_anonymous_answer(
    message: Message, ctx: Ctx, state: FSMContext
) -> None:
    if message.text and message.text.startswith("/"):
        await state.clear()
        await show_menu(ctx)
        return
    if await ctx.restricted():
        await state.clear()
        return

    data = await state.get_data()
    target_id = int(data.get("anonymous_answer_target") or 0)
    if not target_id:
        await state.clear()
        await show_menu(ctx)
        return

    sender_token = await ctx.db.anonymous_question_token(ctx.user_id)
    delivered = await _deliver_anonymous_copy(
        message,
        ctx,
        target_id,
        "💌 <b>Ответ на анонимный вопрос</b>",
        K.anonymous_reply_keyboard(sender_token),
    )
    if delivered:
        await enqueue_anonymous_monitor(
            message, ctx, target_id, kind="answer"
        )
    await state.clear()

    if delivered:
        await ctx.reply("✅ Ответ отправлен.", K.back_menu_keyboard())
    else:
        await ctx.reply(
            "Не получилось доставить ответ.",
            K.back_menu_keyboard(),
        )


# ---------------------------------------------------------------------------------- команды
@router.message(CommandStart())
async def cmd_start(
    message: Message, ctx: Ctx, cfg: Config, is_new_user: bool, state: FSMContext
) -> None:
    await state.clear()
    parts = (message.text or "").split(maxsplit=1)
    if is_new_user and len(parts) == 2 and parts[1].startswith("ref_"):
        raw_referrer = parts[1][4:]
        if raw_referrer.isdigit():
            referrer_id = int(raw_referrer)
            if await ctx.db.award_referral(ctx.user_id, referrer_id, REFERRAL_XP):
                await send_to(
                    ctx.bot,
                    referrer_id,
                    f"🎁 По твоей ссылке пришёл новый пользователь · +{REFERRAL_XP} ⭐",
                    pack=ctx.pack,
                )
    if ctx.is_admin:
        # при первом /start админа Telegram уже позволяет поставить его личное меню модератора
        await ensure_for_admin(ctx.bot, cfg, ctx.user_id, authorized=True)
    await show_welcome(ctx)
    if ctx.mm.status(ctx.user_id) == "queued":
        await ctx.reply("Ты всё ещё в очереди.")


@router.message(Command("ref", "invite"))
async def cmd_referral(message: Message, ctx: Ctx) -> None:
    await show_referral(ctx)


@router.message(Command("help"))
async def cmd_help(message: Message, ctx: Ctx, state: FSMContext) -> None:
    await state.clear()
    await show_help(ctx)


@router.message(Command("rules", "privacy"))
async def cmd_rules(message: Message, ctx: Ctx) -> None:
    await show_rules(ctx)


@router.message(Command("top", "leaderboard"))
async def cmd_top(message: Message, ctx: Ctx) -> None:
    await show_top(ctx)


@router.message(Command("connect", "find", "search"))
async def cmd_connect(message: Message, ctx: Ctx) -> None:
    await act_connect(ctx)


@router.message(Command("next", "skip"))
async def cmd_next(message: Message, ctx: Ctx) -> None:
    await act_next(ctx)


@router.message(Command("stop", "disconnect", "leave"))
async def cmd_stop(message: Message, ctx: Ctx) -> None:
    await act_stop(ctx)


# ---------------------------------------------------------------------------------- кнопки меню
@router.callback_query(F.data == K.CB_MENU)
async def cb_menu(event: CallbackQuery, ctx: Ctx, state: FSMContext) -> None:
    await ctx.ack()
    await state.clear()
    await show_menu(ctx)


@router.callback_query(F.data == K.CB_CONTINUE)
async def cb_continue(event: CallbackQuery, ctx: Ctx, state: FSMContext) -> None:
    await ctx.ack()
    await state.clear()
    await show_menu(ctx)


@router.callback_query(F.data.startswith("onboard:age:"))
async def cb_age(event: CallbackQuery, ctx: Ctx, db: Database, state: FSMContext) -> None:
    try:
        age = int((event.data or "").rsplit(":", 1)[1])
    except (ValueError, IndexError):
        age = 0
    if age != 0 and age not in range(13, 21):
        await ctx.ack("Выбери возраст от 13 до 20 или не указывай", alert=True)
        return
    await db.set_profile(ctx.user_id, age=age)
    ctx.me = await db.get_user(ctx.user_id)
    await ctx.ensure_nick()
    await state.clear()
    await ctx.ack()
    await show_menu(ctx)


@router.callback_query(F.data == K.CB_CONNECT)
async def cb_connect(event: CallbackQuery, ctx: Ctx) -> None:
    await act_connect(ctx)


@router.callback_query(F.data == K.CB_NEXT)
async def cb_next(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack()
    await act_next(ctx)


@router.callback_query(F.data == K.CB_STOP)
async def cb_stop(event: CallbackQuery, ctx: Ctx, cfg: Config) -> None:
    status = ctx.mm.status(ctx.user_id)
    if status == "queued":
        ctx.mm.forget(ctx.user_id)
        await ctx.ack("Поиск остановлен")
        await show_menu(ctx)
        return
    if status != "paired":
        await ctx.ack()
        await ctx.reply(texts.NO_DIALOG, markup=K.menu_keyboard())
        return
    stats = ctx.mm.dialog_stats(ctx.user_id)
    started = float(stats.get("started_at", 0) or 0)
    elapsed = max(0, int(time.time() - started)) if started else 0
    if elapsed >= 5 * 60:
        await ctx.ack()
        mins = max(1, elapsed // 60)
        await ctx.edit(
            f"Диалог идёт уже <b>{mins} мин</b>. Точно остановить?",
            K.confirm_stop_keyboard(),
        )
        return
    await ctx.ack()
    await act_stop(ctx)


@router.callback_query(F.data == K.CB_STOP_YES)
async def cb_stop_yes(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack()
    await act_stop(ctx)


@router.callback_query(F.data == K.CB_STOP_NO)
async def cb_stop_no(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack("Продолжаем")
    await show_menu(ctx)


@router.callback_query(F.data == K.CB_RULES)
async def cb_rules(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack()
    await show_rules(ctx)


@router.callback_query(F.data == K.CB_HELP)
async def cb_help(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack()
    await show_help(ctx)


@router.callback_query(F.data == K.CB_TOP)
async def cb_top(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack()
    await show_top(ctx, "week")


@router.callback_query(F.data.startswith("top:"))
async def cb_top_period(event: CallbackQuery, ctx: Ctx) -> None:
    period = (event.data or "").rsplit(":", 1)[-1]
    if period not in {"week", "month", "all"}:
        await ctx.ack("Кнопка устарела", alert=True)
        return
    await ctx.ack()
    await show_top(ctx, period)


@router.callback_query(F.data == K.CB_REFERRAL)
async def cb_referral(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack()
    await show_referral(ctx)


@router.callback_query(F.data == K.CB_ACTIVITY)
async def cb_activity(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack()
    await show_activity(ctx)


@router.callback_query(F.data == K.CB_STREAK)
async def cb_streak(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack()
    await show_streak(ctx)


@router.callback_query(F.data == K.CB_QUESTS)
async def cb_quests(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack()
    await show_quests(ctx)


@router.callback_query(F.data.startswith("act:"))
async def cb_unknown(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack()
    await show_menu(ctx)


# ---------------------------------------------------------------------------------- оценки
@router.callback_query(F.data == "rate:1")
async def cb_rate_good(event: CallbackQuery, ctx: Ctx) -> None:
    await apply_rating(ctx, positive=True)


@router.callback_query(F.data == "rate:0")
async def cb_rate_bad(event: CallbackQuery, ctx: Ctx) -> None:
    await apply_rating(ctx, positive=False)


@router.callback_query(F.data.startswith("rate:"))
async def cb_rate_unknown(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack("Эта оценка уже учтена")
