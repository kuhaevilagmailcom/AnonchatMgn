"""Анонимный чат по городам — пакет с логикой бота.

Модули:
    config      — настройки из окружения/.env
    db          — SQLite (профили, опыт, жалобы, диалоги)
    levels      — «уровень общения» и звания
    matching    — очередь и подбор пар (in-memory)
    keyboards   — инлайн-кнопки с эмодзи
    texts       — все тексты
    actions     — действия (коннект, следующий, стоп, профиль…)
    middlewares — контекст БД + троттлинг
    handlers/   — роутеры: settings, reports, admin, menu, chat
"""

__all__ = ["__version__"]
__version__ = "1.0.0"
