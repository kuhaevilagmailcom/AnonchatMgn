"""Decorative Telegram screen PNGs are never sent; media relay remains separate."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Chat, Message, PhotoSize, User

from anonchat.actions import (
    Ctx, DeliveryResult, _LIVE_MENUS, _SCREEN_MESSAGES,
    refresh_live_menus, send_screen_to,
)
from anonchat.config import Config
from anonchat.matching import Matchmaker
from anonchat.pack import EmojiPack
from tests.flow import RecordingSession


def make_callback(bot: Bot, uid: int, *, legacy_photo: bool) -> CallbackQuery:
    content: dict = {
        "message_id": 321,
        "date": 1_700_000_000,
        "chat": {"id": uid, "type": "private"},
    }
    if legacy_photo:
        content["photo"] = [
            {"file_id": "old-menu-photo", "file_unique_id": "oldphoto",
             "width": 1, "height": 1},
        ]
        content["caption"] = "Старое меню"
    else:
        content["text"] = "Текстовое меню"
    return CallbackQuery.model_validate({
        "id": "callback-screen",
        "from": {"id": uid, "is_bot": False, "first_name": "Test"},
        "chat_instance": "chat",
        "data": "act:settings",
        "message": content,
    }, context={"bot": bot})


def test_old_photo_menu_is_replaced_by_text_and_buttons() -> None:
    async def scenario() -> None:
        session = RecordingSession()
        bot = Bot(
            "42:TEST", session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        uid = 982301
        _SCREEN_MESSAGES.pop(uid, None)
        _LIVE_MENUS.pop(uid, None)
        try:
            ctx = Ctx(
                bot=bot, db=SimpleNamespace(), mm=Matchmaker(),
                cfg=Config(bot_token="42:TEST"), pack=EmojiPack(),
                event=make_callback(bot, uid, legacy_photo=True), user_id=uid,
            )
            await ctx.render_screen(
                "05_settings.png", "<b>Настройки</b>", live_menu=True,
            )
            methods = [row["method"] for row in session.outbox]
            assert "sendMessage" in methods, methods
            assert "deleteMessage" in methods, methods
            assert "sendPhoto" not in methods
            assert "editMessageMedia" not in methods
            assert "editMessageCaption" not in methods
            assert uid in _LIVE_MENUS
        finally:
            _SCREEN_MESSAGES.pop(uid, None)
            _LIVE_MENUS.pop(uid, None)
            await bot.session.close()
    asyncio.run(scenario())


def test_text_screen_is_edited_in_place_and_online_refresh_uses_text() -> None:
    async def scenario() -> None:
        session = RecordingSession()
        bot = Bot(
            "42:TEST", session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        uid = 982302
        _SCREEN_MESSAGES.pop(uid, None)
        _LIVE_MENUS.pop(uid, None)
        try:
            ctx = Ctx(
                bot=bot, db=SimpleNamespace(), mm=Matchmaker(),
                cfg=Config(bot_token="42:TEST"), pack=EmojiPack(),
                event=make_callback(bot, uid, legacy_photo=False), user_id=uid,
            )
            await ctx.render_screen(
                "01_main_menu.png", "🟢 Онлайн сейчас: <b>0</b>", live_menu=True
            )
            methods = [row["method"] for row in session.outbox]
            assert "editMessageText" in methods, methods
            assert "sendPhoto" not in methods
            assert "editMessageMedia" not in methods
            # Force one refresh, even if nobody else is online.
            _LIVE_MENUS[uid] = (
                uid, 321, "Anonymous", False, -1, 0.0,
            )
            # A fresh timestamp keeps it eligible.
            import time
            _LIVE_MENUS[uid] = (
                uid, 321, "Anonymous", False, -1, time.monotonic(),
            )
            session.clear()
            await refresh_live_menus(bot, ctx.mm, ctx.pack)
            methods = [row["method"] for row in session.outbox]
            assert "editMessageText" in methods, methods
            assert "editMessageCaption" not in methods
        finally:
            _SCREEN_MESSAGES.pop(uid, None)
            _LIVE_MENUS.pop(uid, None)
            await bot.session.close()
    asyncio.run(scenario())


def test_pair_found_notice_uses_text_not_png() -> None:
    async def scenario() -> None:
        session = RecordingSession()
        bot = Bot(
            "42:TEST", session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        uid = 982303
        _SCREEN_MESSAGES.pop(uid, None)
        try:
            result = await send_screen_to(
                bot, uid, "03_found.png", "Собеседник найден",
                pack=EmojiPack(),
            )
            assert result is DeliveryResult.DELIVERED
            assert any(
                row["method"] == "sendMessage" and
                "Собеседник найден" in row.get("text", "")
                for row in session.outbox
            )
            assert not any(row["method"] == "sendPhoto" for row in session.outbox)
        finally:
            _SCREEN_MESSAGES.pop(uid, None)
            await bot.session.close()
    asyncio.run(scenario())


if __name__ == "__main__":
    test_old_photo_menu_is_replaced_by_text_and_buttons()
    test_text_screen_is_edited_in_place_and_online_refresh_uses_text()
    test_pair_found_notice_uses_text_not_png()
    print("Text-only Telegram menu screens passed")
