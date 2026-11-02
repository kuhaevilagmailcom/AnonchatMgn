"""Telegram-native NFT giveaway card with the user's ProtectStatus emoji pack.

Telegram messages do not support arbitrary colored backgrounds. Use supported
HTML styling, blockquotes, accurate campaign metrics and genuine Telegram
custom emoji loaded from the pack, falling back to regular emoji when needed.
"""
from __future__ import annotations

import html
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)
PACK_NAME = "ProtectStatus"
PACK_LINK = "https://t.me/addemoji/ProtectStatus"

# Prefer semantically matching icons within the specified pack, never invent IDs.
ROLE_FALLBACKS: dict[str, str] = {
    "header": "🎁",
    "prize": "🏆",
    "stats": "📊",
    "ticket": "🎟",
    "people": "👥",
    "timer": "⏳",
    "check": "✅",
    "action": "👇",
    "gift": "💎",
}
ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "header": ("🎁", "🎉", "💎", "✨", "🟢"),
    "prize": ("🏆", "🥇", "💎", "🎁", "⭐"),
    "stats": ("📊", "📈", "📉", "📋", "💠"),
    "ticket": ("🎟", "🎫", "🎁", "⭐", "💎"),
    "people": ("👥", "👤", "🧑", "🟢"),
    "timer": ("⏳", "⏰", "🕒", "⌛", "🕐"),
    "check": ("✅", "✔️", "☑️", "🟢"),
    "action": ("👇", "➡️", "👉", "🚀"),
    "gift": ("💎", "🎁", "🎉", "⭐"),
}

# The emoji set is fetched from Telegram at runtime with the bot's own
# credentials; no user token, hard-coded IDs or third-party emoji service.
_pack_cache: dict[str, tuple[str, str]] | None = None
_cache_at: float = 0.0


def _key(glyph: str) -> str:
    return str(glyph or "").replace("\ufe0f", "").replace("\ufe0e", "").strip()


async def load_protect_icons(bot: Any) -> dict[str, tuple[str, str]]:
    global _pack_cache, _cache_at
    now = time.monotonic()
    if _pack_cache is not None and now - _cache_at < 3600:
        return dict(_pack_cache)
    getter = getattr(bot, "get_sticker_set", None)
    if getter is None:
        return {}
    try:
        sticker_set = await getter(name=PACK_NAME)
        sticker_type = getattr(sticker_set, "sticker_type", "")
        sticker_type = getattr(sticker_type, "value", sticker_type)
        if sticker_type and str(sticker_type) != "custom_emoji":
            return {}
    except Exception as exc:
        log.warning("Cannot load %s custom emoji: %s", PACK_NAME, type(exc).__name__)
        return {}

    by_glyph: dict[str, tuple[str, str]] = {}
    first: tuple[str, str] | None = None
    for sticker in getattr(sticker_set, "stickers", ()) or ():
        emoji_id = str(getattr(sticker, "custom_emoji_id", "") or "")
        glyph = str(getattr(sticker, "emoji", "") or "").strip()
        if not re.fullmatch(r"\d{6,25}", emoji_id) or not glyph:
            continue
        item = (emoji_id, glyph)
        if first is None:
            first = item
        by_glyph.setdefault(_key(glyph), item)
    roles: dict[str, tuple[str, str]] = {}
    for role, aliases in ROLE_ALIASES.items():
        for glyph in aliases:
            hit = by_glyph.get(_key(glyph))
            if hit:
                roles[role] = hit
                break
    # The very first status symbol from ProtectStatus is a decorative accent
    # when the pack has no matching gift icon. Other icons remain meaningful.
    if first and "header" not in roles:
        roles["header"] = first
    _pack_cache, _cache_at = roles, now
    return dict(roles)


def icon(role: str, icons: dict[str, tuple[str, str]] | None = None) -> str:
    item = (icons or {}).get(role)
    if item is not None and re.fullmatch(r"\d{6,25}", str(item[0])):
        return f'<tg-emoji emoji-id="{item[0]}">{html.escape(item[1])}</tg-emoji>'
    return ROLE_FALLBACKS.get(role, "✨")


def remaining_time(close_at: int, now: int | float | None = None) -> str:
    seconds = max(0, int(close_at - (time.time() if now is None else now)))
    if not seconds:
        return "0 минут"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = (rem + 59) // 60
    if minutes == 60:
        hours += 1
        minutes = 0
    if hours == 24:
        days += 1
        hours = 0
    parts = []
    if days:
        parts.append(f"{days} д.")
    if hours:
        parts.append(f"{hours} ч.")
    if minutes or not parts:
        parts.append(f"{minutes} мин.")
    return " ".join(parts)


@dataclass(frozen=True)
class RaffleStats:
    participants: int
    tickets: int


def format_giveaway(
    giveaway: Any, stats: RaffleStats,
    icons: dict[str, tuple[str, str]] | None = None,
    *, now: float | None = None, ticket_price_rub: int = 35,
) -> str:
    """Same layout for Telegram channel, bot and mass broadcasts.

    Prize is one real NFT link from campaign config; the current giveaway
    does NOT support three separate prizes, so never claim 2nd/3rd place.
    Participant/ticket numbers must be read from confirmed SQLite entries.
    """
    now = time.time() if now is None else now
    active = now < int(giveaway.close_at)
    heading = "РОЗЫГРЫШ NFT АКТИВЕН!" if active else "РОЗЫГРЫШ NFT ЗАВЕРШЁН"
    nft_link = html.escape(str(giveaway.nft_url), quote=True)
    text = [
        f'{icon("header", icons)} <b>{heading}</b>',
        "",
        f'{icon("prize", icons)} <b>Приз:</b>',
        f'<blockquote>🥇 <a href="{nft_link}">NFT-подарок</a></blockquote>',
        "",
        f'{icon("stats", icons)} <b>Статистика:</b>',
        "<blockquote>"
        f'{icon("ticket", icons)} Билет: <b>{ticket_price_rub} ₽</b>\n'
        f'{icon("people", icons)} Участников: <b>{max(0, stats.participants)}</b>\n'
        f'{icon("gift", icons)} Билетов: <b>{max(0, stats.tickets)}</b>'
        "</blockquote>",
        "",
    ]
    if active:
        text.extend([
            f'{icon("timer", icons)} <b>Осталось времени:</b> '
            f'{remaining_time(giveaway.close_at, now)}',
            f'<i>До {html.escape(str(giveaway.deadline))}</i>',
            "",
            f'{icon("check", icons)} <b>Важно:</b> после оплаты вернись в бот '
            'и нажми <b>«Проверить оплату»</b>, чтобы получить билет.',
            "",
            f'{icon("action", icons)} <b>Успей принять участие!</b>',
        ])
    else:
        text.extend([
            f'{icon("timer", icons)} <b>Приём билетов завершён.</b>',
            "Если уже оплатил, проверь платёж и свои билеты в боте.",
        ])
    return "\n".join(text)
