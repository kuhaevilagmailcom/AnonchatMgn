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
    _keyboard, _save_campaign, _start_ticket_purchase, _ticket_numbers, nft_send,
    _active, _finish_now, _pending_nft_orders, nft_finish_preview, nft_finish_confirm,
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


def test_admin_can_repeat_campaign_broadcast_from_a_new_preview() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            db = await Database(Path(temp) / "test.db").start()
            try:
                await db.ensure_user(123, "owner", "Owner")
                await db.ensure_user(456, "buyer", "Buyer")
                await _save_campaign(
                    db, "https://t.me/nft/Test-repeat", int(time.time()) + 300, "soon"
                )
                ctx = SimpleNamespace(
                    user_id=123,
                    is_owner=True,
                    can=lambda _permission: True,
                    ack=AsyncMock(),
                    reply=AsyncMock(),
                )

                first_preview = SimpleNamespace(
                    message=SimpleNamespace(message_id=101), ack=AsyncMock()
                )
                second_preview = SimpleNamespace(
                    message=SimpleNamespace(message_id=102), ack=AsyncMock()
                )
                await nft_send(first_preview, ctx, db)
                await nft_send(first_preview, ctx, db)
                await nft_send(second_preview, ctx, db)

                row = await db._fetchone(
                    "SELECT COUNT(*) AS count FROM admin_broadcast_jobs"
                )
                assert row and int(row["count"]) == 2
            finally:
                await db.close()
    asyncio.run(run())


def test_owner_can_end_wrong_date_immediately_and_winner_is_fixed() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            db = await Database(Path(temp) / "test.db").start()
            try:
                await db.ensure_user(111, None, "Buyer")
                await db.ensure_user(222, None, "Buyer")
                future = int(time.time()) + 86400 * 30
                g = await _save_campaign(
                    db, "https://t.me/nft/Early", future, "29.11.2026 20:00 МГН",
                )
                for idx, uid in enumerate((111, 222), start=1):
                    local = await db.create_sbp_order(
                        order_id=f"early-{idx}", user_id=uid,
                        kind=f"nft_ticket:{g.campaign}", amount_rub=35,
                    )
                    payment_id = f"payment-early-{idx}"
                    await db.attach_sbp_provider_payment(
                        local, payment_id, f"https://pay.example/{idx}",
                    )
                    await _issue_paid_ticket(db.path, payment_id)
                assert (await _active(db)).close_at == future
                assert await _pending_nft_orders(db.path, g.campaign) == 0
                result, winner, remaining = await _finish_now(db.path, g)
                assert result == "drawn"
                assert winner is not None and winner[0] in (111, 222)
                assert winner[1] in (1, 2) and winner[2] == 2
                assert remaining == 0
                assert (await _active(db)).close_at <= time.time()
                again_result, again_winner, again_pending = await _finish_now(db.path, await _active(db))
                assert again_result == "already_drawn"
                assert again_winner == winner
                assert again_pending == 0
                assert await _draw(db.path, await _active(db)) == winner
                # The original future deadline is now overridden in storage.
                stored = await db._fetchone(
                    "SELECT close_at FROM nft_giveaway_campaigns WHERE campaign=?",
                    (g.campaign,),
                )
                assert stored and int(stored["close_at"]) < future
            finally:
                await db.close()
    asyncio.run(run())


def test_early_end_stops_intake_but_waits_for_pending_invoices() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            db = await Database(Path(temp) / "test.db").start()
            try:
                await db.ensure_user(111, None, "Buyer")
                await db.ensure_user(222, None, "Buyer")
                g = await _save_campaign(
                    db, "https://t.me/nft/Pending",
                    int(time.time()) + 36000, "soon",
                )
                pending_order = await db.create_sbp_order(
                    order_id="unfinished-order", user_id=111,
                    kind=f"nft_ticket:{g.campaign}", amount_rub=35,
                )
                await db.attach_sbp_provider_payment(
                    pending_order, "unfinished-payment", "https://pay.example/unfinished",
                )
                status, winner, n = await _finish_now(db.path, g)
                assert status == "pending" and winner is None and n == 1
                assert (await _active(db)).close_at < time.time()
                # An external invoice already existed; verifying a completed
                # payment must still be possible until winner selection.
                assert await _issue_paid_ticket(db.path, "unfinished-payment") == (1, True)
                status, winner, n = await _finish_now(db.path, await _active(db))
                assert status == "drawn" and winner == (111, 1, 1)
                assert n == 0
            finally:
                await db.close()
    asyncio.run(run())


def test_purchase_does_not_create_provider_invoice_after_early_close() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            db = await Database(Path(temp) / "test.db").start()
            try:
                await db.ensure_user(111, None, "Buyer")
                g = await _save_campaign(
                    db, "https://t.me/nft/Cutoff",
                    int(time.time()) + 36000, "soon",
                )
                assert (await _finish_now(db.path, g))[0] == "empty"
                ctx = SimpleNamespace(
                    user_id=111, cfg=SimpleNamespace(rollypay_enabled=True),
                    restricted=AsyncMock(return_value=False),
                    reply=AsyncMock(),
                )
                with patch(
                    "anonchat.handlers.nft_giveaway.create_payment",
                    new_callable=AsyncMock,
                ) as create:
                    await _start_ticket_purchase(ctx, db)
                create.assert_not_awaited()
                assert "завершена" in ctx.reply.await_args.args[0]
            finally:
                await db.close()
    asyncio.run(run())


def test_early_finish_requires_owner_confirmation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            db = await Database(Path(temp) / "test.db").start()
            try:
                g = await _save_campaign(
                    db, "https://t.me/nft/Admin",
                    int(time.time()) + 36000, "soon",
                )
                outsider = SimpleNamespace(
                    is_owner=False, reply=AsyncMock(), ack=AsyncMock(),
                )
                fake_message = SimpleNamespace(chat=SimpleNamespace(type="private"))
                await nft_finish_preview(fake_message, outsider, db)
                outsider.reply.assert_not_awaited()
                fake_event = SimpleNamespace(
                    data=f"nft:finish:{g.campaign}", message=fake_message,
                )
                await nft_finish_confirm(fake_event, outsider, db)
                outsider.ack.assert_awaited()
                assert (await _active(db)).close_at == g.close_at

                owner = SimpleNamespace(
                    is_owner=True, reply=AsyncMock(), ack=AsyncMock(),
                )
                await nft_finish_preview(fake_message, owner, db)
                owner.reply.assert_awaited_once()
                buttons = owner.reply.await_args.args[1].inline_keyboard
                assert buttons[0][0].callback_data == f"nft:finish:{g.campaign}"
                assert (await _active(db)).close_at == g.close_at
                # No result until pressing the confirmation button.
            finally:
                await db.close()
    asyncio.run(run())


if __name__ == "__main__":
    test_nft_keyboard_sells_ticket_and_old_sbp35_support_is_gone()
    test_each_verified_payment_issues_one_ticket_and_retries_are_idempotent()
    test_buy_button_creates_35_rub_rollypay_ticket_order()
    test_non_ticket_or_wrong_price_payment_never_issues_ticket()
    test_draw_uses_paid_tickets_and_is_stable()
    test_nft_url_validation()
    test_admin_can_repeat_campaign_broadcast_from_a_new_preview()
    test_owner_can_end_wrong_date_immediately_and_winner_is_fixed()
    test_early_end_stops_intake_but_waits_for_pending_invoices()
    test_purchase_does_not_create_provider_invoice_after_early_close()
    test_early_finish_requires_owner_confirmation()
    print("ok NFT tickets: RollyPay 35 RUB, multiple tickets, idempotency and draw")
