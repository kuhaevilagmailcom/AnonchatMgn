"""Точка входа: python run.py (нужен BOT_TOKEN в .env или в окружении)."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, ErrorEvent

from anonchat.config import Config
from anonchat.db import Database
from anonchat.handlers import get_routers
from anonchat.matching import Matchmaker
from anonchat.middlewares import DataContext, Throttling

log = logging.getLogger("anonchat")

COMMANDS = [
    BotCommand(command="start", description="🧲 Меню анонимного чата"),
    BotCommand(command="connect", description="🔎 Найти собеседника"),
    BotCommand(command="next", description="⏭️ Следующий собеседник"),
    BotCommand(command="stop", description="⏹️ Остановить диалог"),
    BotCommand(command="report", description="🚩 Пожаловаться"),
    BotCommand(command="profile", description="📊 Мой уровень общения"),
    BotCommand(command="settings", description="⚙️ Район и фильтры"),
    BotCommand(command="top", description="🏆 Топ МГН"),
    BotCommand(command="help", description="🛠 Как пользоваться"),
    BotCommand(command="rules", description="📜 Правила"),
    BotCommand(command="forget", description="🧹 Удалить мой профиль"),
]

ADMIN_COMMANDS = [
    BotCommand(command="stats", description="📈 Сводка по боту"),
    BotCommand(command="reports", description="🚩 Открытые жалобы"),
    BotCommand(command="queue", description="⏳ Очередь поиска"),
    BotCommand(command="ban", description="⛔ Забанить"),
    BotCommand(command="unban", description="✅ Разбанить"),
    BotCommand(command="mute", description="🔇 Мут на минуты"),
    BotCommand(command="find", description="🔎 Найти профиль"),
    BotCommand(command="bc", description="📣 Рассылка"),
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


async def main() -> None:
    cfg = Config.from_env()
    logging.basicConfig(
        level=logging.DEBUG if cfg.debug else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )

    db = await Database(cfg.db_path).start()
    mm = Matchmaker(queue_limit=cfg.queue_soft_limit)

    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(Throttling(cfg, limit=cfg.inchat_rate_limit))
        observer.middleware(DataContext(cfg, db, mm))

    for router in get_routers():
        dp.include_router(router)

    @dp.error()
    async def on_error(event: ErrorEvent) -> None:  # pragma: no cover
        log.exception("Необработанная ошибка: %s", event.exception)

    @dp.startup()
    async def on_startup(bot: Bot) -> None:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
        except TelegramAPIError as exc:
            log.warning("delete_webhook не сработал: %s", exc)
        try:
            await bot.set_my_commands(COMMANDS, scope=BotCommandScopeAllPrivateChats())
            if cfg.admin_ids:
                await bot.set_my_commands(COMMANDS + ADMIN_COMMANDS)
        except TelegramAPIError as exc:
            log.warning("set_my_commands не сработал: %s", exc)
        me = await bot.get_me()
        log.info("Анонимный чат %s запущен: @%s (id=%s)", cfg.city_short, me.username, me.id)
        if not cfg.admin_ids:
            log.warning("ADMIN_IDS пуст — команды модерации недоступны ни у кого.")
        asyncio.create_task(janitor(mm))

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await dp.storage.close()
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger("anonchat").info("Остановили — пока из МГН!")
