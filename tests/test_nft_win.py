"""Owner-only /win command never modifies raffle state or sends to third parties."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from anonchat.handlers.nft_win import (
    NFTManualResult, format_manual_win, nft_manual_action, nft_manual_start,
    nft_manual_tickets, nft_manual_user_id, nft_manual_win,
)
from anonchat.commands import ADMIN_VISIBLE


def test_manual_winner_message() -> None:
    text = format_manual_win(123456789, 17)
    assert "Победитель: ID <code>123456789</code>" in text
    assert "Билетов у победителя: <b>17</b>" in text
    assert "Ручной итог администратора" in text
    assert all(command.command != "win" for command in ADMIN_VISIBLE)


def test_owner_only_private_win_message() -> None:
    async def run() -> None:
        owner = SimpleNamespace(is_owner=True, reply=AsyncMock())
        outsider = SimpleNamespace(is_owner=False, reply=AsyncMock())
        msg = SimpleNamespace(text="/win 123456789 17", chat=SimpleNamespace(type="private"))
        await nft_manual_win(msg, owner)
        owner.reply.assert_awaited_once_with(format_manual_win(123456789, 17))
        owner.reply.reset_mock()
        await nft_manual_win(msg, outsider)
        outsider.reply.assert_not_awaited()
        await nft_manual_win(
            SimpleNamespace(text="/win 123456789 17", chat=SimpleNamespace(type="group")),
            owner,
        )
        owner.reply.assert_not_awaited()
    asyncio.run(run())


def test_invalid_win_id_never_announces_winner() -> None:
    async def run() -> None:
        ctx = SimpleNamespace(is_owner=True, reply=AsyncMock())
        for value in ["/win", "/win abc 5", "/win 0 5", "/win -1 5", "/win 1<script> 5", "/win 123 0"]:
            ctx.reply.reset_mock()
            await nft_manual_win(
                SimpleNamespace(text=value, chat=SimpleNamespace(type="private")), ctx
            )
            text = ctx.reply.await_args.args[0]
            assert "Пример:" in text
            assert "Розыгрыш завершён" not in text
        ctx.reply.reset_mock()
        await nft_manual_win(
            SimpleNamespace(text="/win 88888888 12", chat=SimpleNamespace(type="private")), ctx
        )
        assert "Билетов у победителя: <b>12</b>" in ctx.reply.await_args.args[0]
    asyncio.run(run())


def test_button_flow_collects_id_and_ticket_count_before_confirmation() -> None:
    async def run() -> None:
        ctx = SimpleNamespace(
            is_owner=True, ack=AsyncMock(), reply=AsyncMock(), edit=AsyncMock(),
        )
        state = SimpleNamespace(
            set_state=AsyncMock(), update_data=AsyncMock(),
            get_data=AsyncMock(return_value={"user_id": 123456789}), clear=AsyncMock(),
        )
        event = SimpleNamespace(
            data="nft:admin:manual_result",
            message=SimpleNamespace(chat=SimpleNamespace(type="private")),
        )
        await nft_manual_start(event, ctx, state)
        state.set_state.assert_awaited_with(NFTManualResult.user_id)

        db = SimpleNamespace(get_user=AsyncMock(return_value={"user_id": 123456789}))
        await nft_manual_user_id(SimpleNamespace(text="123456789"), ctx, state, db)
        state.update_data.assert_awaited_with(user_id=123456789)
        state.set_state.assert_awaited_with(NFTManualResult.tickets)

        await nft_manual_tickets(SimpleNamespace(text="17"), ctx, state)
        assert "Билетов у победителя: <b>17</b>" in ctx.reply.await_args.args[0]

        state.get_data.return_value = {"user_id": 123456789, "tickets": 17}
        event.data = "nft:manual:confirm"
        await nft_manual_action(event, ctx, state)
        state.clear.assert_awaited()
        assert "Победитель: ID <code>123456789</code>" in ctx.edit.await_args.args[0]
    asyncio.run(run())


if __name__ == "__main__":
    test_manual_winner_message()
    test_owner_only_private_win_message()
    test_invalid_win_id_never_announces_winner()
    print("Owner NFT winner command tests passed")
