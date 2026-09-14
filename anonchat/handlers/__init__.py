"""Сборка роутеров. Порядок важен: состояния и экраны раньше, «пересылай всё» — самым последним."""

from __future__ import annotations

from aiogram import Router

from .admin import router as admin_router
from .chat import router as chat_router
from .menu import router as menu_router
from .reports import router as reports_router
from .settings import router as settings_router


def get_routers() -> list[Router]:
    return [
        settings_router,  # /profile, /settings, FSM «о себе»
        reports_router,   # /report, FSM комментария жалобы
        admin_router,     # модерация
        menu_router,      # /start, кнопки меню, оценки
        chat_router,      # catch-all: пересылка сообщений собеседнику
    ]


__all__ = ["get_routers"]
