"""NFT giveaway action appears only for a live raffle and stays in live menus."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message

from anonchat.actions import (
    Ctx, _LIVE_MENUS, _LIVE_MENU_NFT_FLAGS, _SCREEN_MESSAGES,
    refresh_live_menus, show_menu,
)
from anonchat.config import Config
from anonchat.db import Database
from anonchat.handlers.nft_giveaway import _save_campaign, nft_open_from_menu
from anonchat.keyboards import menu_keyboard
from anonchat.matching import Matchmaker
from anonchat.pack import EmojiPack
from tests.flow import RecordingSession


def _buttons(markup) -> dict[str, str | None]:
    return {
        button.text: button.callback_data
        for row in markup.inline_keyboard for button in row
    }


def test_button_visible_only_on_active_free_menu() -> None:
    normal = _buttons(menu_keyboard("free"))
    active = _buttons(menu_keyboard("free", nft_active=True))
    assert "Розыгрыш NFT" not in normal
    assert active["Розыгрыш NFT"] == "nft:open"
    assert "Найти собеседника" in active
    assert "Профиль" in active
    assert "Настройки" in active
    assert "Розыгрыш NFT" not in _buttons(menu_keyboard("queued", nft_active=True))
    assert "Розыгрыш NFT" not in _buttons(menu_keyboard("paired", nft_active=True))
    with_poll = _buttons(menu_keyboard("free", nft_active=True, poll_active=True, admin=True))
    assert with_poll["Розыгрыш NFT"] == "nft:open"
    assert "Панель модератора" in with_poll
    assert "Опрос" in with_poll


def test_main_menu_and_live_refresh_follow_raffle_lifecycle() -> None:
    async def run() -> None:
        uid = 1982341
        with TemporaryDirectory() as temp:
            db = await Database(Path(temp) / "raffle.db").start()
            session = RecordingSession()
            bot = Bot(
                "42:TEST", session=session,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            _LIVE_MENUS.pop(uid, None)
            _LIVE_MENU_NFT_FLAGS.pop(uid, None)
            _SCREEN_MESSAGES.pop(uid, None)
            try:
                await db.ensure_user(uid, "ticketbuyer", "Ticket Buyer")
                event = Message.model_validate({
                    "message_id": 51,
                    "date": int(time.time()),
                    "chat": {"id": uid, "type": "private"},
                    "from": {"id": uid, "is_bot": False, "first_name": "Ticket Buyer"},
                    "text": "/start",
                }, context={"bot": bot})
                mm = Matchmaker()
                pack = EmojiPack()
                cfg = Config(bot_token="42:TEST")
                ctx = Ctx(
                    bot=bot, db=db, mm=mm, pack=pack, cfg=cfg,
                    event=event, user_id=uid, me=await db.get_user(uid),
                )
                await show_menu(ctx)
                assert "Розыгрыш NFT" not in str(session.to(uid)[-1]["reply_markup"])
                assert _LIVE_MENU_NFT_FLAGS[uid] is False
                g = await _save_campaign(
                    db, "https://t.me/nft/MenuPrize",
                    int(time.time()) + 3600, "12.12.2026 20:00 МГН",
                )
                session.clear()
                # Even with no change in online count, the button appears.
                await refresh_live_menus(bot, mm, pack, db)
                edited = [
                    call for call in session.to(uid)
                    if call["method"] == "editMessageText"
                ]
                assert edited
                assert "Розыгрыш NFT" in str(edited[-1]["reply_markup"])
                assert _LIVE_MENU_NFT_FLAGS[uid] is True
                session.clear()
                await db.db.execute(
                    "UPDATE nft_giveaway_campaigns SET close_at=? WHERE campaign=?",
                    (int(time.time()) - 1, g.campaign),
                )
                await db.db.commit()
                # Expired campaigns disappear at the next refresh.
                await refresh_live_menus(bot, mm, pack, db)
                edited = [
                    call for call in session.to(uid)
                    if call["method"] == "editMessageText"
                ]
                assert edited
                assert "Розыгрыш NFT" not in str(edited[-1]["reply_markup"])
                assert _LIVE_MENU_NFT_FLAGS[uid] is False
            finally:
                _LIVE_MENUS.pop(uid, None)
                _LIVE_MENU_NFT_FLAGS.pop(uid, None)
                _SCREEN_MESSAGES.pop(uid, None)
                await bot.session.close()
                await db.close()
    asyncio.run(run())


def test_main_menu_button_opens_live_raffle_but_not_expired_buy() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            db = await Database(Path(temp) / "raffle.db").start()
            try:
                g = await _save_campaign(
                    db, "https://t.me/nft/MenuPrize",
                    int(time.time()) + 3600, "12.12.2026 20:00 МГН",
                )
                ctx = SimpleNamespace(
                    cfg=SimpleNamespace(rollypay_enabled=True),
                    bot=SimpleNamespace(get_sticker_set=AsyncMock(
                        return_value=SimpleNamespace(
                            sticker_type="custom_emoji", stickers=[],
                        ),
                    )),
                    ack=AsyncMock(), reply=AsyncMock(),
                )
                event = SimpleNamespace(data="nft:open")
                await nft_open_from_menu(event, ctx, db)
                ctx.ack.assert_awaited_once()
                text, keyboard = ctx.reply.await_args.args
                assert "РОЗЫГРЫШ NFT АКТИВЕН!" in text
                assert _buttons(keyboard)["Купить билеты · от 35 ₽"] == "nft:buy"
                assert _buttons(keyboard)["Мои билеты"] == "nft:status"
                await db.db.execute(
                    "UPDATE nft_giveaway_campaigns SET close_at=? WHERE campaign=?",
                    (int(time.time()) - 1, g.campaign),
                )
                await db.db.commit()
                ctx.reply.reset_mock()
                await nft_open_from_menu(event, ctx, db)
                assert "завершён" in ctx.reply.await_args.args[0]
                assert len(ctx.reply.await_args.args) == 1
            finally:
                await db.close()
    asyncio.run(run())


if __name__ == "__main__":
    test_button_visible_only_on_active_free_menu()
    test_main_menu_and_live_refresh_follow_raffle_lifecycle()
    test_main_menu_button_opens_live_raffle_but_not_expired_buy()
    print("NFT main-menu button tests passed")
