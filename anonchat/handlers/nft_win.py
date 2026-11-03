"""Owner-only manual NFT winner announcement in the owner's chat.

This command formats a message; it does not alter the verifiable raffle draw,
tickets, payment history, or send anything to the user / channel.
"""
from __future__ import annotations

import re

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ..actions import Ctx

router = Router(name="nft_win")


def format_manual_win(user_id: int) -> str:
    return f"🏆 <b>ID <code>{user_id}</code> выиграл NFT в конкурсе!</b>"


@router.message(Command("win"))
async def nft_manual_win(message: Message, ctx: Ctx) -> None:
    if not ctx.is_owner or message.chat.type != "private":
        return
    raw = (message.text or "").strip().split(maxsplit=1)
    value = raw[1].strip() if len(raw) == 2 else ""
    if not re.fullmatch(r"[1-9][0-9]{0,18}", value):
        await ctx.reply(
            "Укажи Telegram ID победителя. Пример: <code>/win 123456789</code>"
        )
        return
    await ctx.reply(format_manual_win(int(value)))
