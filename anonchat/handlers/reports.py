"""Жалобы: кнопка «Жалоба» → причина → комментарий → карточка админу, авто-мут за серию жалоб."""

from __future__ import annotations

import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import keyboards as K
from .. import nick as nicklib
from .. import texts
from ..actions import Ctx, break_pair, send_to
from ..config import Config
from ..db import Database
from ..matching import Matchmaker

router = Router(name="reports")

REASON_TITLES = K.REASON_TITLES


class ReportStates(StatesGroup):
    comment = State()


async def notify_admins(ctx: Ctx, body: str, markup=None) -> None:
    for admin_id in ctx.cfg.admin_ids:
        await send_to(ctx.bot, admin_id, body, markup, ctx.pack)


# ---------------------------------------------------------------------------------- старт жалобы
@router.message(Command("report", "complain", "жалоба"))
async def cmd_report(message: Message, ctx: Ctx) -> None:
    await open_report(ctx)


@router.callback_query(F.data == K.CB_REPORT)
async def cb_report(event: CallbackQuery, ctx: Ctx) -> None:
    await open_report(ctx)


async def open_report(ctx: Ctx) -> None:
    partner = ctx.mm.partner(ctx.user_id)
    kb = K.report_keyboard()
    if partner is None:
        await ctx.reply(texts.REPORT_NO_TARGET, markup=K.menu_keyboard())
        return
    await ctx.render_screen("07_report.png", texts.REPORT_INTRO, kb)


# ---------------------------------------------------------------------------------- причина
@router.callback_query(F.data == "rep:skip")
async def cb_skip_comment(event: CallbackQuery, ctx: Ctx, state: FSMContext) -> None:
    data = await state.get_data()
    await finish_report(ctx, state, data.get("reason", "other"), "")


@router.callback_query(F.data.startswith("rep:"))
async def cb_reason(event: CallbackQuery, ctx: Ctx, state: FSMContext) -> None:
    code = event.data.split(":", 1)[1]
    if code not in REASON_TITLES:
        await ctx.ack("Не понял причину", alert=True)
        return
    partner = ctx.mm.partner(ctx.user_id)
    if partner is None:
        await state.clear()
        await ctx.reply(texts.REPORT_NO_TARGET, markup=K.menu_keyboard())
        return
    await state.set_state(ReportStates.comment)
    await state.update_data(reason=code, partner=partner)
    prompt = texts.REPORT_COMMENT_PROMPT.format(reason=texts.esc(REASON_TITLES[code]))
    if not await ctx.edit(prompt, K.skip_cancel_keyboard()):
        await ctx.reply(prompt, K.skip_cancel_keyboard())
    await ctx.ack("Принято")


# ---------------------------------------------------------------------------------- текст жалобы
@router.message(ReportStates.comment, F.text, ~F.text.startswith("/"))
async def report_comment(message: Message, ctx: Ctx, state: FSMContext) -> None:
    data = await state.get_data()
    await finish_report(ctx, state, data.get("reason", "other"), (message.text or "").strip()[:500])


async def finish_report(ctx: Ctx, state: FSMContext, reason: str, comment: str) -> None:
    await state.clear()
    mm: Matchmaker = ctx.mm
    db: Database = ctx.db
    cfg: Config = ctx.cfg

    partner = mm.partner(ctx.user_id)
    if partner is None:
        await ctx.reply(texts.REPORT_NO_TARGET, markup=K.menu_keyboard())
        return

    dialog = mm.dialog_stats(ctx.user_id)
    dialog_key = str(dialog.get("dialog_key", ""))
    history = dialog.get("history", []) or []
    context = "\n".join(
        f"— {'жалующийся' if int(uid) == ctx.user_id else 'собеседник'}: {text}"
        for uid, text in history[-10:]
    )
    report_id, day_count = await db.add_report(
        ctx.user_id, partner, reason, comment, dialog_key=dialog_key, context=context
    )
    if report_id is None:
        await ctx.reply(texts.REPORT_DUPLICATE, markup=K.menu_keyboard("paired"))
        return
    target_row = await db.get_user(partner)
    # карточка — только для модератора: здесь настоящие данные уместны
    target_name = (target_row["first_name"] if target_row else "собеседник") or "собеседник"
    target_login = f"@{target_row['username']}" if target_row and target_row["username"] else "без юзернейма"
    target_nick = nicklib.display(
        target_row["nickname"] if target_row else "",
        partner,
        target_row["premium_until"] if target_row else 0,
    )

    card = (
        f"🚩 <b>Жалоба #{report_id}</b>\n"
        f"Причина: <b>{texts.esc(REASON_TITLES.get(reason, reason))}</b>\n"
        f"На: <code>{partner}</code> · в чате как <b>{texts.esc(target_nick)}</b> · "
        f"{texts.esc(target_name)} ({texts.esc(target_login)})\n"
        f"От: <code>{ctx.user_id}</code>\n"
        f"Последние сообщения:\n{texts.esc(context) if context else '<i>нет текстового контекста</i>'}\n\n"
        f"Комментарий: {texts.esc(comment) if comment else '<i>без комментария</i>'}\n"
        f"Жалоб на него за сутки: <b>{day_count}</b> · {time.strftime('%d.%m %H:%M')}"
    )
    await notify_admins(ctx, card, K.admin_report_keyboard(report_id))

    auto = ""
    if cfg.auto_mute_reports > 0 and day_count >= cfg.auto_mute_reports:
        until = await db.set_mute(partner, cfg.auto_mute_minutes)
        mins = max(1, int((until - time.time()) // 60))
        await send_to(ctx.bot, partner, texts.MUTED.format(mins=mins), None, ctx.pack)
        await break_pair(ctx.bot, cfg, mm, partner, texts.MOD_CLOSED_DIALOG, ctx.pack)
        auto = texts.REPORT_AUTO_MUTE.format(mins=mins)

    await ctx.reply(
        texts.REPORT_TAKEN.format(rid=report_id, reason=texts.esc(REASON_TITLES.get(reason, reason)))
        + auto
        + "\n\nМожешь сразу выйти из диалога: <code>/stop</code>.",
        markup=K.menu_keyboard(),
    )


# --------------------------------------------------------------------------------=> /feedback
@router.message(Command("feedback"))
async def cmd_feedback(message: Message, ctx: Ctx) -> None:
    body = (message.text or "").partition(" ")[2].strip()
    if not body:
        await ctx.reply(texts.FEEDBACK_EMPTY)
        return
    await notify_admins(
        ctx,
        f"💌 <b>Фидбек</b> от <code>{ctx.user_id}</code> ({texts.esc(message.from_user.first_name)}):\n"
        f"{texts.esc(body[:1000])}",
    )
    await ctx.reply(texts.FEEDBACK_SENT)
