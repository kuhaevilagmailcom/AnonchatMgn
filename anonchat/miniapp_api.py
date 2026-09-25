"""Same-process HTTP API и статика Telegram Mini App."""

from __future__ import annotations

import asyncio
import hashlib
import io
import html
import hmac
import json
import os
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from aiohttp import web
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import BufferedInputFile

from . import keyboards as K
from . import texts
from . import relay_state
from . import live_chat
from . import word_game as WG
from . import nick as nicklib
from .actions import DeliveryResult, _dialog_summary_text, announce_pairs, send_to
from .levels import rank_for
from .engagement import collect_progress_notifications
from .number_game import NUMBER_DAILY_REWARD_LIMIT, NUMBER_NEAR_DIFFS, NUMBER_REWARDS, NUMBER_ROUNDS
from .runtime_state import online_count as presence_online_count
from .runtime_state import touch as presence_touch


SUBSCRIPTION_REWARD_KEY = "channel_subscription_v1"


def _subscription_chat_id(raw: str) -> int | str | None:
    value = str(raw or "").strip()
    if not value:
        return None
    if value.startswith("https://t.me/"):
        value = value.removeprefix("https://t.me/").split("?", 1)[0].strip("/")
        if value.startswith("+"):
            return None
        value = f"@{value.lstrip('@')}"
    if value.lstrip("-").isdigit():
        return int(value)
    return value if value.startswith("@") else f"@{value}"


def _subscription_url(channel: str, explicit_url: str = "") -> str:
    if str(explicit_url or "").strip():
        return str(explicit_url).strip()
    value = str(channel or "").strip()
    if value.startswith("https://t.me/"):
        return value
    return f"https://t.me/{value.lstrip('@')}" if value and not value.lstrip("-").isdigit() else ""


def _member_is_subscribed(member: object) -> bool:
    status = getattr(getattr(member, "status", ""), "value", getattr(member, "status", ""))
    status = str(status)
    return status in {"member", "administrator", "creator"} or (
        status == "restricted" and bool(getattr(member, "is_member", False))
    )


def _json_error(status: int, message: str) -> web.HTTPException:
    classes = {
        400: web.HTTPBadRequest,
        401: web.HTTPUnauthorized,
        403: web.HTTPForbidden,
        404: web.HTTPNotFound,
        409: web.HTTPConflict,
        413: web.HTTPRequestEntityTooLarge,
        503: web.HTTPServiceUnavailable,
    }
    return classes.get(status, web.HTTPBadRequest)(
        text=json.dumps({"message": message}, ensure_ascii=False),
        content_type="application/json",
    )


def validate_init_data(raw: str, bot_token: str, max_age: int = 3600) -> dict:
    """Проверяет подпись Telegram WebApp initData по официальной HMAC-схеме."""
    if not raw:
        raise _json_error(401, "Открой Mini App внутри Telegram")
    pairs = dict(parse_qsl(raw, keep_blank_values=True))
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        raise _json_error(401, "Нет подписи Telegram")
    data_check = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        raise _json_error(401, "Неверная подпись Telegram")
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise _json_error(401, "Некорректная дата сессии") from exc
    if max_age > 0 and (not auth_date or abs(int(time.time()) - auth_date) > max_age):
        raise _json_error(401, "Сессия Mini App устарела")
    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError as exc:
        raise _json_error(401, "Не удалось прочитать пользователя") from exc
    if not isinstance(user, dict) or not int(user.get("id", 0) or 0):
        raise _json_error(401, "Telegram user не найден")
    return user


