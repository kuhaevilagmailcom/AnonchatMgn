"""Действия бота: поиск пары, следующий, стоп, профиль, ник, настройки-экраны.

Хендлеры только разбирают апдейт и вызывают отсюда нужное действие — кнопка
«🔎 Поиск собеседника» и команда /connect делают буквально одно и то же.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from . import nick as nicklib
from . import texts
from .config import Config
from .db import Database
from .keyboards import (
    back_menu_keyboard, chat_keyboard, menu_keyboard,
    profile_keyboard, rating_keyboard,
)
from .levels import rank_for
from .matching import Matchmaker
from .pack import EmojiPack

ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "menu"


class DeliveryResult(Enum):
    DELIVERED = "delivered"
    TEMP_ERROR = "temp_error"
    UNAVAILABLE = "unavailable"


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
    admin_permissions: frozenset[str] = frozenset()

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
        message = self.event.message
        has_media = bool(getattr(message, "photo", None))
        for attempt in range(2):
            body = self.pack.wrap(text) if attempt == 0 else self.pack.strip(text)
            try:
                if has_media:
                    await message.edit_caption(caption=body, reply_markup=markup)
                else:
                    await message.edit_text(text=body, reply_markup=markup)
                return True
            except TelegramBadRequest as exc:
                if attempt == 0 and self.pack.accept(exc):
                    continue
                return False
            except TelegramAPIError:
                return False
        return False

    async def render_screen(
        self, image: str, caption: str, markup: InlineKeyboardMarkup | None = None
    ) -> Message | None:
        """Меняет картинку, подпись и клавиатуру одним экраном; при ошибке отправляет новый."""
        target = self.event.message if isinstance(self.event, CallbackQuery) else self.event
        if target is None:
            return None
        path = ASSET_DIR / image
        if not path.exists():
            if await self.edit(caption, markup):
                return target
            return await self.reply(caption, markup)

        key = f"menu_file_id:{image}"
        cached = await self.db.get_kv(key)
        sources: list[str | FSInputFile] = ([cached] if cached else []) + [FSInputFile(path)]
        for source in sources:
            for wrapped in (True, False):
                body = self.pack.wrap(caption) if wrapped else self.pack.strip(caption)
                try:
                    if isinstance(self.event, CallbackQuery) and getattr(target, "photo", None):
                        result = await target.edit_media(
                            InputMediaPhoto(media=source, caption=body), reply_markup=markup
                        )
                    else:
                        result = await target.answer_photo(source, caption=body, reply_markup=markup)
                    if isinstance(result, Message) and result.photo:
                        await self.db.set_kv(key, result.photo[-1].file_id)
                    return result if isinstance(result, Message) else target
                except TelegramBadRequest as exc:
                    if wrapped and self.pack.accept(exc):
                        continue
                    break
                except TelegramAPIError:
                    break
            if isinstance(source, str):
                await self.db.delete_kv(key)
        return await self.reply(caption, markup)

    async def screen(
        self, image: str, caption: str, markup: InlineKeyboardMarkup | None = None
    ) -> Message | None:
        return await self.render_screen(image, caption, markup)

    # ------------------------------------------------------------------ профиль
    @property
    def is_admin(self) -> bool:
        return self.user_id in self.cfg.admin_ids or bool(self.admin_permissions)

    @property
    def is_owner(self) -> bool:
        return self.user_id in self.cfg.admin_ids

    def can(self, permission: str) -> bool:
        return self.is_owner or permission in self.admin_permissions

    @property
    def nick(self) -> str:
        return nicklib.display(
            self.me["nickname"] if self.me else "",
            self.user_id,
            self.me["support_stars"] if self.me else 0,
        )

    @property
    def prefs(self) -> dict[str, Any]:
        me = self.me
        return {
            "district": (me["district"] if me else "") or "",
            "same_district": bool(me["same_district"]) if me else False,
        }

    async def ensure_nick(self) -> str:
        """Авто-ник при первом же контакте — чтобы нигде не светилось настоящее имя."""
        if self.me is None:
            return self.nick
        if not (self.me["nickname"] or "").strip():
            auto = nicklib.auto_nick(self.user_id)
            for salt in range(32):
                candidate = nicklib.auto_nick(self.user_id + salt * 1_000_003)
                if not await self.db.nickname_taken(candidate, except_user_id=self.user_id):
                    auto = candidate
                    break
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

    async def dialog_locked(self) -> bool:
        """Пока идёт диалог, свои экраны (профиль, настройки, топ, ник) закрыты.

        Иначе человек посреди переписки уходит смотреть статистику, а собеседник
        остаётся с молчаливым «печатает…». Сначала /stop.
        """
        if self.mm.status(self.user_id) == "paired":
            await self.reply(texts.DIALOG_LOCKED)
            return True
        return False


# --------------------------------------------------------------------- low-level
async def _send_text(
    target: Message, text: str, markup: InlineKeyboardMarkup | None, pack: EmojiPack, **kw: Any
) -> Message | None:
    for attempt in range(3):
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
) -> DeliveryResult:
    if not chat_id:
        return DeliveryResult.UNAVAILABLE
    for attempt in range(2):
        body = pack.wrap(text) if (pack and attempt == 0) else text
        try:
            await bot.send_message(chat_id, body, reply_markup=markup)
            return DeliveryResult.DELIVERED
        except TelegramBadRequest as exc:
            if attempt == 0 and pack is not None and pack.accept(exc):
                continue
            message = str(exc).lower()
            return DeliveryResult.UNAVAILABLE if "chat not found" in message else DeliveryResult.TEMP_ERROR
        except TelegramRetryAfter as exc:
            await asyncio.sleep(max(0.0, float(exc.retry_after)))
            continue
        except TelegramForbiddenError:
            return DeliveryResult.UNAVAILABLE
        except TelegramAPIError:
            return DeliveryResult.TEMP_ERROR
    return DeliveryResult.TEMP_ERROR


async def send_copy_to(
    bot: Bot, message: Message, chat_id: int, text_override: str | None = None
) -> DeliveryResult:
    try:
        await bot.send_chat_action(chat_id, "typing")
    except TelegramAPIError:
        pass
    for _ in range(3):
        try:
            if text_override is not None and message.text is not None:
                await bot.send_message(chat_id, text_override, parse_mode=None)
            elif text_override is not None and message.caption is not None:
                await message.copy_to(chat_id=chat_id, caption=text_override, parse_mode=None)
            else:
                await message.send_copy(chat_id=chat_id)
            return DeliveryResult.DELIVERED
        except TelegramRetryAfter as exc:
            await asyncio.sleep(max(0.0, float(exc.retry_after)))
        except TelegramForbiddenError:
            return DeliveryResult.UNAVAILABLE
        except TelegramBadRequest as exc:
            return DeliveryResult.UNAVAILABLE if "chat not found" in str(exc).lower() else DeliveryResult.TEMP_ERROR
        except TelegramAPIError:
            return DeliveryResult.TEMP_ERROR
    return DeliveryResult.TEMP_ERROR


async def send_screen_to(
    bot: Bot, chat_id: int, image: str, caption: str,
    markup: InlineKeyboardMarkup | None = None, pack: EmojiPack | None = None,
    db: Database | None = None,
) -> DeliveryResult:
    path = ASSET_DIR / image
    if not path.exists():
        return await send_to(bot, chat_id, caption, markup, pack)
    key = f"menu_file_id:{image}"
    cached = await db.get_kv(key) if db else ""
    photo: str | FSInputFile = cached or FSInputFile(path)
    for attempt in range(2):
        body = pack.wrap(caption) if pack and attempt == 0 else (pack.strip(caption) if pack else caption)
        try:
            sent = await bot.send_photo(chat_id, photo, caption=body, reply_markup=markup)
            if db and sent.photo:
                await db.set_kv(key, sent.photo[-1].file_id)
            return DeliveryResult.DELIVERED
        except TelegramBadRequest as exc:
            if attempt == 0 and pack is not None and pack.accept(exc):
                continue
            if cached:
                await db.delete_kv(key)
                cached = ""
                photo = FSInputFile(path)
                continue
            message = str(exc).lower()
            return DeliveryResult.UNAVAILABLE if "chat not found" in message else DeliveryResult.TEMP_ERROR
        except TelegramRetryAfter as exc:
            await asyncio.sleep(max(0.0, float(exc.retry_after)))
        except TelegramForbiddenError:
            return DeliveryResult.UNAVAILABLE
        except TelegramAPIError:
            return DeliveryResult.TEMP_ERROR
    return DeliveryResult.TEMP_ERROR


# --------------------------------------------------------------------- экраны
async def show_menu(ctx: Ctx) -> None:
    status = ctx.mm.status(ctx.user_id)
    state = {
        "paired": texts.STATUS_PAIRED,
        "queued": texts.STATUS_QUEUED,
    }.get(status, texts.STATUS_FREE)

    body = (
        f"<b>{texts.esc(ctx.nick)}</b>\n\n"
        f"{state}\n\n"
        f"🟢 Сейчас ищут: <b>{ctx.mm.queue_size()}</b>"
    )
    kb = menu_keyboard(status, ctx.mm.queue_size(), admin=ctx.is_admin)
    image = {"paired": "03_found.png", "queued": "02_search.png"}.get(status, "01_main_menu.png")
    await ctx.render_screen(image, body, kb)


async def show_welcome(ctx: Ctx) -> None:
    await ctx.ensure_nick()
    await show_menu(ctx)


async def show_help(ctx: Ctx) -> None:
    await ctx.reply(
        texts.HELP,
        markup=menu_keyboard(ctx.mm.status(ctx.user_id)),
    )


async def show_rules(ctx: Ctx) -> None:
    await ctx.render_screen("06_rules.png", texts.RULES, back_menu_keyboard())


async def show_top(ctx: Ctx) -> None:
    if await ctx.dialog_locked():
        return
    rows = await ctx.db.top(10)
    if not rows:
        await ctx.reply("🏆 Топ пуст — начни общаться первым.", markup=menu_keyboard())
        return
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [f"🏆 <b>Топ · {texts.esc(ctx.cfg.city)}</b>", ""]
    for i, row in enumerate(rows, start=1):
        # медали только за места: ранг подписываем словом, иначе 🥇/🥈 слипаются с 🥇 Серебро
        place = medals.get(i, f"<code>{i}</code>")
        lines.append(
            f"{place} <b>{texts.esc(nicklib.display(row['nickname'], int(row['user_id']), row['support_stars']))}</b>"
            f" · <b>{int(row['xp'])} ⭐</b>"
        )
    lines += ["", "<i>Ники участники придумывают сами.</i>"]
    await ctx.render_screen("08_top.png", "\n".join(lines), back_menu_keyboard())


async def show_profile(ctx: Ctx) -> None:
    if await ctx.dialog_locked():
        return
    if ctx.me is None:
        await ctx.reply(texts.PROFILE_MISSING)
        return
    me = ctx.me
    invited, referral_xp = await ctx.db.referral_stats(ctx.user_id)
    messages = int(me["messages"])
    rank = rank_for(messages)
    lines = [
        f"<b>{texts.esc(ctx.nick)}</b>",
        f"{rank.emoji} {texts.esc(rank.title)}",
        "",
        f"Очки: <b>{int(me['xp'])} ⭐</b>",
        f"Приглашено пользователей: <b>{invited}</b>",
        f"Получено за приглашения: <b>{referral_xp} ⭐</b>",
        f"Диалогов: <b>{me['dialogs']}</b>",
        f"👍 {me['good_ratings']}   👎 {me['bad_ratings']}",
        f"Возраст: <b>{me['age']}</b>",
        f"Район: <b>{texts.esc(me['district']) if me['district'] else 'не указан'}</b>",
    ]
    if nicklib.is_supporter(me["support_stars"]):
        lines += ["", f"💎 Поддержал проект: {int(me['support_stars'])} ⭐"]
    bot = await ctx.bot.get_me()
    referral = f"https://t.me/{bot.username}?start=ref_{ctx.user_id}"
    await ctx.render_screen("04_profile.png", "\n".join(lines), profile_keyboard(referral))


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
def partner_card(row: Any, user_id: int) -> str:
    """Публичная карточка собеседника: только анонимный ник и очки."""
    if row is None:
        return f"🙂 <b>{texts.esc(nicklib.display('', user_id))}</b>"
    return texts.MATCHED_CARD.format(
        nick=texts.esc(nicklib.display(row["nickname"], user_id, row["support_stars"]))
    ) + f"\n⭐ <b>{int(row['xp'])}</b>"


def matched_text(card: str, you: str) -> str:
    return texts.MATCHED.format(card=card, you=texts.esc(you))


async def announce_pair(ctx: Ctx, user_id: int, partner_id: int) -> bool:
    """Сообщаем обоим о паре — без кнопок: в диалоге мешают, всё есть командами.

    Каждый видит карточку другого и свой собственный ник. Возвращает False, если
    собеседник недоступен (заблокировал бота).
    """
    partner_row = await ctx.db.get_user(partner_id)
    my_row = await ctx.db.get_user(user_id)
    partner_nick = nicklib.display(partner_row["nickname"], partner_id, partner_row["support_stars"]) if partner_row \
        else nicklib.display("", partner_id)
    my_nick = nicklib.display(my_row["nickname"], user_id, my_row["support_stars"]) if my_row else ctx.nick

    found_kb = chat_keyboard()
    result = await send_screen_to(
        ctx.bot, partner_id, "03_found.png",
        matched_text(partner_card(my_row, user_id), partner_nick), found_kb, ctx.pack, ctx.db
    )
    if result is DeliveryResult.UNAVAILABLE:
        return False
    await send_screen_to(ctx.bot, user_id, "03_found.png",
                         matched_text(partner_card(partner_row, partner_id), my_nick), found_kb, ctx.pack, ctx.db)
    return True


async def announce_pairs(
    bot: Bot,
    cfg: Config,
    mm: Matchmaker,
    pairs: list[tuple[int, int]],
    pack: EmojiPack | None = None,
    db: Database | None = None,
) -> int:
    """Разослать «собеседник найден» тем, кого свёл sweep() после смены настроек."""
    kb = menu_keyboard()
    made = 0
    for a, b in pairs:
        row_a = await db.get_user(a) if db else None
        row_b = await db.get_user(b) if db else None
        nick_a = nicklib.display(row_a["nickname"], a, row_a["support_stars"]) if row_a else nicklib.display("", a)
        nick_b = nicklib.display(row_b["nickname"], b, row_b["support_stars"]) if row_b else nicklib.display("", b)
        result = await send_screen_to(
            bot, b, "03_found.png", matched_text(partner_card(row_a, a), nick_b),
            chat_keyboard(), pack, db,
        )
        if result is DeliveryResult.UNAVAILABLE:
            mm.forget(b)
            await send_to(bot, a, texts.PARTNER_LEFT, kb, pack)
            continue
        await send_screen_to(
            bot, a, "03_found.png", matched_text(partner_card(row_b, b), nick_a),
            chat_keyboard(), pack, db,
        )
        made += 1
    return made


async def break_pair(
    bot: Bot, cfg: Config, mm: Matchmaker, user_id: int, note: str,
    pack: EmojiPack | None = None, db: Database | None = None,
) -> None:
    kb = menu_keyboard()
    partner, _ = mm.release(user_id)
    if partner is None:
        return
    if db is not None:
        await db.close_battles_for_users(user_id, partner)
    await send_to(bot, partner, note, kb, pack)
    await send_to(bot, user_id, note, kb, pack)


async def _end_dialog(ctx: Ctx, ended_by: int, note: str, notify_partner: str) -> None:
    partner, summary = ctx.mm.release(ctx.user_id)
    if partner is None:
        await ctx.reply(texts.NO_DIALOG, markup=menu_keyboard())
        return
    await ctx.db.close_battles_for_users(ctx.user_id, partner)

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
    await ctx.ack()
    if await ctx.restricted():
        return
    await ctx.ensure_nick()
    status = ctx.mm.status(ctx.user_id)
    if status == "paired":
        await ctx.reply(texts.ALREADY_PAIRED, markup=menu_keyboard("paired"))
        return
    if status == "queued":
        await ctx.render_screen(
            "02_search.png",
            texts.QUEUED.format(city=texts.esc(ctx.cfg.city), pos=ctx.mm.position(ctx.user_id) or 1,
                                size=ctx.mm.queue_size()),
            menu_keyboard("queued", ctx.mm.queue_size()),
        )
        return

    prefs = ctx.prefs
    prefs["excluded"] = await ctx.db.excluded_partners(ctx.user_id)
    for _ in range(8):
        outcome, payload = ctx.mm.connect(ctx.user_id, **prefs)
        if outcome == "paired":
            if await announce_pair(ctx, ctx.user_id, payload):
                return
            ctx.mm.forget(payload)
            continue
        if outcome == "queued":
            await ctx.render_screen(
                "02_search.png",
                texts.QUEUED.format(city=texts.esc(ctx.cfg.city), pos=payload or 1,
                                    size=ctx.mm.queue_size()),
                menu_keyboard("queued", ctx.mm.queue_size()),
            )
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
    if ctx.mm.status(ctx.user_id) == "queued":
        ctx.mm.forget(ctx.user_id)
        await ctx.ack("Поиск остановлен")
        await show_menu(ctx)
        return
    if ctx.mm.status(ctx.user_id) != "paired":
        await show_menu(ctx)
        return
    await _end_dialog(ctx, ended_by=ctx.user_id, note=texts.DIALOG_STOPPED, notify_partner=texts.PARTNER_LEFT)


async def apply_rating(ctx: Ctx, positive: bool) -> None:
    entry = ctx.mm.pending_rating(ctx.user_id)
    if entry is None:
        await ctx.ack(texts.RATING_STALE, alert=True)
        return
    match_id, partner = entry
    rated_partner = await ctx.db.rate_dialog(match_id, ctx.user_id, 1 if positive else 0)
    if rated_partner is None:
        await ctx.ack(texts.RATING_STALE, alert=True)
        return
    if positive:
        await ctx.db.award_xp(partner, ctx.cfg.xp_good_rating)
        await ctx.ack("Спасибо")
        result_text = texts.RATING_DONE_GOOD.format(xp=ctx.cfg.xp_good_rating)
    else:
        await ctx.ack("Записал")
        result_text = texts.RATING_DONE_BAD
    await ctx.reply(
        result_text, markup=menu_keyboard(ctx.mm.status(ctx.user_id))
    )


async def forget_everything(ctx: Ctx) -> None:
    partner = ctx.mm.partner(ctx.user_id)
    await ctx.db.close_battles_for_users(ctx.user_id, partner or 0)
    ctx.mm.forget(ctx.user_id)
    await ctx.db.forget_user(ctx.user_id)
    await ctx.reply(
        texts.FORGET_DONE, markup=menu_keyboard()
    )
