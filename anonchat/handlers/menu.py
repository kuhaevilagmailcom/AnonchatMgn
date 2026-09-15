"""Меню, команды-дубликаты кнопок и оценка диалога."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .. import keyboards as K
from .. import texts
from ..actions import (
    Ctx,
    act_connect,
    act_next,
    act_stop,
    apply_rating,
    show_help,
    show_menu,
    show_rules,
    show_top,
    show_welcome,
)
from ..commands import ensure_for_admin
from ..config import Config

router = Router(name="menu")


# ---------------------------------------------------------------------------------- команды
@router.message(CommandStart())
async def cmd_start(message: Message, ctx: Ctx, cfg: Config) -> None:
    if ctx.user_id in cfg.admin_ids:
        # при первом /start админа Telegram уже позволяет поставить его личное меню модератора
        await ensure_for_admin(ctx.bot, cfg, ctx.user_id)
    await show_welcome(ctx)
    if ctx.mm.status(ctx.user_id) == "queued":
        await ctx.reply("⏳ Ты всё ещё в очереди — найду пару автоматически.")


@router.message(Command("help"))
async def cmd_help(message: Message, ctx: Ctx) -> None:
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
async def cb_menu(event: CallbackQuery, ctx: Ctx) -> None:
    await show_menu(ctx)


@router.callback_query(F.data == K.CB_CONNECT)
async def cb_connect(event: CallbackQuery, ctx: Ctx) -> None:
    await act_connect(ctx)


@router.callback_query(F.data == K.CB_NEXT)
async def cb_next(event: CallbackQuery, ctx: Ctx) -> None:
    await act_next(ctx)


@router.callback_query(F.data == K.CB_STOP)
async def cb_stop(event: CallbackQuery, ctx: Ctx, cfg: Config) -> None:
    if ctx.mm.status(ctx.user_id) != "paired":
        await ctx.reply(texts.NO_DIALOG, markup=K.menu_keyboard())
        return
    await ctx.edit(
        "⏹ Остановить диалог? Собеседник увидит, что чат закрыт — но не узнает, кто ты.",
        K.confirm_stop_keyboard(),
    )


@router.callback_query(F.data == K.CB_STOP_YES)
async def cb_stop_yes(event: CallbackQuery, ctx: Ctx) -> None:
    await act_stop(ctx)


@router.callback_query(F.data == K.CB_STOP_NO)
async def cb_stop_no(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack("Хорошо, продолжаем")
    await show_menu(ctx)


@router.callback_query(F.data == K.CB_RULES)
async def cb_rules(event: CallbackQuery, ctx: Ctx) -> None:
    await show_rules(ctx)


@router.callback_query(F.data == K.CB_HELP)
async def cb_help(event: CallbackQuery, ctx: Ctx) -> None:
    await show_help(ctx)


@router.callback_query(F.data == K.CB_TOP)
async def cb_top(event: CallbackQuery, ctx: Ctx) -> None:
    await show_top(ctx)


@router.callback_query(F.data.startswith("act:"))
async def cb_unknown(event: CallbackQuery, ctx: Ctx) -> None:
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
    await ctx.ack("Эта оценка уже учтена 🙂")
