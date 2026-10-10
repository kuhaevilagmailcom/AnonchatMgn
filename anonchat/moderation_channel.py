"""Дополнительный закрытый канал для жалоб, обратной связи и антиспама.

Копия не заменяет отправку администраторам в личные сообщения.
Ошибки Telegram не должны мешать отправке жалобы или работе чата.
"""
from __future__ import annotations

import logging

from .actions import DeliveryResult, send_copy_to, send_to

log = logging.getLogger(__name__)


async def send_moderation_channel(bot, cfg, body: str, *, message=None) -> bool:
    """Отправить уведомление в канал; для обратной связи приложить копию медиа/текста."""
    channel_id = int(getattr(cfg, "moderation_channel_id", 0) or 0)
    if not channel_id:
        return False
    try:
        result = await send_to(bot, channel_id, body)
        if result is not DeliveryResult.DELIVERED:
            log.warning("Moderation channel notification failed: chat_id=%s result=%s", channel_id, result)
            return False
        if message is not None:
            copy_result = await send_copy_to(bot, message, channel_id)
            if copy_result is not DeliveryResult.DELIVERED:
                log.warning("Moderation channel attachment failed: chat_id=%s result=%s", channel_id, copy_result)
        return True
    except Exception:
        log.exception("Moderation channel notification crashed: chat_id=%s", channel_id)
        return False
