"""Оперативная лента Mini App чата.

Сообщения и Telegram file_id живут только в RAM. В SQLite переписка не пишется.
Лента ограничена по размеру и очищается при завершении пары.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import secrets
import time
from typing import Any


@dataclass(slots=True)
class MediaRef:
    token: str
    file_id: str
    users: frozenset[int]
    kind: str
    created_at: float


_SEQ = 0
_EVENTS: dict[int, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=160))
_MEDIA: dict[str, MediaRef] = {}
_STICKERS: dict[str, str] = {}
_TTL = 30 * 60


def _next_seq() -> int:
    global _SEQ
    _SEQ += 1
    return _SEQ


def _prune() -> None:
    cutoff = time.time() - _TTL
    for token, ref in list(_MEDIA.items()):
        if ref.created_at < cutoff:
            _MEDIA.pop(token, None)


def _media_token(file_id: str, users: set[int] | frozenset[int], kind: str) -> str:
    _prune()
    token = secrets.token_urlsafe(18)
    _MEDIA[token] = MediaRef(
        token=token,
        file_id=str(file_id),
        users=frozenset(map(int, users)),
        kind=str(kind),
        created_at=time.time(),
    )
    return token


def register_sticker(sticker_id: str, file_id: str) -> None:
    if sticker_id and file_id:
        _STICKERS[str(sticker_id)] = str(file_id)


def sticker_file_id(sticker_id: str) -> str | None:
    return _STICKERS.get(str(sticker_id))


def media_ref(token: str, user_id: int) -> MediaRef | None:
    _prune()
    ref = _MEDIA.get(str(token))
    if ref is None or int(user_id) not in ref.users:
        return None
    return ref


def publish(
    sender_id: int,
    partner_id: int,
    kind: str,
    *,
    text: str = "",
    file_id: str = "",
    telegram_message_id: int | None = None,
    data: dict[str, Any] | None = None,
) -> int:
    """Добавляет одно событие обоим участникам пары."""
    sender_id, partner_id = int(sender_id), int(partner_id)
    seq = _next_seq()
    created_at = int(time.time())
    token = (
        _media_token(file_id, {sender_id, partner_id}, kind)
        if file_id
        else ""
    )
    base = {
        "id": seq,
        "kind": str(kind),
        "text": str(text or "")[:3000],
        "created_at": created_at,
        "media_token": token,
        "telegram_message_id": int(telegram_message_id or 0),
        "data": dict(data or {}),
    }
    _EVENTS[sender_id].append({**base, "mine": True})
    _EVENTS[partner_id].append({**base, "mine": False})
    return seq


def game_invite(
    inviter_id: int,
    partner_id: int,
    game_type: str,
    game_id: int,
    title: str,
    subtitle: str = "",
) -> int:
    return publish(
        inviter_id,
        partner_id,
        "game_invite",
        text=title,
        data={
            "game_type": str(game_type),
            "game_id": int(game_id),
            "subtitle": str(subtitle or ""),
        },
    )


def game_status(
    user_ids: list[int] | tuple[int, ...] | set[int],
    game_type: str,
    game_id: int,
    status: str,
    text: str,
) -> int:
    seq = _next_seq()
    created_at = int(time.time())
    event = {
        "id": seq,
        "kind": "game_status",
        "text": str(text or "")[:500],
        "created_at": created_at,
        "media_token": "",
        "telegram_message_id": 0,
        "mine": False,
        "data": {
            "game_type": str(game_type),
            "game_id": int(game_id),
            "status": str(status),
        },
    }
    for uid in set(map(int, user_ids)):
        _EVENTS[uid].append(dict(event))
    return seq


def private(user_id: int, text: str, *, kind: str = "system", data: dict[str, Any] | None = None) -> int:
    seq = _next_seq()
    _EVENTS[int(user_id)].append(
        {
            "id": seq,
            "kind": str(kind),
            "text": str(text or "")[:1000],
            "created_at": int(time.time()),
            "media_token": "",
            "telegram_message_id": 0,
            "mine": False,
            "data": dict(data or {}),
        }
    )
    return seq


def system(user_ids: list[int] | tuple[int, ...] | set[int], text: str) -> int:
    seq = _next_seq()
    created_at = int(time.time())
    event = {
        "id": seq,
        "kind": "system",
        "text": str(text or "")[:500],
        "created_at": created_at,
        "media_token": "",
        "telegram_message_id": 0,
        "mine": False,
        "data": {},
    }
    for uid in set(map(int, user_ids)):
        _EVENTS[uid].append(dict(event))
    return seq


def events(user_id: int, after: int = 0, limit: int = 80) -> list[dict[str, Any]]:
    items = _EVENTS.get(int(user_id), ())
    after = max(0, int(after))
    limit = max(1, min(int(limit), 160))
    return [dict(item) for item in items if int(item["id"]) > after][-limit:]


def latest_seq(user_id: int) -> int:
    items = _EVENTS.get(int(user_id))
    return int(items[-1]["id"]) if items else 0


def clear_pair(user_a: int, user_b: int) -> None:
    users = {int(user_a), int(user_b)}
    for uid in users:
        _EVENTS.pop(uid, None)
    for token, ref in list(_MEDIA.items()):
        if ref.users & users:
            _MEDIA.pop(token, None)


def clear_user(user_id: int) -> None:
    uid = int(user_id)
    _EVENTS.pop(uid, None)
    for token, ref in list(_MEDIA.items()):
        if uid in ref.users:
            _MEDIA.pop(token, None)


def size() -> int:
    return sum(len(items) for items in _EVENTS.values())
