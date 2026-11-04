"""NFT bulk ticket purchase: quantity UI, exact amount and atomic issuance."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from anonchat.db import Database
from anonchat.handlers.nft_giveaway import (
    NFTTicketQuantity, _issue_paid_ticket, _parse_quantity, _quantity_for_amount,
    _ticket_numbers, _raffle_stats, _save_campaign, _start_ticket_purchase,
    nft_buy, nft_buy_cancel, nft_check_payment, nft_enter_quantity, _count,
)


def test_quantity_input_bounds_and_price() -> None:
    for text, quantity in (("1", 1), ("05", 5), ("99", 99), (" 9 ", 9)):
        assert _parse_quantity(text) == quantity
        assert _quantity_for_amount(quantity * 35) == quantity
    for text in ("", "0", "100", "1000", "-1", "1.5", "1,5", "1 0", "abc", "9999999999999"):
        assert _parse_quantity(text) is None
    for amount in (0, 1, 34, 36, 3500, -35):
        try:
            _quantity_for_amount(amount)
            raise AssertionError(f"Accepted invalid amount {amount}")
        except ValueError:
            pass


def test_quantity_prompt_and_cancel_do_not_create_payment() -> None:
    async def run() -> None:
        with TemporaryDirectory() as tmp:
            db = await Database(Path(tmp) / "tickets.sqlite").start()
            try:
                await db.ensure_user(111, None, "Buyer")
                await _save_campaign(
                    db, "https://t.me/nft/Gift", int(time.time()) + 1800, "soon",
                )
                state = SimpleNamespace(set_state=AsyncMock(), clear=AsyncMock())
                ctx = SimpleNamespace(
                    user_id=111, cfg=SimpleNamespace(rollypay_enabled=True),
                    restricted=AsyncMock(return_value=False),
                    reply=AsyncMock(), ack=AsyncMock(),
                )
                event = SimpleNamespace(data="nft:buy")
                with patch(
                    "anonchat.handlers.nft_giveaway.create_payment",
                    new_callable=AsyncMock,
                ) as create:
                    await nft_buy(event, ctx, db, state)
                    state.set_state.assert_awaited_once_with(NFTTicketQuantity.waiting)
                    text, keyboard = ctx.reply.await_args.args
                    assert "от 1 до 99" in text
                    assert "35 ₽" in text
                    assert keyboard.inline_keyboard[0][0].callback_data == "nft:buy_cancel"
                    create.assert_not_awaited()
                    await nft_buy_cancel(event, ctx, state)
                    state.clear.assert_awaited_once()
                    create.assert_not_awaited()
            finally:
                await db.close()
    asyncio.run(run())


def test_invalid_quantity_does_not_charge_and_valid_quantity_creates_exact_invoice() -> None:
    async def run() -> None:
        with TemporaryDirectory() as tmp:
            db = await Database(Path(tmp) / "tickets.sqlite").start()
            try:
                await db.ensure_user(111, None, "Buyer")
                g = await _save_campaign(
                    db, "https://t.me/nft/Gift", int(time.time()) + 1800, "soon",
                )
                ctx = SimpleNamespace(
                    user_id=111, cfg=SimpleNamespace(rollypay_enabled=True),
                    restricted=AsyncMock(return_value=False),
                    reply=AsyncMock(), ack=AsyncMock(),
                )
                state = SimpleNamespace(clear=AsyncMock())
                with patch(
                    "anonchat.handlers.nft_giveaway.create_payment",
                    new_callable=AsyncMock,
                    return_value={"payment_id": "bulk-5", "pay_url": "https://pay.example/bulk-5"},
                ) as create:
                    for bad in ("0", "100", "2.5", "abc"):
                        await nft_enter_quantity(SimpleNamespace(text=bad), ctx, db, state)
                        assert "от 1 до 99" in ctx.reply.await_args.args[0]
                        state.clear.assert_not_awaited()
                        create.assert_not_awaited()
                    await nft_enter_quantity(SimpleNamespace(text="5"), ctx, db, state)
                    state.clear.assert_awaited_once()
                    create.assert_awaited_once()
                    assert int(create.await_args.kwargs["amount"]) == 175
                    assert "5 билет" in create.await_args.kwargs["description"]
                    payment = await db.get_sbp_payment("bulk-5")
                    assert payment is not None
                    assert payment["kind"] == f"nft_ticket:{g.campaign}"
                    assert int(payment["amount_rub"]) == 175
                    assert await _count(db.path, g.campaign) == 0
                    text, keyboard = ctx.reply.await_args.args
                    assert "Количество: <b>5</b>" in text
                    assert "К оплате: <b>175 ₽</b>" in text
                    assert keyboard.inline_keyboard[0][0].text == "Оплатить 175 ₽"
                    assert keyboard.inline_keyboard[1][0].callback_data == "nft:check:bulk-5"
            finally:
                await db.close()
    asyncio.run(run())


def test_full_99_ticket_payment_is_issued_atomically_and_only_once() -> None:
    async def run() -> None:
        with TemporaryDirectory() as tmp:
            db = await Database(Path(tmp) / "tickets.sqlite").start()
            try:
                await db.ensure_user(111, None, "Buyer")
                await db.ensure_user(222, None, "Other")
                g = await _save_campaign(
                    db, "https://t.me/nft/Gift", int(time.time()) + 1800, "soon",
                )
                async def make_payment(uid, ident, amount):
                    local = await db.create_sbp_order(
                        order_id=ident, user_id=uid, kind=f"nft_ticket:{g.campaign}",
                        amount_rub=amount,
                    )
                    await db.attach_sbp_provider_payment(
                        local, ident + "-provider", "https://pay.example/" + ident,
                    )
                    return ident + "-provider"
                previous = await make_payment(222, "legacy-one", 35)
                assert await _issue_paid_ticket(db.path, previous) == (1, True)
                bulk = await make_payment(111, "bulk-99", 3465)
                first, fresh = await _issue_paid_ticket(db.path, bulk)
                assert (first, fresh) == (2, True)
                assert await _ticket_numbers(db.path, g.campaign, 111) == list(range(2, 101))
                assert await _count(db.path, g.campaign) == 100
                stats = await _raffle_stats(db.path, g.campaign)
                assert stats.tickets == 100 and stats.participants == 2
                results = await asyncio.gather(*(
                    _issue_paid_ticket(db.path, bulk) for _ in range(3)
                ))
                assert results == [(2, False)] * 3
                assert await _count(db.path, g.campaign) == 100
                payment = await db.get_sbp_payment(bulk)
                assert payment["status"] == "paid"
            finally:
                await db.close()
    asyncio.run(run())


def test_verified_bulk_payment_refuses_wrong_remote_amount_and_other_user() -> None:
    async def run() -> None:
        with TemporaryDirectory() as tmp:
            db = await Database(Path(tmp) / "tickets.sqlite").start()
            try:
                await db.ensure_user(111, None, "Buyer")
                await db.ensure_user(222, None, "Other")
                g = await _save_campaign(
                    db, "https://t.me/nft/Gift", int(time.time()) + 1800, "soon",
                )
                local = await db.create_sbp_order(
                    order_id="bulk-verify", user_id=111, kind=f"nft_ticket:{g.campaign}",
                    amount_rub=175,
                )
                await db.attach_sbp_provider_payment(
                    local, "verified-bulk", "https://pay.example/bulk",
                )
                event = SimpleNamespace(data="nft:check:verified-bulk")
                buyer = SimpleNamespace(
                    user_id=111, cfg=SimpleNamespace(rollypay_enabled=True),
                    ack=AsyncMock(), reply=AsyncMock(),
                )
                wrong_user = SimpleNamespace(
                    user_id=222, cfg=SimpleNamespace(rollypay_enabled=True),
                    ack=AsyncMock(), reply=AsyncMock(),
                )
                with patch(
                    "anonchat.handlers.nft_giveaway.get_payment",
                    new_callable=AsyncMock,
                ) as get_payment:
                    await nft_check_payment(event, wrong_user, db)
                    get_payment.assert_not_awaited()
                    assert await _count(db.path, g.campaign) == 0
                    get_payment.return_value = {
                        "payment_id": "verified-bulk", "order_id": "bulk-verify",
                        "amount": "35", "currency": "RUB", "status": "paid",
                    }
                    await nft_check_payment(event, buyer, db)
                    assert await _count(db.path, g.campaign) == 0
                    assert "не совпали" in buyer.ack.await_args.args[0]
                    get_payment.return_value = {
                        "payment_id": "verified-bulk", "order_id": "bulk-verify",
                        "amount": "175.00", "currency": "RUB", "status": "paid",
                    }
                    await nft_check_payment(event, buyer, db)
                    assert await _count(db.path, g.campaign) == 5
                    assert "№1–№5" in buyer.reply.await_args.args[0]
                    await nft_check_payment(event, buyer, db)
                    assert await _count(db.path, g.campaign) == 5
            finally:
                await db.close()
    asyncio.run(run())


if __name__ == "__main__":
    test_quantity_input_bounds_and_price()
    test_quantity_prompt_and_cancel_do_not_create_payment()
    test_invalid_quantity_does_not_charge_and_valid_quantity_creates_exact_invoice()
    test_full_99_ticket_payment_is_issued_atomically_and_only_once()
    test_verified_bulk_payment_refuses_wrong_remote_amount_and_other_user()
    print("NFT 1-99 ticket purchase tests passed")
