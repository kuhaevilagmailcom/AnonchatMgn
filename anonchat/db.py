"""Асинхронное хранилище на aiosqlite: профили, «уровни общения», жалобы, статистика."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Sequence

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id          INTEGER PRIMARY KEY,
    username         TEXT,
    first_name       TEXT,
    nickname         TEXT    NOT NULL DEFAULT '',
    nick_key         TEXT    NOT NULL DEFAULT '',
    created_at       INTEGER NOT NULL DEFAULT 0,
    last_seen        INTEGER NOT NULL DEFAULT 0,
    xp               INTEGER NOT NULL DEFAULT 0,
    messages         INTEGER NOT NULL DEFAULT 0,
    dialogs          INTEGER NOT NULL DEFAULT 0,
    good_ratings     INTEGER NOT NULL DEFAULT 0,
    bad_ratings      INTEGER NOT NULL DEFAULT 0,
    reports_sent     INTEGER NOT NULL DEFAULT 0,
    reports_received INTEGER NOT NULL DEFAULT 0,
    district         TEXT    NOT NULL DEFAULT '',
    gender           TEXT    NOT NULL DEFAULT '',
    same_district    INTEGER NOT NULL DEFAULT 0,
    about            TEXT    NOT NULL DEFAULT '',
    banned           INTEGER NOT NULL DEFAULT 0,
    ban_reason       TEXT    NOT NULL DEFAULT '',
    mute_until       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS matches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at INTEGER NOT NULL,
    ended_at   INTEGER,
    user_a     INTEGER NOT NULL,
    user_b     INTEGER NOT NULL,
    msg_a      INTEGER NOT NULL DEFAULT 0,
    msg_b      INTEGER NOT NULL DEFAULT 0,
    ended_by   INTEGER,
    rating_a   INTEGER,
    rating_b   INTEGER
);

CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  INTEGER NOT NULL,
    reporter_id INTEGER NOT NULL,
    target_id   INTEGER NOT NULL,
    reason      TEXT    NOT NULL,
    comment     TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'new',
    handled_by  INTEGER,
    handled_at  INTEGER
);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, created_at);
CREATE INDEX IF NOT EXISTS idx_reports_target ON reports(target_id, created_at);
CREATE INDEX IF NOT EXISTS idx_users_xp ON users(xp DESC);
"""

#: колонки, которых не было в ранних версиях схемы — догоняем их на лету
_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("nickname", "ALTER TABLE users ADD COLUMN nickname TEXT NOT NULL DEFAULT ''"),
    ("nick_key", "ALTER TABLE users ADD COLUMN nick_key TEXT NOT NULL DEFAULT ''"),
)


