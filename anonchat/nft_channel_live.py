"""Keep existing NFT Telegram channel posts in sync with confirmed raffle state.

Works only with posts already explicitly published by the owner and recorded
in SQLite. Never creates a new post or broadcasts to subscribers.
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import aiosqlite
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter

from .handlers.nft_channel import (
    _init_posts, _init_repeat_posts, participation_keyboard,
)
from .handlers.nft_giveaway import _active, _card

log = logging.getLogger(__name__)
REFRESH_INTERVAL_SECONDS = 60.0


async def tracked_channel_posts(path, campaign: str, channel: str | None = None) -> list[tuple[str, int]]:
    """Locate original AND reposted messages; ignore unknown and failed sends."""
    await _init_posts(path)
    await _init_repeat_posts(path)
    async with aiosqlite.connect(path, timeout=15.0) as con:
        original = await (await con.execute(
            "SELECT channel,message_id FROM nft_channel_posts "
            "WHERE campaign=? AND status='posted' AND message_id>0",
            (campaign,),
        )).fetchall()
        repeats = await (await con.execute(
            "SELECT channel,message_id FROM nft_channel_repeat_posts "
            "WHERE campaign=? AND status='posted' AND message_id>0",
            (campaign,),
        )).fetchall()
    result: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for chat, mid in (*original, *repeats):
        key = (str(chat), int(mid))
        if (channel is None or key[0] == channel) and key not in seen:
            seen.add(key)
            result.append(key)
    return result


async def refresh_campaign_posts(
    bot: Any, db: Any, *,
    channel: str | None = None,
    cache: dict[tuple[str, int], str] | None = None,
) -> dict[str, int]:
    """Edit existing posts, preserving their URL button and genuine statistics.

    In-memory cache avoids unnecessary API calls when counts and displayed time
    are unchanged. A new process always checks Telegram once after restart.
    """
    result = {"total": 0, "updated": 0, "unchanged": 0, "failed": 0}
    giveaway = await _active(db)
    if giveaway is None:
        return result
    posts = await tracked_channel_posts(db.path, giveaway.campaign, channel)
    result["total"] = len(posts)
    if not posts:
        return result
    me = await bot.get_me()
    if not me.username:
        result["failed"] = len(posts)
        log.warning("Cannot refresh NFT channel posts: bot username is missing")
        return result

    body = await _card(SimpleNamespace(bot=bot), db, giveaway)
    markup = participation_keyboard(me.username)
    for target, message_id in posts:
        key = (target, message_id)
        if cache is not None and cache.get(key) == body:
            result["unchanged"] += 1
            continue
        try:
            await bot.edit_message_text(
                chat_id=int(target) if target.startswith("-100") else target,
                message_id=message_id,
                text=body,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                result["unchanged"] += 1
                if cache is not None:
                    cache[key] = body
                continue
            result["failed"] += 1
            log.warning(
                "Cannot edit NFT channel post %s/%s: %s",
                target, message_id, exc,
            )
        except TelegramRetryAfter as exc:
            result["failed"] += 1
            log.warning(
                "Telegram rate-limited NFT post refresh: wait %s seconds",
                exc.retry_after,
            )
            break
        except TelegramAPIError as exc:
            result["failed"] += 1
            log.warning(
                "NFT post refresh failed for %s/%s: %s", target, message_id, exc,
            )
        else:
            result["updated"] += 1
            if cache is not None:
                cache[key] = body
        # Avoid bursts when the same campaign was republished repeatedly.
        if len(posts) > 1:
            await asyncio.sleep(0.12)
    return result


async def run_worker(bot: Any, db: Any, interval_seconds: float = REFRESH_INTERVAL_SECONDS) -> None:
    """Refresh stats and countdown every minute; recover after transient errors."""
    cache: dict[tuple[str, int], str] = {}
    while True:
        try:
            await refresh_campaign_posts(bot, db, cache=cache)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("NFT channel auto-refresh failed; will retry")
        await asyncio.sleep(interval_seconds)
