"""Мидлвари: доступ к БД в каждом хендлере + защита от флуда."""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

from .actions import Ctx
from .config import Config
from .db import Database
from .pack import EmojiPack


def event_user(event: TelegramObject) -> User | None:
    """Достаём пользователя из любого апдейта, не полагаясь на UserContextMiddleware."""
    if isinstance(event, Message):
        return event.from_user
    if isinstance(event, CallbackQuery):
        return event.from_user
    getter = getattr(event, "from_user", None)
    return getter if isinstance(getter, User) else None


class DataContext(BaseMiddleware):
    """Плюсует cfg/db/matchmaker в data и собирает готовый Ctx для хендлеров."""

    def __init__(self, config: Config, db: Database, matchmaker, pack=None) -> None:
        self.config = config
        self.db = db
        self.mm = matchmaker
        self.pack = pack or EmojiPack(config.emoji_pack_url)

    async def __call__(self, handler, event: TelegramObject, data: dict):
        data["cfg"] = self.config
        data["db"] = self.db
        data["mm"] = self.mm
        data["pack"] = self.pack
        data["is_admin"] = False
        data["is_new_user"] = False
        data["ctx"] = None
        data["me"] = None

        user = data.get("event_from_user") or event_user(event)
        me: Any = None
        if user is not None and not user.is_bot:
            me = await self.db.get_user(user.id)
            if me is None:
                data["is_new_user"] = True
                me = await self.db.ensure_user(user.id, user.username, user.first_name)
            elif me["last_seen"] < int(time.time()) - 60:
                await self.db.touch(user.id)
            data["is_admin"] = user.id in self.config.admin_ids
        data["me"] = me

        if isinstance(event, (Message, CallbackQuery)) and user is not None:
            data["ctx"] = Ctx(
                bot=data["bot"],
                db=self.db,
                mm=self.mm,
                cfg=self.config,
                pack=self.pack,
                event=event,
                user_id=user.id,
                me=me,
            )
        return await handler(event, data)


class Throttling(BaseMiddleware):
    """Скользящее окно: не больше `limit` апдейтов в минуту на пользователя."""

    def __init__(self, config: Config | None = None, limit: int = 40, window: float = 60.0) -> None:
        self.config = config
        self.limit = max(5, limit)
        self.window = window
        self._hits: dict[int, deque[float]] = {}

    async def __call__(self, handler, event: TelegramObject, data: dict):
        cfg = self.config or data.get("cfg")
        user = event_user(event)
        if user is None or user.is_bot or (cfg and user.id in cfg.admin_ids):
            return await handler(event, data)

        bucket = self._hits.setdefault(user.id, deque())
        ts = time.monotonic()
        while bucket and ts - bucket[0] > self.window:
            bucket.popleft()

        if len(bucket) >= self.limit:
            if isinstance(event, CallbackQuery):
                await event.answer("Слишком быстро — подожди секунду.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("Попридержи коней: слишком много сообщений в минуту.")
            return

        bucket.append(ts)
        if len(self._hits) > 5000:  # самочищаемся, чтобы не расти бесконечно
            cutoff = ts - self.window
            for uid in [u for u, b in self._hits.items() if not b or b[-1] < cutoff]:
                self._hits.pop(uid, None)
        return await handler(event, data)