def now() -> int:
    return int(time.time())


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._db: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> "Database":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(SCHEMA)
        await self._migrate()
        await self._db.commit()
        return self

    async def _migrate(self) -> None:
        """Старые базы могут не иметь новых колонок — добавляем, не теряя данные."""
        async with self.db.execute("PRAGMA table_info(users)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        added = False
        for name, sql in _MIGRATIONS:
            if name not in cols:
                await self.db.execute(sql)
                added = True
        if added or "nick_key" in cols:
            await self._backfill_nick_keys()

    async def _backfill_nick_keys(self) -> None:
        """Регистронезависимый ключ ника: LOWER() в SQLite не понимает кириллицу, считаем в Python."""
        rows = await self._fetchall(
            "SELECT user_id, nickname FROM users WHERE nick_key = '' AND nickname <> ''"
        )
        for row in rows:
            await self.db.execute(
                "UPDATE users SET nick_key = ? WHERE user_id = ?",
                (str(row["nickname"]).strip().casefold(), int(row["user_id"])),
            )

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database не инициализирован — сначала await Database.start()")
        return self._db

    async def _fetchone(self, sql: str, params: Sequence[Any] = ()) -> aiosqlite.Row | None:
        async with self.db.execute(sql, params) as cur:
            return await cur.fetchone()

    async def _fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[aiosqlite.Row]:
        async with self.db.execute(sql, params) as cur:
            return list(await cur.fetchall())

    # ------------------------------------------------------------------ users
    async def ensure_user(self, user_id: int, username: str | None, first_name: str) -> aiosqlite.Row:
        await self.db.execute(
            """
            INSERT INTO users (user_id, username, first_name, created_at, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name,
                last_seen  = excluded.last_seen
            """,
            (user_id, username, first_name, now(), now()),
        )
        await self.db.commit()
        row = await self.get_user(user_id)
        assert row is not None
        return row

    async def get_user(self, user_id: int) -> aiosqlite.Row | None:
        return await self._fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))

    async def nickname_taken(self, nickname: str, except_user_id: int = 0) -> int | None:
        """Ник должен быть уникальным — иначе топ превращается в «Аноним, Аноним, Аноним».

        Сравнение по nick_key (casefold), потому что SQLite-ный COLLATE NOCASE
        работает только с латиницей: «МАГНИТ» и «Магнит» для него разные.
        """
        key = str(nickname or "").strip().casefold()
        if not key:
            return None
        row = await self._fetchone(
            "SELECT user_id FROM users WHERE nick_key = ? AND user_id != ? LIMIT 1",
            (key, int(except_user_id)),
        )
        return int(row["user_id"]) if row else None

    async def touch(self, user_id: int) -> None:
        await self.db.execute("UPDATE users SET last_seen = ? WHERE user_id = ?", (now(), user_id))
        await self.db.commit()

    async def set_profile(self, user_id: int, **fields: Any) -> None:
        allowed = {"district", "gender", "same_district", "about", "nickname"}
        if "nickname" in fields:
            fields["nick_key"] = str(fields["nickname"] or "").strip().casefold()
        keys = [k for k in fields if k in allowed]
        if "nick_key" in fields:
            keys.append("nick_key")
        if not keys:
            return
        sets = ", ".join(f"{k} = ?" for k in keys)
        vals = [fields[k] for k in keys] + [user_id]
        await self.db.execute(f"UPDATE users SET {sets} WHERE user_id = ?", vals)
        await self.db.commit()

    async def award_xp(self, user_id: int, amount: int, *, column: str | None = None) -> int:
        """Начисляем опыт и, опционально, плюсует счётчик (messages/dialogs/good_ratings...)."""
        if column and column in {
            "messages",
            "dialogs",
            "good_ratings",
            "bad_ratings",
            "reports_sent",
            "reports_received",
        }:
            await self.db.execute(
                f"UPDATE users SET xp = xp + ?, {column} = {column} + ? WHERE user_id = ?",
                (amount, amount, user_id),
            )
        else:
            await self.db.execute("UPDATE users SET xp = xp + ? WHERE user_id = ?", (amount, user_id))
        await self.db.commit()
        row = await self._fetchone("SELECT xp FROM users WHERE user_id = ?", (user_id,))
        return int(row["xp"]) if row else 0

    # ------------------------------------------------------------------ moderation
    async def is_restricted(self, user_id: int) -> str | None:
        """None — всё ок, иначе причина: 'banned' | 'muted'."""
        row = await self._fetchone(
            "SELECT banned, mute_until FROM users WHERE user_id = ?", (user_id,)
        )
        if row is None:
            return None
        if row["banned"]:
            return "banned"
        if row["mute_until"] and row["mute_until"] > now():
            return "muted"
        return None

    async def _ensure_row(self, user_id: int) -> None:
        """Модерация может прийти по «сырому» id — заводим строку, чтобы что-то банить/мутить."""
        row = await self._fetchone("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if row is None:
            await self.db.execute(
                "INSERT INTO users (user_id, first_name, created_at, last_seen) VALUES (?, ?, ?, 0)",
                (user_id, f"user{user_id}", now()),
            )
            await self.db.commit()

    async def set_ban(self, user_id: int, banned: bool, reason: str = "") -> None:
        await self._ensure_row(user_id)
        await self.db.execute(
            "UPDATE users SET banned = ?, ban_reason = ?, mute_until = 0 WHERE user_id = ?",
            (int(banned), reason if banned else "", user_id),
        )
        await self.db.commit()

    async def set_mute(self, user_id: int, minutes: int) -> int:
        await self._ensure_row(user_id)
        until = now() + max(0, minutes) * 60
        await self.db.execute("UPDATE users SET mute_until = ? WHERE user_id = ?", (until, user_id))
        await self.db.commit()
        return until

    async def add_report(
        self, reporter_id: int, target_id: int, reason: str, comment: str
    ) -> tuple[int, int]:
        """Возвращает (id жалобы, сколько жалоб на цели за сутки)."""
        cur = await self.db.execute(
            """INSERT INTO reports (created_at, reporter_id, target_id, reason, comment)
               VALUES (?, ?, ?, ?, ?)""",
            (now(), reporter_id, target_id, reason, comment),
        )
        await self.db.execute(
            "UPDATE users SET reports_received = reports_received + 1 WHERE user_id = ?", (target_id,)
        )
        await self.db.execute(
            "UPDATE users SET reports_sent = reports_sent + 1 WHERE user_id = ?", (reporter_id,)
        )
        await self.db.commit()
        day = await self._fetchone(
            "SELECT COUNT(*) AS c FROM reports WHERE target_id = ? AND created_at > ?",
            (target_id, now() - 86400),
        )
        return int(cur.lastrowid), int(day["c"]) if day else 1

    async def list_reports(self, status: str = "new", limit: int = 20) -> list[aiosqlite.Row]:
        return await self._fetchall(
            """SELECT r.*, t.username AS target_username, t.first_name AS target_name,
                      t.nickname AS target_nickname
               FROM reports r LEFT JOIN users t ON t.user_id = r.target_id
               WHERE r.status = ? ORDER BY r.created_at DESC LIMIT ?""",
            (status, limit),
        )

    async def get_report(self, report_id: int) -> aiosqlite.Row | None:
        return await self._fetchone(
            """SELECT r.*, t.username AS target_username, t.first_name AS target_name,
                      t.nickname AS target_nickname
               FROM reports r LEFT JOIN users t ON t.user_id = r.target_id WHERE r.id = ?""",
            (report_id,),
        )

    async def resolve_report(self, report_id: int, admin_id: int) -> bool:
        cur = await self.db.execute(
            "UPDATE reports SET status = 'done', handled_by = ?, handled_at = ? "
            "WHERE id = ? AND status = 'new'",
            (admin_id, now(), report_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------ dialogs
    async def log_dialog(
        self, user_a: int, user_b: int, msg_a: int, msg_b: int, started_at: int, ended_by: int | None
    ) -> int:
        cur = await self.db.execute(
            """INSERT INTO matches (started_at, ended_at, user_a, user_b, msg_a, msg_b, ended_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (started_at, now(), user_a, user_b, msg_a, msg_b, ended_by),
        )
        await self.db.execute(
            "UPDATE users SET dialogs = dialogs + 1 WHERE user_id IN (?, ?)", (user_a, user_b)
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def rate_dialog(self, match_id: int, user_id: int, value: int) -> int | None:
        """value: 1 — 👍, 0 — 👎. Возвращает id собеседника, которому поставили оценку."""
        row = await self._fetchone("SELECT user_a, user_b FROM matches WHERE id = ?", (match_id,))
        if row is None:
            return None
        partner = row["user_b"] if row["user_a"] == user_id else row["user_a"]
        column = "rating_a" if row["user_a"] == user_id else "rating_b"
        await self.db.execute(
            f"UPDATE matches SET {column} = ? WHERE id = ?", (value, match_id)
        )
        await self.db.execute(
            "UPDATE users SET good_ratings = good_ratings + ? WHERE user_id = ?",
            (1 if value else 0, partner),
        )
        await self.db.execute(
            "UPDATE users SET bad_ratings = bad_ratings + ? WHERE user_id = ?",
            (0 if value else 1, partner),
        )
        await self.db.commit()
        return partner

    # ------------------------------------------------------------------ stats
    async def active_ids(self, days: int = 7, limit: int = 100000) -> list[int]:
        rows = await self._fetchall(
            "SELECT user_id FROM users WHERE banned = 0 AND last_seen > ? ORDER BY last_seen DESC LIMIT ?",
            (now() - days * 86400, limit),
        )
        return [int(r["user_id"]) for r in rows]

    async def stats(self) -> dict[str, Any]:
        total = await self._fetchone("SELECT COUNT(*) AS c FROM users")
        week = await self._fetchone(
            "SELECT COUNT(*) AS c FROM users WHERE last_seen > ?", (now() - 7 * 86400,)
        )
        dialogs = await self._fetchone("SELECT COUNT(*) AS c FROM matches")
        msgs = await self._fetchone("SELECT COALESCE(SUM(messages), 0) AS c FROM users")
        open_reports = await self._fetchone(
            "SELECT COUNT(*) AS c FROM reports WHERE status = 'new'"
        )
        return {
            "users": int(total["c"]) if total else 0,
            "active_week": int(week["c"]) if week else 0,
            "dialogs": int(dialogs["c"]) if dialogs else 0,
            "messages": int(msgs["c"]) if msgs else 0,
            "open_reports": int(open_reports["c"]) if open_reports else 0,
        }

    async def top(self, limit: int = 10) -> list[aiosqlite.Row]:
        return await self._fetchall(
            """SELECT user_id, nickname, xp, messages, dialogs, good_ratings
               FROM users WHERE banned = 0 ORDER BY xp DESC LIMIT ?""",
            (limit,),
        )

    # ------------------------------------------------------------------ kv (id эмодзи пака и пр.)
    async def get_kv(self, key: str, default: str = "") -> str:
        row = await self._fetchone("SELECT value FROM kv WHERE key = ?", (key,))
        return str(row["value"]) if row else default

    async def set_kv(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self.db.commit()

    async def bump(self, user_id: int, column: str, amount: int = 1) -> None:
        allowed = {
            "messages",
            "dialogs",
            "good_ratings",
            "bad_ratings",
            "reports_sent",
            "reports_received",
            "xp",
        }
        if column not in allowed:
            raise ValueError(f"Неизвестная колонка: {column}")
        await self.db.execute(
            f"UPDATE users SET {column} = {column} + ? WHERE user_id = ?", (amount, user_id)
        )
        await self.db.commit()

    async def forget_user(self, user_id: int) -> None:
        """Полное стирание профиля и следов о нём (/forget, «право на забвение»)."""
        await self.db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        await self.db.execute("DELETE FROM matches WHERE user_a = ? OR user_b = ?", (user_id, user_id))
        await self.db.execute(
            "DELETE FROM reports WHERE reporter_id = ? OR target_id = ?", (user_id, user_id)
        )
        await self.db.commit()

    async def find_user_ids(self, name: str, limit: int = 10) -> list[aiosqlite.Row]:
        like = f"%{name.lstrip('@')}%"
        return await self._fetchall(
            "SELECT user_id, username, first_name, nickname FROM users "
            "WHERE username LIKE ? OR first_name LIKE ? OR nickname LIKE ? LIMIT ?",
            (like, like, like, limit),
        )
