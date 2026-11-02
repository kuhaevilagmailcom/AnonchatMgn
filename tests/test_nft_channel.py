"""NFT channel posting: safe preview, deep-link formatting, duplicate protection."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiosqlite

from anonchat.handlers.nft_channel import (
    _claim_post, _record_post, _claim_repeat, _record_repeat, channel_target,
    nft_repeat_preview, nft_repeat_confirm,
    giveaway_post_text, participation_keyboard,
    nft_post_confirm, nft_post_preview,
)
from anonchat.handlers.nft_giveaway import Giveaway


def test_channel_target_uses_configured_channel() -> None:
    with patch.dict(os.environ, {"NFT_POST_CHANNEL": ""}):
        assert channel_target("@anonmgn") == "@anonmgn"
        assert channel_target("invalid channel") == ""
    with patch.dict(os.environ, {"NFT_POST_CHANNEL": "@MyTestChannel"}):
        assert channel_target("@anonmgn") == "@MyTestChannel"
    with patch.dict(os.environ, {"NFT_POST_CHANNEL": "https://evil.example"}):
        assert channel_target("@anonmgn") == ""


def test_giveaway_post_is_short_and_links_to_bot() -> None:
    g = Giveaway("campaign-1", "https://t.me/nft/Prize-12?a=1&b=2",
                 2_000_000_000, "31.12.2026 20:00 МГН")
    body = giveaway_post_text(g)
    assert "РОЗЫГРЫШ NFT АКТИВЕН!" in body
    assert "<blockquote>" in body
    assert "Участников: <b>0</b>" in body
    assert "Билетов: <b>0</b>" in body
    assert "35 ₽" in body
    assert "31.12.2026 20:00 МГН" in body
    assert "https://t.me/nft/Prize-12?a=1&amp;b=2" in body
    assert len(body) < 1400
    keyboard = participation_keyboard("AnonChatMgn_Bot")
    assert keyboard.inline_keyboard[0][0].url == (
        "https://t.me/AnonChatMgn_Bot?start=nft"
    )


def test_one_post_per_campaign_and_channel_even_under_concurrency() -> None:
    async def run() -> None:
        with TemporaryDirectory() as folder:
            path = Path(folder) / "posts.sqlite3"
            results = await asyncio.gather(*[
                _claim_post(path, "campaign-1", "@anonmgn") for _ in range(6)
            ])
            assert results.count(True) == 1
            assert results.count(False) == 5
            await _record_post(path, "campaign-1", "@anonmgn", "posted", 121)
            assert not await _claim_post(path, "campaign-1", "@anonmgn")
            # Another campaign may publish a separate post.
            assert await _claim_post(path, "campaign-2", "@anonmgn")
            # Known provider failures may be retried, unlike uncertain deliveries.
            await _record_post(path, "campaign-2", "@anonmgn", "failed")
            assert await _claim_post(path, "campaign-2", "@anonmgn")
            await _record_post(path, "campaign-2", "@anonmgn", "unknown")
            assert not await _claim_post(path, "campaign-2", "@anonmgn")
            async with aiosqlite.connect(path) as con:
                row = await (await con.execute(
                    "SELECT message_id,status FROM nft_channel_posts "
                    "WHERE campaign='campaign-1' AND channel='@anonmgn'"
                )).fetchone()
                assert row == (121, "posted")

    asyncio.run(run())


def test_channel_publication_attaches_real_inline_button() -> None:
    async def run() -> None:
        with TemporaryDirectory() as folder:
            g = Giveaway("campaign-1", "https://t.me/nft/Prize-12",
                         2_000_000_000, "31.12.2026 20:00 МГН")
            bot = SimpleNamespace(
                get_me=AsyncMock(return_value=SimpleNamespace(username="AnonChatMgn_Bot")),
                send_message=AsyncMock(return_value=SimpleNamespace(message_id=75)),
            )
            ctx = SimpleNamespace(
                is_owner=True,
                cfg=SimpleNamespace(subscription_channel="@anonmgn"),
                bot=bot,
                reply=AsyncMock(),
                ack=AsyncMock(),
            )
            db = SimpleNamespace(path=Path(folder) / "channel.db")
            message = SimpleNamespace(chat=SimpleNamespace(type="private"))
            event = SimpleNamespace(
                data="nft:post:campaign-1",
                message=message,
            )
            with patch.dict(os.environ, {"NFT_POST_CHANNEL": ""}), patch(
                "anonchat.handlers.nft_channel._active",
                new=AsyncMock(return_value=g),
            ):
                await nft_post_preview(message, ctx, db)
                preview = ctx.reply.await_args.args[1]
                assert preview.inline_keyboard[0][0].text == "Участвовать"
                assert preview.inline_keyboard[0][0].url == (
                    "https://t.me/AnonChatMgn_Bot?start=nft"
                )
                assert preview.inline_keyboard[1][0].callback_data == "nft:post:campaign-1"

                await nft_post_confirm(event, ctx, db)
                assert bot.send_message.await_count == 1
                kwargs = bot.send_message.await_args.kwargs
                assert kwargs["chat_id"] == "@anonmgn"
                assert kwargs["text"] == giveaway_post_text(g)
                real_button = kwargs["reply_markup"].inline_keyboard[0][0]
                assert real_button.text == "Участвовать"
                assert real_button.url == "https://t.me/AnonChatMgn_Bot?start=nft"

                # Repeated confirmation must not post twice.
                await nft_post_confirm(event, ctx, db)
                assert bot.send_message.await_count == 1

    asyncio.run(run())


def test_existing_channel_post_can_be_updated_in_place() -> None:
    async def run() -> None:
        with TemporaryDirectory() as folder:
            from anonchat.handlers.nft_channel import nft_post_update
            g = Giveaway("campaign-update", "https://t.me/nft/NewPrize",
                         2_000_000_000, "31.12.2026 20:00 МГН")
            from anonchat.handlers.nft_channel import _claim_post, _record_post
            db = SimpleNamespace(path=Path(folder) / "channel.db")
            assert await _claim_post(db.path, g.campaign, "@anonmgn")
            await _record_post(db.path, g.campaign, "@anonmgn", "posted", 211)
            bot = SimpleNamespace(
                get_me=AsyncMock(return_value=SimpleNamespace(username="AnonChatMgn_Bot")),
                edit_message_text=AsyncMock(),
                send_message=AsyncMock(),
            )
            ctx = SimpleNamespace(
                is_owner=True,
                cfg=SimpleNamespace(subscription_channel="@anonmgn"),
                bot=bot, reply=AsyncMock(), ack=AsyncMock(),
            )
            msg = SimpleNamespace(chat=SimpleNamespace(type="private"))
            event = SimpleNamespace(
                data="nft:post_update:campaign-update", message=msg,
            )
            with patch.dict(os.environ, {"NFT_POST_CHANNEL": ""}), patch(
                "anonchat.handlers.nft_channel._active",
                new=AsyncMock(return_value=g),
            ):
                await nft_post_update(event, ctx, db)
            bot.edit_message_text.assert_awaited_once()
            kwargs = bot.edit_message_text.await_args.kwargs
            assert kwargs["message_id"] == 211
            assert kwargs["chat_id"] == "@anonmgn"
            assert "Статистика:" in kwargs["text"]
            assert kwargs["reply_markup"].inline_keyboard[0][0].url == (
                "https://t.me/AnonChatMgn_Bot?start=nft"
            )
            bot.send_message.assert_not_awaited()

    asyncio.run(run())


def test_repeat_publications_are_explicit_and_deduped_per_confirmation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as folder:
            path = Path(folder) / "posts.db"
            await _claim_post(path, "campaign", "@anonmgn")
            await _record_post(path, "campaign", "@anonmgn", "posted", 101)
            responses = await asyncio.gather(*(
                _claim_repeat(path, "campaign", "@anonmgn", 777) for _ in range(8)
            ))
            assert responses.count("claimed") == 1
            assert responses.count("duplicate") == 7
            assert await _claim_repeat(path, "campaign", "@anonmgn", 778) == "busy"
            await _record_repeat(path, "campaign", "@anonmgn", 777, "posted", 202)
            assert await _claim_repeat(path, "campaign", "@anonmgn", 777) == "duplicate"
            assert await _claim_repeat(path, "campaign", "@anonmgn", 778) == "claimed"
            await _record_repeat(path, "campaign", "@anonmgn", 778, "unknown")
            assert await _claim_repeat(path, "campaign", "@anonmgn", 778) == "duplicate"
            assert await _claim_repeat(path, "campaign", "@anonmgn", 779) == "claimed"
            await _record_repeat(path, "campaign", "@anonmgn", 779, "failed")
            assert await _claim_repeat(path, "campaign", "@anonmgn", 779) == "claimed"
            # The first post ID stays available for editing as before.
            from anonchat.handlers.nft_channel import _posted_message
            assert await _posted_message(path, "campaign", "@anonmgn") == 101
            async with aiosqlite.connect(path) as con:
                rows = await (await con.execute(
                    "SELECT confirmation_message_id,status,message_id "
                    "FROM nft_channel_repeat_posts ORDER BY confirmation_message_id"
                )).fetchall()
                assert rows == [(777, "posted", 202), (778, "unknown", 0),
                                (779, "sending", 0)]

    asyncio.run(run())


def test_publish_again_button_requires_owner_double_confirmation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as folder:
            g = Giveaway("campaign-repeat", "https://t.me/nft/Prize",
                         2_000_000_000, "31.12.2026 20:00 МГН")
            db = SimpleNamespace(path=Path(folder) / "posts.db")
            assert await _claim_post(db.path, g.campaign, "@anonmgn")
            await _record_post(db.path, g.campaign, "@anonmgn", "posted", 101)
            bot = SimpleNamespace(
                get_me=AsyncMock(return_value=SimpleNamespace(username="AnonChatMgn_Bot")),
                send_message=AsyncMock(return_value=SimpleNamespace(message_id=215)),
            )
            ctx = SimpleNamespace(
                is_owner=True,
                cfg=SimpleNamespace(subscription_channel="@anonmgn"),
                bot=bot, reply=AsyncMock(), ack=AsyncMock(),
            )
            private = SimpleNamespace(chat=SimpleNamespace(type="private"), message_id=900)
            with patch.dict(os.environ, {"NFT_POST_CHANNEL": ""}), patch(
                "anonchat.handlers.nft_channel._active",
                new=AsyncMock(return_value=g),
            ):
                await nft_post_preview(private, ctx, db)
                markup = ctx.reply.await_args.args[1]
                controls = [
                    b for row in markup.inline_keyboard for b in row
                ]
                assert any(
                    b.text == "Обновить опубликованный пост"
                    for b in controls
                )
                repeat = next(b for b in controls if "Выложить розыгрыш ещё раз" in b.text)
                assert repeat.callback_data == f"nft:post_repeat_preview:{g.campaign}"
                assert bot.send_message.await_count == 0

                event = SimpleNamespace(data=repeat.callback_data, message=private)
                ctx.reply.reset_mock()
                await nft_repeat_preview(event, ctx, db)
                confirm_markup = ctx.reply.await_args.args[1]
                confirm = confirm_markup.inline_keyboard[0][0]
                assert confirm.text == "✅ Опубликовать ещё раз"
                assert confirm.callback_data == f"nft:post_repeat_confirm:{g.campaign}"
                assert bot.send_message.await_count == 0

                ctx.reply.reset_mock()
                final_event = SimpleNamespace(data=confirm.callback_data, message=private)
                await nft_repeat_confirm(final_event, ctx, db)
                bot.send_message.assert_awaited_once()
                kwargs = bot.send_message.await_args.kwargs
                assert kwargs["chat_id"] == "@anonmgn"
                assert "РОЗЫГРЫШ NFT АКТИВЕН!" in kwargs["text"]
                assert kwargs["reply_markup"].inline_keyboard[0][0].url == (
                    "https://t.me/AnonChatMgn_Bot?start=nft"
                )
                await nft_repeat_confirm(final_event, ctx, db)
                bot.send_message.assert_awaited_once()

                # Another explicit confirmation can publish a later post.
                private2 = SimpleNamespace(chat=SimpleNamespace(type="private"), message_id=901)
                await nft_repeat_confirm(
                    SimpleNamespace(data=confirm.callback_data, message=private2), ctx, db
                )
                assert bot.send_message.await_count == 2
                # Owner-only: nothing is sent by a non-owner.
                ctx.is_owner = False
                await nft_repeat_confirm(
                    SimpleNamespace(
                        data=confirm.callback_data,
                        message=SimpleNamespace(chat=SimpleNamespace(type="private"), message_id=902),
                    ), ctx, db
                )
                assert bot.send_message.await_count == 2

    asyncio.run(run())


if __name__ == "__main__":
    test_channel_target_uses_configured_channel()
    test_giveaway_post_is_short_and_links_to_bot()
    test_one_post_per_campaign_and_channel_even_under_concurrency()
    test_channel_publication_attaches_real_inline_button()
    test_existing_channel_post_can_be_updated_in_place()
    test_repeat_publications_are_explicit_and_deduped_per_confirmation()
    test_publish_again_button_requires_owner_double_confirmation()
    print("NFT channel post tests passed")
