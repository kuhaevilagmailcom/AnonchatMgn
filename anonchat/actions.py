"""Действия бота: поиск пары, следующий, стоп, профиль, ник, настройки-экраны.

Хендлеры только разбирают апдейт и вызывают отсюда нужное действие — кнопка
«🔎 Поиск собеседника» и команда /connect делают буквально одно и то же.
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

from . import nick as nicklib
from . import texts
from .config import Config
from .db import Database
from .keyboards import menu_keyboard, rating_keyboard
from .levels import rank_for
from .matching import Matchmaker
from .pack import EmojiPack


@dataclass(slots=True)
class Ctx:
    bot: Bot
    db: Database
    mm: Matchmaker
    cfg: Config
    pack: EmojiPack
    event: Message | CallbackQuery
    user_id: int
    me: Any = None

    def __post_init__(self) -> None:
        if self.pack is None:
            self.pack = EmojiPack(self.cfg.emoji_pack_url)

    # ------------------------------------------------------------------ answers
    async def reply(self, text: str, markup: InlineKeyboardMarkup | None = None, **kw: Any) -> Message | None:
        target = self.event.message if isinstance(self.event, CallbackQuery) else self.event
        if target is None:
            return None
        return await _send_text(target, text, markup, self.pack, **kw)

    async def ack(self, text: str = "", alert: bool = False) -> None:
        if isinstance(self.event, CallbackQuery):
            try:
                await self.event.answer(text, show_alert=alert)
            except TelegramAPIError:
                pass

    async def edit(self, text: str, markup: InlineKeyboardMarkup | None = None) -> bool:
        if not isinstance(self.event, CallbackQuery) or self.event.message is None:
            return False
        for attempt in range(2):
            body = self.pack.wrap(text) if attempt == 0 else self.pack.strip(text)
            try:
                await self.event.message.edit_text(text=body, reply_markup=markup)
                return True
            except TelegramBadRequest as exc:
                if attempt == 0 and self.pack.accept(exc):
                    continue
                return False
            except TelegramAPIError:
                return False
        return False

    # ------------------------------------------------------------------ профиль
    @property
    def nick(self) -> str:
        return nicklib.display(self.me["nickname"] if self.me else "", self.user_id)

    @property
    def prefs(self) -> dict[str, Any]:
        me = self.me
        return {
            "district": (me["district"] if me else "") or "",
            "gender": (me["gender"] if me else "") or "",
            "same_district": bool(me["same_district"]) if me else False,
        }

    async def ensure_nick(self) -> str:
        """Авто-ник при первом же контакте — чтобы нигде не светилось настоящее имя."""
        if self.me is None:
            return self.nick
        if not (self.me["nickname"] or "").strip():
            auto = nicklib.auto_nick(self.user_id)
            await self.db.set_profile(self.user_id, nickname=auto)
            self.me = await self.db.get_user(self.user_id)
        return self.nick

    # ------------------------------------------------------------------ guards
    async def restricted(self) -> bool:
        reason = await self.db.is_restricted(self.user_id)
        if reason == "banned":
            row = await self.db.get_user(self.user_id)
            why = (row["ban_reason"] if row else "") or "нарушение правил"
            await self.reply(
                texts.BANNED.format(city=texts.esc(self.cfg.city), reason=texts.esc(why)),
                markup=menu_keyboard(),
            )
            return True
        if reason == "muted":
            row = await self.db.get_user(self.user_id)
            mins = max(1, int(((row["mute_until"] if row else 0) - time.time()) // 60) + 1)
            await self.reply(
                texts.MUTED.format(mins=mins), markup=menu_keyboard()
            )
            return True
        return False


# --------------------------------------------------------------------- low-level
async def _send_text(
    target: Message, text: str, markup: InlineKeyboardMarkup | None, pack: EmojiPack, **kw: Any
) -> Message | None:
    for attempt in range(2):
        body = pack.wrap(text) if attempt == 0 else pack.strip(text)
        try:
            return await target.answer(text=body, reply_markup=markup, **kw)
        except TelegramBadRequest as exc:
            if attempt == 0 and pack.accept(exc):
                continue
            return None
    return None


async def send_to(
    bot: Bot,
    chat_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    pack: EmojiPack | None = None,
) -> bool:
    """Доставка собеседнику. False — пользователь недоступен (заблокировал бота)."""
    if not chat_id:
        return False
    for attempt in range(2):
        body = pack.wrap(text) if (pack and attempt == 0) else text
        try:
            await bot.send_message(chat_id, body, reply_markup=markup)
            return True
        except TelegramBadRequest as exc:
            if attempt == 0 and pack is not None and pack.accept(exc):
                continue
            return False
        except TelegramRetryAfter as exc:
            if attempt == 0:
                await asyncio.sleep(min(float(exc.retry_after) + 0.3, 3.0))
                continue
            return True
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


# --------------------------------------------------------------------- экраны
async def show_menu(ctx: Ctx, edit: bool = True) -> None:
    status = ctx.mm.status(ctx.user_id)
    rank = rank_for(int(ctx.me["messages"]) if ctx.me else 0)
    state = {
        "paired": texts.STATUS_PAIRED,
        "queued": texts.STATUS_QUEUED,
    }.get(status, texts.STATUS_FREE)

    body = (
        f"🧲 <b>{texts.esc(ctx.cfg.city)}</b>\n"
        f"🙋 <b>{texts.esc(ctx.nick)}</b> · {rank.name}\n"
        f"<code>{rank.bar}</code> <i>{rank.pretty(rank.messages)} сообщ.</i>\n\n"
        f"{state}"
    )
    kb = menu_keyboard(status, ctx.mm.queue_size())
    if edit and await ctx.edit(body, kb):
        return
    await ctx.reply(body, kb)


async def show_welcome(ctx: Ctx) -> None:
    nick = await ctx.ensure_nick()
    await ctx.reply(
        texts.WELCOME.format(
            city=texts.esc(ctx.cfg.city),
            nick=texts.esc(nick),
            nick_hint=texts.NICK_HINT,
        ),
        markup=menu_keyboard(ctx.mm.status(ctx.user_id), ctx.mm.queue_size()),
    )


async def show_help(ctx: Ctx) -> None:
    await ctx.reply(
        texts.HELP.format(pack=ctx.cfg.emoji_pack_url),
        markup=menu_keyboard(ctx.mm.status(ctx.user_id)),
    )


async def show_rules(ctx: Ctx) -> None:
    await ctx.reply(texts.RULES, markup=menu_keyboard(ctx.mm.status(ctx.user_id)))


async def show_top(ctx: Ctx) -> None:
    rows = await ctx.db.top(10)
    if not rows:
        await ctx.reply("🏆 Топ пуст — начни общаться первым.", markup=menu_keyboard())
        return
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [f"🏆 <b>Топ · {texts.esc(ctx.cfg.city)}</b>", ""]
    for i, row in enumerate(rows, start=1):
        messages = int(row["messages"])
        rank = rank_for(messages)
        # медали только за места: ранг подписываем словом, иначе 🥇/🥈 слипаются с 🥇 Серебро
        place = medals.get(i, f"<code>{i}</code>")
        lines.append(
            f"{place} <b>{texts.esc(nicklib.display(row['nickname'], int(row['user_id'])))}</b>"
            f" — {rank.pretty(messages)} сообщ. · {texts.esc(rank.title)}"
        )
    lines += ["", "<i>Ники участники придумывают сами.</i>"]
    await ctx.reply("\n".join(lines), markup=menu_keyboard())


async def show_profile(ctx: Ctx) -> None:
    if ctx.me is None:
        await ctx.reply(texts.PROFILE_MISSING)
        return
    me = ctx.me
    messages = int(me["messages"])
    rank = rank_for(messages)
    status = ctx.mm.status(ctx.user_id)
    about = texts.esc(me["about"]) if me["about"] else texts.PROFILE_ABOUT_EMPTY

    progress = f"<code>{rank.bar}</code>"
    if rank.is_max:
        progress += f" <i>максимальный ранг</i>"
    else:
        progress += (
            f" <i>{rank.pretty(messages)} / {rank.pretty(rank.next_need or 0)}"
            f" · до «{texts.esc(rank.next_title)}» ещё {rank.pretty(rank.to_next or 0)}</i>"
        )

    lines = [
        texts.PROFILE_TITLE.format(city=texts.esc(ctx.cfg.city)),
        "",
        f"🙋 <b>{texts.esc(ctx.nick)}</b>",
        f"{rank.emoji} <b>{texts.esc(rank.title)}</b>",
        progress,
        "",
        f"💬 Сообщений: <b>{rank.pretty(messages)}</b> · диалогов: {me['dialogs']}",
        f"⭐ Опыт: {rank.pretty(int(me['xp']))} · оценки 👍 {me['good_ratings']} / 👎 {me['bad_ratings']}",
        f"🚩 Жалоб на тебя: {me['reports_received']}",
        f"📍 {texts.esc(me['district']) if me['district'] else 'район не указан'}"
        f" · ищу: {texts.PROFILE_SEARCH['own' if me['same_district'] else 'city']}",
        f"✍️ {about}",
        "",
        texts.PROFILE_STATUS.get(status, ""),
    ]
    await ctx.reply("\n".join(lines), markup=menu_keyboard(status))


# --------------------------------------------------------------------- ники
async def ask_nick(ctx: Ctx) -> None:
    await ctx.reply(
        texts.NICK_PROMPT.format(
            nick=texts.esc(ctx.nick), min=nicklib.NICK_MIN, max=nicklib.NICK_MAX
        ),
        markup=menu_keyboard(ctx.mm.status(ctx.user_id)),
    )


async def set_nick(ctx: Ctx, raw: str) -> tuple[bool, str]:
    """Валидация + уникальность. Возвращает (успех, текст ответа)."""
    value = (raw or "").strip()
    if value in {"-", "—", "--", "auto"}:
        await ctx.db.set_profile(ctx.user_id, nickname="")
        ctx.me = await ctx.db.get_user(ctx.user_id)
        return True, texts.NICK_RESET.format(nick=texts.esc(await ctx.ensure_nick()))

    candidate, error = nicklib.validate(value)
    if error:
        return False, texts.NICK_BAD.format(error=texts.esc(error))
    if await ctx.db.nickname_taken(candidate, except_user_id=ctx.user_id):
        return False, texts.NICK_TAKEN

    await ctx.db.set_profile(ctx.user_id, nickname=candidate)
    ctx.me = await ctx.db.get_user(ctx.user_id)
    return True, texts.NICK_SAVED.format(nick=texts.esc(candidate))


# --------------------------------------------------------------------- пары
async def announce_pair(ctx: Ctx, user_id: int, partner_id: int) -> bool:
    """Сообщаем обоим о паре — без кнопок: в диалоге мешают, всё есть командами.

    Возвращает False, если собеседник недоступен (заблокировал бота).
    """
    if not await send_to(ctx.bot, partner_id, texts.MATCHED.format(nick="Аноним"), None, ctx.pack):
        return False
    await send_to(ctx.bot, user_id, texts.MATCHED.format(nick=texts.esc(ctx.nick)), None, ctx.pack)
    return True


async def announce_pairs(
    bot: Bot, cfg: Config, mm: Matchmaker, pairs: list[tuple[int, int]], pack: EmojiPack | None = None
) -> int:
    """Разослать «собеседник найден» тем, кого свёл sweep() после смены настроек."""
    kb = menu_keyboard()
    made = 0
    for a, b in pairs:
        if not await send_to(bot, b, texts.MATCHED.format(nick="Аноним"), None, pack):
            mm.forget(b)
            await send_to(bot, a, texts.PARTNER_LEFT, kb, pack)
            continue
        await send_to(bot, a, texts.MATCHED.format(nick="Аноним"), None, pack)
        made += 1
    return made


async def break_pair(
    bot: Bot, cfg: Config, mm: Matchmaker, user_id: int, note: str, pack: EmojiPack | None = None
) -> None:
    kb = menu_keyboard()
    partner, _ = mm.release(user_id)
    if partner is None:
        return
    await send_to(bot, partner, note, kb, pack)
    await send_to(bot, user_id, note, kb, pack)


async def _end_dialog(ctx: Ctx, ended_by: int, note: str, notify_partner: str) -> None:
    partner, summary = ctx.mm.release(ctx.user_id)
    if partner is None:
        await ctx.reply(texts.NO_DIALOG, markup=menu_keyboard())
        return

    counts: dict[int, int] = summary.get("counts", {}) or {}
    mine = int(counts.get(ctx.user_id, 0))
    theirs = int(counts.get(partner, 0))
    started = int(summary.get("started_at", time.time()))

    match_id = await ctx.db.log_dialog(ctx.user_id, partner, mine, theirs, started, ended_by)
    cap = ctx.cfg.xp_message_cap
    live = mine > 0 and theirs > 0 and (mine + theirs) >= 6
    my_xp = min(mine, cap) * ctx.cfg.xp_per_message + (ctx.cfg.xp_per_dialog if live else 0)
    for uid, sent in ((ctx.user_id, mine), (partner, theirs)):
        gain = min(sent, cap) * ctx.cfg.xp_per_message + (ctx.cfg.xp_per_dialog if live else 0)
        if gain:
            await ctx.db.award_xp(uid, gain)
        if sent:
            await ctx.db.bump(uid, "messages", sent)

    ctx.mm.remember_rating([ctx.user_id, partner], match_id)

    await send_to(ctx.bot, partner, notify_partner, menu_keyboard(), ctx.pack)
    await ctx.reply(note + texts.XP_EARNED.format(xp=my_xp), markup=rating_keyboard())
    await send_to(ctx.bot, partner, texts.RATING_ASK, rating_keyboard(), ctx.pack)


async def act_connect(ctx: Ctx) -> None:
    if await ctx.restricted():
        return
    await ctx.ensure_nick()
    status = ctx.mm.status(ctx.user_id)
    if status == "paired":
        await ctx.reply(texts.ALREADY_PAIRED, markup=menu_keyboard("paired"))
        return
    if status == "queued":
        await ctx.reply(
            texts.QUEUED.format(city=texts.esc(ctx.cfg.city), pos=ctx.mm.position(ctx.user_id) or 1,
                                size=ctx.mm.queue_size()),
            markup=menu_keyboard("queued", ctx.mm.queue_size()),
        )
        return

    prefs = ctx.prefs
    for _ in range(8):
        outcome, payload = ctx.mm.connect(ctx.user_id, **prefs)
        if outcome == "paired":
            if await announce_pair(ctx, ctx.user_id, payload):
                await ctx.ack("Собеседник найден")
                return
            ctx.mm.forget(payload)
            continue
        if outcome == "queued":
            await ctx.reply(
                texts.QUEUED.format(city=texts.esc(ctx.cfg.city), pos=payload or 1,
                                    size=ctx.mm.queue_size()),
                markup=menu_keyboard("queued", ctx.mm.queue_size()),
            )
            await ctx.ack("Ты в очереди")
            return
        await ctx.reply(
            texts.QUEUE_FULL.format(limit=ctx.cfg.queue_soft_limit),
            markup=menu_keyboard(),
        )
        return
    await ctx.reply("Не успел никого подобрать — попробуй ещё раз.",
                    markup=menu_keyboard())


async def act_next(ctx: Ctx) -> None:
    if await ctx.restricted():
        return
    if ctx.mm.status(ctx.user_id) != "paired":
        await act_connect(ctx)
        return
    await _end_dialog(ctx, ended_by=ctx.user_id, note="Пропустил.", notify_partner=texts.PARTNER_SKIPPED)
    await act_connect(ctx)


async def act_stop(ctx: Ctx) -> None:
    if ctx.mm.status(ctx.user_id) != "paired":
        ctx.mm.forget(ctx.user_id)
        await ctx.reply(texts.NO_DIALOG, markup=menu_keyboard())
        return
    await _end_dialog(ctx, ended_by=ctx.user_id, note=texts.DIALOG_STOPPED, notify_partner=texts.PARTNER_LEFT)


async def apply_rating(ctx: Ctx, positive: bool) -> None:
    entry = ctx.mm.pop_rating(ctx.user_id)
    if entry is None:
        await ctx.ack(texts.RATING_STALE, alert=True)
        return
    match_id, partner = entry
    await ctx.db.rate_dialog(match_id, ctx.user_id, 1 if positive else 0)
    if positive:
        await ctx.db.award_xp(partner, ctx.cfg.xp_good_rating)
        await send_to(ctx.bot, partner, texts.RATING_DONE_GOOD.format(xp=ctx.cfg.xp_good_rating),
                      None, ctx.pack)
        await ctx.ack("Спасибо")
    else:
        await send_to(ctx.bot, partner, texts.RATING_DONE_BAD, None, ctx.pack)
        await ctx.ack("Записал")
    await ctx.reply(
        "Готово.", markup=menu_keyboard(ctx.mm.status(ctx.user_id))
    )


async def forget_everything(ctx: Ctx) -> None:
    ctx.mm.forget(ctx.user_id)
    await ctx.db.forget_user(ctx.user_id)
    await ctx.reply(
        texts.FORGET_DONE, markup=menu_keyboard()
    )