class MiniAppServer:
    def __init__(self, bot, cfg, db, mm, pack, *, web_dir: str | Path | None = None) -> None:
        self.bot = bot
        self.cfg = cfg
        self.db = db
        self.mm = mm
        self.pack = pack
        self.web_dir = Path(
            web_dir or os.getenv("MINIAPP_WEB_DIR", "miniapp/web")
        ).resolve()
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self._bot_username = ""
        self._brand_sticker_file_id = ""
        self._brand_sticker_bytes: bytes | None = None
        self.serve_static = os.getenv("MINIAPP_SERVE_STATIC", "true").lower() in {
            "1", "true", "yes", "on"
        }
        self.allowed_origins = {
            item.strip().rstrip("/")
            for item in os.getenv("MINIAPP_ALLOWED_ORIGINS", "").split(",")
            if item.strip()
        }
        miniapp_url = str(getattr(cfg, "miniapp_url", "") or "")
        parsed_miniapp_url = urlsplit(miniapp_url)
        if parsed_miniapp_url.scheme == "https" and parsed_miniapp_url.netloc:
            self.allowed_origins.add(
                f"{parsed_miniapp_url.scheme}://{parsed_miniapp_url.netloc}"
            )

    def _telegram_user(self, request: web.Request) -> tuple[int, dict]:
        raw = request.headers.get("X-Telegram-Init-Data", "")
        user = validate_init_data(
            raw,
            self.cfg.bot_token,
            int(os.getenv("MINIAPP_INITDATA_MAX_AGE", "3600")),
        )
        user_id = int(user["id"])
        presence_touch(user_id)
        return user_id, user

    async def _auth(self, request: web.Request) -> tuple[int, dict, object]:
        user_id, user = self._telegram_user(request)
        row = await self.db.ensure_user(
            user_id, user.get("username"), user.get("first_name") or "Пользователь"
        )
        return user_id, user, row

    def _profile_json(self, row, user: dict) -> dict:
        rank = rank_for(int(row["messages"] or 0))
        return {
            "id": int(row["user_id"]),
            "nick": nicklib.display(
                row["nickname"], int(row["user_id"]), int(row["support_stars"] or 0)
            ),
            "photo_url": user.get("photo_url") or "",
            "rank": rank.title,
            "stars": int(row["xp"] or 0),
            "age": int(row["age"] or 0),
            "district": str(row["district"] or ""),
            "gender": str(row["gender"] or ""),
            "looking_for": str(row["looking_for"] or ""),
        }

    async def _stats(self, user_id: int, row=None) -> dict:
        row = row or await self.db.get_user(user_id)
        today = await self.db.activity_totals(user_id, 1)
        engagement = await self.db.engagement_state(user_id)
        return {
            "online": presence_online_count(),
            "chatting": self.mm.online_pairs() * 2,
            "searching": self.mm.queue_size(),
            "dialogs": int(row["dialogs"] or 0) if row else 0,
            "messages": int(row["messages"] or 0) if row else 0,
            "ratings": int(row["good_ratings"] or 0) if row else 0,
            "games": int(engagement["games_total"] or 0),
            "battle_games": int(engagement["battle_games_total"] or 0),
            "number_games": int(engagement["number_games_total"] or 0),
            "streak": int(engagement["current_streak"] or 0),
            "best_streak": int(engagement["best_streak"] or 0),
            "quest_current": int(today.get("messages", 0)),
            "quest_target": 20,
        }

    def _status_payload(self, user_id: int) -> dict:
        status = self.mm.status(user_id)
        return {
            "status": status,
            "position": self.mm.position(user_id) if status == "queued" else None,
            "stats": {
                "online": presence_online_count(),
                "chatting": self.mm.online_pairs() * 2,
                "searching": self.mm.queue_size(),
            },
        }

    async def _username(self) -> str:
        if not self._bot_username:
            me = await self.bot.get_me()
            self._bot_username = me.username or "AnonChatMgn_Bot"
        return self._bot_username

    async def me(self, request: web.Request) -> web.Response:
        uid, user, row = await self._auth(request)
        invited, earned = await self.db.referral_stats(uid)
        bot_username = await self._username()
        return web.json_response(
            {
                "user": self._profile_json(row, user),
                "stats": await self._stats(uid, row),
                "status": self.mm.status(uid),
                "position": self.mm.position(uid),
                "referral": {"invited": invited, "earned": earned},
                "referral_url": f"https://t.me/{bot_username}?start=ref_{uid}",
                "bot_url": f"https://t.me/{bot_username}",
                "notifications": await self._notifications(uid),
            }
        )

    async def status(self, request: web.Request) -> web.Response:
        uid, _ = self._telegram_user(request)
        return web.json_response(self._status_payload(uid))

    def _media_signature(self, user_id: int, token: str, expires: int) -> str:
        payload = f"{int(user_id)}:{str(token)}:{int(expires)}".encode()
        return hmac.new(
            self.cfg.bot_token.encode(), payload, hashlib.sha256
        ).hexdigest()[:32]

    def _signed_media_url(self, user_id: int, token: str) -> str:
        expires = int(time.time()) + 10 * 60
        signature = self._media_signature(user_id, token, expires)
        return (
            f"/api/miniapp/chat/media/{token}"
            f"?uid={int(user_id)}&exp={expires}&sig={signature}"
        )

    def _chat_event_json(self, item: dict, user_id: int) -> dict:
        event = dict(item)
        token = str(event.pop("media_token", "") or "")
        if token:
            event["media_url"] = self._signed_media_url(user_id, token)
        return event

    async def chat_state(self, request: web.Request) -> web.Response:
        uid, _ = self._telegram_user(request)
        try:
            after = int(request.query.get("after", "0") or 0)
        except ValueError:
            after = 0
        status = self.mm.status(uid)
        stats = self.mm.dialog_stats(uid) if status == "paired" else {}
        counts = stats.get("counts", {}) or {}
        partner = self.mm.partner(uid)
        received = int(counts.get(partner, 0)) if partner is not None else 0
        sent = int(counts.get(uid, 0))
        started_at = int(float(stats.get("started_at", 0) or 0))
        events = [
            self._chat_event_json(item, uid)
            for item in live_chat.events(uid, after=after, limit=100)
        ]
        return web.json_response(
            {
                "status": status,
                "started_at": started_at,
                "sent": sent,
                "received": received,
                "events": events,
                "latest": live_chat.latest_seq(uid),
            }
        )

    async def _chat_guard(self, uid: int) -> tuple[int, int]:
        reason = await self.db.is_restricted(uid)
        if reason == "banned":
            raise _json_error(403, "Чат недоступен")
        if reason == "muted":
            raise _json_error(403, "Ты временно не можешь отправлять сообщения")
        result = self.mm.count_message(uid)
        if result is None:
            raise _json_error(409, "Активного диалога нет")
        partner, sent = result
        return int(partner), int(sent)

    async def _chat_delivery_failed(self, uid: int, partner: int, unavailable: bool) -> None:
        self.mm.uncount_message(uid)
        if unavailable:
            await self.db.close_battles_for_users(uid, partner)
            self.mm.forget(uid)
            WG.clear_pair(uid, partner)
            relay_state.clear_pair(uid, partner)
            live_chat.clear_pair(uid, partner)
        self.db.schedule_matchmaker_save(self.mm)

    async def _after_chat_message(
        self, uid: int, partner: int, sent_count: int, *, text: str = ""
    ) -> None:
        multiplier = await self.db.xp_multiplier()
        if multiplier > 1 and sent_count <= max(0, int(self.cfg.xp_message_cap)):
            self.mm.add_bonus_xp(
                uid,
                (multiplier - 1) * max(0, int(self.cfg.xp_per_message)),
            )
        if text:
            self.mm.record_text(uid, text)
            guessed = WG.resolve_guess(uid, partner, text)
            if guessed is not None:
                awarded = await self.db.award_word_guess(
                    guessed.guesser_id, guessed.explainer_id
                )
                game = WG.get_by_id(guessed.game_id)
                reward_line = (
                    f"+<b>{awarded} ⭐</b>."
                    if awarded > 0
                    else "Сегодня награда за эту игру уже исчерпана."
                )
                end_line = (
                    f"\n\n🏁 <b>Игра окончена</b> · {guessed.total_rounds} слов."
                    if guessed.finished
                    else ""
                )
                markup = (
                    K.word_end_keyboard()
                    if guessed.finished
                    else K.word_next_keyboard(guessed.game_id, guessed.round_index)
                )
                await send_to(
                    self.bot,
                    guessed.guesser_id,
                    f"🎯 <b>Угадал!</b>\nСлово: <b>{texts.esc(guessed.word)}</b>\n"
                    f"{reward_line}{end_line}",
                    markup,
                    self.pack,
                )
                await send_to(
                    self.bot,
                    guessed.explainer_id,
                    f"🎯 <b>Слово угадано!</b>\n"
                    f"Слово: <b>{texts.esc(guessed.word)}</b>{end_line}",
                    markup,
                    self.pack,
                )
                live_chat.system(
                    {guessed.guesser_id, guessed.explainer_id},
                    f"🎯 Слово «{guessed.word}» угадано",
                )
                if guessed.finished and game is not None:
                    self.mm.record_game(
                        game.user_a,
                        "words",
                        guessed.correct_total,
                        guessed.total_rounds,
                    )
                    for player_id in (game.user_a, game.user_b):
                        await self.db.record_game_engagement(
                            player_id,
                            "words",
                            matches=guessed.correct_total,
                            total=guessed.total_rounds,
                        )
                        for notice in await collect_progress_notifications(
                            self.db, player_id
                        ):
                            await send_to(
                                self.bot, player_id, notice, pack=self.pack
                            )
                    WG.remove(guessed.game_id)
        self.db.schedule_matchmaker_save(self.mm)

    async def chat_send_text(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        data = await request.json()
        text = str(data.get("text", "") or "").strip()
        if not text:
            raise _json_error(400, "Напиши сообщение")
        if len(text) > int(self.cfg.max_message_len):
            raise _json_error(400, f"Максимум {self.cfg.max_message_len} символов")
        partner = self.mm.partner(uid)
        if partner is not None and WG.explainer_used_secret(uid, partner, text):
            raise _json_error(400, "Не пиши само слово. Объясни его другими словами")
        partner, sent_count = await self._chat_guard(uid)
        try:
            sent = await self.bot.send_message(partner, text, parse_mode=None)
        except TelegramForbiddenError as exc:
            await self._chat_delivery_failed(uid, partner, True)
            raise _json_error(409, "Собеседник больше недоступен") from exc
        except TelegramAPIError as exc:
            await self._chat_delivery_failed(uid, partner, False)
            raise _json_error(503, "Не удалось доставить сообщение") from exc
        live_chat.publish(
            uid, partner, "text", text=text, telegram_message_id=sent.message_id
        )
        await self._after_chat_message(
            uid, partner, sent_count, text=text
        )
        return web.json_response({"ok": True, "latest": live_chat.latest_seq(uid)})

    async def _read_upload(
        self, request: web.Request, *, limit: int
    ) -> tuple[bytes, str, str, str]:
        reader = await request.multipart()
        payload = b""
        filename = ""
        content_type = ""
        caption = ""
        while True:
            field = await reader.next()
            if field is None:
                break
            if field.name == "file":
                filename = str(field.filename or "upload.bin")
                content_type = str(field.headers.get("Content-Type", "") or "")
                chunks = bytearray()
                while True:
                    chunk = await field.read_chunk(size=64 * 1024)
                    if not chunk:
                        break
                    chunks.extend(chunk)
                    if len(chunks) > limit:
                        raise _json_error(413, "Файл слишком большой")
                payload = bytes(chunks)
            elif field.name == "caption":
                caption = (await field.text()).strip()[: int(self.cfg.max_message_len)]
        if not payload:
            raise _json_error(400, "Файл не выбран")
        return payload, filename, content_type, caption

    async def chat_send_photo(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        payload, filename, content_type, caption = await self._read_upload(
            request, limit=8 * 1024 * 1024
        )
        if content_type and not content_type.startswith("image/"):
            raise _json_error(400, "Можно отправить только изображение")
        partner, sent_count = await self._chat_guard(uid)
        try:
            sent = await self.bot.send_photo(
                partner,
                BufferedInputFile(payload, filename=filename or "photo.jpg"),
                caption=caption or None,
                parse_mode=None,
            )
        except TelegramForbiddenError as exc:
            await self._chat_delivery_failed(uid, partner, True)
            raise _json_error(409, "Собеседник больше недоступен") from exc
        except TelegramAPIError as exc:
            await self._chat_delivery_failed(uid, partner, False)
            raise _json_error(503, "Не удалось отправить фото") from exc
        file_id = sent.photo[-1].file_id if sent.photo else ""
        live_chat.publish(
            uid,
            partner,
            "photo",
            text=caption,
            file_id=file_id,
            telegram_message_id=sent.message_id,
        )
        await self._after_chat_message(uid, partner, sent_count)
        return web.json_response({"ok": True, "latest": live_chat.latest_seq(uid)})

    async def _voice_payload(
        self, payload: bytes, content_type: str, filename: str
    ) -> tuple[bytes, str]:
        # MediaRecorder отдаёт разные контейнеры в iOS/Android/WebView.
        # Для Telegram всегда нормализуем в OGG/Opus.
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "48000",
                "-c:a",
                "libopus",
                "-application",
                "voip",
                "-b:a",
                "48k",
                "-f",
                "ogg",
                "pipe:1",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(payload), timeout=25)
        except (FileNotFoundError, TimeoutError, asyncio.TimeoutError) as exc:
            raise _json_error(503, "Не удалось обработать голосовое") from exc
        if proc.returncode != 0 or not out:
            detail = err.decode("utf-8", "ignore").strip()[-180:]
            raise _json_error(
                400,
                "Не удалось обработать запись"
                + (f": {detail}" if detail else ""),
            )
        return out, "voice.ogg"

    async def chat_send_voice(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        payload, filename, content_type, _caption = await self._read_upload(
            request, limit=12 * 1024 * 1024
        )
        payload, filename = await self._voice_payload(
            payload, content_type, filename
        )
        partner, sent_count = await self._chat_guard(uid)
        try:
            sent = await self.bot.send_voice(
                partner,
                BufferedInputFile(payload, filename=filename),
            )
        except TelegramForbiddenError as exc:
            await self._chat_delivery_failed(uid, partner, True)
            raise _json_error(409, "Собеседник больше недоступен") from exc
        except TelegramAPIError as exc:
            await self._chat_delivery_failed(uid, partner, False)
            raise _json_error(503, "Не удалось отправить голосовое") from exc
        file_id = sent.voice.file_id if sent.voice else ""
        live_chat.publish(
            uid,
            partner,
            "voice",
            file_id=file_id,
            telegram_message_id=sent.message_id,
        )
        await self._after_chat_message(uid, partner, sent_count)
        return web.json_response({"ok": True, "latest": live_chat.latest_seq(uid)})

    async def _brand_sticker_payload(self) -> bytes:
        if self._brand_sticker_bytes is not None:
            return self._brand_sticker_bytes
        source = self.web_dir / "assets" / "anon-mgn-logo.png"
        if not source.is_file():
            raise _json_error(503, "Фирменный стикер недоступен")
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-vf",
                "scale=512:512:force_original_aspect_ratio=decrease",
                "-c:v",
                "libwebp",
                "-lossless",
                "1",
                "-compression_level",
                "6",
                "-q:v",
                "82",
                "-an",
                "-f",
                "webp",
                "pipe:1",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _err = await asyncio.wait_for(proc.communicate(), timeout=15)
        except (FileNotFoundError, TimeoutError, asyncio.TimeoutError) as exc:
            raise _json_error(503, "Не удалось подготовить стикер") from exc
        if proc.returncode != 0 or not out:
            raise _json_error(503, "Не удалось подготовить стикер")
        self._brand_sticker_bytes = out
        return out

    async def chat_stickers(self, request: web.Request) -> web.Response:
        self._telegram_user(request)
        pack_name = os.getenv("MINIAPP_STICKER_SET", "NewsEmoji").strip()
        sticker_set = None
        if pack_name:
            try:
                sticker_set = await self.bot.get_sticker_set(pack_name)
            except TelegramAPIError:
                sticker_set = None
        items = [
            {
                "id": "brand-logo",
                "emoji": "🩷",
                "url": "/assets/anon-mgn-logo.png",
                "builtin": True,
            }
        ]
        for sticker in (sticker_set.stickers if sticker_set is not None else ()):
            if bool(sticker.is_animated) or bool(sticker.is_video):
                continue
            sid = hashlib.sha256(sticker.file_id.encode()).hexdigest()[:16]
            live_chat.register_sticker(sid, sticker.file_id)
            items.append(
                {
                    "id": sid,
                    "emoji": sticker.emoji or "",
                    "url": f"/api/miniapp/chat/sticker-media/{sid}",
                }
            )
            if len(items) >= 32:
                break
        return web.json_response({"items": items})

    async def chat_send_sticker(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        data = await request.json()
        sticker_id = str(data.get("id", "") or "")
        file_id = live_chat.sticker_file_id(sticker_id)
        builtin_payload: bytes | None = None
        if sticker_id == "brand-logo":
            if self._brand_sticker_file_id:
                file_id = self._brand_sticker_file_id
            else:
                builtin_payload = await self._brand_sticker_payload()
        elif not file_id:
            raise _json_error(400, "Стикер не найден")
        partner, sent_count = await self._chat_guard(uid)
        try:
            sticker_source = (
                BufferedInputFile(builtin_payload, filename="anon-mgn.webp")
                if builtin_payload is not None
                else file_id
            )
            sent = await self.bot.send_sticker(partner, sticker_source)
        except TelegramForbiddenError as exc:
            await self._chat_delivery_failed(uid, partner, True)
            raise _json_error(409, "Собеседник больше недоступен") from exc
        except TelegramAPIError as exc:
            await self._chat_delivery_failed(uid, partner, False)
            raise _json_error(503, "Не удалось отправить стикер") from exc
        sent_file_id = sent.sticker.file_id if sent.sticker else (file_id or "")
        if sticker_id == "brand-logo" and sent_file_id:
            self._brand_sticker_file_id = sent_file_id
            live_chat.register_sticker("brand-logo", sent_file_id)
        live_chat.publish(
            uid,
            partner,
            "sticker",
            text=(sent.sticker.emoji if sent.sticker else "") or "",
            file_id=sent_file_id,
            telegram_message_id=sent.message_id,
        )
        await self._after_chat_message(uid, partner, sent_count)
        return web.json_response({"ok": True, "latest": live_chat.latest_seq(uid)})

    async def _download_telegram_file(self, file_id: str) -> bytes:
        tg_file = await self.bot.get_file(file_id)
        if not tg_file.file_path:
            raise _json_error(404, "Файл недоступен")
        target = io.BytesIO()
        await self.bot.download_file(tg_file.file_path, destination=target)
        return target.getvalue()

    async def chat_media(self, request: web.Request) -> web.Response:
        token = request.match_info["token"]
        try:
            uid = int(request.query.get("uid", "0") or 0)
            expires = int(request.query.get("exp", "0") or 0)
        except ValueError as exc:
            raise _json_error(403, "Ссылка на медиа недействительна") from exc
        signature = str(request.query.get("sig", "") or "")
        expected = self._media_signature(uid, token, expires)
        if (
            uid <= 0
            or expires < int(time.time())
            or not signature
            or not hmac.compare_digest(signature, expected)
        ):
            raise _json_error(403, "Ссылка на медиа устарела")
        ref = live_chat.media_ref(token, uid)
        if ref is None:
            raise _json_error(404, "Медиа устарело")
        try:
            payload = await self._download_telegram_file(ref.file_id)
        except TelegramAPIError as exc:
            raise _json_error(404, "Медиа недоступно") from exc
        content_type = {
            "photo": "image/jpeg",
            "voice": "audio/ogg",
            "sticker": "image/webp",
        }.get(ref.kind, "application/octet-stream")
        return web.Response(
            body=payload,
            content_type=content_type,
            headers={"Cache-Control": "private, max-age=300"},
        )

    async def chat_sticker_media(self, request: web.Request) -> web.Response:
        self._telegram_user(request)
        file_id = live_chat.sticker_file_id(request.match_info["sticker_id"])
        if not file_id:
            raise _json_error(404, "Стикер не найден")
        try:
            payload = await self._download_telegram_file(file_id)
        except TelegramAPIError as exc:
            raise _json_error(404, "Стикер недоступен") from exc
        return web.Response(
            body=payload,
            content_type="image/webp",
            headers={"Cache-Control": "private, max-age=900"},
        )

    async def _end_chat(self, uid: int, *, next_chat: bool = False) -> dict:
        partner, summary = self.mm.release(uid)
        if partner is None:
            return self._status_payload(uid)
        await self.db.close_battles_for_users(uid, partner)
        WG.clear_pair(uid, partner)
        relay_state.clear_pair(uid, partner)
        live_chat.clear_pair(uid, partner)

        counts = summary.get("counts", {}) or {}
        bonus_xp = summary.get("bonus_xp", {}) or {}
        mine = int(counts.get(uid, 0))
        theirs = int(counts.get(partner, 0))
        started = int(summary.get("started_at", time.time()))
        live = mine > 0 and theirs > 0 and (mine + theirs) >= 6
        match_id = await self.db.log_dialog(
            uid,
            partner,
            mine,
            theirs,
            started,
            uid,
            count_dialog=live,
            commit=False,
        )
        earned_xp: dict[int, int] = {}
        for player_id, sent_count in ((uid, mine), (partner, theirs)):
            gain = (
                min(sent_count, self.cfg.xp_message_cap) * self.cfg.xp_per_message
                + int(bonus_xp.get(player_id, 0))
                + (self.cfg.xp_per_dialog if live else 0)
            )
            if gain:
                await self.db.award_xp(player_id, gain, commit=False)
            if sent_count:
                await self.db.bump(
                    player_id, "messages", sent_count, commit=False
                )
            await self.db.activity_add(
                player_id,
                messages=sent_count,
                dialogs=1 if live else 0,
                commit=False,
            )
            if live:
                await self.db.record_dialog_engagement(
                    player_id, commit=False
                )
                await self.db.update_streak(player_id, commit=False)
            earned_xp[player_id] = gain
        await self.db.db.commit()

        self.mm.remember_rating([uid, partner], match_id)
        my_summary = _dialog_summary_text(
            summary, uid, earned_xp.get(uid, 0)
        )
        partner_summary = _dialog_summary_text(
            summary, partner, earned_xp.get(partner, 0)
        )
        partner_note = texts.PARTNER_SKIPPED if next_chat else texts.PARTNER_LEFT
        my_note = "Пропустил." if next_chat else texts.DIALOG_STOPPED
        await send_to(
            self.bot,
            partner,
            f"{partner_note}\n\n{partner_summary}",
            K.menu_keyboard(),
            self.pack,
        )
        await send_to(
            self.bot,
            uid,
            f"{my_note}\n\n{my_summary}",
            K.rating_keyboard(),
            self.pack,
        )
        await send_to(
            self.bot,
            partner,
            texts.RATING_ASK,
            K.rating_keyboard(),
            self.pack,
        )
        for player_id in (uid, partner):
            for notice in await collect_progress_notifications(
                self.db, player_id
            ):
                await send_to(self.bot, player_id, notice, pack=self.pack)

        if next_chat:
            row = await self.db.get_user(uid)
            if row is not None:
                excluded = await self.db.excluded_partners(
                    uid,
                    recent_seconds=max(
                        0, int(self.cfg.recent_partner_cooldown_minutes)
                    )
                    * 60,
                )
                outcome, payload = self.mm.connect(
                    uid,
                    district=str(row["district"] or ""),
                    same_district=False,
                    gender=str(row["gender"] or ""),
                    looking_for=str(row["looking_for"] or ""),
                    excluded=excluded,
                )
                if outcome == "paired":
                    await announce_pairs(
                        self.bot,
                        self.cfg,
                        self.mm,
                        [(uid, int(payload))],
                        self.pack,
                        self.db,
                    )
        self.db.schedule_matchmaker_save(self.mm)
        result = self._status_payload(uid)
        result["summary"] = {
            "sent": mine,
            "received": theirs,
            "earned": int(earned_xp.get(uid, 0)),
            "started_at": started,
        }
        return result

    async def chat_stop(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        if self.mm.status(uid) == "queued":
            self.mm.forget(uid)
            self.db.schedule_matchmaker_save(self.mm)
            return web.json_response(self._status_payload(uid))
        if self.mm.status(uid) != "paired":
            return web.json_response(self._status_payload(uid))
        return web.json_response(await self._end_chat(uid, next_chat=False))

    async def chat_next(self, request: web.Request) -> web.Response:
        uid, _, row = await self._auth(request)
        if self.mm.status(uid) == "paired":
            return web.json_response(await self._end_chat(uid, next_chat=True))
        if self.mm.status(uid) == "queued":
            return web.json_response(self._status_payload(uid))
        excluded = await self.db.excluded_partners(
            uid,
            recent_seconds=max(
                0, int(self.cfg.recent_partner_cooldown_minutes)
            )
            * 60,
        )
        outcome, payload = self.mm.connect(
            uid,
            district=str(row["district"] or ""),
            same_district=False,
            gender=str(row["gender"] or ""),
            looking_for=str(row["looking_for"] or ""),
            excluded=excluded,
        )
        if outcome == "paired":
            await announce_pairs(
                self.bot,
                self.cfg,
                self.mm,
                [(uid, int(payload))],
                self.pack,
                self.db,
            )
        self.db.schedule_matchmaker_save(self.mm)
        return web.json_response(self._status_payload(uid))

    async def settings(self, request: web.Request) -> web.Response:
        uid, user, _ = await self._auth(request)
        if self.mm.status(uid) == "paired":
            raise _json_error(409, "Настройки нельзя менять во время диалога")
        data = await request.json()
        try:
            age = int(data.get("age", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise _json_error(400, "Некорректный возраст") from exc
        if age and age not in range(13, 21):
            raise _json_error(400, "Возраст: 13–20 или не указывать")
        districts = {"", "Правый берег", "Левый берег"}
        district = str(data.get("district", "") or "")
        if district not in districts:
            raise _json_error(400, "Неизвестный берег")
        gender = str(data.get("gender", "") or "")
        looking_for = str(data.get("looking_for", "") or "")
        if gender not in {"", "m", "f"} or looking_for not in {"", "m", "f"}:
            raise _json_error(400, "Некорректные настройки поиска")
        await self.db.set_profile(
            uid, age=age, district=district, same_district=0,
            gender=gender, looking_for=looking_for,
        )
        row = await self.db.get_user(uid)
        if self.mm.status(uid) == "queued" and row is not None:
            pairs = self.mm.refresh(
                uid, district=district, same_district=False,
                gender=gender, looking_for=looking_for,
            )
            if pairs:
                await announce_pairs(self.bot, self.cfg, self.mm, pairs, self.pack, self.db)
            self.db.schedule_matchmaker_save(self.mm)
        return web.json_response({"user": self._profile_json(row, user)})

    async def settings_reset(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        if self.mm.status(uid) == "paired":
            raise _json_error(409, "Сначала заверши диалог")
        await self.db.set_profile(
            uid, age=0, district="", same_district=0, gender="", looking_for=""
        )
        if self.mm.status(uid) == "queued":
            pairs = self.mm.refresh(
                uid, district="", same_district=False, gender="", looking_for=""
            )
            if pairs:
                await announce_pairs(self.bot, self.cfg, self.mm, pairs, self.pack, self.db)
            self.db.schedule_matchmaker_save(self.mm)
        return web.json_response({"ok": True})

    async def nick(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        if self.mm.status(uid) == "paired":
            raise _json_error(409, "Ник нельзя менять во время диалога")
        data = await request.json()
        candidate, error = nicklib.validate(str(data.get("nick", "")).strip())
        if error:
            raise _json_error(400, str(error))
        if await self.db.nickname_taken(candidate, except_user_id=uid):
            raise _json_error(409, "Этот ник уже занят")
        await self.db.set_profile(uid, nickname=candidate)
        row = await self.db.get_user(uid)
        return web.json_response(
            {"nick": nicklib.display(row["nickname"], uid, int(row["support_stars"] or 0))}
        )

    async def search_start(self, request: web.Request) -> web.Response:
        uid, _, row = await self._auth(request)
        if bool(row["banned"]):
            raise _json_error(403, "Поиск недоступен")
        if int(row["mute_until"] or 0) > int(time.time()):
            raise _json_error(403, "Поиск временно недоступен")
        if self.mm.status(uid) == "paired":
            payload = self._status_payload(uid)
            payload["stats"] = {**await self._stats(uid, row), **payload["stats"]}
            return web.json_response(payload)
        excluded = await self.db.excluded_partners(uid)
        outcome, payload = self.mm.connect(
            uid,
            district=str(row["district"] or ""),
            same_district=False,
            gender=str(row["gender"] or ""),
            looking_for=str(row["looking_for"] or ""),
            excluded=excluded,
        )
        if outcome == "full":
            raise _json_error(503, "Очередь заполнена. Попробуй чуть позже")
        if outcome == "paired":
            made = await announce_pairs(
                self.bot, self.cfg, self.mm, [(uid, int(payload))], self.pack, self.db
            )
            if not made:
                self.mm.forget(uid)
                outcome, payload = "queued", self.mm.connect(
                    uid,
                    district=str(row["district"] or ""),
                    same_district=False,
                    gender=str(row["gender"] or ""),
                    looking_for=str(row["looking_for"] or ""),
                    excluded=excluded,
                )[1]
        self.db.schedule_matchmaker_save(self.mm)
        current = self._status_payload(uid)
        current["stats"] = {**await self._stats(uid, row), **current["stats"]}
        return web.json_response(current)

    async def search_stop(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        status = self.mm.status(uid)
        if status == "paired":
            raise _json_error(409, "Активный диалог заверши в боте через Стоп")
        if status == "queued":
            self.mm.forget(uid)
            self.db.schedule_matchmaker_save(self.mm)
        return web.json_response(self._status_payload(uid))

    async def online(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        current = presence_online_count()
        chatting = self.mm.online_pairs() * 2
        searching = self.mm.queue_size()
        key = time.strftime("miniapp_peak:%Y-%m-%d", time.gmtime(time.time() + 18000))
        peak = max(current, int(await self.db.get_kv(key, "0") or 0))
        if peak == current:
            await self.db.set_kv(key, str(peak))
        return web.json_response(
            {
                "online": current,
                "chatting": chatting,
                "searching": searching,
                "free": max(0, current - chatting - searching),
                "peak": peak,
                "status": self.mm.status(uid),
                "position": self.mm.position(uid) if self.mm.status(uid) == "queued" else None,
            }
        )

    async def activity(self, request: web.Request) -> web.Response:
        uid, _, row = await self._auth(request)
        engagement = await self.db.engagement_state(uid)
        result = {
            "today": await self.db.activity_totals(uid, 1),
            "week": await self.db.activity_totals(uid, 7),
            "month": await self.db.activity_totals(uid, 30),
            "all": {
                "dialogs": int(row["dialogs"] or 0),
                "messages": int(row["messages"] or 0),
                "games": int(engagement["games_total"] or 0),
                "battle_games": int(engagement["battle_games_total"] or 0),
                "number_games": int(engagement["number_games_total"] or 0),
                "good_ratings": int(row["good_ratings"] or 0),
            },
        }
        return web.json_response(result)

    async def streak(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        row = await self.db.engagement_state(uid)
        return web.json_response(
            {"current": int(row["current_streak"] or 0), "best": int(row["best_streak"] or 0)}
        )

    async def quests(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        today = await self.db.activity_totals(uid, 1)
        specs = (("Отправь 20 сообщений", "messages", 20), ("Проведи 3 диалога", "dialogs", 3), ("Сыграй 1 игру", "games", 1))
        items = []
        for title, key, target in specs:
            current = min(target, int(today[key]))
            items.append({"title": title, "current": current, "target": target, "done": current >= target})
        return web.json_response({"items": items})

    async def top(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        rows = await self.db.top(10)
        return web.json_response(
            {
                "items": [
                    {
                        "place": place,
                        "user_id": int(row["user_id"]),
                        "nick": nicklib.display(row["nickname"], int(row["user_id"]), row["support_stars"]),
                        "stars": int(row["xp"] or 0),
                        "rank": rank_for(int(row["messages"] or 0)).title,
                    }
                    for place, row in enumerate(rows, 1)
                ],
                "me": uid,
            }
        )

    async def _notifications(self, uid: int) -> list[dict]:
        status = self.mm.status(uid)
        if status == "paired":
            return [{"id": "dialog-active", "type": "personal", "icon": "message-circle", "title": "Диалог активен", "text": "Собеседник найден. Возвращайся в чат.", "time": "сейчас", "unread": True}]
        if status == "queued":
            return [{"id": "search-active", "type": "system", "icon": "search", "title": "Поиск идёт", "text": "Можно закрыть Mini App — очередь сохранится.", "time": "сейчас", "unread": True}]
        return []

    async def notifications(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        return web.json_response({"items": await self._notifications(uid)})

    async def notification_read(self, request: web.Request) -> web.Response:
        await self._auth(request)
        return web.json_response({"ok": True})

    async def feedback(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        data = await request.json()
        text = str(data.get("text", "")).strip()
        if not 1 <= len(text) <= 1000:
            raise _json_error(400, "Сообщение должно быть от 1 до 1000 символов")
        admin_ids = await self.db.all_admin_ids(self.cfg.admin_ids)
        sent = 0
        for admin_id in admin_ids:
            try:
                await self.bot.send_message(
                    admin_id,
                    f"💬 <b>Обратная связь из Mini App</b>\n\n{html.escape(text)}\n\n<code>{uid}</code>",
                )
                sent += 1
            except TelegramAPIError:
                pass
        if admin_ids and not sent:
            raise _json_error(503, "Не получилось доставить сообщение")
        return web.json_response({"ok": True})

    async def game_battle(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        partner = self.mm.partner(uid)
        if partner is None:
            raise _json_error(409, "Сначала найди собеседника")
        data = await request.json()
        total = int(data.get("total", 10) or 10)
        if total not in {5, 10}:
            total = 10
        existing = await self.db.game_for_pair(uid, partner)
        if existing is not None:
            raise _json_error(409, "У вас уже есть активная игра")
        game, created = await self.db.create_battle_invite(uid, partner, total)
        if not created:
            raise _json_error(409, "Предложение уже создано")
        result = await send_to(
            self.bot,
            partner,
            f"⚔️ <b>Собеседник предлагает сыграть в Битву мнений</b>\nВопросов: <b>{total}</b>",
            K.battle_invite_keyboard(int(game["id"])),
            self.pack,
        )
        if result is DeliveryResult.UNAVAILABLE:
            await self.db.cancel_battle(int(game["id"]))
            raise _json_error(503, "Не удалось доставить приглашение")
        live_chat.system({uid, partner}, "⚔️ Приглашение в «Битву мнений» отправлено")
        return web.json_response({"ok": True, "message": "Приглашение отправлено"})

    async def game_numbers(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        partner = self.mm.partner(uid)
        if partner is None:
            raise _json_error(409, "Сначала найди собеседника")
        data = await request.json()
        try:
            range_max = int(data.get("range_max", 0))
        except (TypeError, ValueError) as exc:
            raise _json_error(400, "Неверный диапазон") from exc
        if range_max not in NUMBER_REWARDS:
            raise _json_error(400, "Можно выбрать 1–10, 1–100 или 1–1000")
        if await self.db.game_for_pair(uid, partner) is not None:
            raise _json_error(409, "У вас уже есть активная игра")
        reward_available = await self.db.number_pair_reward_available(uid, partner)
        game, created = await self.db.create_number_invite(uid, partner, range_max)
        if not created:
            raise _json_error(409, "Предложение уже создано")
        reward = NUMBER_REWARDS[range_max]
        near = reward // 2
        result = await send_to(
            self.bot,
            partner,
            f"🔢 <b>Собеседник предлагает сыграть в Числа</b>\n"
            f"Диапазон: <b>1–{range_max}</b> · раундов: <b>{NUMBER_ROUNDS}</b>\n"
            f"Точное совпадение: <b>{reward} ⭐</b> · "
            f"разница до {NUMBER_NEAR_DIFFS[range_max]}: <b>{near} ⭐</b>\n"
            + (
                f"Награды доступны · дневной лимит {NUMBER_DAILY_REWARD_LIMIT} ⭐."
                if reward_available else "Вы уже играли вместе — эта игра будет без награды."
            ),
            K.number_invite_keyboard(int(game["id"])),
            self.pack,
        )
    async def game_numbers(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        partner = self.mm.partner(uid)
        if partner is None:
            raise _json_error(409, "Сначала найди собеседника")
        data = await request.json()
        try:
            range_max = int(data.get("range_max", 0))
        except (TypeError, ValueError) as exc:
            raise _json_error(400, "Неверный диапазон") from exc
        if range_max not in NUMBER_REWARDS:
            raise _json_error(400, "Можно выбрать 1–10, 1–100 или 1–1000")
        if await self.db.game_for_pair(uid, partner) is not None:
            raise _json_error(409, "У вас уже есть активная игра")
        reward_available = await self.db.number_pair_reward_available(uid, partner)
        game, created = await self.db.create_number_invite(uid, partner, range_max)
        if not created:
            raise _json_error(409, "Предложение уже создано")
        reward = NUMBER_REWARDS[range_max]
        near = reward // 2
        result = await send_to(
            self.bot,
            partner,
            f"🔢 <b>Собеседник предлагает сыграть в Числа</b>\n"
            f"Диапазон: <b>1–{range_max}</b> · раундов: <b>{NUMBER_ROUNDS}</b>\n"
            f"Точное совпадение: <b>{reward} ⭐</b> · "
            f"разница до {NUMBER_NEAR_DIFFS[range_max]}: <b>{near} ⭐</b>\n"
            + (
                f"Награды доступны · дневной лимит {NUMBER_DAILY_REWARD_LIMIT} ⭐."
                if reward_available else "Вы уже играли вместе — эта игра будет без награды."
            ),
            K.number_invite_keyboard(int(game["id"])),
            self.pack,
        )
        if result is DeliveryResult.UNAVAILABLE:
            await self.db.cancel_battle(int(game["id"]))
            raise _json_error(503, "Не удалось доставить приглашение")
        live_chat.system({uid, partner}, "🔢 Приглашение в игру «Числа» отправлено")
        return web.json_response({"ok": True, "message": "Приглашение отправлено"})

    async def game_words(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        partner = self.mm.partner(uid)
        if partner is None:
            raise _json_error(409, "Сначала найди собеседника")
        if WG.active_for_pair(uid, partner):
            raise _json_error(409, "У вас уже есть активная игра «Объясни слово»")
        if await self.db.game_for_pair(uid, partner) is not None:
            raise _json_error(409, "Сначала заверши текущую игру")
        game, created = WG.create_invite(uid, partner)
        if not created:
            raise _json_error(409, "Предложение уже создано")
        result = await send_to(
            self.bot,
            partner,
            "🗣 <b>Собеседник предлагает сыграть в «Объясни слово»</b>\n\n"
            f"Раундов: <b>{WG.WORD_ROUNDS}</b>. Один объясняет слово, второй угадывает. "
            f"За правильное угадывание — до <b>{WG.WORD_REWARD} ⭐</b>.",
            K.word_invite_keyboard(game.id),
            self.pack,
        )
        if result is DeliveryResult.UNAVAILABLE:
            WG.remove(game.id)
            raise _json_error(503, "Не удалось доставить приглашение")
        live_chat.system(
            {uid, partner},
            "🗣 Предложение сыграть в «Объясни слово» отправлено",
        )
        return web.json_response({"ok": True, "message": "Приглашение отправлено"})

    async def subscription(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        return web.json_response(
            {
                "claimed": await self.db.reward_claimed(uid, SUBSCRIPTION_REWARD_KEY),
                "amount": max(1, int(self.cfg.subscription_reward)),
                "url": _subscription_url(
                    self.cfg.subscription_channel, self.cfg.subscription_channel_url
                ),
            }
        )

    async def subscription_claim(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        if await self.db.reward_claimed(uid, SUBSCRIPTION_REWARD_KEY):
            raise _json_error(409, "Эта награда уже получена")
        target = _subscription_chat_id(self.cfg.subscription_channel)
        if target is None:
            raise _json_error(503, "Канал пока не подключён")
        try:
            member = await self.bot.get_chat_member(chat_id=target, user_id=uid)
        except TelegramAPIError as exc:
            raise _json_error(503, "Не удалось проверить подписку") from exc
        if not _member_is_subscribed(member):
            raise _json_error(403, "Сначала подпишись на канал")
        amount = max(1, int(self.cfg.subscription_reward))
        if not await self.db.claim_one_time_reward(uid, SUBSCRIPTION_REWARD_KEY, amount):
            raise _json_error(409, "Эта награда уже получена")
        row = await self.db.get_user(uid)
        return web.json_response(
            {"ok": True, "amount": amount, "stars": int(row["xp"] or 0) if row else 0}
        )

    async def forget(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        if self.mm.status(uid) == "paired":
            raise _json_error(409, "Сначала заверши текущий диалог")
        self.mm.forget(uid)
        await self.db.forget_user(uid)
        self.db.schedule_matchmaker_save(self.mm)
        return web.json_response({"ok": True})

    async def health(self, _request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "service": "anon-mgn-miniapp"})

    @web.middleware
    async def security_headers(self, request: web.Request, handler):
        origin = request.headers.get("Origin", "").rstrip("/")
        origin_host = urlsplit(origin).netloc.lower() if origin else ""
        request_hosts = {str(request.host or "").strip().lower()}
        forwarded_host = request.headers.get("X-Forwarded-Host", "")
        request_hosts.update(
            item.strip().lower()
            for item in forwarded_host.split(",")
            if item.strip()
        )
        same_origin = bool(origin_host and origin_host in request_hosts)
        origin_allowed = same_origin or origin in self.allowed_origins
        if origin and request.path.startswith("/api/") and not origin_allowed:
            raise _json_error(403, "Источник Mini App не разрешён")
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            try:
                response = await handler(request)
            except web.HTTPException as exc:
                response = exc
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://telegram.org; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; "
            "connect-src 'self'; frame-ancestors https://web.telegram.org https://*.telegram.org"
        )
        if origin and origin_allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, X-Telegram-Init-Data"
            )
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Max-Age"] = "600"
        return response

    def create_app(self) -> web.Application:
        if self.serve_static and (
            not self.web_dir.is_dir() or not (self.web_dir / "index.html").is_file()
        ):
            raise RuntimeError(f"MINIAPP_WEB_DIR не найден: {self.web_dir}")
        app = web.Application(client_max_size=12 * 1024 * 1024, middlewares=[self.security_headers])
        app.router.add_get("/api/miniapp/health", self.health)
        app.router.add_get("/api/miniapp/me", self.me)
        app.router.add_get("/api/miniapp/status", self.status)
        app.router.add_get("/api/miniapp/chat/state", self.chat_state)
        app.router.add_post("/api/miniapp/chat/text", self.chat_send_text)
        app.router.add_post("/api/miniapp/chat/photo", self.chat_send_photo)
        app.router.add_post("/api/miniapp/chat/voice", self.chat_send_voice)
        app.router.add_get("/api/miniapp/chat/stickers", self.chat_stickers)
        app.router.add_post("/api/miniapp/chat/sticker", self.chat_send_sticker)
        app.router.add_get("/api/miniapp/chat/media/{token}", self.chat_media)
        app.router.add_get("/api/miniapp/chat/sticker-media/{sticker_id}", self.chat_sticker_media)
        app.router.add_post("/api/miniapp/chat/stop", self.chat_stop)
        app.router.add_post("/api/miniapp/chat/next", self.chat_next)
        app.router.add_post("/api/miniapp/settings", self.settings)
        app.router.add_post("/api/miniapp/settings/reset", self.settings_reset)
        app.router.add_post("/api/miniapp/profile/nick", self.nick)
        app.router.add_post("/api/miniapp/profile/forget", self.forget)
        app.router.add_post("/api/miniapp/search/start", self.search_start)
        app.router.add_post("/api/miniapp/search/stop", self.search_stop)
        app.router.add_get("/api/miniapp/online", self.online)
        app.router.add_get("/api/miniapp/activity", self.activity)
        app.router.add_get("/api/miniapp/streak", self.streak)
        app.router.add_get("/api/miniapp/quests", self.quests)
        app.router.add_get("/api/miniapp/top", self.top)
        app.router.add_get("/api/miniapp/notifications", self.notifications)
        app.router.add_post("/api/miniapp/notifications/{notification_id}/read", self.notification_read)
        app.router.add_post("/api/miniapp/feedback", self.feedback)
        app.router.add_post("/api/miniapp/games/battle/invite", self.game_battle)
        app.router.add_post("/api/miniapp/games/numbers/invite", self.game_numbers)
        app.router.add_post("/api/miniapp/games/words/invite", self.game_words)
        app.router.add_get("/api/miniapp/subscription", self.subscription)
        app.router.add_post("/api/miniapp/subscription/claim", self.subscription_claim)
        app.router.add_route("OPTIONS", "/api/miniapp/{tail:.*}", self.health)

        async def index(_request: web.Request) -> web.StreamResponse:
            return web.FileResponse(self.web_dir / "index.html")

        if self.serve_static:
            app.router.add_get("/", index)
            app.router.add_static("/", self.web_dir, show_index=False, append_version=True)
        return app

    async def start(self) -> None:
        if self.runner is not None:
            return
        self.runner = web.AppRunner(self.create_app(), access_log=None)
        await self.runner.setup()
        host = os.getenv("MINIAPP_HOST", "0.0.0.0")
        port = int(os.getenv("PORT", os.getenv("MINIAPP_PORT", "3000")))
        self.site = web.TCPSite(self.runner, host=host, port=port)
        await self.site.start()

    async def stop(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None
            self.site = None


async def start_miniapp_server(bot, cfg, db, mm, pack, *, web_dir=None) -> MiniAppServer:
    server = MiniAppServer(bot, cfg, db, mm, pack, web_dir=web_dir)
    await server.start()
    return server
