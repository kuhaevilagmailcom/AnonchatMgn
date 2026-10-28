"""Owner-approved NFT giveaway post to a Telegram channel.

No automatic posting, no broadcast to users. /nft_post shows a private preview;
only the owner's confirmation publishes to the configured channel.
"""
from __future__ import annotations

import html
import os
import re
import time

import aiosqlite
from aiogram import F, Router
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
)
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..actions import Ctx
from ..db import Database
from .nft_giveaway import Giveaway, TICKET_PRICE_RUB, _active

router = Router(name="nft_channel")


def channel_target(default: str) -> str:
    """Use NFT_POST_CHANNEL if set, otherwise the existing project channel."""
    target = os.getenv("NFT_POST_CHANNEL", "").strip() or str(default or "").strip()
    if re.fullmatch(r"@[A-Za-z][A-Za-z0-9_]{4,31}", target):
        return target
    if re.fullmatch(r"-100[0-9]{5,17}", target):
        return target
    return ""


def giveaway_post_text(g: Giveaway) -> str:
    nft = html.escape(g.nft_url, quote=True)
    date = html.escape(g.deadline)
    return (
        "🎁 <b>Разыгрываем NFT</b>\n\n"
        f"<a href=\"{nft}\">Посмотреть NFT</a>\n"
        f"🎟 Билет — {TICKET_PRICE_RUB} ₽\n"
        f"⏳ До {date}\n\n"
        "Участие через бота — нажми кнопку ниже."
    )


def participation_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="Участвовать",
            url=f"https://t.me/{bot_username}?start=nft",
        )
    ]])


async def _init_posts(path) -> None:
    async with aiosqlite.connect(path, timeout=15.0) as con:
        await con.execute("""CREATE TABLE IF NOT EXISTS nft_channel_posts (
            campaign TEXT NOT NULL,
            channel TEXT NOT NULL,
            status TEXT NOT NULL,
            message_id INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            PRIMARY KEY (campaign, channel)
        )""")
        await con.commit()


async def _claim_post(path, campaign: str, channel: str) -> bool:
    """Prevent duplicate channel posts on repeat/concurrent confirmation taps."""
    await _init_posts(path)
    async with aiosqlite.connect(path, timeout=15.0) as con:
        await con.execute("PRAGMA busy_timeout=10000")
        await con.execute("BEGIN IMMEDIATE")
        row = await (await con.execute(
            "SELECT status FROM nft_channel_posts WHERE campaign=? AND channel=?",
            (campaign, channel),
        )).fetchone()
        if row is not None:
            if row[0] != "failed":
                await con.commit()
                return False
            await con.execute(
                "UPDATE nft_channel_posts SET status='sending' "
                "WHERE campaign=? AND channel=?",
                (campaign, channel),
            )
        else:
            await con.execute(
                "INSERT INTO nft_channel_posts(campaign,channel,status,created_at) "
                "VALUES (?,?, 'sending',?)",
                (campaign, channel, int(time.time())),
            )
        await con.commit()
        return True


async def _record_post(path, campaign: str, channel: str,
                       status: str, message_id: int = 0) -> None:
    await _init_posts(path)
    async with aiosqlite.connect(path, timeout=15.0) as con:
        await con.execute(
            "UPDATE nft_channel_posts SET status=?,message_id=? "
            "WHERE campaign=? AND channel=? AND status='sending'",
            (status, int(message_id), campaign, channel),
        )
        await con.commit()


@router.message(Command("nft_post"))
async def nft_post_preview(message: Message, ctx: Ctx, db: Database) -> None:
    if not ctx.is_owner or message.chat.type != "private":
        return
    g = await _active(db)
    if g is None or time.time() >= g.close_at:
        await ctx.reply("Сначала создай действующий розыгрыш через /nft_setup.")
        return
    channel = channel_target(ctx.cfg.subscription_channel)
    if not channel:
        await ctx.reply("Укажи корректный NFT_POST_CHANNEL в .env, например @anonmgn.")
        return
    me = await ctx.bot.get_me()
    if not me.username:
        await ctx.reply("Невозможно построить ссылку на бота.")
        return
    body = giveaway_post_text(g)
    # Preview shows the same real Telegram URL button as the channel post.
    markup = InlineKeyboardMarkup(inline_keyboard=[
        *participation_keyboard(me.username).inline_keyboard,
        [InlineKeyboardButton(
            text=f"Опубликовать в {channel}",
            callback_data=f"nft:post:{g.campaign}",
        )],
        [InlineKeyboardButton(text="Отмена", callback_data="nft:post_cancel")],
    ])
    await ctx.reply(
        f"<b>Предпросмотр для {html.escape(channel)}</b>\n\n"
        + body
        + "\n\nКнопка «Участвовать» ниже будет прикреплена прямо к посту "
        "в канале. Для публикации нажми «Опубликовать».",
        markup,
    )


@router.callback_query(F.data == "nft:post_cancel")
async def nft_post_cancel(event: CallbackQuery, ctx: Ctx) -> None:
    if not ctx.is_owner:
        await ctx.ack("Нет доступа", alert=True)
        return
    await ctx.ack("Отменено")
    await ctx.edit("Публикация отменена.")


@router.callback_query(F.data.startswith("nft:post:"))
async def nft_post_confirm(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    if not ctx.is_owner or not event.message or event.message.chat.type != "private":
        await ctx.ack("Нет доступа", alert=True)
        return
    g = await _active(db)
    campaign = (event.data or "").removeprefix("nft:post:")
    if g is None or campaign != g.campaign or time.time() >= g.close_at:
        await ctx.ack("Предпросмотр устарел. Открой /nft_post заново.", alert=True)
        return
    channel = channel_target(ctx.cfg.subscription_channel)
    if not channel:
        await ctx.ack("Канал не настроен.", alert=True)
        return
    me = await ctx.bot.get_me()
    if not me.username:
        await ctx.ack("Не удалось получить имя бота.", alert=True)
        return
    if not await _claim_post(db.path, g.campaign, channel):
        await ctx.ack(
            "Публикация уже отправлена или проверяется. Посмотри канал.",
            alert=True,
        )
        return
    await ctx.ack()
    try:
        sent = await ctx.bot.send_message(
            chat_id=int(channel) if channel.startswith("-100") else channel,
            text=giveaway_post_text(g),
            reply_markup=participation_keyboard(me.username),
            disable_web_page_preview=True,
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        await _record_post(db.path, g.campaign, channel, "failed")
        await ctx.reply(
            "Не получилось опубликовать: добавь бота администратором "
            f"канала {html.escape(channel)} с правом публикации сообщений."
        )
        return
    except (TelegramNetworkError, TelegramAPIError):
        # Delivery might have succeeded; do not blindly resend after network errors.
        await _record_post(db.path, g.campaign, channel, "unknown")
        await ctx.reply(
            "Не удалось подтвердить отправку. Проверь канал вручную: "
            "повторная публикация заблокирована, чтобы не было дублей."
        )
        return
    await _record_post(db.path, g.campaign, channel, "posted", sent.message_id)
    if channel.startswith("@"):
        channel_link = f"https://t.me/{channel[1:]}/{sent.message_id}"
        await ctx.reply(
            "<b>Розыгрыш опубликован!</b>\n\n"
            f"<a href=\"{channel_link}\">Открыть пост в {html.escape(channel)}</a>"
        )
    else:
        await ctx.reply("Розыгрыш опубликован в канале.")
