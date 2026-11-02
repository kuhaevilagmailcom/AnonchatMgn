"""NFT giveaway card: real SQLite stats, safe HTML and ProtectStatus emoji."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anonchat.nft_presentation as presentation
from anonchat.db import Database
from anonchat.handlers.nft_giveaway import (
    _card, _raffle_stats, _issue_paid_ticket, _save_campaign,
)
from anonchat.nft_presentation import (
    RaffleStats, format_giveaway, icon, load_protect_icons, remaining_time,
)


def test_card_layout_uses_actual_one_prize_and_safe_html() -> None:
    g = SimpleNamespace(
        nft_url='https://t.me/nft/Prize-1?q=one&x="two"',
        close_at=1_900_000_000,
        deadline="11.11.2026 20:00 МГН",
    )
    html = format_giveaway(g, RaffleStats(2, 5), now=1_899_900_000)
    assert "<b>РОЗЫГРЫШ NFT АКТИВЕН!</b>" in html
    assert 'href="https://t.me/nft/Prize-1?q=one&amp;x=&quot;two&quot;"' in html
    assert "<blockquote>" in html
    assert "Участников: <b>2</b>" in html
    assert "Билетов: <b>5</b>" in html
    assert "Билет: <b>35 ₽</b>" in html
    assert "Проверить оплату" in html
    assert "Успей принять участие!" in html
    assert "2-е место" not in html and "3-е место" not in html
    assert len(html) < 4096


def test_countdown_and_closed_variant() -> None:
    assert remaining_time(100000, 100000) == "0 минут"
    assert remaining_time(100060, 100000) == "1 мин."
    assert remaining_time(100000 + 90061, 100000) == "1 д. 1 ч. 2 мин."
    g = SimpleNamespace(
        nft_url="https://t.me/nft/Prize-1",
        close_at=10, deadline="expired",
    )
    html = format_giveaway(g, RaffleStats(4, 8), now=20)
    assert "ЗАВЕРШЁН" in html
    assert "Приём билетов завершён" in html
    assert "Успей принять участие" not in html


def test_pack_loaded_by_name_via_bot_api_with_real_ids() -> None:
    async def scenario():
        original_cache, original_at = presentation._pack_cache, presentation._cache_at
        presentation._pack_cache, presentation._cache_at = None, 0
        try:
            stickers = [
                SimpleNamespace(custom_emoji_id="5123456789012345678", emoji="🎁"),
                SimpleNamespace(custom_emoji_id="5234567890123456789", emoji="📊"),
                SimpleNamespace(custom_emoji_id="5345678901234567890", emoji="✅"),
                SimpleNamespace(custom_emoji_id="", emoji="🏆"),
            ]
            bot = SimpleNamespace(get_sticker_set=AsyncMock(
                return_value=SimpleNamespace(sticker_type="custom_emoji", stickers=stickers)
            ))
            result = await load_protect_icons(bot)
            bot.get_sticker_set.assert_awaited_once_with(name="ProtectStatus")
            assert "5123456789012345678" in icon("header", result)
            assert "5234567890123456789" in icon("stats", result)
            assert "5345678901234567890" in icon("check", result)
            assert "<tg-emoji" in icon("header", result)
            assert "5123456789012345678" in icon("prize", result)
            # In the same process, a cached pack prevents an API call per user.
            await load_protect_icons(bot)
            bot.get_sticker_set.assert_awaited_once()
        finally:
            presentation._pack_cache = original_cache
            presentation._cache_at = original_at

    asyncio.run(scenario())


def test_real_confirmed_user_and_ticket_counts() -> None:
    async def scenario():
        with TemporaryDirectory() as folder:
            db = await Database(Path(folder) / "raffle.db").start()
            try:
                for uid in (111, 222):
                    await db.ensure_user(uid, "buyer", "Buyer")
                g = await _save_campaign(
                    db, "https://t.me/nft/TestPrizes",
                    int(time.time()) + 3600, "01.12.2026 20:00 МГН",
                )
                async def paid(uid, idx):
                    local = await db.create_sbp_order(
                        order_id=f"stat-{idx}", user_id=uid,
                        kind=f"nft_ticket:{g.campaign}", amount_rub=35,
                    )
                    pid = f"pay-{idx}"
                    await db.attach_sbp_provider_payment(
                        local, pid, f"https://pay.example/{idx}",
                    )
                    await _issue_paid_ticket(db.path, pid)
                await paid(111, 1)
                await paid(111, 2)
                await paid(222, 3)
                totals = await _raffle_stats(db.path, g.campaign)
                assert totals == RaffleStats(participants=2, tickets=3)
                bot = SimpleNamespace(get_sticker_set=AsyncMock(
                    return_value=SimpleNamespace(sticker_type="custom_emoji", stickers=[])
                ))
                ctx = SimpleNamespace(bot=bot)
                text = await _card(ctx, db, g)
                assert "Участников: <b>2</b>" in text
                assert "Билетов: <b>3</b>" in text
            finally:
                await db.close()

    asyncio.run(scenario())


if __name__ == "__main__":
    test_card_layout_uses_actual_one_prize_and_safe_html()
    test_countdown_and_closed_variant()
    test_pack_loaded_by_name_via_bot_api_with_real_ids()
    test_real_confirmed_user_and_ticket_counts()
    print("NFT presentation tests passed")
