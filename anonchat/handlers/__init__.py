"""Сборка роутеров. Порядок важен: состояния и экраны раньше, «пересылай всё» — самым последним."""

from __future__ import annotations

from aiogram import Router

from .admin import router as admin_router
from .admin_extras import router as admin_extras_router
from .chat import router as chat_router
from .games import router as games_router
from .group_geo import router as group_geo_router
from .menu import router as menu_router
from .polls import router as polls_router
from .reports import router as reports_router
from .settings import router as settings_router
from .support import router as support_router
from .nft_giveaway import router as nft_giveaway_router
from .nft_channel import router as nft_channel_router
from .nft_setup import router as nft_setup_router
from .raiony import router as raiony_router


def get_routers() -> list[Router]:
    return [
        group_geo_router, # /gamegeo и геометки в группах
        settings_router,  # /profile, /settings, FSM ника
        raiony_router,   # районы: проверенные XTR-платежи и складские приглашения
        support_router,   # добровольная поддержка через Telegram Stars
        nft_setup_router,  # настройка NFT через личные сообщения
        nft_channel_router,  # публикация NFT в канале
        nft_giveaway_router,  # NFT-розыгрыш: билеты через RollyPay и админ-команды
        reports_router,   # /report, FSM комментария жалобы
        games_router,     # игры внутри активного диалога
        admin_extras_router,  # компактные админские экраны
        admin_router,     # модерация
        polls_router,     # активный опрос дня
        menu_router,      # /start, кнопки меню, оценки
        chat_router,      # catch-all: пересылка сообщений собеседнику
    ]


__all__ = ["get_routers"]
