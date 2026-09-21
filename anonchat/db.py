"""Асинхронное хранилище на aiosqlite: профили, «уровни общения», жалобы, статистика."""

from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Sequence

import aiosqlite

from .number_game import NUMBER_ROUNDS, NUMBER_REWARDS, number_reward
from .permissions import ALL_ADMIN_PERMISSIONS, serialize_permissions

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id          INTEGER PRIMARY KEY,
    username         TEXT,
    first_name       TEXT,
    nickname         TEXT    NOT NULL DEFAULT '',
    nick_key         TEXT    NOT NULL DEFAULT '',
    age              INTEGER NOT NULL DEFAULT 0,
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
    looking_for      TEXT    NOT NULL DEFAULT '',
    same_district    INTEGER NOT NULL DEFAULT 0,
    about            TEXT    NOT NULL DEFAULT '',
    banned           INTEGER NOT NULL DEFAULT 0,
    ban_reason       TEXT    NOT NULL DEFAULT '',
    mute_until       INTEGER NOT NULL DEFAULT 0,
    premium_until    INTEGER NOT NULL DEFAULT 0,
    support_stars    INTEGER NOT NULL DEFAULT 0,
    profile_deleted  INTEGER NOT NULL DEFAULT 0
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
    dialog_key  TEXT    NOT NULL DEFAULT '',
    context     TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'new',
    handled_by  INTEGER,
    handled_at  INTEGER
);

CREATE TABLE IF NOT EXISTS blocks (
    user_id     INTEGER NOT NULL,
    blocked_id  INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    PRIMARY KEY (user_id, blocked_id)
);

