"""Меню команд бота (то, что видно в «/»-подсказках Telegram).

Нюансы Bot API:

* `BotCommandScopeChat` для конкретного пользователя принимается только после того,
  как он сам написал боту (иначе — «chat not found»), поэтому при старте ставим общее
  меню и пробуем админское (молча пропускаем недоступное), а при первом /start админа
  добиваем его личное меню — `ensure_for_admin`;
* служебные команды модерации в список меню **не выкладываем**: они работают, если
  ввести их руками, но показываем мы только `/admin` — дальше панель кнопками.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat

from .config import Config

log = logging.getLogger("anonchat")

COMMANDS = (
    BotCommand(command="start", description="🧲 Меню чата"),
    BotCommand(command="connect", description="🔎 Найти собеседника"),
    BotCommand(command="next", description="⏭ Следующий"),
    BotCommand(command="stop", description="⏹ Остановить диалог"),
    BotCommand(command="report", description="🚩 Пожаловаться"),
    BotCommand(command="send", description="🔗 Отправить username или ссылку собеседнику"),
    BotCommand(command="user", description="🔗 Отправить username собеседнику"),
    BotCommand(command="nick", description="🙋 Ник, который видят другие"),
    BotCommand(command="profile", description="📊 Мой ранг и статистика"),
    BotCommand(command="settings", description="⚙️ Район и фильтры"),
    BotCommand(command="top", description="🏆 Топ города"),
    BotCommand(command="help", description="❓ Как пользоваться"),
    BotCommand(command="rules", description="📜 Правила"),
    BotCommand(command="support", description="⭐ Поддержать проект"),
    BotCommand(command="forget", description="🧹 Удалить мой профиль"),
)

#: админские команды, которые видны в меню модератора
ADMIN_VISIBLE = (
    BotCommand(command="admin", description="🛡 Панель модератора"),
    BotCommand(command="unblock", description="🔓 Сбросить скрытых собеседников"),
)

#: работают, если ввести руками (и из панели), но в меню не показываются
ADMIN_COMMANDS = (
    BotCommand(command="stats", description="📈 Сводка по боту"),
    BotCommand(command="reports", description="🚩 Открытые жалобы"),
    BotCommand(command="queue", description="⏳ Очередь поиска"),
    BotCommand(command="ban", description="⛔ Забанить"),
    BotCommand(command="unban", description="✅ Разбанить"),
    BotCommand(command="mute", description="🔇 Мут на минуты"),
    BotCommand(command="find", description="🔎 Найти профиль"),
    BotCommand(command="feedback", description="💌 Фидбек владельцу"),
    BotCommand(command="bc", description="📣 Рассылка"),
)

_done: set[int] = set()


async def register_common(bot: Bot, cfg: Config) -> None:
    """Общее меню для всех личных чатов + попытка поставить админское."""
    try:
        await bot.set_my_commands(list(COMMANDS), scope=BotCommandScopeAllPrivateChats())
    except TelegramAPIError as exc:  # pragma: no cover
        log.warning("не удалось задать общее меню команд: %s", exc)
    for admin_id in cfg.admin_ids:
        await ensure_for_admin(bot, cfg, admin_id, quiet=True)


async def ensure_for_admin(bot: Bot, cfg: Config, user_id: int, quiet: bool = False) -> bool:
    """Меню модератора для конкретного чата. False — чат ещё не существует (боту не писали)."""
    if user_id not in cfg.admin_ids or user_id in _done:
        return user_id in _done
    try:
        await bot.set_my_commands(
            list(COMMANDS + ADMIN_VISIBLE), scope=BotCommandScopeChat(chat_id=user_id)
        )
    except TelegramAPIError as exc:
        if not quiet:
            log.info("меню админа для %s пока недоступно (%s) — настроится при /start", user_id, exc)
        return False
    _done.add(user_id)
    log.info("меню модератора включено для %s", user_id)
    return True
