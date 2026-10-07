"""Неблокирующая доставка копий чатов администраторам."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict, deque
from typing import Any

from aiogram.exceptions import TelegramAPIError
from aiogram.types import ReplyParameters

from . import texts
from .actions import DeliveryResult, send_copy_to_message, send_to

log = logging.getLogger("anonchat.monitoring")

_CACHE_UNTIL = 0.0
_CACHE_IDS: tuple[int, ...] = ()
_ANON_CACHE_UNTIL = 0.0
_ANON_CACHE_IDS: tuple[int, ...] = ()
_PENDING: set[asyncio.Task] = set()
_SEMAPHORE = asyncio.Semaphore(4)
_MAX_PENDING = 100

# Антиспам: ловим очевидные повторы и слишком быстрые серии сообщений.
# Состояние только оперативное — после рестарта начинается с чистого листа.
_SPAM_WINDOW_SECONDS = 12.0
_SPAM_REPEAT_SECONDS = 20.0
_SPAM_REPEAT_COUNT = 3
_SPAM_BURST_COUNT = 8
_SPAM_ALERT_COOLDOWN = 60.0
_SPAM_EVENTS: dict[int, deque[tuple[float, str, str]]] = defaultdict(
    lambda: deque(maxlen=16)
)
_SPAM_ALERT_UNTIL: dict[int, float] = {}
_SPACE_RE = re.compile(r"\s+")


def invalidate_monitor_cache() -> None:
    global _CACHE_UNTIL, _CACHE_IDS, _ANON_CACHE_UNTIL, _ANON_CACHE_IDS
    _CACHE_UNTIL = 0.0
    _CACHE_IDS = ()
    _ANON_CACHE_UNTIL = 0.0
    _ANON_CACHE_IDS = ()


async def _monitor_ids(db, owner_ids: tuple[int, ...]) -> tuple[int, ...]:
    global _CACHE_UNTIL, _CACHE_IDS
    now_mono = time.monotonic()
    if now_mono < _CACHE_UNTIL:
        return _CACHE_IDS
    candidates = await db.admin_ids_with_permission("monitor", owner_ids)
    enabled: list[int] = []
    for admin_id in candidates:
        if await db.get_kv(f"chat_monitor:{admin_id}") == "1":
            enabled.append(int(admin_id))
    _CACHE_IDS = tuple(enabled)
    _CACHE_UNTIL = now_mono + 15
    return _CACHE_IDS

async def _anonymous_monitor_ids(db, owner_ids: tuple[int, ...]) -> tuple[int, ...]:
    global _ANON_CACHE_UNTIL, _ANON_CACHE_IDS
    now_mono = time.monotonic()
    if now_mono < _ANON_CACHE_UNTIL:
        return _ANON_CACHE_IDS
    candidates = await db.admin_ids_with_permission("monitor", owner_ids)
    enabled: list[int] = []
    for admin_id in candidates:
        if await db.get_kv(f"anonq_monitor:{admin_id}") == "1":
            enabled.append(int(admin_id))
    _ANON_CACHE_IDS = tuple(enabled)
    _ANON_CACHE_UNTIL = now_mono + 15
    return _ANON_CACHE_IDS


def _identity(row: Any, user_id: int) -> str:
    username = f"@{row['username']}" if row is not None and row["username"] else "без username"
    nickname = row["nickname"] if row is not None and row["nickname"] else f"Аноним-{user_id}"
    return f"{texts.esc(username)} · {texts.esc(nickname)} · <code>{int(user_id)}</code>"


def _message_preview(message) -> str:
    """Короткое описание сообщения для цитаты/антиспама."""
    raw = str(getattr(message, "text", "") or getattr(message, "caption", "") or "").strip()
    if raw:
        return _SPACE_RE.sub(" ", raw)[:320]
    if getattr(message, "photo", None):
        return "Фото"
    if getattr(message, "voice", None):
        return "Голосовое сообщение"
    if getattr(message, "video_note", None):
        return "Видеосообщение"
    if getattr(message, "video", None):
        return "Видео"
    if getattr(message, "animation", None):
        return "GIF"
    if getattr(message, "sticker", None):
        emoji = str(getattr(getattr(message, "sticker", None), "emoji", "") or "").strip()
        return f"Стикер {emoji}".strip()
    if getattr(message, "document", None):
        return "Файл"
    return "Сообщение"


def _normalize_spam_text(value: str) -> str:
    value = _SPACE_RE.sub(" ", str(value or "").strip().lower())
    # Для повторов игнорируем простую пунктуацию по краям.
    return value.strip(" .,!?:;—–-_…")


def _register_spam_message(
    user_id: int,
    preview: str,
    *,
    now_mono: float | None = None,
) -> tuple[str, list[str]] | None:
    """Регистрирует сообщение и возвращает (причина, последние цитаты) при спаме."""
    now_value = time.monotonic() if now_mono is None else float(now_mono)
    uid = int(user_id)
    normalized = _normalize_spam_text(preview)
    events = _SPAM_EVENTS[uid]
    events.append((now_value, normalized, str(preview or "")[:320]))

    # Чистим старое, но оставляем окно для повторяющихся сообщений чуть длиннее.
    cutoff = now_value - _SPAM_REPEAT_SECONDS
    while events and events[0][0] < cutoff:
        events.popleft()

    if now_value < _SPAM_ALERT_UNTIL.get(uid, 0.0):
        return None

    repeat_count = 0
    if len(normalized) >= 2:
        repeat_count = sum(
            1
            for ts, fingerprint, _ in events
            if ts >= now_value - _SPAM_REPEAT_SECONDS and fingerprint == normalized
        )

    burst_count = sum(
        1 for ts, _, _ in events if ts >= now_value - _SPAM_WINDOW_SECONDS
    )

    reason = ""
    if repeat_count >= _SPAM_REPEAT_COUNT:
        reason = f"повтор одного сообщения ×{repeat_count}"
    elif burst_count >= _SPAM_BURST_COUNT:
        reason = f"слишком частые сообщения · {burst_count} за {int(_SPAM_WINDOW_SECONDS)} сек"

    if not reason:
        return None

    _SPAM_ALERT_UNTIL[uid] = now_value + _SPAM_ALERT_COOLDOWN
    samples = [
        sample
        for ts, _, sample in events
        if ts >= now_value - _SPAM_REPEAT_SECONDS and sample
    ][-4:]
    return reason, samples


def _chat_header(pack, sender: Any, sender_id: int, partner: Any, partner_id: int) -> str:
    chat_icon = pack.admin_icon("chat") if pack is not None else "💬"
    user_icon = pack.admin_icon("user") if pack is not None else "👤"
    return (
        f"{chat_icon} <b>Активный чат</b>\n\n"
        f"{user_icon} <b>От:</b> {_identity(sender, sender_id)}\n"
        f"<b>Кому:</b> {_identity(partner, partner_id)}"
    )


async def _spam_monitor_ids(db, owner_ids: tuple[int, ...]) -> tuple[int, ...]:
    """Антиспам приходит модераторам с правом monitor даже без live-monitor toggle."""
    candidates = await db.admin_ids_with_permission("monitor", owner_ids)
    return tuple(int(admin_id) for admin_id in candidates)


async def _notify_spam(
    message,
    bot,
    db,
    cfg,
    pack,
    sender_id: int,
    partner_id: int,
) -> None:
    preview = _message_preview(message)
    detected = _register_spam_message(sender_id, preview)
    if detected is None:
        return

    ids = await _spam_monitor_ids(db, cfg.admin_ids)
    # Участнику чата не раскрываем служебные ID/username другого участника,
    # даже если сам участник является модератором.
    ids = tuple(
        admin_id
        for admin_id in ids
        if admin_id not in {int(sender_id), int(partner_id)}
    )
    if not ids:
        return

    reason, samples = detected
    sender = await db.get_user(int(sender_id))
    partner = await db.get_user(int(partner_id))
    spam_icon = pack.admin_icon("spam") if pack is not None else "🚨"
    user_icon = pack.admin_icon("user") if pack is not None else "👤"
    repeat_icon = pack.admin_icon("repeat") if pack is not None else "🔁"

    quotes = "\n".join(
        f"<blockquote>{texts.esc(sample)}</blockquote>" for sample in samples
    )
    body = (
        f"{spam_icon} <b>Похоже на спам</b>\n\n"
        f"{user_icon} <b>От:</b> {_identity(sender, int(sender_id))}\n"
        f"<b>Собеседник:</b> {_identity(partner, int(partner_id))}\n"
        f"{repeat_icon} <b>Причина:</b> {texts.esc(reason)}"
    )
    if quotes:
        body += f"\n\n<b>Последние сообщения</b>\n{quotes}"

    for admin_id in ids:
        await send_to(bot, admin_id, body, None, pack)


async def _deliver(message, bot, pack, monitor_ids: tuple[int, ...], header: str) -> None:
    async with _SEMAPHORE:
        preview = _message_preview(message)
        quoted = f"<blockquote>{texts.esc(preview)}</blockquote>"
        for admin_id in monitor_ids:
            if message.text:
                await send_to(
                    bot, admin_id, f"{header}\n\n{quoted}", None, pack
                )
            else:
                result, sent = await send_copy_to_message(bot, message, admin_id)
                notice = f"{header}\n\n{quoted}"
                if result is DeliveryResult.DELIVERED and sent is not None:
                    try:
                        await bot.send_message(
                            admin_id,
                            pack.wrap(notice) if pack is not None else notice,
                            reply_parameters=ReplyParameters(message_id=sent.message_id),
                        )
                    except TelegramAPIError:
                        await send_to(bot, admin_id, notice, None, pack)
                elif result is DeliveryResult.DELIVERED:
                    await send_to(bot, admin_id, notice, None, pack)


async def enqueue_chat_monitor(message, ctx, partner_id: int) -> None:
    """Ставит monitor-copy в ограниченный фон, не тормозя основной диалог."""
    await _notify_spam(
        message, ctx.bot, ctx.db, ctx.cfg, ctx.pack, ctx.user_id, int(partner_id)
    )
    ids = await _monitor_ids(ctx.db, ctx.cfg.admin_ids)
    # Участнику диалога не шлём служебную monitor-копию с ID/username:
    # он и так получает обычное анонимное сообщение. Наблюдающие админы видят обе стороны.
    ids = tuple(
        admin_id
        for admin_id in ids
        if admin_id not in {int(ctx.user_id), int(partner_id)}
    )
    if not ids:
        return
    if len(_PENDING) >= _MAX_PENDING:
        log.warning("monitor queue full: delivering chat copy inline user_id=%s", ctx.user_id)
        sender = ctx.me or await ctx.db.get_user(ctx.user_id)
        partner = await ctx.db.get_user(int(partner_id))
        header = _chat_header(
            ctx.pack, sender, ctx.user_id, partner, int(partner_id)
        )
        await _deliver(message, ctx.bot, ctx.pack, ids, header)
        return

    sender = ctx.me or await ctx.db.get_user(ctx.user_id)
    partner = await ctx.db.get_user(int(partner_id))
    header = _chat_header(
        ctx.pack, sender, ctx.user_id, partner, int(partner_id)
    )
    task = asyncio.create_task(_deliver(message, ctx.bot, ctx.pack, ids, header))
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)
    # Отдаём задаче один такт event loop, но не ждём Telegram API.
    await asyncio.sleep(0)


async def enqueue_chat_monitor_sent(
    message,
    bot,
    db,
    cfg,
    pack,
    sender_id: int,
    partner_id: int,
) -> None:
    """Мониторинг сообщений, отправленных через Mini App.

    Mini App шлёт сообщение напрямую через Bot API, поэтому обычный
    message-handler Telegram здесь не вызывается. Используем уже созданное
    Telegram Message и тот же формат мониторинга, что у обычного чата.
    """
    await _notify_spam(
        message, bot, db, cfg, pack, int(sender_id), int(partner_id)
    )
    ids = await _monitor_ids(db, cfg.admin_ids)
    ids = tuple(
        admin_id
        for admin_id in ids
        if admin_id not in {int(sender_id), int(partner_id)}
    )
    if not ids:
        return

    sender = await db.get_user(int(sender_id))
    partner = await db.get_user(int(partner_id))
    header = _chat_header(
        pack, sender, int(sender_id), partner, int(partner_id)
    )

    if len(_PENDING) >= _MAX_PENDING:
        log.warning(
            "monitor queue full: delivering Mini App copy inline user_id=%s",
            sender_id,
        )
        await _deliver(message, bot, pack, ids, header)
        return

    task = asyncio.create_task(_deliver(message, bot, pack, ids, header))
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)
    await asyncio.sleep(0)


def pending_count() -> int:
    return len(_PENDING)


async def enqueue_anonymous_monitor(
    message,
    ctx,
    target_id: int,
    *,
    kind: str = "question",
) -> None:
    """Копирует анонимные вопросы/ответы только модераторам с включённым мониторингом."""
    ids = await _anonymous_monitor_ids(ctx.db, ctx.cfg.admin_ids)
    # Для анонимных вопросов модератор получает копию даже если сам является
    # отправителем или получателем — иначе тест собственной ссылки выглядит
    # так, будто мониторинг не работает.
    if not ids:
        return
    if len(_PENDING) >= _MAX_PENDING:
        log.warning("monitor queue full: delivering anonymous copy inline user_id=%s", ctx.user_id)
        sender = ctx.me or await ctx.db.get_user(ctx.user_id)
        recipient = await ctx.db.get_user(int(target_id))
        title = "💌 <b>Анонимный вопрос</b>" if kind == "question" else "↩️ <b>Ответ на анонимный вопрос</b>"
        header = (
            f"{title}\n"
            f"От: {_identity(sender, ctx.user_id)}\n"
            f"Кому: {_identity(recipient, int(target_id))}"
        )
        await _deliver(message, ctx.bot, ctx.pack, ids, header)
        return

    sender = ctx.me or await ctx.db.get_user(ctx.user_id)
    recipient = await ctx.db.get_user(int(target_id))
    title = "💌 <b>Анонимный вопрос</b>" if kind == "question" else "↩️ <b>Ответ на анонимный вопрос</b>"
    header = (
        f"{title}\n"
        f"От: {_identity(sender, ctx.user_id)}\n"
        f"Кому: {_identity(recipient, int(target_id))}"
    )
    task = asyncio.create_task(_deliver(message, ctx.bot, ctx.pack, ids, header))
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)
    await asyncio.sleep(0)