CREATE TABLE IF NOT EXISTS referrals (
    invitee_id  INTEGER PRIMARY KEY,
    referrer_id INTEGER NOT NULL,
    xp_awarded  INTEGER NOT NULL,
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id                    INTEGER NOT NULL,
    kind                       TEXT NOT NULL,
    stars                      INTEGER NOT NULL,
    telegram_payment_charge_id TEXT NOT NULL UNIQUE,
    provider_payment_charge_id TEXT NOT NULL DEFAULT '',
    created_at                 INTEGER NOT NULL,
    payload                    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS admins (
    user_id      INTEGER PRIMARY KEY,
    permissions TEXT    NOT NULL DEFAULT '',
    granted_by  INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS battle_games (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_a         INTEGER NOT NULL,
    user_b         INTEGER NOT NULL,
    inviter_id     INTEGER NOT NULL,
    game_type      TEXT    NOT NULL DEFAULT 'battle',
    status         TEXT    NOT NULL DEFAULT 'invited',
    question_ids   TEXT    NOT NULL DEFAULT '[]',
    question_index INTEGER NOT NULL DEFAULT 0,
    answer_a       INTEGER,
    answer_b       INTEGER,
    matches        INTEGER NOT NULL DEFAULT 0,
    total_questions INTEGER NOT NULL DEFAULT 5,
    reward_awarded INTEGER NOT NULL DEFAULT 0,
    range_max      INTEGER NOT NULL DEFAULT 0,
    reward_total   INTEGER NOT NULL DEFAULT 0,
    created_at     INTEGER NOT NULL,
    updated_at     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, created_at);
CREATE INDEX IF NOT EXISTS idx_reports_target ON reports(target_id, created_at);
CREATE INDEX IF NOT EXISTS idx_users_xp ON users(xp DESC);
CREATE INDEX IF NOT EXISTS idx_users_messages ON users(messages DESC);
CREATE INDEX IF NOT EXISTS idx_matches_recent ON matches(ended_at, user_a, user_b);
CREATE INDEX IF NOT EXISTS idx_blocks_reverse ON blocks(blocked_id, user_id);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id, created_at);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_admins_granted_by ON admins(granted_by, updated_at);
CREATE INDEX IF NOT EXISTS idx_battle_users_a ON battle_games(user_a, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_battle_users_b ON battle_games(user_b, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_battle_status_updated ON battle_games(status, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_battle_live_pair
ON battle_games(MIN(user_a, user_b), MAX(user_a, user_b))
WHERE status IN ('invited', 'active', 'round_done');
"""

#: колонки, которых не было в ранних версиях схемы — догоняем их на лету
_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("nickname", "ALTER TABLE users ADD COLUMN nickname TEXT NOT NULL DEFAULT ''"),
    ("nick_key", "ALTER TABLE users ADD COLUMN nick_key TEXT NOT NULL DEFAULT ''"),
    ("age", "ALTER TABLE users ADD COLUMN age INTEGER NOT NULL DEFAULT 0"),
    ("gender", "ALTER TABLE users ADD COLUMN gender TEXT NOT NULL DEFAULT ''"),
    ("looking_for", "ALTER TABLE users ADD COLUMN looking_for TEXT NOT NULL DEFAULT ''"),
    ("premium_until", "ALTER TABLE users ADD COLUMN premium_until INTEGER NOT NULL DEFAULT 0"),
    ("support_stars", "ALTER TABLE users ADD COLUMN support_stars INTEGER NOT NULL DEFAULT 0"),
    ("profile_deleted", "ALTER TABLE users ADD COLUMN profile_deleted INTEGER NOT NULL DEFAULT 0"),
)

_REPORT_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("dialog_key", "ALTER TABLE reports ADD COLUMN dialog_key TEXT NOT NULL DEFAULT ''"),
    ("context", "ALTER TABLE reports ADD COLUMN context TEXT NOT NULL DEFAULT ''"),
)

_BATTLE_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("total_questions", "ALTER TABLE battle_games ADD COLUMN total_questions INTEGER NOT NULL DEFAULT 5"),
    ("reward_awarded", "ALTER TABLE battle_games ADD COLUMN reward_awarded INTEGER NOT NULL DEFAULT 0"),
    ("game_type", "ALTER TABLE battle_games ADD COLUMN game_type TEXT NOT NULL DEFAULT 'battle'"),
    ("range_max", "ALTER TABLE battle_games ADD COLUMN range_max INTEGER NOT NULL DEFAULT 0"),
    ("reward_total", "ALTER TABLE battle_games ADD COLUMN reward_total INTEGER NOT NULL DEFAULT 0"),
)


def now() -> int:
    return int(time.time())


REFERRAL_DAILY_LIMIT = 30
# Магнитогорск живёт по UTC+5. Фиксированный сдвиг не зависит от часового пояса хостинга.
REFERRAL_TIMEZONE_OFFSET = 5 * 60 * 60


def referral_day_start(timestamp: int | None = None) -> int:
    value = now() if timestamp is None else int(timestamp)
    return ((value + REFERRAL_TIMEZONE_OFFSET) // 86_400) * 86_400 - REFERRAL_TIMEZONE_OFFSET


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._db: aiosqlite.Connection | None = None
        self._matchmaker = None
        self._matchmaker_dirty = False
        self._matchmaker_task: asyncio.Task | None = None
        self._matchmaker_snapshot_key = ""
        self._referral_lock = asyncio.Lock()

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> "Database":
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._db = await aiosqlite.connect(self.path)
            self._db.row_factory = aiosqlite.Row
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            await self._db.executescript(SCHEMA)
            await self._migrate()
            await self._db.commit()
        except (OSError, aiosqlite.Error) as exc:
            if self._db is not None:
                await self._db.close()
                self._db = None
            raise RuntimeError(f"Не удалось открыть SQLite {self.path}: {exc}") from exc
        return self

    async def _migrate(self) -> None:
        """Старые базы могут не иметь новых колонок — добавляем, не теряя данные."""
        async with self.db.execute("PRAGMA table_info(users)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        support_added = "support_stars" not in cols
        added = False
        for name, sql in _MIGRATIONS:
            if name not in cols:
                await self.db.execute(sql)
                added = True
        async with self.db.execute("PRAGMA table_info(reports)") as cur:
            report_cols = {row[1] for row in await cur.fetchall()}
        for name, sql in _REPORT_MIGRATIONS:
            if name not in report_cols:
                await self.db.execute(sql)
        async with self.db.execute("PRAGMA table_info(battle_games)") as cur:
            battle_cols = {row[1] for row in await cur.fetchall()}
        for name, sql in _BATTLE_MIGRATIONS:
            if name not in battle_cols:
                await self.db.execute(sql)
        await self.db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_dialog_once "
            "ON reports(reporter_id, target_id, dialog_key) WHERE dialog_key <> ''"
        )
        # Историю игр не храним: после обновления удаляем старые завершённые записи.
        await self.db.execute(
            "DELETE FROM battle_games WHERE status NOT IN ('invited', 'active', 'round_done')"
        )
        if added or "nick_key" in cols:
            await self._backfill_nick_keys()
        # Старые версии хранили административные районы. Теперь пользователю доступны
        # только два берега; известные значения переносим, неоднозначный Орджоникидзевский
        # сбрасываем, чтобы человек выбрал берег заново.
        await self.db.execute(
            """UPDATE users
               SET district = CASE
                   WHEN district = 'Правобережный' THEN 'Правый берег'
                   WHEN district = 'Левобережный' THEN 'Левый берег'
                   WHEN district = 'Орджоникидзевский' THEN ''
                   ELSE district
               END
               WHERE district IN ('Правобережный', 'Левобережный', 'Орджоникидзевский')"""
        )
        if support_added:
            await self.db.execute(
                """UPDATE users SET support_stars = (
                       SELECT COALESCE(SUM(stars), 0) FROM payments
                       WHERE payments.user_id = users.user_id AND payments.kind = 'support'
                   )
                   WHERE EXISTS (
                       SELECT 1 FROM payments
                       WHERE payments.user_id = users.user_id AND payments.kind = 'support'
                   )"""
            )

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
            if self._matchmaker is not None:
                await self.flush_matchmaker(self._matchmaker)
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
        existing = await self.get_user(user_id)
        if existing is not None and existing["profile_deleted"]:
            restricted = bool(existing["banned"] or int(existing["mute_until"] or 0) > now())
            if restricted:
                return existing
        if (
            existing is not None
            and existing["username"] == username
            and existing["first_name"] == first_name
            and int(existing["last_seen"] or 0) >= now() - 60
        ):
            return existing
        await self.db.execute(
            """
            INSERT INTO users (user_id, username, first_name, created_at, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name,
                last_seen  = excluded.last_seen,
                profile_deleted = 0
            """,
            (user_id, username, first_name, now(), now()),
        )
        await self.db.execute(
            """UPDATE users SET support_stars = (
                   SELECT COALESCE(SUM(stars), 0) FROM payments
                   WHERE payments.user_id = users.user_id AND payments.kind = 'support'
               )
               WHERE user_id = ? AND support_stars = 0""",
            (user_id,),
        )
        await self.db.commit()
        row = await self.get_user(user_id)
        assert row is not None
        return row

    async def get_user(self, user_id: int) -> aiosqlite.Row | None:
        return await self._fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))

    # ------------------------------------------------------------------ admin roles
    async def get_admin_permissions(
        self, user_id: int, owner_ids: tuple[int, ...] = ()
    ) -> frozenset[str]:
        if user_id in owner_ids:
            return ALL_ADMIN_PERMISSIONS
        row = await self._fetchone("SELECT permissions FROM admins WHERE user_id = ?", (user_id,))
        if row is None:
            return frozenset()
        return frozenset(
            item for item in str(row["permissions"] or "").split(",")
            if item in ALL_ADMIN_PERMISSIONS
        )

    async def set_admin(
        self, user_id: int, permissions: set[str] | frozenset[str], granted_by: int
    ) -> frozenset[str]:
        clean = frozenset(permissions) & ALL_ADMIN_PERMISSIONS
        if not clean:
            raise ValueError("Нужно выдать хотя бы одно право")
        await self._ensure_row(user_id)
        ts = now()
        await self.db.execute(
            """INSERT INTO admins(user_id, permissions, granted_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   permissions=excluded.permissions,
                   granted_by=excluded.granted_by,
                   updated_at=excluded.updated_at""",
            (user_id, serialize_permissions(clean), granted_by, ts, ts),
        )
        await self.db.commit()
        return clean

    async def remove_admin(self, user_id: int) -> bool:
        cur = await self.db.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        await self.db.commit()
        return cur.rowcount > 0

    async def list_admins(self) -> list[aiosqlite.Row]:
        return await self._fetchall(
            """SELECT a.*, u.username, u.first_name
               FROM admins a LEFT JOIN users u ON u.user_id = a.user_id
               ORDER BY a.updated_at DESC"""
        )

    async def admin_ids_with_permission(
        self, permission: str, owner_ids: tuple[int, ...] = ()
    ) -> list[int]:
        rows = await self._fetchall("SELECT user_id, permissions FROM admins")
        result = set(owner_ids)
        for row in rows:
            perms = str(row["permissions"] or "").split(",")
            if permission in perms:
                result.add(int(row["user_id"]))
        return sorted(result)

    async def all_admin_ids(self, owner_ids: tuple[int, ...] = ()) -> list[int]:
        rows = await self._fetchall("SELECT user_id FROM admins")
        return sorted(set(owner_ids) | {int(row["user_id"]) for row in rows})

    # ------------------------------------------------------------------ games
    async def game_for_pair(self, user_a: int, user_b: int) -> aiosqlite.Row | None:
        return await self._fetchone(
            """SELECT * FROM battle_games
               WHERE status IN ('invited', 'active', 'round_done')
                 AND ((user_a = ? AND user_b = ?) OR (user_a = ? AND user_b = ?))
               ORDER BY id DESC LIMIT 1""",
            (user_a, user_b, user_b, user_a),
        )

    async def battle_for_pair(self, user_a: int, user_b: int) -> aiosqlite.Row | None:
        return await self._fetchone(
            """SELECT * FROM battle_games
               WHERE game_type='battle'
                 AND status IN ('invited', 'active', 'round_done')
                 AND ((user_a = ? AND user_b = ?) OR (user_a = ? AND user_b = ?))
               ORDER BY id DESC LIMIT 1""",
            (user_a, user_b, user_b, user_a),
        )

    async def number_for_pair(self, user_a: int, user_b: int) -> aiosqlite.Row | None:
        return await self._fetchone(
            """SELECT * FROM battle_games
               WHERE game_type='numbers'
                 AND status IN ('invited', 'active', 'round_done')
                 AND ((user_a = ? AND user_b = ?) OR (user_a = ? AND user_b = ?))
               ORDER BY id DESC LIMIT 1""",
            (user_a, user_b, user_b, user_a),
        )

    async def get_battle(self, game_id: int) -> aiosqlite.Row | None:
        return await self._fetchone("SELECT * FROM battle_games WHERE id = ?", (game_id,))

    async def list_battles(self, history: bool = False, limit: int = 8) -> tuple[list[aiosqlite.Row], int]:
        if history:
            return [], 0
        statuses = ("invited", "active", "round_done")
        placeholders = ",".join("?" for _ in statuses)
        total_row = await self._fetchone(
            f"SELECT COUNT(*) AS c FROM battle_games WHERE status IN ({placeholders})", statuses
        )
        rows = await self._fetchall(
            f"""SELECT g.*,
                       a.username AS user_a_username, a.nickname AS user_a_nickname,
                       a.support_stars AS user_a_support_stars,
                       b.username AS user_b_username, b.nickname AS user_b_nickname,
                       b.support_stars AS user_b_support_stars
                  FROM battle_games g
                  LEFT JOIN users a ON a.user_id = g.user_a
                  LEFT JOIN users b ON b.user_id = g.user_b
                 WHERE g.status IN ({placeholders})
                 ORDER BY g.updated_at DESC LIMIT ?""",
            (*statuses, max(1, min(limit, 20))),
        )
        return rows, int(total_row["c"] if total_row else 0)

    async def create_battle_invite(
        self, inviter_id: int, partner_id: int, total_questions: int = 5
    ) -> tuple[aiosqlite.Row, bool]:
        ts = now()
        cur = await self.db.execute(
            """INSERT OR IGNORE INTO battle_games(
                   user_a, user_b, inviter_id, game_type, total_questions, created_at, updated_at
               ) VALUES (?, ?, ?, 'battle', ?, ?, ?)""",
            (inviter_id, partner_id, inviter_id, total_questions, ts, ts),
        )
        await self.db.commit()
        created = cur.rowcount > 0
        row = (
            await self.get_battle(int(cur.lastrowid))
            if created
            else await self.game_for_pair(inviter_id, partner_id)
        )
        assert row is not None
        return row, created

    async def accept_battle(
        self, game_id: int, user_id: int, question_ids: Sequence[int]
    ) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            """UPDATE battle_games
               SET status='active', question_ids=?, question_index=0,
                   answer_a=NULL, answer_b=NULL, matches=0, reward_awarded=0, updated_at=?
               WHERE id=? AND game_type='battle'
                 AND status='invited' AND user_b=? AND inviter_id<>?""",
            (json.dumps([int(item) for item in question_ids]), now(), game_id, user_id, user_id),
        )
        await self.db.commit()
        return await self.get_battle(game_id) if cur.rowcount else None

    async def decline_battle(self, game_id: int, user_id: int) -> aiosqlite.Row | None:
        row = await self.get_battle(game_id)
        if (
            row is None
            or str(row["game_type"] or "battle") != "battle"
            or int(row["user_b"]) != user_id
        ):
            return None
        cur = await self.db.execute(
            "DELETE FROM battle_games WHERE id=? AND game_type='battle' AND status='invited'",
            (game_id,),
        )
        await self.db.commit()
        return row if cur.rowcount else None

    async def answer_battle(
        self, game_id: int, user_id: int, question_index: int, choice: int
    ) -> tuple[str, aiosqlite.Row | None]:
        row = await self.get_battle(game_id)
        if (
            row is None
            or str(row["game_type"] or "battle") != "battle"
            or user_id not in {int(row["user_a"]), int(row["user_b"])}
        ):
            return "missing", row
        if row["status"] != "active" or int(row["question_index"]) != question_index:
            return "closed", row
        column = "answer_a" if int(row["user_a"]) == user_id else "answer_b"
        cur = await self.db.execute(
            f"""UPDATE battle_games SET {column}=?, updated_at=?
                 WHERE id=? AND status='active' AND question_index=? AND {column} IS NULL""",
            (choice, now(), game_id, question_index),
        )
        if not cur.rowcount:
            await self.db.commit()
            return "already", await self.get_battle(game_id)
        resolved = await self.db.execute(
            """UPDATE battle_games
               SET matches = matches + CASE WHEN answer_a = answer_b THEN 1 ELSE 0 END,
                   status = CASE WHEN question_index >= total_questions - 1
                                 THEN 'finished' ELSE 'round_done' END,
                   reward_awarded = CASE
                       WHEN question_index >= total_questions - 1
                        AND matches + CASE WHEN answer_a = answer_b THEN 1 ELSE 0 END = total_questions
                       THEN 1 ELSE reward_awarded END,
                   updated_at=?
               WHERE id=? AND status='active' AND question_index=?
                 AND answer_a IS NOT NULL AND answer_b IS NOT NULL""",
            (now(), game_id, question_index),
        )
        game = await self.get_battle(game_id)
        if resolved.rowcount and game is not None and int(game["reward_awarded"]):
            await self.db.execute(
                "UPDATE users SET xp=xp+25 WHERE user_id IN (?, ?)",
                (int(game["user_a"]), int(game["user_b"])),
            )
        if resolved.rowcount and game is not None and str(game["status"]) == "finished":
            await self.db.execute("DELETE FROM battle_games WHERE id = ?", (game_id,))
        await self.db.commit()
        return ("resolved" if resolved.rowcount else "waiting"), game

    async def advance_battle(
        self, game_id: int, user_id: int, question_index: int
    ) -> aiosqlite.Row | None:
        row = await self.get_battle(game_id)
        if (
            row is None
            or str(row["game_type"] or "battle") != "battle"
            or user_id not in {int(row["user_a"]), int(row["user_b"])}
        ):
            return None
        cur = await self.db.execute(
            """UPDATE battle_games
               SET status='active', question_index=question_index+1,
                   answer_a=NULL, answer_b=NULL, updated_at=?
               WHERE id=? AND status='round_done' AND question_index=?""",
            (now(), game_id, question_index),
        )
        await self.db.commit()
        return await self.get_battle(game_id) if cur.rowcount else None

    async def create_number_invite(
        self, inviter_id: int, partner_id: int, range_max: int
    ) -> tuple[aiosqlite.Row, bool]:
        range_max = int(range_max)
        if range_max not in NUMBER_REWARDS:
            raise ValueError("Неверный диапазон игры Числа")
        ts = now()
        cur = await self.db.execute(
            """INSERT OR IGNORE INTO battle_games(
                   user_a, user_b, inviter_id, game_type, total_questions,
                   range_max, reward_total, created_at, updated_at
               ) VALUES (?, ?, ?, 'numbers', ?, ?, 0, ?, ?)""",
            (inviter_id, partner_id, inviter_id, NUMBER_ROUNDS, range_max, ts, ts),
        )
        await self.db.commit()
        created = cur.rowcount > 0
        row = (
            await self.get_battle(int(cur.lastrowid))
            if created
            else await self.game_for_pair(inviter_id, partner_id)
        )
        assert row is not None
        return row, created

    async def accept_number(self, game_id: int, user_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            """UPDATE battle_games
               SET status='active', question_index=0,
                   answer_a=NULL, answer_b=NULL, matches=0,
                   reward_total=0, updated_at=?
               WHERE id=? AND game_type='numbers' AND status='invited'
                 AND user_b=? AND inviter_id<>?""",
            (now(), game_id, user_id, user_id),
        )
        await self.db.commit()
        return await self.get_battle(game_id) if cur.rowcount else None

    async def decline_number(self, game_id: int, user_id: int) -> aiosqlite.Row | None:
        row = await self.get_battle(game_id)
        if (
            row is None
            or str(row["game_type"] or "") != "numbers"
            or int(row["user_b"]) != user_id
        ):
            return None
        cur = await self.db.execute(
            "DELETE FROM battle_games WHERE id=? AND game_type='numbers' AND status='invited'",
            (game_id,),
        )
        await self.db.commit()
        return row if cur.rowcount else None

    async def answer_number(
        self, game_id: int, user_id: int, round_index: int, value: int
    ) -> tuple[str, aiosqlite.Row | None]:
        row = await self.get_battle(game_id)
        if (
            row is None
            or str(row["game_type"] or "") != "numbers"
            or user_id not in {int(row["user_a"]), int(row["user_b"])}
        ):
            return "missing", row
        range_max = int(row["range_max"] or 0)
        if range_max not in NUMBER_REWARDS or not 1 <= int(value) <= range_max:
            return "invalid", row
        if row["status"] != "active" or int(row["question_index"]) != round_index:
            return "closed", row

        column = "answer_a" if int(row["user_a"]) == user_id else "answer_b"
        cur = await self.db.execute(
            f"""UPDATE battle_games SET {column}=?, updated_at=?
                 WHERE id=? AND game_type='numbers' AND status='active'
                   AND question_index=? AND {column} IS NULL""",
            (int(value), now(), game_id, round_index),
        )
        if not cur.rowcount:
            await self.db.commit()
            return "already", await self.get_battle(game_id)

        game = await self.get_battle(game_id)
        if game is None or game["answer_a"] is None or game["answer_b"] is None:
            await self.db.commit()
            return "waiting", game

        reward = number_reward(range_max, int(game["answer_a"]), int(game["answer_b"]))
        exact = int(game["answer_a"]) == int(game["answer_b"])
        status = "finished" if round_index >= NUMBER_ROUNDS - 1 else "round_done"
        resolved = await self.db.execute(
            """UPDATE battle_games
               SET matches=matches+?,
                   reward_total=reward_total+?,
                   status=?, updated_at=?
               WHERE id=? AND game_type='numbers' AND status='active'
                 AND question_index=? AND answer_a IS NOT NULL AND answer_b IS NOT NULL""",
            (1 if exact else 0, reward, status, now(), game_id, round_index),
        )
        game = await self.get_battle(game_id)
        if resolved.rowcount and reward > 0 and game is not None:
            await self.db.execute(
                "UPDATE users SET xp=xp+? WHERE user_id IN (?, ?)",
                (reward, int(game["user_a"]), int(game["user_b"])),
            )
        if resolved.rowcount and game is not None and status == "finished":
            await self.db.execute("DELETE FROM battle_games WHERE id=?", (game_id,))
        await self.db.commit()
        return ("resolved" if resolved.rowcount else "waiting"), game

    async def advance_number(
        self, game_id: int, user_id: int, round_index: int
    ) -> aiosqlite.Row | None:
        row = await self.get_battle(game_id)
        if (
            row is None
            or str(row["game_type"] or "") != "numbers"
            or user_id not in {int(row["user_a"]), int(row["user_b"])}
        ):
            return None
        cur = await self.db.execute(
            """UPDATE battle_games
               SET status='active', question_index=question_index+1,
                   answer_a=NULL, answer_b=NULL, updated_at=?
               WHERE id=? AND game_type='numbers'
                 AND status='round_done' AND question_index=?""",
            (now(), game_id, round_index),
        )
        await self.db.commit()
        return await self.get_battle(game_id) if cur.rowcount else None

    async def cancel_battle(self, game_id: int) -> bool:
        cur = await self.db.execute(
            "DELETE FROM battle_games WHERE id=? AND status IN ('invited', 'active', 'round_done')",
            (game_id,),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def close_battles_for_users(self, *user_ids: int) -> int:
        ids = sorted({int(user_id) for user_id in user_ids if user_id})
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        cur = await self.db.execute(
            f"""DELETE FROM battle_games
                 WHERE status IN ('invited', 'active', 'round_done')
                   AND (user_a IN ({placeholders}) OR user_b IN ({placeholders}))""",
            (*ids, *ids),
        )
        await self.db.commit()
        return cur.rowcount

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

    async def set_profile(self, user_id: int, **fields: Any) -> None:
        allowed = {"age", "district", "same_district", "nickname", "gender", "looking_for"}
        if "gender" in fields:
            fields["gender"] = fields["gender"] if fields["gender"] in {"m", "f"} else ""
        if "looking_for" in fields:
            fields["looking_for"] = fields["looking_for"] if fields["looking_for"] in {"m", "f"} else ""
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

    async def award_referral(
        self,
        invitee_id: int,
        referrer_id: int,
        amount: int,
        daily_limit: int = REFERRAL_DAILY_LIMIT,
    ) -> bool:
        if invitee_id == referrer_id:
            return False
        timestamp = now()
        limit = max(1, int(daily_limit))
        async with self._referral_lock:
            cur = await self.db.execute(
                """INSERT OR IGNORE INTO referrals
                       (invitee_id, referrer_id, xp_awarded, created_at)
                   SELECT ?, ?, ?, ?
                   WHERE EXISTS (SELECT 1 FROM users WHERE user_id = ?)
                     AND (SELECT COUNT(*) FROM referrals
                          WHERE referrer_id = ? AND created_at >= ?) < ?""",
                (
                    invitee_id,
                    referrer_id,
                    amount,
                    timestamp,
                    referrer_id,
                    referrer_id,
                    referral_day_start(timestamp),
                    limit,
                ),
            )
            if cur.rowcount != 1:
                await self.db.commit()
                return False
            await self.db.execute(
                "UPDATE users SET xp = xp + ? WHERE user_id = ?",
                (amount, referrer_id),
            )
            await self.db.commit()
            return True

    async def referral_stats(self, referrer_id: int) -> tuple[int, int]:
        row = await self._fetchone(
            "SELECT COUNT(*) AS invited, COALESCE(SUM(xp_awarded), 0) AS earned "
            "FROM referrals WHERE referrer_id = ?",
            (referrer_id,),
        )
        return (int(row["invited"]), int(row["earned"])) if row else (0, 0)

    async def referral_cleanup_preview(
        self, referrer_id: int, protected_ids: Sequence[int] = ()
    ) -> dict[str, int]:
        """Считает последствия очистки, не меняя базу и не затрагивая платежи."""
        rows = await self._fetchall(
            """SELECT r.invitee_id, r.xp_awarded, u.user_id AS existing_user_id,
                      EXISTS(SELECT 1 FROM payments p WHERE p.user_id = r.invitee_id) AS paid,
                      EXISTS(SELECT 1 FROM admins a WHERE a.user_id = r.invitee_id) AS admin,
                      COALESCE(u.support_stars, 0) AS support_stars
               FROM referrals r
               LEFT JOIN users u ON u.user_id = r.invitee_id
               WHERE r.referrer_id = ?""",
            (referrer_id,),
        )
        protected = {int(value) for value in protected_ids}
        kept = sum(
            1
            for row in rows
            if int(row["invitee_id"]) in protected
            or bool(row["paid"])
            or bool(row["admin"])
            or int(row["support_stars"] or 0) > 0
        )
        removable = sum(
            1
            for row in rows
            if row["existing_user_id"] is not None
            and int(row["invitee_id"]) not in protected
            and not bool(row["paid"])
            and not bool(row["admin"])
            and int(row["support_stars"] or 0) <= 0
        )
        owner = await self.get_user(referrer_id)
        return {
            "referrer_id": int(referrer_id),
            "referrals": len(rows),
            "referral_xp": sum(int(row["xp_awarded"] or 0) for row in rows),
            "current_xp": int(owner["xp"] or 0) if owner else 0,
            "users_to_delete": removable,
            "protected_users": kept,
        }

    async def purge_referral_abuse(
        self, referrer_id: int, protected_ids: Sequence[int] = ()
    ) -> dict[str, Any]:
        """Атомарно убирает накрутку: связи, очки и безопасно удаляемые фейк-профили.

        Платежи никогда не удаляются. Пользователи с платежами, поддержкой или правами
        администратора сохраняются, но их мошенническая реферальная связь удаляется.
        """
        await self.db.commit()
        cleanup = await aiosqlite.connect(self.path)
        cleanup.row_factory = aiosqlite.Row
        deleted_user_ids: list[int] = []
        try:
            await cleanup.execute("PRAGMA busy_timeout=10000")
            await cleanup.execute("BEGIN IMMEDIATE")
            async with cleanup.execute(
                """SELECT r.invitee_id, r.xp_awarded, u.user_id AS existing_user_id,
                          EXISTS(SELECT 1 FROM payments p WHERE p.user_id=r.invitee_id) AS paid,
                          EXISTS(SELECT 1 FROM admins a WHERE a.user_id=r.invitee_id) AS admin,
                          COALESCE(u.support_stars, 0) AS support_stars
                   FROM referrals r
                   LEFT JOIN users u ON u.user_id=r.invitee_id
                   WHERE r.referrer_id=?""",
                (referrer_id,),
            ) as cur:
                rows = list(await cur.fetchall())

            protected = {int(value) for value in protected_ids}
            deleted_user_ids = [
                int(row["invitee_id"])
                for row in rows
                if row["existing_user_id"] is not None
                and int(row["invitee_id"]) not in protected
                and not bool(row["paid"])
                and not bool(row["admin"])
                and int(row["support_stars"] or 0) <= 0
            ]

            await cleanup.execute("UPDATE users SET xp=0 WHERE user_id=?", (referrer_id,))
            await cleanup.execute("DELETE FROM referrals WHERE referrer_id=?", (referrer_id,))

            # Два поля в одном DELETE дают по два параметра на id; размер 400 ниже
            # стандартного лимита SQLite в 999 переменных.
            for offset in range(0, len(deleted_user_ids), 400):
                chunk = deleted_user_ids[offset : offset + 400]
                marks = ",".join("?" for _ in chunk)
                twice = (*chunk, *chunk)
                await cleanup.execute(
                    f"DELETE FROM blocks WHERE user_id IN ({marks}) OR blocked_id IN ({marks})",
                    twice,
                )
                await cleanup.execute(
                    f"DELETE FROM reports WHERE reporter_id IN ({marks}) OR target_id IN ({marks})",
                    twice,
                )
                await cleanup.execute(
                    f"DELETE FROM matches WHERE user_a IN ({marks}) OR user_b IN ({marks})",
                    twice,
                )
                await cleanup.execute(
                    f"DELETE FROM battle_games WHERE user_a IN ({marks}) OR user_b IN ({marks})",
                    twice,
                )
                await cleanup.execute(
                    f"DELETE FROM referrals WHERE invitee_id IN ({marks}) OR referrer_id IN ({marks})",
                    twice,
                )
                await cleanup.execute(
                    f"DELETE FROM users WHERE user_id IN ({marks})",
                    tuple(chunk),
                )

            await cleanup.commit()
        except BaseException:
            await cleanup.rollback()
            raise
        finally:
            await cleanup.close()

        return {
            "referrer_id": int(referrer_id),
            "referrals_removed": len(rows),
            "referral_xp_removed": sum(int(row["xp_awarded"] or 0) for row in rows),
            "users_deleted": len(deleted_user_ids),
            "protected_users": sum(
                1
                for row in rows
                if int(row["invitee_id"]) in protected
                or bool(row["paid"])
                or bool(row["admin"])
                or int(row["support_stars"] or 0) > 0
            ),
            "deleted_user_ids": deleted_user_ids,
        }

    async def record_payment(
        self,
        user_id: int,
        kind: str,
        stars: int,
        telegram_charge_id: str,
        provider_charge_id: str,
        payload: str,
    ) -> tuple[bool, int]:
        try:
            await self.db.execute(
                """INSERT INTO payments
                   (user_id, kind, stars, telegram_payment_charge_id,
                    provider_payment_charge_id, created_at, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, kind, stars, telegram_charge_id, provider_charge_id, now(), payload),
            )
        except aiosqlite.IntegrityError:
            await self.db.rollback()
            row = await self.get_user(user_id)
            return False, int(row["support_stars"] or 0) if row else 0

        total_support = 0
        if kind == "support":
            await self.db.execute(
                "UPDATE users SET support_stars = support_stars + ? WHERE user_id = ?",
                (stars, user_id),
            )
            row = await self.get_user(user_id)
            total_support = int(row["support_stars"] or 0) if row else stars
        await self.db.commit()
        return True, total_support

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

    async def list_restricted(
        self, kind: str, limit: int = 10, offset: int = 0
    ) -> tuple[list[aiosqlite.Row], int]:
        if kind == "ban":
            where, params = "banned = 1", ()
            order = "last_seen DESC"
        elif kind == "mute":
            where, params = "banned = 0 AND mute_until > ?", (now(),)
            order = "mute_until ASC"
        else:
            raise ValueError("Неизвестный вид ограничения")
        total_row = await self._fetchone(f"SELECT COUNT(*) AS c FROM users WHERE {where}", params)
        rows = await self._fetchall(
            f"""SELECT user_id, username, first_name, nickname, support_stars,
                       ban_reason, mute_until, last_seen
                  FROM users WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?""",
            (*params, max(1, min(limit, 50)), max(0, offset)),
        )
        return rows, int(total_row["c"] if total_row else 0)

    async def add_report(
        self, reporter_id: int, target_id: int, reason: str, comment: str,
        dialog_key: str = "", context: str = "",
    ) -> tuple[int | None, int]:
        """Одна жалоба участника на один диалог; порог считает разных отправителей."""
        try:
            cur = await self.db.execute(
                """INSERT INTO reports
                   (created_at, reporter_id, target_id, reason, comment, dialog_key, context)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (now(), reporter_id, target_id, reason, comment, dialog_key, context),
            )
        except aiosqlite.IntegrityError:
            return None, 0
        await self.db.execute(
            "UPDATE users SET reports_received = reports_received + 1 WHERE user_id = ?", (target_id,)
        )
        await self.db.execute(
            "UPDATE users SET reports_sent = reports_sent + 1 WHERE user_id = ?", (reporter_id,)
        )
        await self.db.commit()
        day = await self._fetchone(
            "SELECT COUNT(DISTINCT reporter_id) AS c FROM reports WHERE target_id = ? AND created_at > ?",
            (target_id, now() - 86400),
        )
        return int(cur.lastrowid), int(day["c"]) if day else 1

    async def block_user(self, user_id: int, blocked_id: int) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO blocks(user_id, blocked_id, created_at) VALUES (?, ?, ?)",
            (user_id, blocked_id, now()),
        )
        await self.db.commit()

    async def clear_blocks(self, user_id: int) -> int:
        cur = await self.db.execute(
            "DELETE FROM blocks WHERE user_id = ?",
            (user_id,),
        )
        await self.db.commit()
        return int(cur.rowcount or 0)

    async def excluded_partners(self, user_id: int, recent_seconds: int = 0) -> set[int]:
        rows = await self._fetchall(
            """SELECT blocked_id AS uid FROM blocks WHERE user_id = ?
               UNION SELECT user_id AS uid FROM blocks WHERE blocked_id = ?""",
            (user_id, user_id),
        )
        return {int(row["uid"]) for row in rows}

    async def list_reports(self, status: str = "new", limit: int = 20) -> list[aiosqlite.Row]:
        return await self._fetchall(
            """SELECT r.*, t.username AS target_username, t.first_name AS target_name,
                      t.nickname AS target_nickname, t.support_stars AS target_support_stars,
                      t.reports_received AS target_reports_received,
                      p.username AS reporter_username, p.first_name AS reporter_name,
                      p.nickname AS reporter_nickname, p.support_stars AS reporter_support_stars
               FROM reports r LEFT JOIN users t ON t.user_id = r.target_id
                              LEFT JOIN users p ON p.user_id = r.reporter_id
               WHERE r.status = ? ORDER BY r.created_at DESC LIMIT ?""",
            (status, limit),
        )

    async def get_report(self, report_id: int) -> aiosqlite.Row | None:
        return await self._fetchone(
            """SELECT r.*, t.username AS target_username, t.first_name AS target_name,
                      t.nickname AS target_nickname, t.support_stars AS target_support_stars,
                      t.reports_received AS target_reports_received,
                      p.username AS reporter_username, p.first_name AS reporter_name,
                      p.nickname AS reporter_nickname, p.support_stars AS reporter_support_stars
               FROM reports r LEFT JOIN users t ON t.user_id = r.target_id
                              LEFT JOIN users p ON p.user_id = r.reporter_id
               WHERE r.id = ?""",
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

    async def cleanup_report_context(self, retention_days: int = 7) -> int:
        cutoff = now() - max(0, retention_days) * 86400
        cur = await self.db.execute(
            "UPDATE reports SET context = '' WHERE status = 'done' AND handled_at < ? AND context <> ''",
            (cutoff,),
        )
        await self.db.commit()
        return int(cur.rowcount or 0)

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
        if row["user_a"] == user_id:
            partner, column = row["user_b"], "rating_a"
        elif row["user_b"] == user_id:
            partner, column = row["user_a"], "rating_b"
        else:
            return None
        cur = await self.db.execute(
            f"UPDATE matches SET {column} = ? WHERE id = ? AND {column} IS NULL", (value, match_id)
        )
        if cur.rowcount == 0:
            return None
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
        """Активность с упором на диалоги и оценки; спам в одном чате быстро упирается в лимит."""
        return await self._fetchall(
            """SELECT user_id, nickname, messages, xp, dialogs, good_ratings, support_stars
               FROM users WHERE banned = 0
               ORDER BY xp DESC, dialogs DESC, messages DESC LIMIT ?""",
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

    async def save_matchmaker(self, state: dict[str, Any]) -> None:
        await self.set_kv(
            "matchmaker_state",
            json.dumps(state, ensure_ascii=False, separators=(",", ":")),
        )

    def schedule_matchmaker_save(self, matchmaker) -> None:
        """Пишет snapshot только если состояние реально изменилось, а не после каждого апдейта."""
        snapshot_key = json.dumps(
            matchmaker.snapshot(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        if snapshot_key == self._matchmaker_snapshot_key:
            return
        self._matchmaker_snapshot_key = snapshot_key
        self._matchmaker = matchmaker
        self._matchmaker_dirty = True
        if self._matchmaker_task is None or self._matchmaker_task.done():
            self._matchmaker_task = asyncio.create_task(self._save_matchmaker_loop())

    async def _save_matchmaker_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(0.25)
                self._matchmaker_dirty = False
                if self._matchmaker is not None:
                    await self.save_matchmaker(self._matchmaker.snapshot())
                if not self._matchmaker_dirty:
                    return
        finally:
            self._matchmaker_task = None

    async def flush_matchmaker(self, matchmaker) -> None:
        task = self._matchmaker_task
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._matchmaker_task = None
        self._matchmaker_dirty = False
        await self.save_matchmaker(matchmaker.snapshot())

    async def backup_to(self, path: Path | str) -> None:
        """Создаёт согласованную копию работающей SQLite, включая данные из WAL."""
        target = sqlite3.connect(Path(path), check_same_thread=False)
        try:
            await self.db.commit()
            await self.db.backup(target)
        finally:
            target.close()

    async def load_matchmaker(self) -> dict[str, Any] | None:
        value = await self.get_kv("matchmaker_state")
        if not value:
            return None
        self._matchmaker_snapshot_key = value
        try:
            state = json.loads(value)
        except json.JSONDecodeError:
            return None
        return state if isinstance(state, dict) else None

    async def delete_kv(self, key: str) -> None:
        await self.db.execute("DELETE FROM kv WHERE key = ?", (key,))
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

    async def adjust_xp(self, user_id: int, amount: int) -> int:
        await self._ensure_row(user_id)
        await self.db.execute(
            "UPDATE users SET xp = MAX(0, xp + ?) WHERE user_id = ?", (int(amount), user_id)
        )
        await self.db.commit()
        row = await self.get_user(user_id)
        return int(row["xp"] or 0) if row else 0

    async def list_users(self, limit: int = 100, offset: int = 0) -> list[aiosqlite.Row]:
        return await self._fetchall(
            """SELECT user_id, username, first_name, nickname, xp, support_stars,
                      banned, mute_until, last_seen
               FROM users ORDER BY last_seen DESC LIMIT ? OFFSET ?""",
            (max(1, min(limit, 500)), max(0, offset)),
        )

    async def forget_user(self, user_id: int) -> None:
        """Стирает профиль, но сохраняет действующий бан/мут и модерационные доказательства."""
        row = await self.get_user(user_id)
        restricted = bool(row and (row["banned"] or int(row["mute_until"] or 0) > now()))
        if restricted:
            await self.db.execute(
                """UPDATE users SET username=NULL, first_name='Удалённый пользователь', nickname='',
                   nick_key='', age=0, xp=0, messages=0, dialogs=0, good_ratings=0,
                   bad_ratings=0, reports_sent=0, district='', gender='', looking_for='', same_district=0,
                   about='', last_seen=0, premium_until=0, support_stars=0,
                   profile_deleted=1 WHERE user_id=?""",
                (user_id,),
            )
        else:
            await self.db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        # История диалогов/жалоб нужна для блокировок и открытой модерации; личные поля там не хранятся.
        await self.db.commit()

    async def find_user_ids(self, name: str, limit: int = 10) -> list[aiosqlite.Row]:
        like = f"%{name.lstrip('@')}%"
        return await self._fetchall(
            "SELECT user_id, username, first_name, nickname, messages, xp, dialogs, reports_received, "
            "banned, support_stars "
            "FROM users "
            "WHERE username LIKE ? OR first_name LIKE ? OR nickname LIKE ? LIMIT ?",
            (like, like, like, limit),
        )
