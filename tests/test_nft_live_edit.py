"""Live NFT raffle settings: mutable price/deadline and immutable invoice amounts."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiosqlite

from anonchat.db import Database
from anonchat.handlers.nft_giveaway import (
    _active, _count, _issue_paid_ticket, _price_for_order, _save_campaign,
    _start_ticket_purchase, _update_active_campaign,
)
from anonchat.handlers.nft_setup import (
    _parse_mgn_date, nft_admin_date_command, nft_admin_edit_prompt,
    nft_admin_price_command,
)


def test_price_and_deadline_change_without_renumbering_old_orders() -> None:
    async def scenario() -> None:
        with TemporaryDirectory() as temp:
            db = await Database(Path(temp) / "live.db").start()
            try:
                await db.ensure_user(111, "buyer", "Buyer")
                g = await _save_campaign(
                    db, "https://t.me/nft/Test", int(time.time()) + 3600, "soon",
                )
                assert g.price_rub == 30
                assert (await _active(db)).price_rub == 30

                async def invoice(order: str, amount: int) -> str:
                    local = await db.create_sbp_order(
                        order_id=order, user_id=111,
                        kind=f"nft_ticket:{g.campaign}", amount_rub=amount,
                    )
                    pid = "payment-" + order
                    await db.attach_sbp_provider_payment(
                        local, pid, "https://pay.example/" + order,
                    )
                    return pid

                legacy = await invoice("legacy-35", 35)
                previous = await invoice("old-price50", 100)
                current = await invoice("new-price30", 90)
                assert _price_for_order("legacy-35") == 35
                assert _price_for_order("old-price50") == 50
                assert _price_for_order("new-price30") == 30

                changed = await _update_active_campaign(db, price_rub=75)
                assert changed.price_rub == 75
                assert (await _active(db)).price_rub == 75
                new_date = int(time.time()) + 7200
                updated = await _update_active_campaign(
                    db, close_at=new_date, deadline="new deadline",
                )
                assert updated.close_at == new_date
                assert updated.price_rub == 75
                assert (await _active(db)).deadline == "new deadline"

                buyer = SimpleNamespace(
                    user_id=111, cfg=SimpleNamespace(rollypay_enabled=True),
                    restricted=AsyncMock(return_value=False), reply=AsyncMock(),
                )
                with patch(
                    "anonchat.handlers.nft_giveaway.create_payment",
                    new_callable=AsyncMock,
                    return_value={
                        "payment_id": "payment-dynamic",
                        "pay_url": "https://pay.example/dynamic",
                    },
                ) as create:
                    await _start_ticket_purchase(buyer, db, 2)
                    assert int(create.await_args.kwargs["amount"]) == 150
                    order = await db.get_sbp_payment("payment-dynamic")
                    assert order["order_id"].endswith("-price75")
                    assert int(order["amount_rub"]) == 150

                await _update_active_campaign(db, price_rub=80)
                for pid, first in (
                    (legacy, 1), (previous, 2), (current, 4),
                    ("payment-dynamic", 7),
                ):
                    assert await _issue_paid_ticket(db.path, pid) == (first, True)
                    assert await _issue_paid_ticket(db.path, pid) == (first, False)
                assert await _count(db.path, g.campaign) == 8

                for invalid in (0, 10001):
                    try:
                        await _update_active_campaign(db, price_rub=invalid)
                        assert False, "invalid price accepted"
                    except ValueError:
                        pass
                try:
                    await _update_active_campaign(
                        db, close_at=int(time.time()) - 10, deadline="past",
                    )
                    assert False, "past deadline accepted"
                except ValueError:
                    pass
            finally:
                await db.close()
    asyncio.run(scenario())


def test_existing_campaign_table_is_migrated() -> None:
    async def scenario() -> None:
        with TemporaryDirectory() as temp:
            db = await Database(Path(temp) / "old.db").start()
            try:
                async with aiosqlite.connect(db.path) as con:
                    await con.execute(
                        "CREATE TABLE nft_giveaway_campaigns ("
                        "campaign TEXT PRIMARY KEY,prize TEXT NOT NULL,"
                        "close_at INTEGER NOT NULL,deadline TEXT NOT NULL,"
                        "rules_url TEXT NOT NULL,created_at INTEGER NOT NULL)"
                    )
                    await con.execute(
                        "INSERT INTO nft_giveaway_campaigns VALUES (?,?,?,?,?,?)",
                        ("older", "https://t.me/nft/Older",
                         int(time.time()) + 300, "soon", "", int(time.time())),
                    )
                    await con.commit()
                g = await _active(db)
                assert g.campaign == "older"
                assert g.price_rub == 30
                assert (await _update_active_campaign(db, price_rub=42)).price_rub == 42
            finally:
                await db.close()
    asyncio.run(scenario())


def test_owner_can_edit_from_commands_and_panel() -> None:
    async def scenario() -> None:
        with TemporaryDirectory() as temp:
            db = await Database(Path(temp) / "commands.db").start()
            try:
                await _save_campaign(
                    db, "https://t.me/nft/Owner", int(time.time()) + 3600, "soon",
                )
                ctx = SimpleNamespace(
                    is_owner=True, bot=SimpleNamespace(),
                    reply=AsyncMock(), ack=AsyncMock(),
                )
                state = SimpleNamespace(set_state=AsyncMock(), clear=AsyncMock())
                date = (datetime.now(timezone(timedelta(hours=5))) +
                        timedelta(days=2)).strftime("%d.%m.%Y %H:%M")
                expected_ts, expected_text = _parse_mgn_date(date)
                with patch(
                    "anonchat.nft_channel_live.refresh_campaign_posts",
                    new_callable=AsyncMock,
                ):
                    await nft_admin_price_command(
                        SimpleNamespace(text="/nft_price 45"), ctx, state, db,
                    )
                    assert (await _active(db)).price_rub == 45
                    await nft_admin_date_command(
                        SimpleNamespace(text="/nft_date " + date), ctx, state, db,
                    )
                    assert (await _active(db)).close_at == expected_ts
                    assert (await _active(db)).deadline == expected_text
                    await nft_admin_edit_prompt(
                        SimpleNamespace(data="nft:admin:price"), ctx, state, db,
                    )
                    state.set_state.assert_awaited()
                    denied = SimpleNamespace(
                        is_owner=False, ack=AsyncMock(), reply=AsyncMock(),
                    )
                    await nft_admin_edit_prompt(
                        SimpleNamespace(data="nft:admin:date"), denied, state, db,
                    )
                    denied.ack.assert_awaited_once_with(
                        "Нет доступа", alert=True,
                    )
            finally:
                await db.close()
    asyncio.run(scenario())


if __name__ == "__main__":
    test_price_and_deadline_change_without_renumbering_old_orders()
    test_existing_campaign_table_is_migrated()
    test_owner_can_edit_from_commands_and_panel()
    print("NFT live edits passed")
