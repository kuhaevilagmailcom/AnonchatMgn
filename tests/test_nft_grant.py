"""Manual NFT ticket grant regressions: authorization, audit and one-shot mint."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite

from anonchat.db import Database
from anonchat.commands import ADMIN_VISIBLE
from anonchat.handlers.nft_giveaway import (
    Giveaway, _count, _draw, _raffle_stats, _save_campaign, _ticket_numbers,
)
from anonchat.handlers.nft_grant import (
    _create_grant, _finish_grant, _parse_grant,
    nft_grant_action, nft_grant_preview,
)


def test_grant_command_syntax_and_owner_menu() -> None:
    assert any(command.command == "nft_give" for command in ADMIN_VISIBLE)
    assert _parse_grant("/nft_give 123456789 1") == (123456789, 1)
    assert _parse_grant("/nft_give 123456789 99") == (123456789, 99)
    for raw in (
        "", "/nft_give", "/nft_give 123", "/nft_give abc 5",
        "/nft_give -1 2", "/nft_give 0 1",
        "/nft_give 123 0", "/nft_give 123 100", "/nft_give 123 1.5",
        "/nft_give 123 5 extra", "/nft_give 9223372036854775808 1",
        "/nft_give <svg> 2",
    ):
        assert _parse_grant(raw) is None, raw


async def _setup(path: Path):
    db = await Database(path).start()
    await db.ensure_user(222, "recipient", "Recipient")
    g = await _save_campaign(
        db, "https://t.me/nft/AdminGift",
        int(time.time()) + 3600, "01.12.2026 20:00 МГН",
    )
    return db, g


def test_owner_only_and_confirmation_without_early_credit() -> None:
    async def scenario():
        with TemporaryDirectory() as root:
            db, g = await _setup(Path(root) / "db.sqlite")
            try:
                message = SimpleNamespace(
                    text="/nft_give 222 5",
                    chat=SimpleNamespace(type="private"),
                )
                outsider = SimpleNamespace(is_owner=False, user_id=111, reply=AsyncMock())
                await nft_grant_preview(message, outsider, db)
                outsider.reply.assert_not_awaited()
                ctx = SimpleNamespace(is_owner=True, user_id=111, reply=AsyncMock())
                await nft_grant_preview(
                    SimpleNamespace(
                        text="/nft_give 999999 5",
                        chat=SimpleNamespace(type="private"),
                    ), ctx, db,
                )
                assert "не найден в базе" in ctx.reply.await_args.args[0]
                assert await _count(db.path, g.campaign) == 0
                ctx.reply.reset_mock()
                await nft_grant_preview(message, ctx, db)
                preview, keyboard = ctx.reply.await_args.args
                assert "Количество: <b>5</b>" in preview
                assert "222" in preview
                confirm = keyboard.inline_keyboard[0][0].callback_data
                assert confirm.startswith("nft:grant:confirm:")
                assert keyboard.inline_keyboard[1][0].callback_data.startswith(
                    "nft:grant:cancel:"
                )
                assert await _count(db.path, g.campaign) == 0
                token = confirm.rsplit(":", 1)[-1]
                status, *_ = await _finish_grant(
                    db.path, token=token, actor_id=999,
                    current=g, approve=True,
                )
                assert status == "invalid"
                assert await _count(db.path, g.campaign) == 0
            finally:
                await db.close()
    asyncio.run(scenario())


def test_issued_99_tickets_are_durable_atomic_and_not_paid() -> None:
    async def scenario():
        with TemporaryDirectory() as root:
            db, g = await _setup(Path(root) / "db.sqlite")
            try:
                token = await _create_grant(
                    db.path, campaign=g.campaign, actor_id=111,
                    user_id=222, quantity=99,
                )
                async def approve():
                    return await _finish_grant(
                        db.path, token=token, actor_id=111, current=g,
                        approve=True,
                    )
                responses = await asyncio.gather(*[approve() for _ in range(3)])
                assert sorted(x[0] for x in responses) == [
                    "already_issued", "already_issued", "issued",
                ], responses
                assert responses[0][1:] == (222, 99, 1)
                assert await _ticket_numbers(db.path, g.campaign, 222) == list(range(1, 100))
                assert await _raffle_stats(db.path, g.campaign) == type(
                    await _raffle_stats(db.path, g.campaign)
                )(participants=1, tickets=99)
                assert (await db._fetchone(
                    "SELECT COUNT(*) AS n FROM sbp_payments"
                ))["n"] == 0
                grant = await db._fetchone(
                    "SELECT actor_id,user_id,quantity,status,first_number,confirmed_at "
                    "FROM nft_ticket_grants WHERE token=?", (token,),
                )
                assert (int(grant["actor_id"]), int(grant["user_id"]),
                        int(grant["quantity"]), str(grant["status"]),
                        int(grant["first_number"])) == (111, 222, 99, "issued", 1)
                assert int(grant["confirmed_at"]) > 0
                # The real random draw includes these free admin-issued tickets.
                closed = Giveaway(g.campaign, g.nft_url, int(time.time()) - 1, g.deadline)
                assert (await _draw(db.path, closed))[0] == 222
            finally:
                await db.close()
    asyncio.run(scenario())


def test_cancelled_expired_and_closed_grants_never_mint() -> None:
    async def scenario():
        with TemporaryDirectory() as root:
            db, g = await _setup(Path(root) / "db.sqlite")
            try:
                cancel_token = await _create_grant(
                    db.path, campaign=g.campaign, actor_id=111,
                    user_id=222, quantity=3,
                )
                assert (await _finish_grant(
                    db.path, token=cancel_token, actor_id=111,
                    current=g, approve=False,
                ))[0] == "cancelled"
                assert (await _finish_grant(
                    db.path, token=cancel_token, actor_id=111,
                    current=g, approve=True,
                ))[0] == "cancelled"
                expired_token = await _create_grant(
                    db.path, campaign=g.campaign, actor_id=111,
                    user_id=222, quantity=4,
                )
                async with aiosqlite.connect(db.path) as con:
                    await con.execute(
                        "UPDATE nft_ticket_grants SET created_at=? WHERE token=?",
                        (int(time.time()) - 700, expired_token),
                    )
                    await con.commit()
                assert (await _finish_grant(
                    db.path, token=expired_token, actor_id=111,
                    current=g, approve=True,
                ))[0] == "expired"
                closed_token = await _create_grant(
                    db.path, campaign=g.campaign, actor_id=111,
                    user_id=222, quantity=5,
                )
                async with aiosqlite.connect(db.path) as con:
                    await con.execute(
                        "UPDATE nft_giveaway_campaigns SET close_at=? WHERE campaign=?",
                        (int(time.time()) - 1, g.campaign),
                    )
                    await con.commit()
                assert (await _finish_grant(
                    db.path, token=closed_token, actor_id=111,
                    current=g, approve=True,
                ))[0] == "expired"
                assert await _count(db.path, g.campaign) == 0
            finally:
                await db.close()
    asyncio.run(scenario())


def test_confirm_handler_notifies_user_only_once() -> None:
    async def scenario():
        with TemporaryDirectory() as root:
            db, g = await _setup(Path(root) / "db.sqlite")
            try:
                token = await _create_grant(
                    db.path, campaign=g.campaign, actor_id=111,
                    user_id=222, quantity=2,
                )
                event = SimpleNamespace(
                    data=f"nft:grant:confirm:{token}",
                    message=SimpleNamespace(chat=SimpleNamespace(type="private")),
                )
                bot = SimpleNamespace(send_message=AsyncMock())
                ctx = SimpleNamespace(
                    is_owner=True, user_id=111, bot=bot,
                    ack=AsyncMock(), reply=AsyncMock(),
                )
                await nft_grant_action(event, ctx, db)
                bot.send_message.assert_awaited_once()
                assert bot.send_message.await_args.kwargs["chat_id"] == 222
                assert "№1–№2" in bot.send_message.await_args.kwargs["text"]
                assert await _ticket_numbers(db.path, g.campaign, 222) == [1, 2]
                await nft_grant_action(event, ctx, db)
                bot.send_message.assert_awaited_once()
                assert await _count(db.path, g.campaign) == 2
                ctx.is_owner = False
                await nft_grant_action(
                    SimpleNamespace(
                        data="nft:grant:confirm:not-own",
                        message=SimpleNamespace(chat=SimpleNamespace(type="private")),
                    ), ctx, db,
                )
                bot.send_message.assert_awaited_once()
            finally:
                await db.close()
    asyncio.run(scenario())


if __name__ == "__main__":
    test_grant_command_syntax_and_owner_menu()
    test_owner_only_and_confirmation_without_early_credit()
    test_issued_99_tickets_are_durable_atomic_and_not_paid()
    test_cancelled_expired_and_closed_grants_never_mint()
    test_confirm_handler_notifies_user_only_once()
    print("NFT manual ticket grant tests passed")
