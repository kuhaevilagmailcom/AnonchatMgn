"""Public JPEG share previews and native Telegram share cards for Wall posts."""
from __future__ import annotations

import io
import logging
import os
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


def share_caption(post, link):
    title = str(post["title"] or "").strip()
    body = str(post["body"] or "").strip()
    # Inline photo captions have a strict 1024-character Telegram limit.
    header = "АНОН МГН · Стена"
    text = "\n\n".join(x for x in (header, title, body) if x)
    room = 1024 - len(link) - 4
    if len(text) > room:
        text = text[:max(1, room - 1)].rstrip() + "…"
    return f"{text}\n\n{link}"


def _jpeg_preview(wall, post_id):
    canvas = Image.new("RGB", (1000, 620), "#000000")
    logo = wall.server.web_dir / "assets" / "anon-mgn-logo.png"
    row = None
    # Public posts may be shared; private unattached/hidden media may not.
    # Caller has already checked wall_posts.hidden and public_enabled.
    return canvas, logo


async def preview(wall, request):
    if not wall.public_enabled:
        raise web.HTTPNotFound()
    post_id = wall._parse_id(request.match_info["post_id"])
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
        candidate = wall.server.web_dir / "assets" / "anon-mgn-logo.png"
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
    origin_parts = urlsplit(str(wall.server.cfg.miniapp_url))
    if origin_parts.scheme != "https" or not origin_parts.netloc:
        raise web.HTTPServiceUnavailable(text="HTTPS-адрес Mini App не настроен")
    image_url = (f"{origin_parts.scheme}://{origin_parts.netloc}"
                 f"/api/miniapp/wall/share-preview/{post_id}.jpg")
    target_url = wall_link(post_id, source="wall", medium="share", campaign="post")
    result = InlineQueryResultPhoto(
        id=uuid.uuid4().hex,
        photo_url=image_url,
        thumbnail_url=image_url,
        photo_width=1000,
        photo_height=620,
        title=str(post["title"] or "Публикация АНОН МГН")[:100],
        caption=share_caption(post, target_url),
        parse_mode=None,
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
        "url":target_url,
        "caption":share_caption(post, target_url),
    })
