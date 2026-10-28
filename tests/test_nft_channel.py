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
    _claim_post, _record_post, channel_target,
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
    assert "<b>Разыгрываем NFT</b>" in body
    assert "35 ₽" in body
    assert "31.12.2026 20:00 МГН" in body
    assert "https://t.me/nft/Prize-12?a=1&amp;b=2" in body
    assert len(body) < 500
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


if __name__ == "__main__":
    test_channel_target_uses_configured_channel()
    test_giveaway_post_is_short_and_links_to_bot()
    test_one_post_per_campaign_and_channel_even_under_concurrency()
    test_channel_publication_attaches_real_inline_button()
    print("NFT channel post tests passed")
