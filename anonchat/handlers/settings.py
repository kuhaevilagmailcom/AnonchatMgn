"""Настройки профиля: ник, возраст, район, фильтр и удаление данных."""

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
from ..actions import Ctx, announce_pairs, forget_everything, set_nick, show_menu, show_profile
from ..config import Config
from ..db import Database
from ..matching import Matchmaker
from ..message_styles import STYLE_LABELS

router = Router(name="settings")


def _nick_prompt(ctx: Ctx) -> str:
    return texts.NICK_PROMPT.format(
        nick=texts.esc(ctx.nick), min=nicklib.NICK_MIN, max=nicklib.NICK_MAX
    )

DISTRICTS = {
    "none": "",
    "right": "Правобережный",
    "left": "Левобережный",
    "ordz": "Орджоникидзевский",
}

class ProfileStates(StatesGroup):
    nick = State()


async def _apply(ctx: Ctx, db: Database, mm: Matchmaker, **fields) -> None:
    """Сохраняем профиль и пересобираем очередь с новыми фильтрами."""
    await db.set_profile(ctx.user_id, **fields)
    me = await db.get_user(ctx.user_id)
    if me is None:
        return
    ctx.me = me
    pairs = mm.refresh(
        ctx.user_id,
        district=me["district"],
        same_district=bool(me["same_district"]),
    )
    if pairs:
        await announce_pairs(ctx.bot, ctx.cfg, mm, pairs, ctx.pack, db)


async def settings_screen(ctx: Ctx) -> None:
    if await ctx.dialog_locked():
        return
    me = ctx.me
    district = (me["district"] if me else "") or ""
    same = bool(me["same_district"]) if me else False
    body = (
        f"{texts.SETTINGS_TITLE}\n\n"
        f"🙋 Ник: <b>{texts.esc(ctx.nick)}</b>\n"
        f"📍 Район: <b>{texts.esc(district or 'не выбран')}</b>\n"
        f"Возраст: <b>{int(me['age']) if me and int(me['age'] or 0) else 'не указан'}</b> "
        f"<i>(необязательно)</i>\n"
        f"Район: <i>необязательно</i>\n"
        f"🧭 Ищу: <b>{'только свой район' if same else 'весь ' + texts.esc(ctx.cfg.city_short)}</b>\n\n"
        f"{texts.SETTINGS_NOTE}"
    )
    kb = K.settings_keyboard(same, district, ctx.nick)
    await ctx.render_screen("05_settings.png", body, kb)


@router.callback_query(F.data == "cfg:age:ask")
async def cb_age_ask(event: CallbackQuery, ctx: Ctx) -> None:
    if await ctx.dialog_locked():
        return
    await ctx.edit("<b>Сколько тебе лет?</b>", K.age_keyboard())


# ---------------------------------------------------------------------------------- экран настроек
@router.message(Command("settings", "config"))
async def cmd_settings(message: Message, ctx: Ctx) -> None:
    await settings_screen(ctx)


@router.callback_query(F.data == K.CB_SETTINGS)
async def cb_settings(event: CallbackQuery, ctx: Ctx) -> None:
    await settings_screen(ctx)


async def communication_style_screen(ctx: Ctx, cfg: Config) -> None:
    row = ctx.me or await ctx.db.get_user(ctx.user_id)
    if row is None or int(row["premium_until"] or 0) <= int(time.time()):
        from .support import show_premium

        await show_premium(ctx, cfg)
        return
    current = str(row["communication_style"] or "")
    current_label = STYLE_LABELS.get(current, "🚫 Отключён")
    await ctx.edit(
        f"🎭 <b>Стиль общения</b>\n\nТекущий стиль: <b>{current_label}</b>\n\n"
        "Он автоматически применяется к твоим сообщениям в диалогах.",
        K.communication_style_keyboard(current),
    )


@router.callback_query(F.data == "cfg:style")
async def cb_communication_style(event: CallbackQuery, ctx: Ctx, cfg: Config) -> None:
    if await ctx.dialog_locked():
        return
    await communication_style_screen(ctx, cfg)
    await ctx.ack()


@router.callback_query(F.data.startswith("cfg:style:"))
async def cb_set_communication_style(event: CallbackQuery, ctx: Ctx, cfg: Config) -> None:
    if await ctx.dialog_locked():
        return
    row = ctx.me or await ctx.db.get_user(ctx.user_id)
    if row is None or int(row["premium_until"] or 0) <= int(time.time()):
        from .support import show_premium

        await show_premium(ctx, cfg)
        await ctx.ack("Нужна активная подписка", alert=True)
        return
    value = event.data.rsplit(":", 1)[1]
    style = "" if value == "off" else value
    if style not in STYLE_LABELS and style:
        await ctx.ack("Неизвестный стиль", alert=True)
        return
    await ctx.db.set_communication_style(ctx.user_id, style)
    ctx.me = await ctx.db.get_user(ctx.user_id)
    await ctx.ack("Стиль отключён" if not style else f"Выбран: {STYLE_LABELS[style]}")
    await communication_style_screen(ctx, cfg)


