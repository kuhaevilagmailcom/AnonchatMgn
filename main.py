"""Точка входа: python main.py (нужен BOT_TOKEN в .env или в окружении).

Здесь только сборка приложения: конфиг → база → матчмейкер → бот → диспетчер →
мидлвары → роутеры → регистрация команд → polling. Вся логика разговора — в пакете `anonchat`.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from anonchat.commands import ADMIN_COMMANDS, COMMANDS, register_common
from anonchat.config import Config
from anonchat.db import Database
from anonchat.handlers import get_routers
from anonchat.matching import Matchmaker
from anonchat.middlewares import DataContext, Throttling
from anonchat.pack import EmojiPack

log = logging.getLogger("anonchat")

__all__ = [
    "COMMANDS",
    "ADMIN_COMMANDS",
    "build",
    "janitor",
    "register_commands",
    "main",
]


async def janitor(mm: Matchmaker) -> None:
    """Раз в пару минут подчищаем протухшие приглашения оценить диалог."""
    while True:
        try:
            await asyncio.sleep(120)
            mm.drop_stale_ratings()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("janitor: что-то пошло не так, продолжаем")


def build(cfg: Config) -> tuple[Bot, Dispatcher, Database, Matchmaker, EmojiPack]:
    """Собираем всё приложение одной функцией — удобно для тестов и вебхук-режима."""
    db = Database(cfg.db_path)
    mm = Matchmaker(queue_limit=cfg.queue_soft_limit)
    pack = EmojiPack(cfg.emoji_pack_url)
    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(Throttling(cfg))
        observer.middleware(DataContext(cfg, db, mm, pack))
    dp.pre_checkout_query.middleware(DataContext(cfg, db, mm, pack))

    for router in get_routers():
        dp.include_router(router)

    @dp.error()
    async def on_error(event: ErrorEvent) -> None:  # pragma: no cover
        log.exception("Необработанная ошибка: %s", event.exception)

    return bot, dp, db, mm, pack


async def register_commands(bot: Bot, cfg: Config) -> None:
    """Общее меню — всем; модерационные команды только админам (и донастраиваются при /start)."""
    await register_common(bot, cfg)


async def main() -> None:  # pragma: no cover
    import sys

    token_arg = sys.argv[1] if len(sys.argv) > 1 else None
    cfg = Config.from_env(token_arg=token_arg)
    logging.basicConfig(
        level=logging.DEBUG if cfg.debug else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )

    bot, dp, database, mm, pack = build(cfg)
    await database.start()
    await database.cleanup_report_context(cfg.report_context_retention_days)

    janitor_task: asyncio.Task | None = None

    @dp.startup()
    async def on_startup(bot: Bot) -> None:
        nonlocal janitor_task
        try:
            await bot.delete_webhook(drop_pending_updates=cfg.drop_pending_updates)
        except TelegramAPIError as exc:
            log.warning("delete_webhook не сработал: %s", exc)
        await register_commands(bot, cfg)
        me = await bot.get_me()
        log.info("Анонимный чат %s запущен: @%s (id=%s)", cfg.city_short, me.username, me.id)
        if cfg.admin_ids:
            log.info("модераторы: %s · панель — командой /admin", cfg.admin_markup())
        else:
            log.warning("Администраторы не настроены.")
        janitor_task = asyncio.create_task(janitor(mm))

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        if janitor_task is not None:
            janitor_task.cancel()
        await dp.storage.close()
        await bot.session.close()
        await database.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger("anonchat").info("Остановили — пока из МГН!")
