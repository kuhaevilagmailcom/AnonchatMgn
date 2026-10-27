"""Билеты NFT: последовательные номера в каждой кампании и защита от дублей."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from anonchat.handlers.nft_giveaway import (
    Giveaway, _active, _count, _draw, _join, _save_campaign,
    _ticket, _message, valid_nft_url,
)


def test_nft_entry_is_unique_even_for_parallel_taps() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            path = Path(temp) / "test.db"
            g = Giveaway("first-nft", "https://t.me/nft/Test-1",
                         int(time.time()) + 120, "01.11.2026 20:00 МГН")
            results = await asyncio.gather(*[_join(path, g, 123) for _ in range(5)])
            assert await _count(path, g.campaign) == 1
            assert sum(int(created) for _, created in results) == 1
            assert results[0][0] == 1
            assert all(ticket == 1 for ticket, _ in results)
            assert await _ticket(path, g.campaign, 123) == 1

    asyncio.run(run())


def test_nft_numbers_restart_from_one_per_campaign() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            path = Path(temp) / "test.db"
            closing = int(time.time()) + 100
            first = Giveaway("first", "https://t.me/nft/Test-1", closing, "soon")
            second = Giveaway("second", "https://t.me/nft/Test-2", closing, "soon")
            assert await _join(path, first, 111) == (1, True)
            assert await _join(path, first, 222) == (2, True)
            assert await _join(path, second, 333) == (1, True)
            assert await _ticket(path, first.campaign, 222) == 2
            assert await _ticket(path, second.campaign, 333) == 1

    asyncio.run(run())


def test_nft_draw_cannot_change_winner_or_accept_late_entries() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            path = Path(temp) / "test.db"
            g = Giveaway("test-nft", "https://t.me/nft/Test-3",
                         int(time.time()) + 60, "soon")
            await _join(path, g, 111)
            await _join(path, g, 222)
            closed = Giveaway(g.campaign, g.nft_url, int(time.time()) - 1, g.deadline)
            assert await _join(path, closed, 333) == (None, False)
            winner = await _draw(path, closed)
            assert winner is not None
            assert winner[0] in (111, 222)
            assert winner[1] in (1, 2)
            assert winner[2] == 2
            assert await _draw(path, closed) == winner

    asyncio.run(run())


def test_nft_settings_and_no_title_or_rules() -> None:
    import aiosqlite

    class FakeDB:
        def __init__(self, path):
            self.path = path

        async def _fetchone(self, query, params=()):
            async with aiosqlite.connect(self.path) as con:
                con.row_factory = aiosqlite.Row
                return await (await con.execute(query, params)).fetchone()

    async def run() -> None:
        with TemporaryDirectory() as temp:
            db = FakeDB(Path(temp) / "test.db")
            then = int(time.time()) + 300
            url = "https://t.me/nft/Test-4"
            created = await _save_campaign(db, url, then, "01.11.2026 20:00 МГН")
            active = await _active(db)
            assert active == created
            assert url in _message(active)
            assert "Правила:" not in _message(active)
            assert "Название:" not in _message(active)
            try:
                await _save_campaign(db, "https://t.me/nft/Test-5", then,
                                     "02.11.2026 20:00 МГН")
                assert False, "Overwriting running giveaway must fail"
            except ValueError:
                pass

    assert valid_nft_url("https://t.me/nft/Test-1")
    assert not valid_nft_url("javascript:alert(1)")
    assert not valid_nft_url("http://t.me/nft/Test-1")
    assert not valid_nft_url("https://t.me/nft/Test-1\nInjected")
    asyncio.run(run())
