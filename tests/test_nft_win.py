"""Owner-only /win command never modifies raffle state or sends to third parties."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from anonchat.handlers.nft_win import format_manual_win, nft_manual_win
from anonchat.commands import ADMIN_VISIBLE


def test_manual_winner_message() -> None:
    assert format_manual_win(123456789) == (
        "🏆 <b>ID <code>123456789</code> выиграл NFT в конкурсе!</b>"
    )
    assert any(command.command == "win" for command in ADMIN_VISIBLE)


def test_owner_only_private_win_message() -> None:
    async def run() -> None:
        owner = SimpleNamespace(is_owner=True, reply=AsyncMock())
        outsider = SimpleNamespace(is_owner=False, reply=AsyncMock())
        msg = SimpleNamespace(text="/win 123456789", chat=SimpleNamespace(type="private"))
        await nft_manual_win(msg, owner)
        owner.reply.assert_awaited_once_with(format_manual_win(123456789))
        owner.reply.reset_mock()
        await nft_manual_win(msg, outsider)
        outsider.reply.assert_not_awaited()
        await nft_manual_win(
            SimpleNamespace(text="/win 123456789", chat=SimpleNamespace(type="group")),
            owner,
        )
        owner.reply.assert_not_awaited()
    asyncio.run(run())


def test_invalid_win_id_never_announces_winner() -> None:
    async def run() -> None:
        ctx = SimpleNamespace(is_owner=True, reply=AsyncMock())
        for value in ["/win", "/win abc", "/win 0", "/win -1", "/win 1<script>", "/win 123 456"]:
            ctx.reply.reset_mock()
            await nft_manual_win(
                SimpleNamespace(text=value, chat=SimpleNamespace(type="private")), ctx
            )
            text = ctx.reply.await_args.args[0]
            assert "Пример:" in text
            assert "выиграл" not in text
        ctx.reply.reset_mock()
        await nft_manual_win(
            SimpleNamespace(text="/win 88888888", chat=SimpleNamespace(type="private")), ctx
        )
        assert "выиграл NFT в конкурсе" in ctx.reply.await_args.args[0]
    asyncio.run(run())


if __name__ == "__main__":
    test_manual_winner_message()
    test_owner_only_private_win_message()
    test_invalid_win_id_never_announces_winner()
    print("Owner NFT winner command tests passed")
