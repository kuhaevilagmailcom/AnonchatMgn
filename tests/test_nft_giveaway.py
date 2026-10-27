"""NFT raffle: every verified 35 RUB payment creates one durable ticket."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from anonchat.commands import COMMANDS
from anonchat.db import Database
from anonchat.handlers.nft_giveaway import (
    TICKET_PRICE_RUB, Giveaway, _count, _draw, _issue_paid_ticket,
    _keyboard, _save_campaign, _start_ticket_purchase, _ticket_numbers,
    valid_nft_url,
)
from anonchat import keyboards as K


def test_nft_keyboard_sells_ticket_and_old_sbp35_support_is_gone() -> None:
    labels = [button.text for row in _keyboard(True).inline_keyboard for button in row]
    callbacks = [button.callback_data for row in _keyboard(True).inline_keyboard for button in row]
    support_labels = [button.text for row in K.support_method_keyboard(sbp_enabled=True).inline_keyboard for button in row]
    assert "Купить билет · 35 ₽" in labels
    assert "nft:buy" in callbacks
    assert "Поддержать 35 ₽ · СБП" not in support_labels
    assert all(command.command != "sbp35" for command in COMMANDS)
    assert TICKET_PRICE_RUB == 35


def test_each_verified_payment_issues_one_ticket_and_retries_are_idempotent() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            db = await Database(Path(temp) / "test.db").start()
            try:
                await db.ensure_user(123, "buyer", "Buyer")
                await db.ensure_user(456, "other", "Other")
                g = await _save_campaign(db, "https://t.me/nft/Test-1", int(time.time()) + 300, "01.11.2026 20:00 МГН")

                async def paid(user_id: int, suffix: str) -> str:
                    local = await db.create_sbp_order(order_id=f"nft-{suffix}", user_id=user_id, kind=f"nft_ticket:{g.campaign}", amount_rub=35)
                    payment_id = f"payment-{suffix}"
                    await db.attach_sbp_provider_payment(local, payment_id, f"https://pay.example/{suffix}")
                    return payment_id

                first = await paid(123, "one")
                assert await _issue_paid_ticket(db.path, first) == (1, True)
                assert await _issue_paid_ticket(db.path, first) == (1, False)
                second = await paid(123, "two")
                assert await _issue_paid_ticket(db.path, second) == (2, True)
                third = await paid(456, "three")
                assert await _issue_paid_ticket(db.path, third) == (3, True)
                assert await _ticket_numbers(db.path, g.campaign, 123) == [1, 2]
                assert await _count(db.path, g.campaign) == 3
                row = await db.get_sbp_payment(first)
                assert row and row["status"] == "paid"
            finally:
                await db.close()
    asyncio.run(run())


def test_buy_button_creates_35_rub_rollypay_ticket_order() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            db = await Database(Path(temp) / "test.db").start()
            try:
                await db.ensure_user(123, "buyer", "Buyer")
                g = await _save_campaign(
                    db, "https://t.me/nft/Test-buy", int(time.time()) + 300, "soon"
                )
                ctx = SimpleNamespace(
                    user_id=123,
                    cfg=SimpleNamespace(rollypay_enabled=True),
                    restricted=AsyncMock(return_value=False),
                    reply=AsyncMock(),
                )
                with patch(
                    "anonchat.handlers.nft_giveaway.create_payment",
                    new_callable=AsyncMock,
                    return_value={
                        "payment_id":"provider-payment",
                        "pay_url":"https://pay.example/ticket",
                    },
                ) as create:
                    await _start_ticket_purchase(ctx, db)
                local = await db.get_sbp_payment("provider-payment")
                assert local and local["kind"] == f"nft_ticket:{g.campaign}"
                assert int(local["amount_rub"]) == 35
                assert create.await_args.kwargs["amount"].as_tuple().exponent == 0
                assert int(create.await_args.kwargs["amount"]) == 35
                message, markup = ctx.reply.await_args.args
                assert "35 ₽" in message
                assert any(
                    button.url == "https://pay.example/ticket"
                    for row in markup.inline_keyboard for button in row
                )
            finally:
                await db.close()
    asyncio.run(run())


def test_non_ticket_or_wrong_price_payment_never_issues_ticket() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            db = await Database(Path(temp) / "test.db").start()
            try:
                await db.ensure_user(123, None, "Buyer")
                for kind, amount, suffix in (("support", 35, "support"), ("nft_ticket:campaign", 34, "wrong-price")):
                    local = await db.create_sbp_order(order_id=f"order-{suffix}", user_id=123, kind=kind, amount_rub=amount)
                    await db.attach_sbp_provider_payment(local, f"payment-{suffix}", f"https://pay.example/{suffix}")
                    try:
                        await _issue_paid_ticket(db.path, f"payment-{suffix}")
                        assert False, "Invalid payment unexpectedly issued a ticket"
                    except ValueError:
                        pass
                assert await _count(db.path, "campaign") == 0
            finally:
                await db.close()
    asyncio.run(run())


def test_draw_uses_paid_tickets_and_is_stable() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            db = await Database(Path(temp) / "test.db").start()
            try:
                for user_id in (111, 222):
                    await db.ensure_user(user_id, None, "Buyer")
                g = await _save_campaign(db, "https://t.me/nft/Test-2", int(time.time()) + 60, "soon")
                for index, user_id in enumerate((111, 222), 1):
                    local = await db.create_sbp_order(order_id=f"draw-{index}", user_id=user_id, kind=f"nft_ticket:{g.campaign}", amount_rub=35)
                    payment_id = f"draw-payment-{index}"
                    await db.attach_sbp_provider_payment(local, payment_id, "https://pay.example")
                    await _issue_paid_ticket(db.path, payment_id)
                closed = Giveaway(g.campaign, g.nft_url, int(time.time()) - 1, g.deadline)
                winner = await _draw(db.path, closed)
                assert winner is not None and winner[0] in (111, 222) and winner[1] in (1, 2) and winner[2] == 2
                assert await _draw(db.path, closed) == winner
            finally:
                await db.close()
    asyncio.run(run())


def test_nft_url_validation() -> None:
    assert valid_nft_url("https://t.me/nft/Test-1")
    assert not valid_nft_url("javascript:alert(1)")
    assert not valid_nft_url("http://t.me/nft/Test-1")
    assert not valid_nft_url("https://t.me/nft/Test-1\nInjected")


if __name__ == "__main__":
    test_nft_keyboard_sells_ticket_and_old_sbp35_support_is_gone()
    test_each_verified_payment_issues_one_ticket_and_retries_are_idempotent()
    test_buy_button_creates_35_rub_rollypay_ticket_order()
    test_non_ticket_or_wrong_price_payment_never_issues_ticket()
    test_draw_uses_paid_tickets_and_is_stable()
    test_nft_url_validation()
    print("ok NFT tickets: RollyPay 35 RUB, multiple tickets, idempotency and draw")
