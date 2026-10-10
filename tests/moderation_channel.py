"""Изолированные проверки копирования уведомлений в приватный админ-канал."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from anonchat.actions import DeliveryResult
from anonchat.moderation_channel import send_moderation_channel
from anonchat.monitoring import _notify_spam


async def run() -> None:
    cfg = SimpleNamespace(admin_ids=(), moderation_channel_id=-1004482932867)
    original = SimpleNamespace(text="отзыв", content_type="text")
    with (
        patch("anonchat.moderation_channel.send_to", new_callable=AsyncMock) as send,
        patch("anonchat.moderation_channel.send_copy_to", new_callable=AsyncMock) as copy,
    ):
        send.return_value = DeliveryResult.DELIVERED
        copy.return_value = DeliveryResult.DELIVERED
        assert await send_moderation_channel(object(), cfg, "Обратная связь", message=original)
        assert send.await_count == 1
        assert send.await_args.args[1] == -1004482932867
        assert copy.await_count == 1

        send.reset_mock()
        copy.reset_mock()
        send.return_value = DeliveryResult.TEMP_ERROR
        assert not await send_moderation_channel(object(), cfg, "Ошибка Telegram", message=original)
        copy.assert_not_awaited()

        cfg.moderation_channel_id = 0
        send.reset_mock()
        assert not await send_moderation_channel(object(), cfg, "Выключено")
        send.assert_not_awaited()

    cfg.moderation_channel_id = -1004482932867
    db = SimpleNamespace(get_user=AsyncMock(return_value=None))
    with (
        patch("anonchat.monitoring._register_spam_message", return_value=("повторы", ["слово", "слово"])),
        patch("anonchat.monitoring._spam_monitor_ids", new_callable=AsyncMock, return_value=()),
        patch("anonchat.monitoring.send_moderation_channel", new_callable=AsyncMock, return_value=True) as channel,
    ):
        await _notify_spam(
            SimpleNamespace(text="слово", caption=None),
            object(), db, cfg, None, 123, 456,
        )
        channel.assert_awaited_once()
        assert "Похоже на спам" in channel.await_args.args[2]


if __name__ == "__main__":
    asyncio.run(run())
    print("Moderation channel smoke tests: OK")
