"""Automatically refresh already published NFT channel messages, no duplicates."""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from anonchat.db import Database
from anonchat.handlers.nft_channel import (
    _claim_post, _record_post, _claim_repeat, _record_repeat,
    nft_post_update,
)
from anonchat.handlers.nft_giveaway import _issue_paid_ticket, _save_campaign
from anonchat.nft_channel_live import (
    refresh_campaign_posts, run_worker, tracked_channel_posts,
)


async def _setup(path: Path):
    db = await Database(path).start()
    await db.ensure_user(111, "buyer", "Buyer")
    g = await _save_campaign(
        db, "https://t.me/nft/Live", int(time.time()) + 3600,
        "12.12.2026 20:00 МГН",
    )
    assert await _claim_post(db.path, g.campaign, "@anonmgn")
    await _record_post(db.path, g.campaign, "@anonmgn", "posted", 401)
    assert await _claim_repeat(db.path, g.campaign, "@anonmgn", 991) == "claimed"
    await _record_repeat(db.path, g.campaign, "@anonmgn", 991, "posted", 402)
    # Unknown deliveries and other campaigns must not be edited.
    assert await _claim_repeat(db.path, g.campaign, "@anonmgn", 992) == "claimed"
    await _record_repeat(db.path, g.campaign, "@anonmgn", 992, "unknown")
    return db, g


def _bot():
    return SimpleNamespace(
        get_me=AsyncMock(return_value=SimpleNamespace(username="AnonChatMgn_Bot")),
        edit_message_text=AsyncMock(),
    )


def test_original_and_reposted_messages_refresh_with_real_ticket_stats() -> None:
    async def run() -> None:
        with TemporaryDirectory() as tmp:
            db, g = await _setup(Path(tmp) / "raffle.db")
            bot = _bot()
            try:
                tracked = await tracked_channel_posts(db.path, g.campaign)
                assert tracked == [("@anonmgn", 401), ("@anonmgn", 402)]
                cache = {}
                result = await refresh_campaign_posts(bot, db, cache=cache)
                assert result == {"total": 2, "updated": 2, "unchanged": 0, "failed": 0}
                assert {x.kwargs["message_id"] for x in bot.edit_message_text.await_args_list} == {
                    401, 402,
                }
                for call in bot.edit_message_text.await_args_list:
                    assert call.kwargs["chat_id"] == "@anonmgn"
                    assert "Участников: <b>0</b>" in call.kwargs["text"]
                    assert "Билетов: <b>0</b>" in call.kwargs["text"]
                    button = call.kwargs["reply_markup"].inline_keyboard[0][0]
                    assert button.text == "Участвовать"
                    assert button.url == "https://t.me/AnonChatMgn_Bot?start=nft"
                result = await refresh_campaign_posts(bot, db, cache=cache)
                assert result["unchanged"] == 2 and result["updated"] == 0
                assert bot.edit_message_text.await_count == 2

                local_id = await db.create_sbp_order(
                    order_id="raffle-paid-5", user_id=111,
                    kind=f"nft_ticket:{g.campaign}", amount_rub=175,
                )
                await db.attach_sbp_provider_payment(
                    local_id, "paid-5", "https://pay.example/5",
                )
                assert await _issue_paid_ticket(db.path, "paid-5") == (1, True)
                result = await refresh_campaign_posts(bot, db, cache=cache)
                assert result["updated"] == 2 and result["failed"] == 0
                for call in bot.edit_message_text.await_args_list[-2:]:
                    assert "Участников: <b>1</b>" in call.kwargs["text"]
                    assert "Билетов: <b>5</b>" in call.kwargs["text"]
                assert bot.edit_message_text.await_count == 4
            finally:
                await db.close()
    asyncio.run(run())


def test_manual_update_refreshes_all_channel_posts() -> None:
    async def run() -> None:
        with TemporaryDirectory() as tmp:
            db, g = await _setup(Path(tmp) / "raffle.db")
            bot = _bot()
            ctx = SimpleNamespace(
                is_owner=True,
                cfg=SimpleNamespace(subscription_channel="@anonmgn"),
                bot=bot, ack=AsyncMock(), reply=AsyncMock(),
            )
            event = SimpleNamespace(
                data=f"nft:post_update:{g.campaign}",
                message=SimpleNamespace(chat=SimpleNamespace(type="private")),
            )
            try:
                with patch.dict(os.environ, {"NFT_POST_CHANNEL": ""}):
                    await nft_post_update(event, ctx, db)
                assert bot.edit_message_text.await_count == 2
                assert "Обновлено публикаций" in ctx.reply.await_args.args[0]
            finally:
                await db.close()
    asyncio.run(run())


def test_background_worker_retries_and_stops_cleanly() -> None:
    async def run() -> None:
        with TemporaryDirectory() as tmp:
            db, _ = await _setup(Path(tmp) / "raffle.db")
            bot = _bot()
            worker = asyncio.create_task(run_worker(bot, db, interval_seconds=0.03))
            try:
                for _ in range(80):
                    if bot.edit_message_text.await_count >= 2:
                        break
                    await asyncio.sleep(0.015)
                else:
                    raise AssertionError("Live NFT worker did not refresh posted messages")
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
                assert worker.done()
            finally:
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
                await db.close()
    asyncio.run(run())


if __name__ == "__main__":
    test_original_and_reposted_messages_refresh_with_real_ticket_stats()
    test_manual_update_refreshes_all_channel_posts()
    test_background_worker_retries_and_stops_cleanly()
    print("NFT channel live refresh tests passed")
