"""Действия бота (коннект, следующий, стоп, профиль…) — общая логика для команд и кнопок.

Хендлеры в handlers/* только разбирают апдейт и вызывают отсюда нужное действие,
так что кнопка «🔎 Поиск собеседника» и команда /connect делают буквально одно и то же.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from . import texts
from .config import Config
from .db import Database
from .keyboards import menu_keyboard, rating_keyboard, back_menu_keyboard
from .levels import level_for
from .matching import Matchmaker


@dataclass(slots=True)
class Ctx:
    """Всё, что нужно действию: бот, сервисы, кто запросил и откуда отвечать."""

    bot: Bot
    db: Database
    mm: Matchmaker
    cfg: Config
    event: Message | CallbackQuery
    user_id: int
    me: Any

    @classmethod
    def build(cls, event: Message | CallbackQuery, data: dict) -> "Ctx":
        user = data.get("event_from_user")
        return cls(
            bot=data["bot"],
            db=data["db"],
            mm=data["mm"],
            cfg=data["cfg"],
            event=event,
            user_id=getattr(user, "id", 0),
            me=data.get("me"),
        )

    # ------------------------------------------------------------------ answers
    async def reply(self, text: str, markup: InlineKeyboardMarkup | None = None, **kw: Any) -> Message | None:
        if isinstance(self.event, CallbackQuery):
            if self.event.message is None:
                return None
            return await self.event.message.answer(text=text, reply_markup=markup, **kw)
        return await self.event.answer(text=text, reply_markup=markup, **kw)
    async def ack(self, text: str = "", alert: bool = False) -> None:
        if isinstance(self.event, CallbackQuery):
            try:
                await self.event.answer(text, show_alert=alert)
            except TelegramAPIError:
                pass

    async def edit(self, text: str, markup: InlineKeyboardMarkup | None = None) -> bool:
        if not isinstance(self.event, CallbackQuery) or self.event.message is None:
            return False
        try:
            await self.event.message.edit_text(text=text, reply_markup=markup)
            return True
        except TelegramBadRequest:
            return False  # «Message is not modified» — не страшно
        except TelegramAPIError:
            return False

    # ------------------------------------------------------------------ prefs / guards
    @property
    def prefs(self) -> dict[str, Any]:
        me = self.me
        return {
            "district": (me["district"] if me else "") or "",
            "gender": (me["gender"] if me else "") or "",
            "same_district": bool(me["same_district"]) if me else False,
        }

    async def restricted(self) -> bool:
        """True — пользователю нельзя в чат (бан/мут). Уже всё объяснили."""
        reason = await self.db.is_restricted(self.user_id)
        if reason == "banned":
            row = await self.db.get_user(self.user_id)
            why = (row["ban_reason"] if row else "") or "нарушение правил Анончата"
            await self.reply(
                texts.BANNED.format(city=self.cfg.city, reason=texts.esc(why), contact="/feedback"),
                markup=back_menu_keyboard(),
            )
            return True
        if reason == "muted":
            row = await self.db.get_user(self.user_id)
            mins = max(1, int(((row["mute_until"] if row else 0) - time.time()) // 60) + 1)
            await self.reply(texts.MUTED.format(mins=mins), markup=menu_keyboard(self.cfg.emoji_pack_url))
            return True
        return False


async def send_to(bot: Bot, chat_id: int, text: str, markup: InlineKeyboardMarkup | None = None) -> bool:
    """Доставка собеседнику. False — пользователь недоступен (заблокировал бота)."""
    for attempt in range(2):
        try:
            await bot.send_message(chat_id, text, reply_markup=markup)
            return True
        except TelegramRetryAfter as exc:
            if attempt == 0:
                await asyncio.sleep(min(float(exc.retry_after) + 0.3, 3.0))
                continue
            return True  # не паникуем: сообщение дойдёт при следующей попытке
        except (TelegramForbiddenError, TelegramAPIError):
            return False
    return False


async def send_copy_to(bot: Bot, message: Message, chat_id: int) -> bool:
    try:
        await bot.send_chat_action(chat_id, "typing")
    except TelegramAPIError:
        pass
    try:
        await message.send_copy(chat_id=chat_id)
        return True
    except TelegramRetryAfter:
        return True
    except (TelegramForbiddenError, TelegramAPIError):
        return False


# --------------------------------------------------------------------- menus
async def show_menu(ctx: Ctx, edit: bool = True) -> None:
    status = ctx.mm.status(ctx.user_id)
    xp = int(ctx.me["xp"]) if ctx.me else 0
    info = level_for(xp)
    state = {
        "paired": texts.STATUS_PAIRED,
        "queued": texts.STATUS_QUEUED.format(city=ctx.cfg.city),
    }.get(status, texts.STATUS_FREE.format(city=ctx.cfg.city))

    body = (
        f"🧲 <b>Анонимный чат · {texts.esc(ctx.cfg.city)}</b>\n\n"
        f"🥇 Уровень <b>{info.level}</b> · {texts.esc(info.title)}\n"
        f"<code>{info.bar}</code> {info.xp} XP"
        + (f" · ещё {info.to_next} до «{texts.esc(info.next_title)}»" if info.to_next is not None else "")
        + f"\n\n{state}"
    )
    kb = menu_keyboard(ctx.cfg.emoji_pack_url, status)
    if edit and await ctx.edit(body, kb):
        return
    await ctx.reply(body, kb)


async def show_help(ctx: Ctx) -> None:
    await ctx.reply(
        texts.HELP.format(city=texts.esc(ctx.cfg.city), pack=ctx.cfg.emoji_pack_url),
        markup=menu_keyboard(ctx.cfg.emoji_pack_url, ctx.mm.status(ctx.user_id)),
    )


async def show_rules(ctx: Ctx) -> None:
    await ctx.reply(texts.RULES, markup=menu_keyboard(ctx.cfg.emoji_pack_url, ctx.mm.status(ctx.user_id)))


async def show_top(ctx: Ctx) -> None:
    rows = await ctx.db.top(10)
    if not rows:
        await ctx.reply("🏆 Топ пуст — будь первым, кто начнёт общаться в городе!",
                        markup=menu_keyboard(ctx.cfg.emoji_pack_url))
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🏆 <b>Топ собеседников · {texts.esc(ctx.cfg.city)}</b>", ""]
    for i, row in enumerate(rows, start=1):
        info = level_for(int(row["xp"]))
        mark = medals[i - 1] if i <= 3 else f"{i}."
        lines.append(
            f"{mark} <b>{texts.esc(row['first_name'])}</b> — {info.xp} XP · {texts.esc(info.title)}"
            f"\n     💬 {row['dialogs']} диалогов · 👍 {row['good_ratings']}"
        )
    await ctx.reply("\n".join(lines), markup=menu_keyboard(ctx.cfg.emoji_pack_url))


async def show_profile(ctx: Ctx) -> None:
    if ctx.me is None:
        await ctx.reply(texts.PROFILE_MISSING)
        return
    me = ctx.me
    xp = int(me["xp"])
    info = level_for(xp)
    dialog = ctx.mm.dialog_stats(ctx.user_id)
    status_line = {
        "paired": "💬 сейчас в диалоге",
        "queued": "⏳ ждёт пару в очереди",
    }.get(ctx.mm.status(ctx.user_id), "🧊 свободен")

    about = texts.esc(me["about"]) if me["about"] else "<i>не заполнено — добавь в ⚙️ Настройках</i>"
    lines = [
        f"👤 <b>Профиль собеседника · {texts.esc(ctx.cfg.city)}</b>",
        "",
        f"🥇 <b>Уровень {info.level}</b> — {texts.esc(info.title)}",
        f"<code>{info.bar}</code> <b>{info.xp} XP</b>"
        + (f" → ещё {info.to_next} XP до «{texts.esc(info.next_title)}»" if info.to_next is not None else " · максимум"),
        "",
        f"✉️ Сообщений отправлено: <b>{me['messages']}</b>",
        f"💬 Диалогов проведено: <b>{me['dialogs']}</b>",
        f"👍 Хороших оценок: <b>{me['good_ratings']}</b> · 👎 скучных: <b>{me['bad_ratings']}</b>",
        f"🚩 Жалоб на тебя: <b>{me['reports_received']}</b>",
        f"📍 Район: <b>{texts.esc(me['district']) if me['district'] else 'не указан'}</b>",
        f"🗣 {about}",
        "",
        f"Статус: {status_line}",
    ]
    if dialog:
        dur = int(time.time() - dialog["started_at"])
        lines.append(f"⏱ Текущий диалог идёт: {dur // 60} мин {dur % 60} сек")
    await ctx.reply("\n".join(lines), markup=menu_keyboard(ctx.cfg.emoji_pack_url, ctx.mm.status(ctx.user_id)))


# --------------------------------------------------------------------- dialogs
async def _notify_pair(bot: Bot, cfg: Config, user_id: int, partner_id: int) -> bool:
    """Сообщаем обоим, что пара найдена. False — собеседник недоступен."""
    kb = menu_keyboard(cfg.emoji_pack_url, "paired")
    if not await send_to(bot, partner_id, texts.MATCHED, kb):
        return False
    await send_to(bot, user_id, texts.MATCHED, kb)
    return True


async def announce_pairs(bot: Bot, cfg: Config, mm: Matchmaker, pairs: list[tuple[int, int]]) -> int:
    """Разослать «пара найдена» тем, кого свёл sweep() после смены настроек."""
    kb = menu_keyboard(cfg.emoji_pack_url, "paired")
    made = 0
    for a, b in pairs:
        if not await send_to(bot, b, texts.MATCHED, kb):
            mm.forget(b)
            await send_to(bot, a, texts.PARTNER_LEFT, kb)
            continue
        await send_to(bot, a, texts.MATCHED, kb)
        made += 1
    return made


async def break_pair(bot: Bot, cfg: Config, mm: Matchmaker, user_id: int, note: str) -> None:
    """Расцепить пару (модерация/мут) и честно сообщить обеим сторонам."""
    kb = menu_keyboard(cfg.emoji_pack_url)
    partner, summary = mm.release(user_id)
    if partner is None:
        return
    await send_to(bot, partner, note, kb)
    await send_to(bot, user_id, note, kb)


async def _end_dialog(ctx: Ctx, ended_by: int, note: str, notify_partner: str) -> None:
    partner, summary = ctx.mm.release(ctx.user_id)
    if partner is None:
        await ctx.reply(texts.NO_DIALOG, markup=menu_keyboard(ctx.cfg.emoji_pack_url))
        return

    counts: dict[int, int] = summary.get("counts", {}) or {}
    mine = int(counts.get(ctx.user_id, 0))
    theirs = int(counts.get(partner, 0))
    started = int(summary.get("started_at", time.time()))

    match_id = await ctx.db.log_dialog(
        ctx.user_id, partner, mine, theirs, started, ended_by
    )
    cap = ctx.cfg.xp_message_cap
    live = mine > 0 and theirs > 0 and (mine + theirs) >= 6
    for uid, sent in ((ctx.user_id, mine), (partner, theirs)):
        gain = min(sent, cap) * ctx.cfg.xp_per_message + (ctx.cfg.xp_per_dialog if live else 0)
        if gain:
            await ctx.db.award_xp(uid, gain)
        if sent:
            await ctx.db.bump(uid, "messages", sent)

    ctx.mm.remember_rating([ctx.user_id, partner], match_id)

    await send_to(ctx.bot, partner, notify_partner, menu_keyboard(ctx.cfg.emoji_pack_url))
    xp_hint = f"\n+{min(mine, cap) * ctx.cfg.xp_per_message + (ctx.cfg.xp_per_dialog if live else 0)} XP за этот диалог"
    await ctx.reply(note + xp_hint, markup=rating_keyboard())
    await send_to(ctx.bot, partner, texts.RATING_ASK.format(xp=ctx.cfg.xp_good_rating), rating_keyboard())


async def act_connect(ctx: Ctx) -> None:
    if await ctx.restricted():
        return
    status = ctx.mm.status(ctx.user_id)
    if status == "paired":
        await ctx.reply(texts.ALREADY_PAIRED, markup=menu_keyboard(ctx.cfg.emoji_pack_url, "paired"))
        return
    if status == "queued":
        await ctx.reply(
            texts.QUEUED.format(
                city=texts.esc(ctx.cfg.city), pos=ctx.mm.position(ctx.user_id) or 1, size=ctx.mm.queue_size()
            ),
            markup=menu_keyboard(ctx.cfg.emoji_pack_url, "queued"),
        )
        return

    prefs = ctx.prefs
    for _ in range(8):
        outcome, payload = ctx.mm.connect(ctx.user_id, **prefs)
        if outcome == "paired":
            if await _notify_pair(ctx.bot, ctx.cfg, ctx.user_id, payload):
                await ctx.ack("🧲 Пара найдена!")
                return
            # собеседник исчез — убираем его и пробуем снова
            ctx.mm.forget(payload)
            continue
        if outcome == "queued":
            await ctx.reply(
                texts.QUEUED.format(
                    city=texts.esc(ctx.cfg.city), pos=payload or 1, size=ctx.mm.queue_size()
                ),
                markup=menu_keyboard(ctx.cfg.emoji_pack_url, "queued"),
            )
            await ctx.ack("⏳ Ты в очереди")
            return
        await ctx.reply(texts.QUEUE_FULL.format(limit=ctx.cfg.queue_soft_limit),
                        markup=menu_keyboard(ctx.cfg.emoji_pack_url))
        return
    await ctx.reply("😅 Не успел никого подобрать. Попробуй ещё разок.",
                    markup=menu_keyboard(ctx.cfg.emoji_pack_url))


async def act_next(ctx: Ctx) -> None:
    if await ctx.restricted():
        return
    if ctx.mm.status(ctx.user_id) != "paired":
        await act_connect(ctx)
        return
    await _end_dialog(
        ctx,
        ended_by=ctx.user_id,
        note="⏭️ Пропустил. Ищу нового собеседника…",
        notify_partner=texts.PARTNER_SKIPPED,
    )
    await act_connect(ctx)


async def act_stop(ctx: Ctx) -> None:
    if ctx.mm.status(ctx.user_id) != "paired":
        ctx.mm.forget(ctx.user_id)
        await ctx.reply(texts.NO_DIALOG, markup=menu_keyboard(ctx.cfg.emoji_pack_url))
        return
    await _end_dialog(
        ctx,
        ended_by=ctx.user_id,
        note="⏹️ Диалог остановлен. Ты анонимно вышел — собеседник не узнает ничего лишнего.",
        notify_partner=texts.PARTNER_LEFT,
    )


async def apply_rating(ctx: Ctx, positive: bool) -> None:
    entry = ctx.mm.pop_rating(ctx.user_id)
    if entry is None:
        await ctx.ack("Оценку уже учли или диалог слишком старый 🙂", alert=True)
        return
    match_id, partner = entry
    await ctx.db.rate_dialog(match_id, ctx.user_id, 1 if positive else 0)
    if positive:
        await ctx.db.award_xp(partner, ctx.cfg.xp_good_rating)
        await send_to(ctx.bot, partner, texts.RATING_DONE_GOOD.format(xp=ctx.cfg.xp_good_rating))
        await ctx.ack("👍 Спасибо!")
    else:
        await send_to(ctx.bot, partner, texts.RATING_DONE_BAD)
        await ctx.ack("Записал")
    await ctx.reply(
        "Готово. Жми <b>🔎 Поиск собеседника</b>, когда захочешь продолжить.",
        markup=menu_keyboard(ctx.cfg.emoji_pack_url),
    )


async def forget_everything(ctx: Ctx) -> None:
    """Полное удаление профиля (по желанию пользователя)."""
    ctx.mm.forget(ctx.user_id)
    await ctx.db.forget_user(ctx.user_id)
    await ctx.reply(texts.FORGET_DONE.format(city=texts.esc(ctx.cfg.city)),
                    markup=menu_keyboard(ctx.cfg.emoji_pack_url))
