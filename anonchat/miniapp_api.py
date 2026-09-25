"""Same-process HTTP API и статика Telegram Mini App."""

from __future__ import annotations

import asyncio
import hashlib
import io
import html
import hmac
import json
import os
import random
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
from .actions import DeliveryResult, _dialog_summary_text, announce_pairs, break_pair, send_to
from .levels import rank_for
from .battle_questions import get_question, questions
from .engagement import collect_progress_notifications
from .number_game import NUMBER_DAILY_REWARD_LIMIT, NUMBER_NEAR_DIFFS, NUMBER_REWARDS, NUMBER_ROUNDS
from .runtime_state import online_count as presence_online_count
from .runtime_state import touch as presence_touch
from .miniapp_features import (
    REPORT_REASONS,
    achievement_items,
    dialog_result_payload,
    event_payload,
    period_deadline,
    poll_payload,
    quest_items,
)


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

    async def _push_event(
        self,
        user_id: int,
        event_type: str,
        title: str,
        text: str = "",
        *,
        icon: str = "bell",
        action: str = "",
    ) -> int:
        event_id = await self.db.add_miniapp_event(
            user_id, event_type, title, text, icon=icon, action=action
        )
        live_chat.signal({user_id}, "events_changed", event_id=event_id)
        return event_id

    def _auth_init_data(self, raw: str) -> tuple[int, dict]:
        user = validate_init_data(
            raw,
            self.cfg.bot_token,
            int(os.getenv("MINIAPP_INITDATA_MAX_AGE", "3600")),
        )
        user_id = int(user["id"])
        presence_touch(user_id)
        return user_id, user

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

    async def _mirror_to_sender(
        self, sender_id: int, partner_id: int, message_id: int
    ) -> None:
        """Копирует сообщение, отправленное из Mini App, в Telegram-чат отправителя.

        Telegram Bot API не может создать настоящий исходящий пузырь от имени пользователя,
        поэтому используется точная копия бот-сообщения/медиа.
        """
        if not message_id:
            return
        try:
            await self.bot.copy_message(
                chat_id=int(sender_id),
                from_chat_id=int(partner_id),
                message_id=int(message_id),
            )
        except TelegramAPIError:
            # Зеркало не должно ломать основную доставку собеседнику.
            pass

    def _battle_state_from_row(self, uid: int, row) -> dict:
        game_id = int(row["id"])
        status = str(row["status"] or "")
        user_a, user_b = int(row["user_a"]), int(row["user_b"])
        payload = {
            "type": "battle",
            "id": game_id,
            "status": status,
            "inviter": int(row["inviter_id"]) == int(uid),
            "round": int(row["question_index"] or 0) + 1,
            "total": int(row["total_questions"] or 0),
        }
        if status in {"active", "round_done", "finished"}:
            ids = json.loads(str(row["question_ids"] or "[]"))
            index = int(row["question_index"] or 0)
            if 0 <= index < len(ids):
                question = get_question(int(ids[index]))
                payload.update(
                    {
                        "question": question.text,
                        "options": [question.first, question.second],
                    }
                )
            mine = row["answer_a"] if user_a == int(uid) else row["answer_b"]
            other = row["answer_b"] if user_a == int(uid) else row["answer_a"]
            payload["answered"] = mine is not None
            payload["my_answer"] = int(mine) if mine is not None else None
            payload["partner_answer"] = int(other) if other is not None else None
            payload["matches"] = int(row["matches"] or 0)
            if mine is not None and other is not None:
                payload["matched"] = int(mine) == int(other)
            payload["can_next"] = status == "round_done"
            payload["finished"] = status == "finished"
        return payload

    def _number_state_from_row(self, uid: int, row) -> dict:
        status = str(row["status"] or "")
        user_a = int(row["user_a"])
        mine = row["answer_a"] if user_a == int(uid) else row["answer_b"]
        other = row["answer_b"] if user_a == int(uid) else row["answer_a"]
        payload = {
            "type": "numbers",
            "id": int(row["id"]),
            "status": status,
            "inviter": int(row["inviter_id"]) == int(uid),
            "round": int(row["question_index"] or 0) + 1,
            "total": int(row["total_questions"] or NUMBER_ROUNDS),
            "range_max": int(row["range_max"] or 0),
            "reward_enabled": bool(int(row["reward_awarded"] or 0)),
            "reward_total": int(
                (row["reward_total_a"] if user_a == int(uid) else row["reward_total_b"])
                or 0
            ),
            "answered": mine is not None,
            "my_answer": int(mine) if mine is not None else None,
            "partner_answer": int(other) if other is not None else None,
            "matches": int(row["matches"] or 0),
            "can_next": status == "round_done",
            "finished": status == "finished",
        }
        if mine is not None and other is not None:
            payload["difference"] = abs(int(mine) - int(other))
            payload["matched"] = int(mine) == int(other)
        return payload

    def _word_state(self, uid: int, partner: int) -> dict | None:
        game = WG.get_for_pair(uid, partner)
        if game is None:
            return None
        payload = {
            "type": "words",
            "id": int(game.id),
            "status": str(game.status),
            "inviter": int(game.inviter_id) == int(uid),
            "round": int(game.round_index) + 1,
            "total": int(WG.WORD_ROUNDS),
            "correct": int(sum(game.correct.values())),
            "can_next": str(game.status) == "round_done",
        }
        if game.status in {"active", "round_done"}:
            if int(game.explainer_id) == int(uid):
                payload["role"] = "explainer"
                payload["word"] = str(game.word)
                payload["hint"] = "Объясни слово собеседнику, не называя его."
            else:
                payload["role"] = "guesser"
                payload["word"] = ""
                payload["hint"] = "Угадай слово по объяснению собеседника."
        return payload

    async def _game_state_payload(self, uid: int, partner: int | None) -> dict | None:
        if partner is None:
            return None
        word = self._word_state(uid, partner)
        if word is not None:
            return word
        row = await self.db.game_for_pair(uid, partner)
        if row is None:
            return None
        game_type = str(row["game_type"] or "battle")
        if game_type == "numbers":
            return self._number_state_from_row(uid, row)
        return self._battle_state_from_row(uid, row)

    async def chat_state(self, request: web.Request) -> web.Response:
        uid, _ = self._telegram_user(request)
        try:
            after = int(request.query.get("after", "0") or 0)
        except ValueError:
            after = 0
        status = self.mm.status(uid)
        partner = self.mm.partner(uid)
        if status == "paired" and partner is not None:
            await live_chat.ensure_loaded(self.db, uid, partner)
        stats = self.mm.dialog_stats(uid) if status == "paired" else {}
        counts = stats.get("counts", {}) or {}
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
                "game": await self._game_state_payload(uid, partner),
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
        await self._mirror_to_sender(uid, partner, sent.message_id)
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
        await self._mirror_to_sender(uid, partner, sent.message_id)
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
        await self._mirror_to_sender(uid, partner, sent.message_id)
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
        await self._mirror_to_sender(uid, partner, sent.message_id)
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
        duration_seconds = max(0, int(time.time()) - started)
        game_stats = summary.get("game_stats", {}) or {}
        games_summary = []
        if int(game_stats.get("battle_games", 0)):
            games_summary.append({
                "type": "battle",
                "games": int(game_stats.get("battle_games", 0)),
                "matches": int(game_stats.get("battle_matches", 0)),
                "total": int(game_stats.get("battle_questions", 0)),
            })
        if int(game_stats.get("number_games", 0)):
            games_summary.append({
                "type": "numbers",
                "games": int(game_stats.get("number_games", 0)),
                "exact": int(game_stats.get("number_exact", 0)),
            })
        other_games = max(
            0,
            int(game_stats.get("games", 0))
            - int(game_stats.get("battle_games", 0))
            - int(game_stats.get("number_games", 0)),
        )
        if other_games:
            games_summary.append({"type": "words", "games": other_games})
        await self.db.save_dialog_result(
            uid, match_id, partner,
            started_at=started, duration=duration_seconds,
            sent=mine, received=theirs, earned=int(earned_xp.get(uid, 0)),
            games=games_summary,
        )
        await self.db.save_dialog_result(
            partner, match_id, uid,
            started_at=started, duration=duration_seconds,
            sent=theirs, received=mine, earned=int(earned_xp.get(partner, 0)),
            games=games_summary,
        )
        duration_label = (
            f"{max(1, duration_seconds // 60)} мин"
            if duration_seconds >= 60 else "меньше минуты"
        )
        await self._push_event(
            uid, "dialog", "Диалог завершён",
            f"{duration_label} · {mine} сообщений · +{int(earned_xp.get(uid, 0))} ⭐",
            icon="message-circle", action="dialog:result",
        )
        await self._push_event(
            partner, "dialog", "Диалог завершён",
            f"{duration_label} · {theirs} сообщений · +{int(earned_xp.get(partner, 0))} ⭐",
            icon="message-circle", action="dialog:result",
        )
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
        result["result"] = dialog_result_payload(await self.db.dialog_result(uid))
        live_chat.signal({uid, partner}, "status_changed", status="free")
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

    async def chat_result(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        return web.json_response(
            {"result": dialog_result_payload(await self.db.dialog_result(uid))}
        )

    async def chat_rate(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        data = await request.json()
        value = 1 if bool(data.get("positive")) else 0
        result_row = await self.db.dialog_result(uid)
        if result_row is None:
            raise _json_error(404, "Итог диалога уже недоступен")
        if bool(int(result_row["rated"] or 0)):
            raise _json_error(409, "Оценка уже учтена")
        partner = await self.db.rate_dialog(int(result_row["match_id"]), uid, value)
        if partner is None:
            await self.db.mark_dialog_result_rated(uid)
            raise _json_error(409, "Оценка уже учтена")
        await self.db.activity_add(uid, ratings_given=1)
        reward = 0
        if value:
            reward = max(0, int(self.cfg.xp_good_rating))
            if reward:
                await self.db.award_xp(partner, reward)
            await self.db.activity_add(partner, good_ratings=1)
            await self._push_event(
                partner, "rating", "Хорошая оценка",
                f"Собеседник поставил 👍 · +{reward} ⭐",
                icon="thumbs-up", action="profile",
            )
        await self.db.mark_dialog_result_rated(uid)
        self.mm.pop_rating(uid)
        for notice in await collect_progress_notifications(self.db, uid):
            await send_to(self.bot, uid, notice, pack=self.pack)
        if value:
            for notice in await collect_progress_notifications(self.db, partner):
                await send_to(self.bot, partner, notice, pack=self.pack)
        live_chat.signal({uid}, "result_changed", rated=True)
        return web.json_response({"ok": True, "positive": bool(value), "reward": reward})

    async def chat_report(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        partner = self.mm.partner(uid)
        if partner is None:
            raise _json_error(409, "Жалобу можно отправить только во время диалога")
        data = await request.json()
        reason = str(data.get("reason", "") or "")
        if reason not in REPORT_REASONS:
            raise _json_error(400, "Выбери причину жалобы")
        comment = str(data.get("comment", "") or "").strip()[:500]
        dialog = self.mm.dialog_stats(uid)
        history = dialog.get("history", []) or []
        context = "\n".join(
            f"— {'жалующийся' if int(author) == uid else 'собеседник'}: {text}"
            for author, text in history[-6:]
        )
        report_id, day_count = await self.db.add_report(
            uid,
            partner,
            reason,
            comment,
            dialog_key=str(dialog.get("dialog_key", "")),
            context=context,
        )
        if report_id is None:
            raise _json_error(409, "На этот диалог жалоба уже отправлена")
        admin_ids = await self.db.admin_ids_with_permission("reports", self.cfg.admin_ids)
        body = (
            f"🚨 <b>Новая жалоба #{report_id}</b>\n\n"
            f"Причина: <b>{html.escape(REPORT_REASONS[reason])}</b>\n"
            f"Комментарий: {html.escape(comment) if comment else '—'}\n\n"
            f"На пользователя: <code>{partner}</code>\n"
            f"От пользователя: <code>{uid}</code>"
        )
        for admin_id in admin_ids:
            try:
                permissions = await self.db.get_admin_permissions(admin_id, self.cfg.admin_ids)
                await self.bot.send_message(
                    admin_id,
                    body,
                    reply_markup=K.admin_report_keyboard(report_id, permissions),
                )
            except TelegramAPIError:
                pass
        auto_muted = False
        if self.cfg.auto_mute_reports > 0 and day_count >= self.cfg.auto_mute_reports:
            await self.db.set_mute(partner, self.cfg.auto_mute_minutes)
            await break_pair(
                self.bot, self.cfg, self.mm, partner,
                texts.MOD_CLOSED_DIALOG, self.pack, self.db
            )
            auto_muted = True
        await self._push_event(
            uid, "report", "Жалоба отправлена",
            f"#{report_id} · {REPORT_REASONS[reason]}",
            icon="shield-check", action="events",
        )
        return web.json_response(
            {"ok": True, "report_id": report_id, "auto_muted": auto_muted}
        )

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
        return web.json_response({"items": await quest_items(self.db, uid)})

    async def achievements(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        items = await achievement_items(self.db, uid)
        return web.json_response({
            "items": items,
            "unlocked": sum(1 for item in items if item["unlocked"]),
            "total": len(items),
        })

    async def top(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        period = str(request.query.get("period", "week") or "week").lower()
        days = {"week": 7, "month": 30, "all": 0}.get(period)
        if days is None:
            raise _json_error(400, "Период: week, month или all")
        rows = await self.db.top_period(days, 10)
        return web.json_response(
            {
                "period": period,
                "items": [
                    {
                        "place": place,
                        "user_id": int(row["user_id"]),
                        "nick": nicklib.display(
                            row["nickname"],
                            int(row["user_id"]),
                            row["support_stars"],
                        ),
                        "stars": int(row["xp"] or 0),
                        "rank": rank_for(int(row["messages"] or 0)).title,
                        "me": int(row["user_id"]) == uid,
                    }
                    for place, row in enumerate(rows, 1)
                ],
                "me": uid,
                "my": await self.db.top_position_period(uid, days),
                "ends_at": period_deadline(period),
            }
        )

    async def _notifications(self, uid: int) -> list[dict]:
        rows = await self.db.miniapp_events(uid, limit=60)
        items = [event_payload(row) for row in rows]
        status = self.mm.status(uid)
        if status == "paired":
            items.insert(0, {
                "id": "dialog-active", "type": "personal", "icon": "message-circle",
                "title": "Диалог активен", "text": "Собеседник найден. Открыть чат.",
                "action": "chat", "created_at": int(time.time()), "unread": False,
            })
        elif status == "queued":
            items.insert(0, {
                "id": "search-active", "type": "system", "icon": "search",
                "title": "Поиск идёт", "text": "Очередь работает даже когда Mini App закрыта.",
                "action": "search", "created_at": int(time.time()), "unread": False,
            })
        return items

    async def notifications(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        items = await self._notifications(uid)
        return web.json_response({
            "items": items,
            "unread": sum(1 for item in items if item.get("unread")),
        })

    async def notification_read(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        raw = request.match_info["notification_id"]
        if raw == "all":
            changed = await self.db.read_all_miniapp_events(uid)
        elif raw.isdigit():
            changed = int(await self.db.read_miniapp_event(uid, int(raw)))
        else:
            changed = 0
        live_chat.signal({uid}, "events_changed")
        return web.json_response({"ok": True, "changed": changed})

    async def poll(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        return web.json_response({"poll": await poll_payload(self.db, uid)})

    async def poll_vote(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        data = await request.json()
        try:
            poll_id = int(data.get("poll_id", 0) or 0)
            choice = int(data.get("choice", -1))
        except (TypeError, ValueError) as exc:
            raise _json_error(400, "Некорректный вариант") from exc
        if choice not in {0, 1} or not await self.db.vote_poll(poll_id, uid, choice):
            raise _json_error(409, "Опрос уже закрыт")
        live_chat.signal({uid}, "poll_changed", poll_id=poll_id)
        return web.json_response({"ok": True, "poll": await poll_payload(self.db, uid)})

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
        live_chat.game_invite(
            uid,
            partner,
            "battle",
            int(game["id"]),
            "⚔️ Битва мнений",
            f"{total} вопросов",
        )
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
        if result is DeliveryResult.UNAVAILABLE:
            await self.db.cancel_battle(int(game["id"]))
            raise _json_error(503, "Не удалось доставить приглашение")
        live_chat.game_invite(
            uid,
            partner,
            "numbers",
            int(game["id"]),
            "🔢 Числа",
            f"Диапазон 1–{range_max} · {NUMBER_ROUNDS} раунда",
        )
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
        live_chat.game_invite(
            uid,
            partner,
            "words",
            int(game.id),
            "🗣 Объясни слово",
            f"{WG.WORD_ROUNDS} слов · до {WG.WORD_REWARD} ⭐ за угадывание",
        )
        return web.json_response({"ok": True, "message": "Приглашение отправлено"})

    async def game_respond(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        data = await request.json()
        game_type = str(data.get("game_type", "") or "")
        try:
            game_id = int(data.get("game_id", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise _json_error(400, "Игра не найдена") from exc
        accept = bool(data.get("accept", False))
        partner = self.mm.partner(uid)
        if partner is None:
            raise _json_error(409, "Диалог уже завершён")

        if game_type == "words":
            game = WG.get_by_id(game_id)
            if game is None or {int(game.user_a), int(game.user_b)} != {uid, partner}:
                raise _json_error(404, "Предложение уже закрыто")
            if accept:
                game = WG.accept(game_id, uid)
                if game is None:
                    raise _json_error(409, "На предложение уже ответили")
                for player_id in (game.user_a, game.user_b):
                    role = WG.role_text(game, player_id)
                    await send_to(self.bot, player_id, role, K.chat_keyboard(), self.pack)
                    live_chat.private(player_id, role, kind="game_round", data={
                        "game_type": "words", "game_id": int(game.id)
                    })
                live_chat.game_status(
                    {game.user_a, game.user_b}, "words", game_id, "accepted", "Игра началась"
                )
                return web.json_response({"ok": True, "status": "accepted"})
            declined = WG.decline(game_id, uid)
            if declined is None:
                raise _json_error(409, "Предложение уже закрыто")
            await send_to(
                self.bot,
                int(declined.inviter_id),
                "Собеседник пока не хочет играть в «Объясни слово».",
                K.chat_keyboard(),
                self.pack,
            )
            live_chat.game_status(
                {declined.user_a, declined.user_b},
                "words",
                game_id,
                "declined",
                "Предложение отклонено",
            )
            return web.json_response({"ok": True, "status": "declined"})

        row = await self.db.get_battle(game_id)
        if row is None:
            raise _json_error(404, "Предложение уже закрыто")
        user_a, user_b = int(row["user_a"]), int(row["user_b"])
        if {user_a, user_b} != {uid, partner}:
            raise _json_error(403, "Это предложение не для тебя")
        actual_type = str(row["game_type"] or "battle")
        if actual_type != game_type:
            raise _json_error(400, "Тип игры не совпадает")

        if game_type == "battle":
            if accept:
                total = int(row["total_questions"])
                selected = random.sample(list(questions()), total)
                game = await self.db.accept_battle(game_id, uid, selected)
                if game is None:
                    raise _json_error(409, "На предложение уже ответили")
                ids = json.loads(str(game["question_ids"] or "[]"))
                index = int(game["question_index"])
                question = get_question(int(ids[index]))
                body = f"⚔️ <b>{index + 1}/{int(game['total_questions'])}</b>\n\n{texts.esc(question.text)}"
                markup = K.battle_answer_keyboard(
                    game_id, index, question.first, question.second
                )
                for player_id in (user_a, user_b):
                    await send_to(self.bot, player_id, body, markup, self.pack)
                live_chat.game_status(
                    {user_a, user_b}, "battle", game_id, "accepted", "Игра началась"
                )
                return web.json_response({"ok": True, "status": "accepted"})
            declined = await self.db.decline_battle(game_id, uid)
            if declined is None:
                raise _json_error(409, "Предложение уже закрыто")
            await send_to(
                self.bot,
                int(declined["inviter_id"]),
                "Собеседник пока не хочет играть.",
                K.chat_keyboard(),
                self.pack,
            )
            live_chat.game_status(
                {user_a, user_b}, "battle", game_id, "declined", "Предложение отклонено"
            )
            return web.json_response({"ok": True, "status": "declined"})

        if game_type == "numbers":
            if accept:
                game = await self.db.accept_number(game_id, uid)
                if game is None:
                    raise _json_error(409, "На предложение уже ответили")
                range_max = int(game["range_max"])
                round_index = int(game["question_index"])
                reward = NUMBER_REWARDS[range_max]
                body = (
                    f"🔢 <b>Числа · раунд {round_index + 1}/{NUMBER_ROUNDS}</b>\n\n"
                    f"Выбери число от <b>1</b> до <b>{range_max}</b>.\n"
                    f"Точное совпадение: до <b>{reward} ⭐</b>."
                )
                markup = K.number_input_keyboard(game_id, round_index)
                for player_id in (user_a, user_b):
                    await send_to(self.bot, player_id, body, markup, self.pack)
                live_chat.game_status(
                    {user_a, user_b}, "numbers", game_id, "accepted", "Игра началась"
                )
                return web.json_response({"ok": True, "status": "accepted"})
            declined = await self.db.decline_number(game_id, uid)
            if declined is None:
                raise _json_error(409, "Предложение уже закрыто")
            await send_to(
                self.bot,
                int(declined["inviter_id"]),
                "Собеседник пока не хочет играть в Числа.",
                K.chat_keyboard(),
                self.pack,
            )
            live_chat.game_status(
                {user_a, user_b}, "numbers", game_id, "declined", "Предложение отклонено"
            )
            return web.json_response({"ok": True, "status": "declined"})

        raise _json_error(400, "Неизвестная игра")

    async def game_action(self, request: web.Request) -> web.Response:
        uid, _, _ = await self._auth(request)
        partner = self.mm.partner(uid)
        if partner is None:
            raise _json_error(409, "Диалог уже завершён")
        data = await request.json()
        game_type = str(data.get("game_type", "") or "")
        action = str(data.get("action", "") or "")
        try:
            game_id = int(data.get("game_id", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise _json_error(400, "Игра не найдена") from exc

        if game_type == "words":
            game = WG.get_by_id(game_id)
            if game is None or {game.user_a, game.user_b} != {uid, partner}:
                raise _json_error(404, "Игра уже завершена")
            if action != "next":
                raise _json_error(400, "Неизвестное действие")
            current_round = int(game.round_index)
            game = WG.advance(game_id, uid, current_round)
            if game is None:
                raise _json_error(409, "Собеседник уже перешёл дальше")
            for player_id in (game.user_a, game.user_b):
                role = WG.role_text(game, player_id)
                await send_to(self.bot, player_id, role, K.chat_keyboard(), self.pack)
                live_chat.private(
                    player_id,
                    role,
                    kind="game_round",
                    data={"game_type": "words", "game_id": int(game.id)},
                )
            live_chat.game_status(
                {game.user_a, game.user_b},
                "words",
                game_id,
                "active",
                f"Раунд {game.round_index + 1}/{WG.WORD_ROUNDS}",
            )
            return web.json_response(
                {"ok": True, "game": self._word_state(uid, partner)}
            )

        row = await self.db.get_battle(game_id)
        if row is None:
            raise _json_error(404, "Игра уже завершена")
        user_a, user_b = int(row["user_a"]), int(row["user_b"])
        if {user_a, user_b} != {uid, partner}:
            raise _json_error(403, "Это не ваша игра")
        actual_type = str(row["game_type"] or "battle")
        if actual_type != game_type:
            raise _json_error(400, "Тип игры не совпадает")

        if game_type == "battle":
            if action == "answer":
                try:
                    choice = int(data.get("choice"))
                except (TypeError, ValueError) as exc:
                    raise _json_error(400, "Выбери вариант") from exc
                if choice not in {0, 1}:
                    raise _json_error(400, "Выбери один из двух вариантов")
                index = int(row["question_index"])
                result, game = await self.db.answer_battle(
                    game_id, uid, index, choice
                )
                if result in {"already", "closed"}:
                    raise _json_error(409, "Ты уже ответил или раунд закрыт")
                if result == "missing" or game is None:
                    raise _json_error(404, "Игра уже завершена")
                if result == "waiting":
                    return web.json_response(
                        {"ok": True, "game": self._battle_state_from_row(uid, game)}
                    )
                ids = json.loads(str(game["question_ids"] or "[]"))
                question = get_question(int(ids[index]))
                a, b = int(game["answer_a"]), int(game["answer_b"])
                matched = a == b
                for player_id in (user_a, user_b):
                    mine = a if player_id == user_a else b
                    other = b if player_id == user_a else a
                    body = (
                        ("🤝 <b>Совпало!</b>\n" if matched else "💥 <b>Разошлись</b>\n")
                        + f"Ты: <b>{texts.esc(question.option(mine))}</b>\n"
                        + f"Собеседник: <b>{texts.esc(question.option(other))}</b>"
                    )
                    if str(game["status"]) == "finished":
                        body += (
                            f"\n\n⚔️ <b>Битва окончена</b>\n"
                            f"Совпадений: <b>{int(game['matches'])}/{int(game['total_questions'])}</b>."
                        )
                        if int(game["matches"]) == int(game["total_questions"]):
                            body += "\n🎁 Каждому начислено <b>25 ⭐</b>."
                    await send_to(self.bot, player_id, body, K.chat_keyboard(), self.pack)
                if str(game["status"]) == "finished":
                    self.mm.record_game(
                        user_a,
                        "battle",
                        int(game["matches"]),
                        int(game["total_questions"]),
                    )
                    for player_id in (user_a, user_b):
                        await self.db.record_game_engagement(
                            player_id,
                            "battle",
                            matches=int(game["matches"]),
                            total=int(game["total_questions"]),
                        )
                        for notice in await collect_progress_notifications(self.db, player_id):
                            await send_to(self.bot, player_id, notice, pack=self.pack)
                    live_chat.game_status(
                        {user_a, user_b}, "battle", game_id, "finished", "Битва окончена"
                    )
                else:
                    live_chat.game_status(
                        {user_a, user_b}, "battle", game_id, "round_done",
                        "Ответы получены · можно перейти дальше",
                    )
                return web.json_response(
                    {"ok": True, "game": self._battle_state_from_row(uid, game)}
                )

            if action == "next":
                index = int(row["question_index"])
                game = await self.db.advance_battle(game_id, uid, index)
                if game is None:
                    raise _json_error(409, "Собеседник уже перешёл дальше")
                ids = json.loads(str(game["question_ids"] or "[]"))
                question = get_question(int(ids[int(game["question_index"])]))
                body = (
                    f"⚔️ <b>{int(game['question_index']) + 1}/{int(game['total_questions'])}</b>"
                    f"\n\n{texts.esc(question.text)}"
                )
                markup = K.battle_answer_keyboard(
                    game_id,
                    int(game["question_index"]),
                    question.first,
                    question.second,
                )
                for player_id in (user_a, user_b):
                    await send_to(self.bot, player_id, body, markup, self.pack)
                live_chat.game_status(
                    {user_a, user_b}, "battle", game_id, "active",
                    f"Вопрос {int(game['question_index']) + 1}/{int(game['total_questions'])}",
                )
                return web.json_response(
                    {"ok": True, "game": self._battle_state_from_row(uid, game)}
                )
            raise _json_error(400, "Неизвестное действие")

        if game_type == "numbers":
            if action == "answer":
                try:
                    value = int(data.get("value"))
                except (TypeError, ValueError) as exc:
                    raise _json_error(400, "Введи число") from exc
                index = int(row["question_index"])
                result, game, reward_a, reward_b = await self.db.answer_number(
                    game_id, uid, index, value
                )
                if result == "invalid":
                    raise _json_error(400, f"Число должно быть от 1 до {int(row['range_max'])}")
                if result in {"already", "closed"}:
                    raise _json_error(409, "Ты уже выбрал число или раунд закрыт")
                if result == "missing" or game is None:
                    raise _json_error(404, "Игра уже завершена")
                if result == "waiting":
                    return web.json_response(
                        {"ok": True, "game": self._number_state_from_row(uid, game)}
                    )
                a, b = int(game["answer_a"]), int(game["answer_b"])
                diff = abs(a - b)
                for player_id in (user_a, user_b):
                    mine = a if player_id == user_a else b
                    other = b if player_id == user_a else a
                    reward = reward_a if player_id == user_a else reward_b
                    body = (
                        f"🔢 <b>Результат</b>\n"
                        f"Ты: <b>{mine}</b> · Собеседник: <b>{other}</b>\n"
                        f"Разница: <b>{diff}</b>"
                    )
                    if reward > 0:
                        body += f"\n+<b>{reward} ⭐</b>"
                    if str(game["status"]) == "finished":
                        body += (
                            f"\n\n🏁 <b>Игра окончена</b> · "
                            f"точных совпадений: <b>{int(game['matches'])}/{NUMBER_ROUNDS}</b>."
                        )
                    await send_to(self.bot, player_id, body, K.chat_keyboard(), self.pack)
                if str(game["status"]) == "finished":
                    self.mm.record_game(
                        user_a, "numbers", int(game["matches"]), NUMBER_ROUNDS
                    )
                    for player_id in (user_a, user_b):
                        await self.db.record_game_engagement(
                            player_id,
                            "numbers",
                            matches=int(game["matches"]),
                            total=NUMBER_ROUNDS,
                            number_exact=int(game["matches"]),
                            range_max=int(game["range_max"]),
                        )
                        for notice in await collect_progress_notifications(self.db, player_id):
                            await send_to(self.bot, player_id, notice, pack=self.pack)
                    live_chat.game_status(
                        {user_a, user_b}, "numbers", game_id, "finished", "Игра окончена"
                    )
                else:
                    live_chat.game_status(
                        {user_a, user_b}, "numbers", game_id, "round_done",
                        "Оба числа выбраны · можно дальше",
                    )
                return web.json_response(
                    {"ok": True, "game": self._number_state_from_row(uid, game)}
                )

            if action == "next":
                index = int(row["question_index"])
                game = await self.db.advance_number(game_id, uid, index)
                if game is None:
                    raise _json_error(409, "Собеседник уже перешёл дальше")
                body = (
                    f"🔢 <b>Числа · раунд {int(game['question_index']) + 1}/{NUMBER_ROUNDS}</b>"
                    f"\n\nВыбери число от <b>1</b> до <b>{int(game['range_max'])}</b>."
                )
                markup = K.number_input_keyboard(game_id, int(game["question_index"]))
                for player_id in (user_a, user_b):
                    await send_to(self.bot, player_id, body, markup, self.pack)
                live_chat.game_status(
                    {user_a, user_b}, "numbers", game_id, "active",
                    f"Раунд {int(game['question_index']) + 1}/{NUMBER_ROUNDS}",
                )
                return web.json_response(
                    {"ok": True, "game": self._number_state_from_row(uid, game)}
                )
            raise _json_error(400, "Неизвестное действие")

        raise _json_error(400, "Неизвестная игра")

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

    async def websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=25, autoping=True, max_msg_size=128 * 1024)
        await ws.prepare(request)
        uid = 0
        queue = None
        pump_task: asyncio.Task | None = None
        try:
            try:
                first = await asyncio.wait_for(ws.receive(), timeout=8)
            except asyncio.TimeoutError:
                await ws.close(code=4001, message=b"auth timeout")
                return ws
            if first.type != web.WSMsgType.TEXT:
                await ws.close(code=4001, message=b"auth required")
                return ws
            try:
                payload = json.loads(first.data)
            except (TypeError, json.JSONDecodeError):
                await ws.close(code=4001, message=b"bad auth")
                return ws
            if payload.get("type") != "auth":
                await ws.close(code=4001, message=b"auth required")
                return ws
            try:
                uid, user = self._auth_init_data(str(payload.get("initData", "") or ""))
            except web.HTTPException:
                await ws.close(code=4003, message=b"unauthorized")
                return ws
            await self.db.ensure_user(
                uid, user.get("username"), user.get("first_name") or "Пользователь"
            )
            queue = live_chat.subscribe(uid)
            await ws.send_json({
                "type": "ready",
                "status": self.mm.status(uid),
                "latest": live_chat.latest_seq(uid),
            })

            async def pump() -> None:
                while not ws.closed:
                    event = await queue.get()
                    await ws.send_json(event)

            pump_task = asyncio.create_task(pump())
            async for message in ws:
                if message.type == web.WSMsgType.TEXT:
                    try:
                        data = json.loads(message.data)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if data.get("type") == "ping":
                        presence_touch(uid)
                        await ws.send_json({"type": "pong", "ts": int(time.time())})
                elif message.type in {web.WSMsgType.CLOSE, web.WSMsgType.CLOSED, web.WSMsgType.ERROR}:
                    break
        finally:
            if pump_task is not None:
                pump_task.cancel()
                try:
                    await pump_task
                except (asyncio.CancelledError, ConnectionError):
                    pass
            if uid and queue is not None:
                live_chat.unsubscribe(uid, queue)
        return ws

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
        if isinstance(response, web.WebSocketResponse):
            return response
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
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
        app.router.add_get("/api/miniapp/ws", self.websocket)
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
        app.router.add_get("/api/miniapp/chat/result", self.chat_result)
        app.router.add_post("/api/miniapp/chat/rate", self.chat_rate)
        app.router.add_post("/api/miniapp/chat/report", self.chat_report)
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
        app.router.add_get("/api/miniapp/achievements", self.achievements)
        app.router.add_get("/api/miniapp/top", self.top)
        app.router.add_get("/api/miniapp/notifications", self.notifications)
        app.router.add_post("/api/miniapp/notifications/{notification_id}/read", self.notification_read)
        app.router.add_get("/api/miniapp/poll", self.poll)
        app.router.add_post("/api/miniapp/poll/vote", self.poll_vote)
        app.router.add_post("/api/miniapp/feedback", self.feedback)
        app.router.add_post("/api/miniapp/games/battle/invite", self.game_battle)
        app.router.add_post("/api/miniapp/games/numbers/invite", self.game_numbers)
        app.router.add_post("/api/miniapp/games/words/invite", self.game_words)
        app.router.add_post("/api/miniapp/games/respond", self.game_respond)
        app.router.add_post("/api/miniapp/games/action", self.game_action)
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
