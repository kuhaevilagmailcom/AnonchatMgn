"""Матчмейкер: очередь поиска, подбор пар по полу и приоритету берега, активные диалоги.

Операции выполняются в памяти, а снимок состояния сохраняется в SQLite middleware-слоем.
Поэтому после рестарта восстанавливаются очередь, активные пары и ожидание оценки.
"""

from __future__ import annotations

import time
from typing import Any
from dataclasses import dataclass, field


QUEUE_TTL_SECONDS = 15 * 60


@dataclass(slots=True)
class Candidate:
    user_id: int
    district: str = ""
    same_district: bool = False
    gender: str = ""
    looking_for: str = ""
    excluded: set[int] = field(default_factory=set)
    joined_at: float = field(default_factory=time.time)
    active_at: float = field(default_factory=time.time)

    def refresh(
        self, district: str, same_district: bool, gender: str = "",
        looking_for: str = "", excluded: set[int] | None = None,
    ) -> None:
        self.district = district or ""
        self.same_district = bool(same_district)
        self.gender = gender if gender in {"m", "f"} else ""
        self.looking_for = looking_for if looking_for in {"m", "f"} else ""
        if excluded is not None:
            self.excluded = set(excluded)
        self.active_at = time.time()


@dataclass(slots=True)
class Pair:
    a: int
    b: int
    started_at: float = field(default_factory=time.time)
    counts: dict[int, int] = field(default_factory=dict)
    history: list[tuple[int, str]] = field(default_factory=list)

    def partner_of(self, user_id: int) -> int:
        return self.b if user_id == self.a else self.a

    def add_message(self, user_id: int) -> int:
        self.counts[user_id] = self.counts.get(user_id, 0) + 1
        return self.counts[user_id]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def compatible(x: Candidate, y: Candidate) -> bool:
    """Жёсткие ограничения: блокировки и выбранный пол. Берег — только приоритет."""
    if y.user_id in x.excluded or x.user_id in y.excluded:
        return False
    if x.looking_for and y.gender != x.looking_for:
        return False
    if y.looking_for and x.gender != y.looking_for:
        return False
    return True


def bank_score(x: Candidate, y: Candidate) -> int:
    """Одинаковый выбранный берег всегда приоритетнее, но не блокирует другие пары."""
    return int(bool(x.district and y.district and x.district == y.district))