# ---------------------------------------------------------------------------------- ник
@router.message(Command("nick", "ник"))
async def cmd_nick(message: Message, ctx: Ctx, state: FSMContext) -> None:
    """`/nick Ким` — сразу меняем; голая `/nick` или кнопка — спрашиваем следующим сообщением."""
    if await ctx.dialog_locked():
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1:
        ok, answer = await set_nick(ctx, parts[1])
        await state.clear()  # иначе следующее сообщение пользователя уйдёт в ник вместо чата
        await message.answer(answer)
        return
    await state.set_state(ProfileStates.nick)
    await ctx.reply(_nick_prompt(ctx))


@router.callback_query(F.data == K.CB_NICK)
async def cb_nick_ask(event: CallbackQuery, ctx: Ctx, state: FSMContext) -> None:
    if await ctx.dialog_locked():
        return
    await state.set_state(ProfileStates.nick)
    await ctx.edit(_nick_prompt(ctx), K.back_menu_keyboard())


@router.message(ProfileStates.nick, F.text, ~F.text.startswith("/"))
async def nick_text(message: Message, ctx: Ctx, state: FSMContext) -> None:
    if ctx.mm.status(ctx.user_id) == "paired":
        await state.clear()  # иначе текст диалога съедается вводом ника
        await message.answer(texts.DIALOG_LOCKED)
        return
    ok, answer = await set_nick(ctx, message.text or "")
    await message.answer(answer)
    if not ok:
        await state.set_state(ProfileStates.nick)  # даём шанс перебрать ник
        return
    await state.clear()
    await settings_screen(ctx)


# ---------------------------------------------------------------------------------- район
@router.callback_query(F.data == "cfg:district:ask")
async def cb_district_ask(event: CallbackQuery, ctx: Ctx) -> None:
    if await ctx.dialog_locked():
        return
    await ctx.edit(f"С каким районом {texts.esc(ctx.cfg.city_short)} ты себя ассоциируешь?", K.district_keyboard())


@router.callback_query(F.data.startswith("cfg:district:"))
async def cb_district(event: CallbackQuery, ctx: Ctx, db: Database, mm: Matchmaker) -> None:
    if await ctx.dialog_locked():
        return
    key = event.data.split(":", 2)[2]
    await _apply(ctx, db, mm, district=DISTRICTS.get(key, ""))
    await ctx.ack("Район обновлён")
    await settings_screen(ctx)


# ---------------------------------------------------------------------------------- «только мой район»
@router.callback_query(F.data == "cfg:same:toggle")
async def cb_same_toggle(event: CallbackQuery, ctx: Ctx, db: Database, mm: Matchmaker) -> None:
    if await ctx.dialog_locked():
        return
    me = ctx.me or await db.get_user(ctx.user_id)
    new = 0 if (me and me["same_district"]) else 1
    await _apply(ctx, db, mm, same_district=new)
    await ctx.ack("Ищем только в своём районе" if new else "Ищем по всему городу")
    await settings_screen(ctx)


# ---------------------------------------------------------------------------------- сброс / удаление
@router.callback_query(F.data == "cfg:reset")
async def cb_reset(event: CallbackQuery, ctx: Ctx, db: Database, mm: Matchmaker) -> None:
    if await ctx.dialog_locked():
        return
    await _apply(ctx, db, mm, district="", same_district=0)
    await ctx.reply(texts.RESET_DONE)
    await settings_screen(ctx)


@router.callback_query(F.data == "cfg:blocks:ask")
async def cb_blocks_ask(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.edit("Вернуть в поиск всех скрытых людей?", K.confirm_blocks_keyboard())


@router.callback_query(F.data == "cfg:blocks:yes")
async def cb_blocks_yes(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    await db.clear_blocks(ctx.user_id)
    await ctx.ack("Скрытые собеседники сброшены")
    await settings_screen(ctx)


@router.callback_query(F.data == "cfg:blocks:no")
async def cb_blocks_no(event: CallbackQuery, ctx: Ctx) -> None:
    await settings_screen(ctx)


@router.callback_query(F.data == "cfg:forget:ask")
async def cb_forget_ask(event: CallbackQuery, ctx: Ctx) -> None:
    if await ctx.dialog_locked():
        return
    await ctx.edit(
        "Удалить профиль целиком? Слетят опыт, статистика, ник и настройки. Отменить нельзя.",
        K.confirm_forget_keyboard(),
    )


@router.callback_query(F.data == "cfg:forget:yes")
async def cb_forget_yes(event: CallbackQuery, ctx: Ctx) -> None:
    if await ctx.dialog_locked():
        return
    await forget_everything(ctx)


@router.callback_query(F.data == "cfg:forget:no")
async def cb_forget_no(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack("Окей, не трогаем")
    await settings_screen(ctx)


@router.message(Command("forget"))
async def cmd_forget(message: Message, ctx: Ctx) -> None:
    if await ctx.dialog_locked():
        return
    await ctx.reply(
        "Точно стереть профиль? Кнопка ниже или /cancel, чтобы отменить.",
        markup=K.confirm_forget_keyboard(),
    )


# ---------------------------------------------------------------------------------- профиль / отмена
@router.message(Command("profile", "me"))
async def cmd_profile(message: Message, ctx: Ctx) -> None:
    await show_profile(ctx)


@router.callback_query(F.data == K.CB_PROFILE)
async def cb_profile(event: CallbackQuery, ctx: Ctx) -> None:
    await show_profile(ctx)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, ctx: Ctx, state: FSMContext) -> None:
    if await state.get_state() is None:
        await ctx.reply("Нечего отменять.")
        return
    await state.clear()
    await show_menu(ctx)
