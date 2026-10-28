"""NFT channel posting: safe preview, deep-link formatting, duplicate protection."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import aiosqlite

from anonchat.handlers.nft_channel import (
    _claim_post, _record_post, channel_target,
    giveaway_post_text, participation_keyboard,
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


if __name__ == "__main__":
    test_channel_target_uses_configured_channel()
    test_giveaway_post_is_short_and_links_to_bot()
    test_one_post_per_campaign_and_channel_even_under_concurrency()
    print("NFT channel post tests passed")
