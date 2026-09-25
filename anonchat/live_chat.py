"""Оперативная лента Mini App чата с временным восстановлением после redeploy.

События текущей пары живут в RAM для быстрого polling и батчами сохраняются в SQLite.
При stop/next пара очищается и из RAM, и из SQLite — постоянного архива переписок нет.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
import json
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


_SEQ = int(time.time() * 1000)
_EVENTS: dict[int, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=160))
_MEDIA: dict[str, MediaRef] = {}
_STICKERS: dict[str, str] = {}
_TTL = 30 * 60
_DB: Any = None
_PERSIST_QUEUE: deque[dict[str, Any]] = deque()
_PERSIST_TASK: asyncio.Task | None = None
_LOADED_PAIRS: set[tuple[int, int]] = set()


def _pair_key(user_a: int, user_b: int) -> tuple[int, int]:
    a, b = sorted((int(user_a), int(user_b)))
    return a, b


def bind_database(db: Any) -> None:
    global _DB
    _DB = db


def _next_seq() -> int:
    global _SEQ
    _SEQ = max(_SEQ + 1, int(time.time() * 1000))
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


def _queue_op(op: dict[str, Any]) -> None:
    global _PERSIST_TASK
    if _DB is None:
        return
    _PERSIST_QUEUE.append(op)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _PERSIST_TASK is None or _PERSIST_TASK.done():
        _PERSIST_TASK = loop.create_task(_persist_loop())


async def _persist_loop() -> None:
    global _PERSIST_TASK
    try:
        while _PERSIST_QUEUE and _DB is not None:
            await asyncio.sleep(0.08)
            ops: list[dict[str, Any]] = []
            while _PERSIST_QUEUE and len(ops) < 100:
                ops.append(_PERSIST_QUEUE.popleft())
            if ops:
                await _DB.apply_active_chat_ops(ops)
    finally:
        _PERSIST_TASK = None


async def flush() -> None:
    task = _PERSIST_TASK
    if task is not None and not task.done():
        await task
    if _PERSIST_QUEUE and _DB is not None:
        ops = list(_PERSIST_QUEUE)
        _PERSIST_QUEUE.clear()
        await _DB.apply_active_chat_ops(ops)


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


def _append_for_pair(
    event_id: int,
    sender_id: int,
    partner_id: int,
    kind: str,
    *,
    text: str = "",
    file_id: str = "",
    telegram_message_id: int = 0,
    data: dict[str, Any] | None = None,
    created_at: int | None = None,
    persist: bool = True,
) -> int:
    global _SEQ
    sender_id, partner_id = int(sender_id), int(partner_id)
    event_id = int(event_id)
    _SEQ = max(_SEQ, event_id)
    created = int(created_at or time.time())
    token = _media_token(file_id, {sender_id, partner_id}, kind) if file_id else ""
    base = {
        "id": event_id,
        "kind": str(kind),
        "text": str(text or "")[:3000],
        "created_at": created,
        "media_token": token,
        "telegram_message_id": int(telegram_message_id or 0),
        "data": dict(data or {}),
    }
    _EVENTS[sender_id].append({**base, "mine": True})
    _EVENTS[partner_id].append({**base, "mine": False})
    _LOADED_PAIRS.add(_pair_key(sender_id, partner_id))
    if persist:
        _queue_op(
            {
                "op": "append",
                "id": event_id,
                "user_a": sender_id,
                "user_b": partner_id,
                "sender_id": sender_id,
                "kind": str(kind),
                "text": str(text or "")[:3000],
                "file_id": str(file_id or ""),
                "telegram_message_id": int(telegram_message_id or 0),
                "data": dict(data or {}),
                "created_at": created,
            }
        )
    return event_id


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
    return _append_for_pair(
        _next_seq(),
        sender_id,
        partner_id,
        kind,
        text=text,
        file_id=file_id,
        telegram_message_id=int(telegram_message_id or 0),
        data=data,
    )


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


def _shared_event(
    user_ids: list[int] | tuple[int, ...] | set[int],
    kind: str,
    text: str,
    data: dict[str, Any] | None = None,
) -> int:
    users = list(dict.fromkeys(map(int, user_ids)))
    seq = _next_seq()
    created_at = int(time.time())
    event = {
        "id": seq,
        "kind": str(kind),
        "text": str(text or "")[:1000],
        "created_at": created_at,
        "media_token": "",
        "telegram_message_id": 0,
        "mine": False,
        "data": dict(data or {}),
    }
    for uid in users:
        _EVENTS[uid].append(dict(event))
    if len(users) == 2:
        a, b = users
        _LOADED_PAIRS.add(_pair_key(a, b))
        _queue_op(
            {
                "op": "append",
                "id": seq,
                "user_a": a,
                "user_b": b,
                "sender_id": 0,
                "kind": str(kind),
                "text": str(text or "")[:1000],
                "file_id": "",
                "telegram_message_id": 0,
                "data": dict(data or {}),
                "created_at": created_at,
            }
        )
    return seq


def game_status(
    user_ids: list[int] | tuple[int, ...] | set[int],
    game_type: str,
    game_id: int,
    status: str,
    text: str,
) -> int:
    return _shared_event(
        user_ids,
        "game_status",
        text,
        {
            "game_type": str(game_type),
            "game_id": int(game_id),
            "status": str(status),
        },
    )


def private(
    user_id: int,
    text: str,
    *,
    kind: str = "system",
    data: dict[str, Any] | None = None,
) -> int:
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
    return _shared_event(user_ids, "system", text, {})


async def ensure_loaded(db: Any, user_a: int, user_b: int) -> None:
    key = _pair_key(user_a, user_b)
    if key in _LOADED_PAIRS:
        return
    rows = await db.active_chat_events(user_a, user_b, limit=160)
    users = {int(user_a), int(user_b)}
    for uid in users:
        _EVENTS.pop(uid, None)
    for row in rows:
        try:
            data = json.loads(str(row["data"] or "{}"))
        except (TypeError, json.JSONDecodeError):
            data = {}
        sender = int(row["sender_id"] or 0)
        event_id = int(row["id"])
        if sender in users:
            partner = int(user_b) if sender == int(user_a) else int(user_a)
            _append_for_pair(
                event_id,
                sender,
                partner,
                str(row["kind"] or "system"),
                text=str(row["text"] or ""),
                file_id=str(row["file_id"] or ""),
                telegram_message_id=int(row["telegram_message_id"] or 0),
                data=data,
                created_at=int(row["created_at"] or time.time()),
                persist=False,
            )
        else:
            event = {
                "id": event_id,
                "kind": str(row["kind"] or "system"),
                "text": str(row["text"] or ""),
                "created_at": int(row["created_at"] or time.time()),
                "media_token": "",
                "telegram_message_id": int(row["telegram_message_id"] or 0),
                "mine": False,
                "data": data,
            }
            for uid in users:
                _EVENTS[uid].append(dict(event))
            global _SEQ
            _SEQ = max(_SEQ, event_id)
    _LOADED_PAIRS.add(key)


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
    key = _pair_key(user_a, user_b)
    _LOADED_PAIRS.discard(key)
    for uid in users:
        _EVENTS.pop(uid, None)
    for token, ref in list(_MEDIA.items()):
        if ref.users & users:
            _MEDIA.pop(token, None)
    _queue_op({"op": "clear", "user_a": int(user_a), "user_b": int(user_b)})


def clear_user(user_id: int) -> None:
    uid = int(user_id)
    _EVENTS.pop(uid, None)
    for key in list(_LOADED_PAIRS):
        if uid in key:
            _LOADED_PAIRS.discard(key)
    for token, ref in list(_MEDIA.items()):
        if uid in ref.users:
            _MEDIA.pop(token, None)
    _queue_op({"op": "clear_user", "user_id": uid})


def size() -> int:
    return sum(len(items) for items in _EVENTS.values())
