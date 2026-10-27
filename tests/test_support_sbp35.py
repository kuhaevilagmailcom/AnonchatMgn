"""Smoke tests for the fixed 35 RUB SBP support checkout."""
from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from anonchat import keyboards as K
from anonchat.handlers.support import QUICK_SBP_AMOUNT_RUB, _send_support_sbp_payment


def test_fixed_sbp_button_only_when_provider_enabled() -> None:
    enabled = K.support_method_keyboard(sbp_enabled=True)
    disabled = K.support_method_keyboard(sbp_enabled=False)
    callbacks = [
        btn.callback_data for row in enabled.inline_keyboard for btn in row
    ]
    no_provider = [
        btn.callback_data for row in disabled.inline_keyboard for btn in row
    ]
    assert K.CB_SUPPORT_SBP_35 in callbacks
    assert K.CB_SUPPORT_SBP_35 not in no_provider
    assert QUICK_SBP_AMOUNT_RUB == 35


def test_sbp35_uses_support_order_without_adding_any_nft_entry() -> None:
    async def run() -> None:
        ctx = SimpleNamespace(
            cfg=SimpleNamespace(rollypay_enabled=True),
            user_id=123,
            reply=AsyncMock(),
        )
        db = SimpleNamespace(
            create_sbp_order=AsyncMock(return_value="creating:support-test"),
            attach_sbp_provider_payment=AsyncMock(),
            set_sbp_status=AsyncMock(),
        )
        with patch(
            "anonchat.handlers.support.create_payment",
            new_callable=AsyncMock,
            return_value={
                "payment_id": "payment-123",
                "pay_url": "https://provider.example/pay/123",
            },
        ) as create:
            await _send_support_sbp_payment(ctx, db, QUICK_SBP_AMOUNT_RUB)

        assert db.create_sbp_order.await_args.kwargs["kind"] == "support"
        assert db.create_sbp_order.await_args.kwargs["amount_rub"] == 35
        assert create.await_args.kwargs["amount"] == Decimal(35)
        assert db.attach_sbp_provider_payment.await_count == 1
        assert ctx.reply.await_count == 1
        message, markup = ctx.reply.await_args.args
        assert "35 ₽" in message
        assert "не покупка NFT-билета" in message
        buttons = [button for row in markup.inline_keyboard for button in row]
        assert any(button.url == "https://provider.example/pay/123" for button in buttons)
        assert any(
            button.callback_data == K.CB_SUPPORT_SBP_CHECK_PREFIX + "payment-123"
            for button in buttons
        )

    asyncio.run(run())


def test_sbp35_provider_disabled_never_creates_payment() -> None:
    async def run() -> None:
        ctx = SimpleNamespace(
            cfg=SimpleNamespace(rollypay_enabled=False),
            user_id=123,
            reply=AsyncMock(),
        )
        db = SimpleNamespace(
            create_sbp_order=AsyncMock(),
            attach_sbp_provider_payment=AsyncMock(),
        )
        await _send_support_sbp_payment(ctx, db, 35)
        db.create_sbp_order.assert_not_awaited()
        assert "СБП временно недоступна" in ctx.reply.await_args.args[0]

    asyncio.run(run())