class Matchmaker:
    def __init__(self, queue_limit: int = 500, rating_ttl: int = 900) -> None:
        self.queue_limit = queue_limit
        self.rating_ttl = rating_ttl
        self._queue: dict[int, Candidate] = {}          #OrderedDict semantics: dict keeps insertion order
        self._pairs: dict[int, Pair] = {}               # user_id -> Pair
        self._pending_rating: dict[int, tuple[int, int, float]] = {}  # uid -> (match_id, partner, ts)

    # ------------------------------------------------------------------ state
    def status(self, user_id: int) -> str:
        if user_id in self._pairs:
            return "paired"
        if user_id in self._queue:
            return "queued"
        return "free"

    def partner(self, user_id: int) -> int | None:
        pair = self._pairs.get(user_id)
        return pair.partner_of(user_id) if pair else None

    def queue_size(self) -> int:
        return len(self._queue)

    def online_pairs(self) -> int:
        return len(self._pairs) // 2

    def position(self, user_id: int) -> int | None:
        if user_id not in self._queue:
            return None
        ordered = sorted(self._queue.values(), key=lambda c: c.joined_at)
        for i, cand in enumerate(ordered, start=1):
            if cand.user_id == user_id:
                return i
        return None

    def queue_snapshot(self, limit: int = 10) -> list[tuple[int, str]]:
        ordered = sorted(self._queue.values(), key=lambda c: c.joined_at)
        return [(c.user_id, c.district) for c in ordered[:limit]]

    def queue_debug_snapshot(self, limit: int = 15) -> list[dict[str, Any]]:
        ordered = sorted(self._queue.values(), key=lambda c: c.joined_at)
        now_ts = time.time()
        return [
            {
                "user_id": c.user_id,
                "district": c.district,
                "gender": c.gender,
                "looking_for": c.looking_for,
                "waiting_seconds": max(0, int(now_ts - c.joined_at)),
                "idle_seconds": max(0, int(now_ts - c.active_at)),
            }
            for c in ordered[:limit]
        ]

    def touch_queue(self, user_id: int) -> bool:
        candidate = self._queue.get(user_id)
        if candidate is None:
            return False
        candidate.active_at = time.time()
        return True

    def prune_queue(
        self, max_age: int = QUEUE_TTL_SECONDS, *, now_ts: float | None = None
    ) -> list[int]:
        """Удаляет тех, кто давно никак не подтверждал поиск."""
        ts = time.time() if now_ts is None else float(now_ts)
        stale = [
            uid for uid, candidate in self._queue.items()
            if ts - candidate.active_at >= max(1, int(max_age))
        ]
        for uid in stale:
            self._queue.pop(uid, None)
        return stale

    def users_in_play(self) -> set[int]:
        return set(self._queue) | set(self._pairs)

    # ------------------------------------------------------------------ pairing
    def _pair(self, a: int, b: int) -> Pair:
        self._queue.pop(a, None)
        self._queue.pop(b, None)
        pair = Pair(a=a, b=b)
        self._pairs[a] = pair
        self._pairs[b] = pair
        return pair

    def _pick(self, me: Candidate) -> int | None:
        """Берём лучший вариант: свой берег приоритетнее, затем самый старый в очереди."""
        candidates = [
            other for other in self._queue.values()
            if other.user_id != me.user_id and compatible(me, other)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda other: (-bank_score(me, other), other.joined_at))
        return candidates[0].user_id

    def connect(
        self, user_id: int, *, district: str = "", same_district: bool = False,
        gender: str = "", looking_for: str = "", excluded: set[int] | None = None,
    ):
        """Возвращает ('paired', partner_id) | ('queued', position) | ('full', None)."""
        if user_id in self._pairs:
            return "paired", self.partner(user_id)
        if user_id in self._queue:
            self._queue[user_id].refresh(district, same_district, gender, looking_for, excluded)
            return "queued", self.position(user_id)
        if len(self._queue) >= self.queue_limit:
            return "full", None

        me = Candidate(
            user_id=user_id,
            district=district,
            same_district=same_district,
            gender=gender if gender in {"m", "f"} else "",
            looking_for=looking_for if looking_for in {"m", "f"} else "",
            excluded=set(excluded or ()),
        )
        # сначала пытаемся дать собеседника НОВОМУ, потом — кому-то из ожидающих
        partner_id = self._pick(me)
        if partner_id is not None:
            self._pair(user_id, partner_id)
            return "paired", partner_id

        self._queue[user_id] = me
        return "queued", self.position(user_id)

    def sweep(self) -> list[tuple[int, int]]:
        """Сначала собираем пары по предпочтительному берегу, затем любые допустимые."""
        candidates = sorted(self._queue.values(), key=lambda c: c.joined_at)
        ranked: list[tuple[int, float, float, int, int]] = []
        for i, first in enumerate(candidates):
            for other in candidates[i + 1:]:
                if not compatible(first, other):
                    continue
                ranked.append((
                    -bank_score(first, other),
                    min(first.joined_at, other.joined_at),
                    max(first.joined_at, other.joined_at),
                    first.user_id,
                    other.user_id,
                ))
        ranked.sort()
        pairs: list[tuple[int, int]] = []
        taken: set[int] = set()
        for _score, _oldest, _newest, a, b in ranked:
            if a in taken or b in taken:
                continue
            pairs.append((a, b))
            taken.update({a, b})
        for a, b in pairs:
            self._pair(a, b)
        return pairs

    def refresh(
        self, user_id: int, *, district: str, same_district: bool,
        gender: str = "", looking_for: str = "", excluded: set[int] | None = None,
    ) -> list[tuple[int, int]]:
        if user_id in self._queue:
            self._queue[user_id].refresh(
                district, same_district, gender, looking_for, excluded
            )
            return self.sweep()
        return []

    # ------------------------------------------------------------------ breaking
    def release(self, user_id: int) -> tuple[int | None, dict]:
        """Разрывает диалог. Возвращает (partner_id, summary) и сбрасывает счётчики."""
        pair = self._pairs.pop(user_id, None)
        if pair is None:
            self._queue.pop(user_id, None)
            return None, {}
        partner = pair.partner_of(user_id)
        self._pairs.pop(partner, None)
        summary = {
            "partner": partner,
            "counts": dict(pair.counts),
            "started_at": pair.started_at,
            "total": pair.total,
        }
        return partner, summary

    def forget(self, user_id: int) -> dict:
        """Пользователь недоступен (заблокировал бота / удалён аккаунт)."""
        partner, summary = self.release(user_id)
        self._queue.pop(user_id, None)
        self._pending_rating.pop(user_id, None)
        return summary

    # ------------------------------------------------------------------ chat counters
    def count_message(self, user_id: int) -> tuple[int, int] | None:
        """(partner_id, сколько сообщений отправил этот пользователь в текущем диалоге)."""
        pair = self._pairs.get(user_id)
        if pair is None:
            return None
        return pair.partner_of(user_id), pair.add_message(user_id)

    def uncount_message(self, user_id: int) -> None:
        """Откат счётчика: сообщение не было доставлено — XP за него начислять нельзя."""
        pair = self._pairs.get(user_id)
        if pair is None:
            return
        current = pair.counts.get(user_id, 0)
        pair.counts[user_id] = max(0, current - 1)

    def dialog_stats(self, user_id: int) -> dict:
        pair = self._pairs.get(user_id)
        if pair is None:
            return {}
        return {
            "partner": pair.partner_of(user_id),
            "started_at": pair.started_at,
            "counts": dict(pair.counts),
            "dialog_key": f"{min(pair.a, pair.b)}:{max(pair.a, pair.b)}:{int(pair.started_at)}",
            "history": list(pair.history),
        }

    def record_text(self, user_id: int, text: str) -> None:
        pair = self._pairs.get(user_id)
        if pair is None or not text:
            return
        pair.history.append((user_id, text[:500]))
        del pair.history[:-10]

    def is_paired_with(self, user_id: int, other_id: int) -> bool:
        partner = self.partner(user_id)
        return partner is not None and partner == other_id

    # ------------------------------------------------------------------ pending ratings
    def remember_rating(self, user_ids: list[int], match_id: int) -> None:
        ts = time.time()
        for uid in user_ids:
            partner = next((u for u in user_ids if u != uid), None)
            if partner is not None:
                self._pending_rating[uid] = (match_id, partner, ts)

    def pop_rating(self, user_id: int) -> tuple[int, int] | None:
        entry = self._pending_rating.pop(user_id, None)
        if entry is None:
            return None
        match_id, partner, ts = entry
        if time.time() - ts > self.rating_ttl:
            return None
        return match_id, partner

    def rating_partner(self, user_id: int) -> int | None:
        entry = self._pending_rating.get(user_id)
        if entry is None:
            return None
        _, partner, ts = entry
        return partner if time.time() - ts <= self.rating_ttl else None

    def pending_rating(self, user_id: int) -> tuple[int, int] | None:
        entry = self._pending_rating.get(user_id)
        if entry is None:
            return None
        match_id, partner, ts = entry
        return (match_id, partner) if time.time() - ts <= self.rating_ttl else None

    def drop_stale_ratings(self) -> int:
        deadline = time.time() - self.rating_ttl
        stale = [uid for uid, (_, _, ts) in self._pending_rating.items() if ts < deadline]
        for uid in stale:
            self._pending_rating.pop(uid, None)
        return len(stale)

    def snapshot(self) -> dict[str, Any]:
        pairs = []
        seen: set[tuple[int, int]] = set()
        for pair in self._pairs.values():
            key = (min(pair.a, pair.b), max(pair.a, pair.b))
            if key in seen:
                continue
            seen.add(key)
            pairs.append({
                "a": pair.a, "b": pair.b, "started_at": pair.started_at,
                "counts": pair.counts, "history": pair.history,
            })
        return {
            "queue": [
                {
                    "user_id": c.user_id, "district": c.district,
                    "same_district": c.same_district, "gender": c.gender,
                    "looking_for": c.looking_for, "excluded": list(c.excluded),
                    "joined_at": c.joined_at, "active_at": c.active_at,
                }
                for c in self._queue.values()
            ],
            "pairs": pairs,
            "pending_rating": {
                str(uid): list(entry) for uid, entry in self._pending_rating.items()
            },
        }

    def restore(self, state: dict[str, Any]) -> None:
        self._queue.clear()
        self._pairs.clear()
        self._pending_rating.clear()
        for item in state.get("queue", []):
            candidate = Candidate(
                user_id=int(item["user_id"]),
                district=str(item.get("district") or ""),
                same_district=bool(item.get("same_district")),
                gender=str(item.get("gender") or ""),
                looking_for=str(item.get("looking_for") or ""),
                excluded=set(map(int, item.get("excluded", []))),
                joined_at=float(item.get("joined_at", time.time())),
                active_at=float(item.get("active_at", item.get("joined_at", time.time()))),
            )
            self._queue[candidate.user_id] = candidate
        for item in state.get("pairs", []):
            pair = Pair(
                int(item["a"]), int(item["b"]), float(item.get("started_at", time.time())),
                {int(uid): int(count) for uid, count in dict(item.get("counts", {})).items()},
                [(int(uid), str(text)) for uid, text in item.get("history", [])],
            )
            self._pairs[pair.a] = pair
            self._pairs[pair.b] = pair
        for uid, entry in dict(state.get("pending_rating", {})).items():
            if len(entry) == 3:
                self._pending_rating[int(uid)] = (int(entry[0]), int(entry[1]), float(entry[2]))
