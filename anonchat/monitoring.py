"""Неблокирующая доставка копий чатов администраторам."""
from __future__ import annotations

import asyncio
import logging
import time
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


async def _deliver(message, bot, pack, monitor_ids: tuple[int, ...], header: str) -> None:
    async with _SEMAPHORE:
        for admin_id in monitor_ids:
            if message.text:
                await send_to(
                    bot, admin_id, f"{header}\n\n{texts.esc(message.text)}", None, pack
                )
            else:
                result, sent = await send_copy_to_message(bot, message, admin_id)
                if result is DeliveryResult.DELIVERED:
                    if sent is not None:
                        try:
                            await bot.send_message(
                                admin_id,
                                header,
                                reply_parameters=ReplyParameters(message_id=sent.message_id),
                            )
                        except TelegramAPIError:
                            await send_to(bot, admin_id, header, None, pack)
                    else:
                        await send_to(bot, admin_id, header, None, pack)


async def enqueue_chat_monitor(message, ctx, partner_id: int) -> None:
    """Ставит monitor-copy в ограниченный фон, не тормозя основной диалог."""
    ids = await _monitor_ids(ctx.db, ctx.cfg.admin_ids)
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
        header = (
            "👁 <b>Сообщение в активном чате</b>\n"
            f"От: {_identity(sender, ctx.user_id)}\n"
            f"Собеседник: {_identity(partner, int(partner_id))}"
        )
        await _deliver(message, ctx.bot, ctx.pack, ids, header)
        return

    sender = ctx.me or await ctx.db.get_user(ctx.user_id)
    partner = await ctx.db.get_user(int(partner_id))
    header = (
        "👁 <b>Сообщение в активном чате</b>\n"
        f"От: {_identity(sender, ctx.user_id)}\n"
        f"Собеседник: {_identity(partner, int(partner_id))}"
    )
    task = asyncio.create_task(_deliver(message, ctx.bot, ctx.pack, ids, header))
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)
    # Отдаём задаче один такт event loop, но не ждём Telegram API.
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
