"""NFT: одна запись на пользователя, одинаковый результат повторного розыгрыша."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from anonchat.handlers.nft_giveaway import Giveaway, _count, _draw, _join


def test_nft_entry_is_unique_even_for_parallel_taps() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            path = Path(temp) / "test.db"
            g = Giveaway("test-nft", "NFT", int(time.time()) + 120, "", "https://example.com/rules")
            results = await asyncio.gather(*[_join(path, g, 123) for _ in range(5)])
            assert await _count(path, g.campaign) == 1
            assert sum(int(created) for _, created in results) == 1
            assert len({ticket for ticket, _ in results}) == 1
            assert all(ticket is not None for ticket, _ in results)

    asyncio.run(run())


def test_nft_draw_cannot_change_winner_or_accept_late_entries() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            path = Path(temp) / "test.db"
            g = Giveaway("test-nft", "NFT", int(time.time()) + 60, "", "https://example.com/rules")
            await _join(path, g, 111)
            await _join(path, g, 222)
            closed = Giveaway(g.campaign, g.prize, int(time.time()) - 1, g.deadline, g.rules_url)
            assert await _join(path, closed, 333) == (None, False)
            winner = await _draw(path, closed)
            assert winner is not None
            assert winner[0] in (111, 222)
            assert winner[2] == 2
            assert await _draw(path, closed) == winner

    asyncio.run(run())
