"""Public JPEG share previews and native Telegram share cards for Wall posts."""
from __future__ import annotations

import io
import html
import hashlib
import hmac
import time
import logging
import re
import uuid
from urllib.parse import urlsplit

from aiohttp import web
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultPhoto
from PIL import Image, ImageOps

log = logging.getLogger(__name__)
BOT_APP = "https://t.me/AnonChatMgn_Bot/anonmgn"
_TRACK_RE = re.compile(r"[^a-z0-9-]")


def track_slug(value, max_length=24):
    return _TRACK_RE.sub("-", str(value or "").lower()).strip("-")[:max_length]


def wall_link(post_id=None, *, source="anonmgn", medium="share", campaign="wall"):
    start = "wall" if post_id is None else f"wall_{int(post_id)}"
    for key, value, limit in (("source", source, 24), ("medium", medium, 24), ("campaign", campaign, 32)):
        clean = track_slug(value, limit)
        if clean:
            start += f"__utm_{key}_{clean}"
    return f"{BOT_APP}?startapp={start}"


def share_preview_url(wall, post_id):
    parsed = urlsplit(str(wall.server.cfg.miniapp_url))
    if parsed.scheme != "https" or not parsed.netloc:
        raise web.HTTPServiceUnavailable(text="HTTPS-адрес Mini App не настроен")
    expires = int(time.time()) + 12 * 3600
    mac = _preview_mac(wall, post_id, expires)
    return (f"{parsed.scheme}://{parsed.netloc}"
            f"/api/miniapp/wall/share-preview/{post_id}.jpg"
            f"?expires={expires}&sig={mac}")


def _preview_mac(wall, post_id, expires):
    data = f"wall-photo:{post_id}:{expires}".encode()
    return hmac.new(wall.server.cfg.bot_token.encode(), data, hashlib.sha256).hexdigest()


def share_plain_caption(post, post_id=None):
    """Human-readable post text; the link exists only in the button."""
    pid = int(post_id if post_id is not None else post["id"])
    heading = f"Пост №{pid} · Стена АНОН МГН"
    title = str(post["title"] or "").strip()
    body = str(post["body"] or "").strip()
    quote = "\n".join(part for part in (title, body) if part) or "Публикация с фото"
    if len(quote) > 850:
        quote = quote[:849].rstrip() + "…"
    return heading, quote


def share_caption(post, post_id=None):
    """Caption fits Telegram's 1024 UTF-16-unit limit even after HTML escaping."""
    heading, quote = share_plain_caption(post, post_id)
    prefix = f"<b>{html.escape(heading)}</b>\n\n<blockquote>"
    suffix = "</blockquote>"

    def units(value):
        return len(value.encode("utf-16-le")) // 2

    available = 1024 - units(prefix) - units(suffix)
    # Escape user text before counting: a wall post may contain hundreds of &<>.
    lo, hi = 0, len(quote)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if units(html.escape(quote[:mid])) <= available:
            lo = mid
        else:
            hi = mid - 1
    if lo < len(quote):
        clipped = quote[:lo]
        while clipped and units(html.escape(clipped + "…")) > available:
            clipped = clipped[:-1]
        quote = clipped.rstrip() + "…"
    return prefix + html.escape(quote) + suffix


async def preview(wall, request):
    if not wall.public_enabled:
        raise web.HTTPNotFound()
    post_id = wall._parse_id(request.match_info["post_id"])
    try:
        expires = int(request.query.get("expires", "0"))
    except ValueError:
        raise web.HTTPNotFound() from None
    if expires < time.time() or expires > time.time() + 12 * 3600:
        raise web.HTTPNotFound()
    signature = str(request.query.get("sig", ""))
    if not hmac.compare_digest(signature, _preview_mac(wall, post_id, expires)):
        raise web.HTTPNotFound()
    post = await wall.db._fetchone(
        "SELECT id FROM wall_posts WHERE id=? AND hidden=0", (post_id,)
    )
    if not post:
        raise web.HTTPNotFound()
    media = await wall.db._fetchone(
        """SELECT key,poster_key,kind FROM wall_media
           WHERE post_id=? ORDER BY CASE WHEN kind='image' THEN 0 ELSE 1 END,id LIMIT 1""",
        (post_id,),
    )
    candidate = None
    if media:
        key = media["key"] if media["kind"] == "image" else media["poster_key"]
        if key and "/" not in key and "\\" not in key:
            candidate = wall.media.base / key
    if not candidate or not candidate.is_file():
        candidate = wall.server.web_dir / "assets" / "anon-mgn-wall-avatar.jpg"
    canvas = Image.new("RGB", (1000, 620), "#000000")
    try:
        with Image.open(candidate) as opened:
            opened.draft("RGB", (1400, 1000))
            art = ImageOps.contain(ImageOps.exif_transpose(opened).convert("RGB"),
                                   (1000, 620), Image.Resampling.LANCZOS)
        canvas.paste(art, ((1000 - art.width) // 2, (620 - art.height) // 2))
    except (OSError, ValueError) as exc:
        log.warning("Wall share preview media unavailable: %s", exc)
    output = io.BytesIO()
    canvas.save(output, "JPEG", quality=85, optimize=True)
    return web.Response(body=output.getvalue(), content_type="image/jpeg")


async def prepare_share(wall, request):
    uid = await wall._user(request)
    post_id = wall._parse_id(request.match_info["post_id"])
    post = await wall._post(post_id, uid)
    if post is None:
        raise web.HTTPNotFound()
    image_url = share_preview_url(wall, post_id)
    target_url = wall_link(post_id, source="wall", medium="share", campaign="post")
    result = InlineQueryResultPhoto(
        id=uuid.uuid4().hex,
        photo_url=image_url,
        thumbnail_url=image_url,
        photo_width=1000,
        photo_height=620,
        title=str(post["title"] or "Публикация АНОН МГН")[:100],
        caption=share_caption(post, post_id),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Открыть публикацию", url=target_url)
        ]]),
    )
    try:
        saved = await wall.server.bot.save_prepared_inline_message(
            user_id=uid,
            result=result,
            allow_user_chats=True,
            allow_bot_chats=True,
            allow_group_chats=True,
            allow_channel_chats=True,
        )
    except Exception as exc:
        log.warning("Telegram Wall prepared message failed for post %s: %s",
                    post_id, type(exc).__name__)
        raise web.HTTPServiceUnavailable(
            text='{"message":"Не получилось подготовить публикацию для Telegram"}',
            content_type="application/json",
        ) from exc
    return web.json_response({
        "prepared_id":saved.id,
        "preview_url":image_url,
        "url":target_url,
        "caption":share_caption(post, post_id),
    })


async def share_details(wall, request):
    """Return a temporary signed JPEG URL for native Web Share without Bot API."""
    uid = await wall._user(request)
    post_id = wall._parse_id(request.match_info["post_id"])
    post = await wall._post(post_id, uid)
    if post is None:
        raise web.HTTPNotFound()
    target_url = wall_link(post_id, source="wall", medium="share", campaign="post")
    return web.json_response({
        "preview_url":share_preview_url(wall, post_id),
        "url":target_url,
        "caption":"\n".join(share_plain_caption(post, post_id)),
    })
