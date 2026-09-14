"""Профиль, настройки подбора (район / «только свой район» / описание) и удаление профиля."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import keyboards as K
from .. import texts
from ..actions import Ctx, announce_pairs, forget_everything, show_menu, show_profile
from ..config import Config
from ..db import Database
from ..matching import Matchmaker

router = Router(name="settings")

DISTRICTS = {
    "none": "",
    "right": "Правобережный",
    "left": "Левобережный",
    "ordz": "Орджоникидзевский",
}

GENDERS = {"m": "🙋‍♂️ парень", "f": "🙋‍♀️ девушка", "none": ""}


class AboutStates(StatesGroup):
    text = State()


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
        gender=me["gender"],
        same_district=bool(me["same_district"]),
    )
    if pairs:
        await announce_pairs(ctx.bot, ctx.cfg, mm, pairs)


async def settings_screen(ctx: Ctx, edit: bool = True) -> None:
    me = ctx.me
    district = (me["district"] if me else "") or "не выбран"
    gender = (me["gender"] if me else "") or "не указан"
    same = bool(me["same_district"]) if me else False
    body = (
        "⚙️ <b>Настройки подбора</b>\n\n"
        f"📍 Район: <b>{texts.esc(district)}</b>\n"
        f"👤 Пол в профиле: <b>{texts.esc(gender)}</b>\n"
        f"🧭 Ищу: <b>{'только свой район' if same else 'весь ' + texts.esc(ctx.cfg.city_short)}</b>\n\n"
        "Фильтр по району срабатывает, когда вы <i>оба</i> поставили «только свой» — "
        "иначе ищем по всему городу, чтобы не сидеть в очереди полдня."
    )
    kb = K.settings_keyboard(same, (me["district"] if me else "") or "")
    if edit and await ctx.edit(body, kb):
        return
    await ctx.reply(body, kb)


# ---------------------------------------------------------------------------------- экран настроек
@router.message(Command("settings", "config"))
async def cmd_settings(message: Message, ctx: Ctx) -> None:
    await settings_screen(ctx, edit=False)


@router.callback_query(F.data == K.CB_SETTINGS)
async def cb_settings(event: CallbackQuery, ctx: Ctx) -> None:
    await settings_screen(ctx)


# ---------------------------------------------------------------------------------- район
@router.callback_query(F.data == "cfg:district:ask")
async def cb_district_ask(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.edit("📍 С каким районом МГН ты себя ассоциируешь?", K.district_keyboard())


@router.callback_query(F.data.startswith("cfg:district:"))
async def cb_district(event: CallbackQuery, ctx: Ctx, db: Database, mm: Matchmaker) -> None:
    key = event.data.split(":", 2)[2]
    await _apply(ctx, db, mm, district=DISTRICTS.get(key, ""))
    await ctx.ack("📍 Район обновлён")
    await settings_screen(ctx)


# ---------------------------------------------------------------------------------- пол
@router.callback_query(F.data == "cfg:gender:ask")
async def cb_gender_ask(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.edit(
        "👤 Кого указать в профиле? На подбор не влияет — только чтобы ты сам(а) решал(а), "
        "что писать в «О себе».",
        K.gender_keyboard(),
    )


@router.callback_query(F.data.startswith("cfg:gender:"))
async def cb_gender(event: CallbackQuery, ctx: Ctx, db: Database, mm: Matchmaker) -> None:
    key = event.data.split(":", 2)[2]
    await _apply(ctx, db, mm, gender=GENDERS.get(key, ""))
    await ctx.ack("👤 Обновлено")
    await settings_screen(ctx)


# ---------------------------------------------------------------------------------- «только мой район»
@router.callback_query(F.data == "cfg:same:toggle")
async def cb_same_toggle(event: CallbackQuery, ctx: Ctx, db: Database, mm: Matchmaker) -> None:
    me = ctx.me or await db.get_user(ctx.user_id)
    new = 0 if (me and me["same_district"]) else 1
    await _apply(ctx, db, mm, same_district=new)
    await ctx.ack("🔒 Ищем только в своём районе" if new else "🔓 Ищем по всему городу")
    await settings_screen(ctx)


# ---------------------------------------------------------------------------------- «о себе»
@router.callback_query(F.data == "cfg:about:ask")
async def cb_about_ask(event: CallbackQuery, ctx: Ctx, state: FSMContext) -> None:
    await state.set_state(AboutStates.text)
    await ctx.edit(texts.ABOUT_PROMPT, K.back_menu_keyboard())


@router.message(AboutStates.text, F.text)
async def about_text(message: Message, ctx: Ctx, state: FSMContext, db: Database) -> None:
    raw = (message.text or "").strip()
    value = "" if raw in {"-", "—", "--"} else raw[:120]
    await db.set_profile(ctx.user_id, about=value)
    await state.clear()
    await message.answer(texts.ABOUT_SAVED if value else "🧹 Описание очищено.")
    await show_menu(ctx, edit=False)


# ---------------------------------------------------------------------------------- сброс / удаление
@router.callback_query(F.data == "cfg:reset")
async def cb_reset(event: CallbackQuery, ctx: Ctx, db: Database, mm: Matchmaker, cfg: Config) -> None:
    await _apply(ctx, db, mm, district="", gender="", same_district=0, about="")
    await ctx.reply(texts.RESET_DONE.format(city=texts.esc(cfg.city)))
    await settings_screen(ctx, edit=False)


@router.callback_query(F.data == "cfg:forget:ask")
async def cb_forget_ask(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.edit(
        "🧹 Удалить профиль целиком? Слетит опыт, статистика и история диалогов. "
        "Отменить будет нельзя.",
        K.confirm_forget_keyboard(),
    )


@router.callback_query(F.data == "cfg:forget:yes")
async def cb_forget_yes(event: CallbackQuery, ctx: Ctx) -> None:
    await forget_everything(ctx)


@router.callback_query(F.data == "cfg:forget:no")
async def cb_forget_no(event: CallbackQuery, ctx: Ctx) -> None:
    await ctx.ack("Окей, не трогаем 🤝")
    await settings_screen(ctx)


@router.message(Command("forget"))
async def cmd_forget(message: Message, ctx: Ctx) -> None:
    await ctx.reply(
        "Точно стереть профиль? Кнопка ниже или <code>/cancel</code>, чтобы отменить.",
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
        await ctx.reply("Нечего отменять 🙂")
        return
    await state.clear()
    await show_menu(ctx, edit=False)
