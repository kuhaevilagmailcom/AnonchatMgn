"""Асинхронное хранилище на aiosqlite: профили, «уровни общения», жалобы, статистика."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Sequence

import aiosqlite

ANON_PLUS_LIFETIME_UNTIL = 253402300799

from .number_game import (
    NUMBER_ROUNDS,
    NUMBER_REWARDS,
    number_reward,
)
from .permissions import ALL_ADMIN_PERMISSIONS, serialize_permissions
from .word_game import WORD_REWARD
from .geoquest import (
    GEO_ROUND_OPTIONS,
    GEO_ROUND_SECONDS,
    geo_reward,
    valid_guess_coordinate,
)

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
    anon_plus_theme   TEXT    NOT NULL DEFAULT 'pink',
    anon_plus_emoji   TEXT    NOT NULL DEFAULT '',
    anon_plus_show_nick INTEGER NOT NULL DEFAULT 0,
    support_stars    INTEGER NOT NULL DEFAULT 0,
    support_rub      INTEGER NOT NULL DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS sbp_payments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id    TEXT    NOT NULL UNIQUE,
    order_id      TEXT    NOT NULL UNIQUE,
    user_id       INTEGER NOT NULL,
    kind          TEXT    NOT NULL,
    amount_rub    INTEGER NOT NULL,
    premium_days  INTEGER NOT NULL DEFAULT 0,
    pay_url       TEXT    NOT NULL DEFAULT '',
    status        TEXT    NOT NULL DEFAULT 'creating',
    created_at    INTEGER NOT NULL,
    paid_at       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reward_claims (
    user_id    INTEGER NOT NULL,
    reward_key TEXT    NOT NULL,
    amount     INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, reward_key)
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
    reward_total_a INTEGER NOT NULL DEFAULT 0,
    reward_total_b INTEGER NOT NULL DEFAULT 0,
    geo_round_started_at INTEGER NOT NULL DEFAULT 0,
    created_at     INTEGER NOT NULL,
    updated_at     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS number_game_pairs (
    user_low    INTEGER NOT NULL,
    user_high   INTEGER NOT NULL,
    consumed_at INTEGER NOT NULL,
    PRIMARY KEY (user_low, user_high)
);

CREATE TABLE IF NOT EXISTS number_daily_rewards (
    user_id   INTEGER NOT NULL,
    day_start INTEGER NOT NULL,
    stars     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day_start)
);

CREATE TABLE IF NOT EXISTS word_game_rewards (
    user_id    INTEGER NOT NULL,
    partner_id INTEGER NOT NULL,
    day_start  INTEGER NOT NULL,
    stars      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, partner_id, day_start)
);

CREATE TABLE IF NOT EXISTS geo_game_pairs (
    user_low    INTEGER NOT NULL,
    user_high   INTEGER NOT NULL,
    day_start   INTEGER NOT NULL,
    consumed_at INTEGER NOT NULL,
    PRIMARY KEY (user_low, user_high, day_start)
);

CREATE TABLE IF NOT EXISTS geo_daily_rewards (
    user_id   INTEGER NOT NULL,
    day_start INTEGER NOT NULL,
    stars     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day_start)
);

CREATE TABLE IF NOT EXISTS geo_place_history (
    user_id  INTEGER NOT NULL,
    place_id INTEGER NOT NULL,
    shown_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, place_id)
);

CREATE INDEX IF NOT EXISTS idx_geo_place_history_recent
    ON geo_place_history(user_id, shown_at DESC);

CREATE TABLE IF NOT EXISTS active_chat_events (
    id                  INTEGER PRIMARY KEY,
    user_low            INTEGER NOT NULL,
    user_high           INTEGER NOT NULL,
    sender_id           INTEGER NOT NULL DEFAULT 0,
    kind                TEXT    NOT NULL,
    text                TEXT    NOT NULL DEFAULT '',
    file_id             TEXT    NOT NULL DEFAULT '',
    telegram_message_id INTEGER NOT NULL DEFAULT 0,
    data                TEXT    NOT NULL DEFAULT '{}',
    created_at          INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_active_chat_pair
    ON active_chat_events(user_low, user_high, id);

CREATE TABLE IF NOT EXISTS miniapp_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    type       TEXT    NOT NULL DEFAULT 'system',
    icon       TEXT    NOT NULL DEFAULT 'bell',
    title      TEXT    NOT NULL,
    text       TEXT    NOT NULL DEFAULT '',
    action     TEXT    NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    read_at    INTEGER
);

CREATE TABLE IF NOT EXISTS miniapp_dialog_results (
    user_id    INTEGER PRIMARY KEY,
    match_id   INTEGER NOT NULL,
    partner_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    started_at INTEGER NOT NULL,
    duration   INTEGER NOT NULL DEFAULT 0,
    sent       INTEGER NOT NULL DEFAULT 0,
    received   INTEGER NOT NULL DEFAULT 0,
    earned     INTEGER NOT NULL DEFAULT 0,
    games      TEXT    NOT NULL DEFAULT '[]',
    rated      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS admin_notice_outbox (
    event_key           TEXT PRIMARY KEY,
    user_id             INTEGER NOT NULL,
    kind                TEXT NOT NULL,
    title               TEXT NOT NULL,
    body                TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    attempts            INTEGER NOT NULL DEFAULT 0,
    created_at          INTEGER NOT NULL,
    next_attempt_at     INTEGER NOT NULL,
    sent_at             INTEGER NOT NULL DEFAULT 0,
    telegram_message_id INTEGER NOT NULL DEFAULT 0,
    last_error          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_notice_outbox_pending
    ON admin_notice_outbox(status, next_attempt_at, created_at);
CREATE INDEX IF NOT EXISTS idx_notice_outbox_user
    ON admin_notice_outbox(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS admin_broadcast_jobs (
    job_key      TEXT PRIMARY KEY,
    actor_id     INTEGER NOT NULL,
    message      TEXT NOT NULL,
    button_text  TEXT NOT NULL DEFAULT '',
    button_url   TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'running',
    created_at   INTEGER NOT NULL,
    finished_at  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS admin_broadcast_targets (
    job_key       TEXT NOT NULL,
    user_id       INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    attempts      INTEGER NOT NULL DEFAULT 0,
    next_retry_at INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT NOT NULL DEFAULT '',
    telegram_message_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (job_key,user_id)
);
CREATE INDEX IF NOT EXISTS idx_broadcast_delivery
    ON admin_broadcast_targets(job_key,status,next_retry_at);

CREATE INDEX IF NOT EXISTS idx_miniapp_events_user
    ON miniapp_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_miniapp_events_unread
    ON miniapp_events(user_id, read_at, created_at DESC);

CREATE TABLE IF NOT EXISTS daily_activity (
    user_id          INTEGER NOT NULL,
    day_start        INTEGER NOT NULL,
    messages         INTEGER NOT NULL DEFAULT 0,
    dialogs          INTEGER NOT NULL DEFAULT 0,
    games            INTEGER NOT NULL DEFAULT 0,
    battle_games     INTEGER NOT NULL DEFAULT 0,
    number_games     INTEGER NOT NULL DEFAULT 0,
    ratings_given    INTEGER NOT NULL DEFAULT 0,
    good_ratings     INTEGER NOT NULL DEFAULT 0,
    battle_matches   INTEGER NOT NULL DEFAULT 0,
    battle_questions INTEGER NOT NULL DEFAULT 0,
    number_exact     INTEGER NOT NULL DEFAULT 0,
    xp_earned        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day_start)
);

CREATE TABLE IF NOT EXISTS user_engagement (
    user_id           INTEGER PRIMARY KEY,
    current_streak    INTEGER NOT NULL DEFAULT 0,
    best_streak       INTEGER NOT NULL DEFAULT 0,
    last_active_day   INTEGER NOT NULL DEFAULT 0,
    achievements      TEXT    NOT NULL DEFAULT '[]',
    quest_day         INTEGER NOT NULL DEFAULT 0,
    quest_claimed     TEXT    NOT NULL DEFAULT '[]',
    dialogs_total     INTEGER NOT NULL DEFAULT 0,
    games_total       INTEGER NOT NULL DEFAULT 0,
    battle_games_total INTEGER NOT NULL DEFAULT 0,
    number_games_total INTEGER NOT NULL DEFAULT 0,
    battle_perfect_5  INTEGER NOT NULL DEFAULT 0,
    battle_perfect_10 INTEGER NOT NULL DEFAULT 0,
    number_exact_1000 INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS polls (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    question   TEXT    NOT NULL,
    option_a   TEXT    NOT NULL,
    option_b   TEXT    NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    closed_at  INTEGER
);

CREATE TABLE IF NOT EXISTS poll_votes (
    poll_id    INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    choice     INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (poll_id, user_id)
);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS anonymous_reply_routes (
    recipient_id INTEGER NOT NULL,
    message_id   INTEGER NOT NULL,
    target_id    INTEGER NOT NULL,
    created_at   INTEGER NOT NULL,
    PRIMARY KEY (recipient_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, created_at);
CREATE INDEX IF NOT EXISTS idx_reports_target ON reports(target_id, created_at);
CREATE INDEX IF NOT EXISTS idx_users_xp ON users(xp DESC);
CREATE INDEX IF NOT EXISTS idx_users_messages ON users(messages DESC);
CREATE INDEX IF NOT EXISTS idx_users_created ON users(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_polls_active ON polls(active, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_poll_votes_poll_choice ON poll_votes(poll_id, choice);
CREATE INDEX IF NOT EXISTS idx_matches_recent ON matches(ended_at, user_a, user_b);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id, created_at);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sbp_payments_user ON sbp_payments(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sbp_payments_status ON sbp_payments(status, created_at);
CREATE INDEX IF NOT EXISTS idx_anon_reply_routes_created
ON anonymous_reply_routes(created_at);
CREATE INDEX IF NOT EXISTS idx_admins_granted_by ON admins(granted_by, updated_at);
CREATE INDEX IF NOT EXISTS idx_battle_users_a ON battle_games(user_a, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_battle_users_b ON battle_games(user_b, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_battle_status_updated ON battle_games(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_number_daily_day ON number_daily_rewards(day_start);
CREATE INDEX IF NOT EXISTS idx_word_game_rewards_day ON word_game_rewards(day_start, user_id);
CREATE INDEX IF NOT EXISTS idx_geo_game_pairs_day ON geo_game_pairs(day_start);
CREATE INDEX IF NOT EXISTS idx_geo_daily_day ON geo_daily_rewards(day_start);
CREATE INDEX IF NOT EXISTS idx_activity_day ON daily_activity(day_start, xp_earned DESC);
CREATE INDEX IF NOT EXISTS idx_activity_user_day ON daily_activity(user_id, day_start DESC);
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
    ("anon_plus_theme", "ALTER TABLE users ADD COLUMN anon_plus_theme TEXT NOT NULL DEFAULT 'pink'"),
    ("anon_plus_emoji", "ALTER TABLE users ADD COLUMN anon_plus_emoji TEXT NOT NULL DEFAULT ''"),
    ("anon_plus_show_nick", "ALTER TABLE users ADD COLUMN anon_plus_show_nick INTEGER NOT NULL DEFAULT 0"),
    ("support_stars", "ALTER TABLE users ADD COLUMN support_stars INTEGER NOT NULL DEFAULT 0"),
    ("support_rub", "ALTER TABLE users ADD COLUMN support_rub INTEGER NOT NULL DEFAULT 0"),
    ("profile_deleted", "ALTER TABLE users ADD COLUMN profile_deleted INTEGER NOT NULL DEFAULT 0"),
    ("xp_source", "ALTER TABLE users ADD COLUMN xp_source TEXT NOT NULL DEFAULT ''"),
    ("xp_reason", "ALTER TABLE users ADD COLUMN xp_reason TEXT NOT NULL DEFAULT ''"),
    ("xp_actor_id", "ALTER TABLE users ADD COLUMN xp_actor_id INTEGER NOT NULL DEFAULT 0"),
    ("xp_reference_type", "ALTER TABLE users ADD COLUMN xp_reference_type TEXT NOT NULL DEFAULT ''"),
    ("xp_reference_id", "ALTER TABLE users ADD COLUMN xp_reference_id TEXT NOT NULL DEFAULT ''"),
    ("xp_idempotency_key", "ALTER TABLE users ADD COLUMN xp_idempotency_key TEXT NOT NULL DEFAULT ''"),
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
    ("reward_total_a", "ALTER TABLE battle_games ADD COLUMN reward_total_a INTEGER NOT NULL DEFAULT 0"),
    ("reward_total_b", "ALTER TABLE battle_games ADD COLUMN reward_total_b INTEGER NOT NULL DEFAULT 0"),
    ("geo_lat_a", "ALTER TABLE battle_games ADD COLUMN geo_lat_a REAL"),
    ("geo_lon_a", "ALTER TABLE battle_games ADD COLUMN geo_lon_a REAL"),
    ("geo_lat_b", "ALTER TABLE battle_games ADD COLUMN geo_lat_b REAL"),
    ("geo_lon_b", "ALTER TABLE battle_games ADD COLUMN geo_lon_b REAL"),
    ("geo_distance_a", "ALTER TABLE battle_games ADD COLUMN geo_distance_a REAL"),
    ("geo_distance_b", "ALTER TABLE battle_games ADD COLUMN geo_distance_b REAL"),
    ("geo_round_started_at", "ALTER TABLE battle_games ADD COLUMN geo_round_started_at INTEGER NOT NULL DEFAULT 0"),
)


def now() -> int:
    return int(time.time())


REFERRAL_DAILY_LIMIT = 30
GAME_INACTIVE_TTL_SECONDS = 2 * 24 * 60 * 60
GAME_XP_DAILY_LIMIT = 500
# Overall cap across the games available in the bot. Legacy Numbers rewards from
# earlier today also count, so removal cannot reset a user's daily allowance.
GAME_XP_SOURCES = ("battle", "numbers", "geoguessr", "word_game")


# Магнитогорск живёт по UTC+5. Фиксированный сдвиг не зависит от часового пояса хостинга.
REFERRAL_TIMEZONE_OFFSET = 5 * 60 * 60


def referral_day_start(timestamp: int | None = None) -> int:
    value = now() if timestamp is None else int(timestamp)
    return ((value + REFERRAL_TIMEZONE_OFFSET) // 86_400) * 86_400 - REFERRAL_TIMEZONE_OFFSET


def week_period_start(timestamp: int | None = None) -> int:
    """Понедельник 00:00 текущей недели по Магнитогорску (UTC+5)."""
    day = referral_day_start(timestamp)
    local_midnight = day + REFERRAL_TIMEZONE_OFFSET
    weekday = time.gmtime(local_midnight).tm_wday  # Monday == 0
    return day - weekday * 86_400


def month_period_start(timestamp: int | None = None) -> int:
    """Первое число текущего месяца 00:00 по Магнитогорску (UTC+5)."""
    day = referral_day_start(timestamp)
    local_midnight = day + REFERRAL_TIMEZONE_OFFSET
    month_day = time.gmtime(local_midnight).tm_mday
    return day - (month_day - 1) * 86_400


def number_reward_day_start(timestamp: int | None = None) -> int:
    return referral_day_start(timestamp)


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._db: aiosqlite.Connection | None = None
        self._matchmaker = None
        self._matchmaker_dirty = False
        self._matchmaker_task: asyncio.Task | None = None
        self._matchmaker_snapshot_key = ""
        self._matchmaker_revision = -1
        self._referral_lock = asyncio.Lock()
        self._number_reward_lock = asyncio.Lock()
        self._word_reward_lock = asyncio.Lock()
        self._game_reward_lock = asyncio.Lock()
        self._engagement_lock = asyncio.Lock()
        self._nickname_lock = asyncio.Lock()
        self._anon_question_lock = asyncio.Lock()
        self._xp_lock = asyncio.Lock()
        self._admin_permissions_cache: dict[int, tuple[float, frozenset[str]]] = {}
        self._top_cache: dict[tuple[int, ...], tuple[float, list[aiosqlite.Row]]] = {}
        self._xp_multiplier_cache: int | None = None

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> "Database":
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Autocommit не даёт разным asyncio-обработчикам случайно делить одну
            # неявную транзакцию одной Connection. Многошаговые операции остаются
            # идемпотентными/защищёнными уникальными ключами и локами уровня домена.
            self._db = await aiosqlite.connect(self.path, isolation_level=None)
            self._db.row_factory = aiosqlite.Row
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            await self._db.executescript(SCHEMA)
            await self._migrate()
            await self._backfill_legacy_activity_xp()
            await self._db.commit()
        except (OSError, aiosqlite.Error) as exc:
            if self._db is not None:
                await self._db.close()
                self._db = None
            raise RuntimeError(f"Не удалось открыть SQLite {self.path}: {exc}") from exc
        return self

    async def _backfill_legacy_activity_xp(self) -> int:
        """Один раз переносит старый баланс в периодную статистику.

        До появления daily_activity звёзды хранились только в users.xp без даты.
        Для старых аккаунтов недостающую часть относим к дню создания аккаунта —
        это не выдумывает дополнительные звёзды и не меняет общий баланс.
        """
        marker = "daily_activity_xp_backfill_v1"
        if await self.get_kv(marker) == "1":
            return 0

        rows = await self._fetchall(
            """SELECT u.user_id, u.xp, u.created_at,
                      COALESCE(SUM(a.xp_earned), 0) AS tracked
                 FROM users u
                 LEFT JOIN daily_activity a ON a.user_id=u.user_id
                GROUP BY u.user_id"""
        )
        added = 0
        for row in rows:
            total = max(0, int(row["xp"] or 0))
            tracked = max(0, int(row["tracked"] or 0))
            missing = max(0, total - tracked)
            if missing <= 0:
                continue
            created_at = int(row["created_at"] or 0) or now()
            day = referral_day_start(created_at)
            await self.db.execute(
                """INSERT INTO daily_activity(user_id, day_start, xp_earned)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, day_start)
                   DO UPDATE SET xp_earned=xp_earned+excluded.xp_earned""",
                (int(row["user_id"]), day, missing),
            )
            added += missing

        await self.db.execute(
            """INSERT INTO kv(key, value) VALUES (?, '1')
               ON CONFLICT(key) DO UPDATE SET value='1'""",
            (marker,),
        )
        return added

    async def _migrate(self) -> None:
        """Старые базы могут не иметь новых колонок — добавляем, не теряя данные."""
        # Функция «Больше не встречаться» удалена. Старые вечные блокировки
        # снимаем всем сразу, чтобы бывшие скрытые пользователи снова матчились.
        await self.db.execute("DROP TABLE IF EXISTS blocks")
        async with self.db.execute("PRAGMA table_info(users)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        support_added = "support_stars" not in cols
        added = False
        for name, sql in _MIGRATIONS:
            if name not in cols:
                await self.db.execute(sql)
                added = True
        await self._migrate_xp_ledger()
        async with self.db.execute("PRAGMA table_info(reports)") as cur:
            report_cols = {row[1] for row in await cur.fetchall()}
        for name, sql in _REPORT_MIGRATIONS:
            if name not in report_cols:
                await self.db.execute(sql)
        async with self.db.execute("PRAGMA table_info(battle_games)") as cur:
            battle_cols = {row[1] for row in await cur.fetchall()}
        number_antifarm_added = (
            "reward_total_a" not in battle_cols or "reward_total_b" not in battle_cols
        )
        for name, sql in _BATTLE_MIGRATIONS:
            if name not in battle_cols:
                await self.db.execute(sql)
        await self.db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_dialog_once "
            "ON reports(reporter_id, target_id, dialog_key) WHERE dialog_key <> ''"
        )
        # Числа больше не доступны. Удаляем приглашения и незавершённые сессии
        # при запуске, но сохраняем прошлые XP-операции и статистику игроков.
        await self.db.execute("DELETE FROM battle_games WHERE game_type='numbers'")
        # Историю игр не храним: после обновления удаляем старые завершённые записи.
        await self.db.execute(
            "DELETE FROM battle_games WHERE status NOT IN ('invited', 'active', 'round_done')"
        )
        # Для дневного лимита нужны только свежие агрегаты. Старше недели они бесполезны.
        await self.db.execute(
            "DELETE FROM number_daily_rewards WHERE day_start < ?",
            (number_reward_day_start() - 7 * 86_400,),
        )
        await self.db.execute(
            "DELETE FROM word_game_rewards WHERE day_start < ?",
            (referral_day_start() - 7 * 86_400,),
        )
        await self.db.execute(
            "DELETE FROM geo_game_pairs WHERE day_start < ?",
            (referral_day_start() - 7 * 86_400,),
        )
        await self.db.execute(
            "DELETE FROM geo_daily_rewards WHERE day_start < ?",
            (referral_day_start() - 7 * 86_400,),
        )
        # Активная лента нужна только для незавершённого диалога; очень старые
        # остатки после аварийных завершений не держим.
        await self.db.execute(
            "DELETE FROM active_chat_events WHERE created_at < ?",
            (now() - 2 * 86_400,),
        )
        # Для топов недели/месяца и личной активности достаточно последних 40 суток.
        await self.db.execute(
            "DELETE FROM daily_activity WHERE day_start < ?",
            (referral_day_start() - 39 * 86_400,),
        )
        # Только при первом переходе на антифарм: уже начатая старая игра считается
        # использованной попыткой пары. На обычных рестартах новые игры не трогаем.
        if number_antifarm_added:
            await self.db.execute(
                """INSERT OR IGNORE INTO number_game_pairs(user_low, user_high, consumed_at)
                   SELECT MIN(user_a, user_b), MAX(user_a, user_b), updated_at
                     FROM battle_games
                    WHERE game_type='numbers' AND status IN ('active', 'round_done')"""
            )
            await self.db.execute(
                """UPDATE battle_games SET reward_awarded=0
                    WHERE game_type='numbers' AND status IN ('active', 'round_done')"""
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
        await self.db.execute(
            """UPDATE users SET support_rub = (
                   SELECT COALESCE(SUM(amount_rub), 0) FROM sbp_payments
                   WHERE sbp_payments.user_id = users.user_id
                     AND sbp_payments.kind = 'support'
                     AND sbp_payments.status = 'paid'
               )
               WHERE EXISTS (
                   SELECT 1 FROM sbp_payments
                   WHERE sbp_payments.user_id = users.user_id
                     AND sbp_payments.kind = 'support'
                     AND sbp_payments.status = 'paid'
               )"""
        )
        # Все уже активные подписки переводим на новую бессрочную модель.
        await self.db.execute(
            "UPDATE users SET premium_until=? WHERE premium_until>?",
            (ANON_PLUS_LIFETIME_UNTIL, now()),
        )

    async def _migrate_xp_ledger(self) -> None:
        """Неразрушающий одноразовый снимок старых балансов и атомарный аудит через SQLite."""
        await self.db.executescript("""
            CREATE TABLE IF NOT EXISTS admin_action_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_key TEXT NOT NULL UNIQUE,
                actor_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL DEFAULT 0,
                action TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                reference_id INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_admin_actions_recent
                ON admin_action_log(created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_admin_actions_target
                ON admin_action_log(target_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS xp_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                source TEXT NOT NULL DEFAULT 'other',
                reason TEXT NOT NULL DEFAULT '',
                actor_id INTEGER NOT NULL DEFAULT 0,
                reference_type TEXT NOT NULL DEFAULT '',
                reference_id TEXT NOT NULL DEFAULT '',
                idempotency_key TEXT UNIQUE,
                created_at INTEGER NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_xp_transactions_user_time
                ON xp_transactions(user_id, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_xp_transactions_period
                ON xp_transactions(created_at, source, user_id);
            CREATE INDEX IF NOT EXISTS idx_users_dialogs ON users(dialogs DESC, user_id);
            CREATE INDEX IF NOT EXISTS idx_users_banned ON users(banned, user_id);
            CREATE INDEX IF NOT EXISTS idx_users_mute_until ON users(mute_until, user_id);
            CREATE INDEX IF NOT EXISTS idx_users_support ON users(support_stars, support_rub);
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_users_nick_key ON users(nick_key);
        """)
        # Восстанавливать детализацию прошлых начислений невозможно. Одна стартовая
        # запись создаётся строго один раз, без изменения пользователей и daily_activity.
        if await self.get_kv("xp_ledger_baseline_v1") != "1":
            await self.db.execute(
                """INSERT INTO xp_transactions(user_id, amount, balance_after, source,
                                              reason, created_at)
                   SELECT u.user_id, u.xp, u.xp, 'opening_balance',
                          'Начальный баланс до введения журнала', ?
                     FROM users u
                    WHERE NOT EXISTS (
                        SELECT 1 FROM xp_transactions t WHERE t.user_id=u.user_id
                    )""",
                (now(),),
            )
            await self.db.execute(
                "INSERT INTO kv(key, value) VALUES ('xp_ledger_baseline_v1','1') "
                "ON CONFLICT(key) DO UPDATE SET value='1'"
            )
        # Любое изменение users.xp попадает в тот же SQLite statement, включая
        # старые игровые пути и обновления через отдельное соединение.
        await self.db.executescript("""
            CREATE TRIGGER IF NOT EXISTS trg_xp_no_edit
            BEFORE UPDATE ON xp_transactions
            BEGIN SELECT RAISE(ABORT, 'XP journal is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS trg_xp_no_delete
            BEFORE DELETE ON xp_transactions
            BEGIN SELECT RAISE(ABORT, 'XP journal is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS trg_xp_transactions
            AFTER UPDATE OF xp ON users
            WHEN NEW.xp <> OLD.xp
            BEGIN
                INSERT INTO xp_transactions (
                    user_id, amount, balance_after, source, reason, actor_id,
                    reference_type, reference_id, idempotency_key, created_at
                ) VALUES (
                    NEW.user_id, NEW.xp - OLD.xp, NEW.xp,
                    COALESCE(NULLIF(NEW.xp_source, ''), 'other'),
                    NEW.xp_reason, NEW.xp_actor_id,
                    NEW.xp_reference_type, NEW.xp_reference_id,
                    NULLIF(NEW.xp_idempotency_key, ''), CAST(strftime('%s', 'now') AS INTEGER)
                );
                UPDATE users SET xp_source='', xp_reason='', xp_actor_id=0,
                    xp_reference_type='', xp_reference_id='', xp_idempotency_key=''
                    WHERE user_id=NEW.user_id;
            END;
        """)

    async def change_xp(
        self, user_id: int, amount: int, *, source: str, reason: str,
        actor_id: int = 0, reference_type: str = '', reference_id: str = '',
        idempotency_key: str = '',
    ) -> tuple[int, bool]:
        """Атомарное изменение баланса. Возвращает (баланс, применено).

        Выделенное соединение + BEGIN IMMEDIATE изолирует несколько конкурентных
        callback от остальных autocommit-обработчиков общей connection.
        """
        uid = int(user_id)
        delta = int(amount)
        if uid <= 0 or not delta:
            raise ValueError("Укажите пользователя и ненулевую сумму")
        if not str(reason).strip():
            raise ValueError("Укажите причину")
        if abs(delta) > 1_000_000_000:
            raise ValueError("Сумма слишком большая")
        key = str(idempotency_key or '')
        if len(key) > 180:
            raise ValueError("Слишком длинный ключ операции")
        async with self._xp_lock:
            async with aiosqlite.connect(self.path, isolation_level=None) as conn:
                conn.row_factory = aiosqlite.Row
                await conn.execute("PRAGMA busy_timeout=10000")
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    if key:
                        async with conn.execute(
                            "SELECT user_id, balance_after FROM xp_transactions WHERE idempotency_key=?",
                            (key,),
                        ) as cur:
                            previous = await cur.fetchone()
                        if previous:
                            if int(previous["user_id"]) != uid:
                                raise ValueError("Ключ операции принадлежит другому пользователю")
                            await conn.commit()
                            return int(previous["balance_after"]), False
                    async with conn.execute(
                        "SELECT xp FROM users WHERE user_id=?", (uid,)
                    ) as cur:
                        row = await cur.fetchone()
                    if row is None:
                        raise ValueError("Пользователь не найден")
                    before = int(row["xp"] or 0)
                    after = before + delta
                    if after < 0:
                        raise ValueError("Недостаточно очков для списания")
                    await conn.execute(
                        """UPDATE users SET xp=?, xp_source=?, xp_reason=?,
                               xp_actor_id=?, xp_reference_type=?, xp_reference_id=?,
                               xp_idempotency_key=? WHERE user_id=?""",
                        (after, str(source), str(reason)[:500], int(actor_id),
                         str(reference_type), str(reference_id), key, uid),
                    )
                    if delta > 0:
                        await conn.execute(
                            """INSERT INTO daily_activity(user_id, day_start, xp_earned)
                               VALUES (?, ?, ?) ON CONFLICT(user_id, day_start)
                               DO UPDATE SET xp_earned=xp_earned+excluded.xp_earned""",
                            (uid, referral_day_start(), delta),
                        )
                    if str(source) in {"admin_award", "admin_debit"}:
                        from .admin_events import enqueue
                        await enqueue(
                            conn, uid, "points", reason=reason, amount=delta,
                            balance=after, event_key=f"xp:{key}" if key else "",
                        )
                    await conn.commit()
                    self._top_cache.clear()
                    return after, True
                except Exception:
                    await conn.rollback()
                    raise

    async def xp_history(
        self, user_id: int, *, limit: int = 10, offset: int = 0,
        kind: str = 'all', source: str = '', since: int = 0,
    ) -> tuple[list[aiosqlite.Row], dict[str, int]]:
        where = ["user_id=?"]
        args: list[Any] = [int(user_id)]
        if kind == 'plus':
            where.append("amount>0")
        elif kind == 'minus':
            where.append("amount<0")
        if source:
            where.append("source=?")
            args.append(str(source))
        if since:
            where.append("created_at>=?")
            args.append(int(since))
        cond = " AND ".join(where)
        rows = await self._fetchall(
            f"SELECT * FROM xp_transactions WHERE {cond} "
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (*args, max(1, min(int(limit), 30)), max(0, int(offset))),
        )
        summary = await self._fetchone(
            f"SELECT COUNT(*) AS count, "
            f"COALESCE(SUM(CASE WHEN amount>0 THEN amount END),0) AS credits, "
            f"COALESCE(SUM(CASE WHEN amount<0 THEN -amount END),0) AS debits "
            f"FROM xp_transactions WHERE {cond}",
            args,
        )
        return rows, {k: int(summary[k] or 0) for k in ('count','credits','debits')}

    async def admin_user_list(
        self, *, limit: int = 12, offset: int = 0, sort: str = 'recent',
        filter_by: str = 'all', query: str = '', ids: Sequence[int] = (),
    ) -> tuple[list[aiosqlite.Row], int]:
        orders = {
            'recent': 'last_seen DESC, user_id DESC',
            'new': 'created_at DESC, user_id DESC',
            'xp': 'xp DESC, user_id ASC',
            'messages': 'messages DESC, user_id ASC',
            'dialogs': 'dialogs DESC, user_id ASC',
        }
        where: list[str] = []
        args: list[Any] = []
        if filter_by == 'active':
            where.append('last_seen>=?')
            args.append(now()-600)
        elif filter_by == 'ban':
            where.append('banned=1')
        elif filter_by == 'mute':
            where.append('mute_until>?')
            args.append(now())
        elif filter_by == 'support':
            where.append('(support_stars>0 OR support_rub>0)')
        elif filter_by == 'admins':
            where.append('user_id IN (SELECT user_id FROM admins)')
        elif filter_by in {'queue','dialog'}:
            selected = [int(uid) for uid in ids][:500]
            if not selected:
                return [], 0
            where.append('user_id IN ('+','.join('?' for _ in selected)+')')
            args.extend(selected)
        if query:
            value = query.strip().lstrip('@')[:100]
            if value.isdigit():
                where.append('(user_id=? OR username LIKE ? OR nickname LIKE ? OR first_name LIKE ?)')
                args.extend((int(value),f'%{value}%',f'%{value}%',f'%{value}%'))
            else:
                value = value.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
                where.append("(username LIKE ? ESCAPE '\\' OR nickname LIKE ? ESCAPE '\\' "
                             "OR first_name LIKE ? ESCAPE '\\')")
                args.extend((f'%{value}%',)*3)
        condition = (' WHERE ' + ' AND '.join(where)) if where else ''
        total = await self._fetchone('SELECT COUNT(*) AS c FROM users'+condition, args)
        rows = await self._fetchall(
            'SELECT user_id, username, first_name, nickname, xp, support_stars, '
            'messages, dialogs, last_seen, created_at, banned, mute_until '
            'FROM users'+condition+' ORDER BY '+orders.get(sort,'last_seen DESC, user_id DESC')+
            ' LIMIT ? OFFSET ?',
            (*args, max(1, min(int(limit), 15)), max(0, int(offset))),
        )
        return rows, int(total['c'] if total else 0)

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

    # ------------------------------------------------------ active Mini App chat
    async def apply_active_chat_ops(self, ops: Sequence[dict[str, Any]]) -> None:
        """Пакетно сохраняет только текущую активную ленту Mini App.

        Эти записи не являются архивом: clear удаляет всю пару при stop/next.
        """
        if not ops:
            return
        for op in ops:
            kind = str(op.get("op", ""))
            if kind == "append":
                user_a = int(op["user_a"])
                user_b = int(op["user_b"])
                low, high = sorted((user_a, user_b))
                await self.db.execute(
                    """INSERT OR REPLACE INTO active_chat_events(
                           id, user_low, user_high, sender_id, kind, text, file_id,
                           telegram_message_id, data, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        int(op["id"]),
                        low,
                        high,
                        int(op.get("sender_id", 0) or 0),
                        str(op.get("kind", "system") or "system"),
                        str(op.get("text", "") or "")[:3000],
                        str(op.get("file_id", "") or ""),
                        int(op.get("telegram_message_id", 0) or 0),
                        json.dumps(op.get("data") or {}, ensure_ascii=False, separators=(",", ":")),
                        int(op.get("created_at", now()) or now()),
                    ),
                )
                # Активному диалогу достаточно последних 160 событий.
                await self.db.execute(
                    """DELETE FROM active_chat_events
                       WHERE user_low=? AND user_high=?
                         AND id NOT IN (
                             SELECT id FROM active_chat_events
                              WHERE user_low=? AND user_high=?
                              ORDER BY id DESC LIMIT 160
                         )""",
                    (low, high, low, high),
                )
            elif kind == "clear":
                low, high = sorted((int(op["user_a"]), int(op["user_b"])))
                await self.db.execute(
                    "DELETE FROM active_chat_events WHERE user_low=? AND user_high=?",
                    (low, high),
                )
            elif kind == "clear_user":
                uid = int(op["user_id"])
                await self.db.execute(
                    "DELETE FROM active_chat_events WHERE user_low=? OR user_high=?",
                    (uid, uid),
                )
        await self.db.commit()

    async def active_chat_events(
        self, user_a: int, user_b: int, *, after: int = 0, limit: int = 160
    ) -> list[aiosqlite.Row]:
        low, high = sorted((int(user_a), int(user_b)))
        return await self._fetchall(
            """SELECT * FROM active_chat_events
               WHERE user_low=? AND user_high=? AND id>?
               ORDER BY id ASC LIMIT ?""",
            (low, high, max(0, int(after)), max(1, min(int(limit), 160))),
        )

    async def clear_active_chat(self, user_a: int, user_b: int) -> None:
        low, high = sorted((int(user_a), int(user_b)))
        await self.db.execute(
            "DELETE FROM active_chat_events WHERE user_low=? AND user_high=?",
            (low, high),
        )
        await self.db.commit()

    # ------------------------------------------------------------------ users
    async def ensure_user(
        self, user_id: int, username: str | None, first_name: str,
        *, existing: aiosqlite.Row | None = None,
    ) -> aiosqlite.Row:
        if existing is None:
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
        cached = self._admin_permissions_cache.get(int(user_id))
        now_mono = time.monotonic()
        if cached is not None and now_mono - cached[0] < 30:
            return cached[1]
        row = await self._fetchone("SELECT permissions FROM admins WHERE user_id = ?", (user_id,))
        permissions = (
            frozenset(
                item for item in str(row["permissions"] or "").split(",")
                if item in ALL_ADMIN_PERMISSIONS
            )
            if row is not None else frozenset()
        )
        self._admin_permissions_cache[int(user_id)] = (now_mono, permissions)
        return permissions

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
        self._admin_permissions_cache.pop(int(user_id), None)
        return clean

    async def remove_admin(self, user_id: int) -> bool:
        cur = await self.db.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        await self.db.commit()
        self._admin_permissions_cache.pop(int(user_id), None)
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

    async def geo_for_pair(self, user_a: int, user_b: int) -> aiosqlite.Row | None:
        return await self._fetchone(
            """SELECT * FROM battle_games
               WHERE game_type='geo'
                 AND status IN ('invited', 'active', 'round_done')
                 AND ((user_a = ? AND user_b = ?) OR (user_a = ? AND user_b = ?))
               ORDER BY id DESC LIMIT 1""",
            (user_a, user_b, user_b, user_a),
        )

    async def get_battle(self, game_id: int) -> aiosqlite.Row | None:
        return await self._fetchone("SELECT * FROM battle_games WHERE id = ?", (game_id,))

    async def cleanup_stale_games(
        self, max_age: int = GAME_INACTIVE_TTL_SECONDS, timestamp: int | None = None
    ) -> int:
        """Удаляет игры без активности дольше заданного срока."""
        cutoff = (now() if timestamp is None else int(timestamp)) - max(1, int(max_age))
        async with self._number_reward_lock:
            rows = await self._fetchall(
                """SELECT * FROM battle_games
                    WHERE status IN ('invited', 'active', 'round_done')
                      AND updated_at <= ?""",
                (cutoff,),
            )
            if not rows:
                return 0

            ids = [int(row["id"]) for row in rows]
            for row in rows:
                await self._release_unplayed_number_pair(row)
                await self._release_unplayed_geo_pair(row)

            placeholders = ",".join("?" for _ in ids)
            await self.db.execute(
                f"DELETE FROM battle_games WHERE id IN ({placeholders})",
                tuple(ids),
            )
            await self.db.commit()
            return len(ids)

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
            payouts = []
            for player_id in (int(game["user_a"]), int(game["user_b"])):
                payouts.append(await self.award_game_xp(
                    player_id, 25, source="battle",
                    reason=f"Идеальное совпадение: {game['total_questions']} вопросов",
                    reference_type="game", reference_id=str(game_id),
                    commit=False,
                ))
            await self.db.execute(
                "UPDATE battle_games SET reward_total_a=?, reward_total_b=? WHERE id=?",
                (payouts[0], payouts[1], game_id),
            )
            game = await self.get_battle(game_id)
        if resolved.rowcount and game is not None and str(game["status"]) == "finished":
            await self.db.execute("DELETE FROM battle_games WHERE id = ?", (game_id,))
        await self.db.commit()
        if resolved.rowcount and game is not None and int(game["reward_awarded"] or 0):
            self._top_cache.clear()
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

    async def game_xp_today(self, user_id: int, timestamp: int | None = None) -> int:
        """Полученные за текущие сутки игровые звёзды (Магнитогорск UTC+5).

        Используем неизменяемый XP-журнал вместо разрозненных счётчиков
        отдельных игр. Ручное списание не восстанавливает дневную квоту.
        """
        row = await self._fetchone(
            """SELECT COALESCE(SUM(amount), 0) AS earned
                 FROM xp_transactions
                WHERE user_id=? AND created_at>=?
                  AND source IN ('battle','numbers','geoguessr','word_game')
                  AND amount>0""",
            (int(user_id), referral_day_start(timestamp)),
        )
        return int(row["earned"] or 0) if row else 0

    async def game_xp_remaining(self, user_id: int) -> int:
        return max(0, GAME_XP_DAILY_LIMIT - await self.game_xp_today(user_id))

    async def award_game_xp(
        self, user_id: int, amount: int, *, source: str,
        reason: str = "", reference_type: str = "game",
        reference_id: str = "", commit: bool = True,
        already_multiplied: bool = False,
    ) -> int:
        """Единый дневной лимит ВСЕХ игр: не больше 500 ⭐ на человека.

        Множитель применяется ДО ограничения. Общий lock не допускает двух
        параллельных выигрышей через разные игры выйти за дневную квоту.
        """
        if source not in GAME_XP_SOURCES:
            raise ValueError("Неизвестный тип игровой награды")
        requested = max(0, int(amount))
        if requested <= 0:
            return 0
        effective = requested if already_multiplied else await self.effective_xp_reward(requested)
        async with self._game_reward_lock:
            available = await self.game_xp_remaining(user_id)
            credited = min(effective, available)
            if credited <= 0:
                return 0
            await self.db.execute(
                """UPDATE users SET xp=xp+?, xp_source=?, xp_reason=?,
                          xp_reference_type=?, xp_reference_id=?
                    WHERE user_id=?""",
                (credited, source, str(reason)[:500],
                 str(reference_type), str(reference_id), int(user_id)),
            )
            await self.db.execute(
                """INSERT INTO daily_activity(user_id, day_start, xp_earned)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, day_start)
                   DO UPDATE SET xp_earned=xp_earned+excluded.xp_earned""",
                (int(user_id), referral_day_start(), credited),
            )
            if commit:
                await self.db.commit()
            self._top_cache.clear()
            return credited

    async def number_pair_reward_available(self, user_a: int, user_b: int) -> bool:
        return True

    async def number_daily_reward(self, user_id: int, timestamp: int | None = None) -> int:
        row = await self._fetchone(
            "SELECT stars FROM number_daily_rewards WHERE user_id=? AND day_start=?",
            (int(user_id), number_reward_day_start(timestamp)),
        )
        return int(row["stars"] or 0) if row else 0

    async def _award_number_daily_unlocked(
        self, user_id: int, requested: int, day_start: int,
        game_id: int = 0, round_index: int = 0,
    ) -> int:
        requested = max(0, int(requested))
        if requested <= 0:
            return 0
        awarded = await self.award_game_xp(
            user_id, requested, source="numbers",
            reason=f"Числа · раунд {round_index + 1}",
            reference_id=str(game_id), commit=False,
        )
        if awarded:
            await self.db.execute(
                """INSERT INTO number_daily_rewards(user_id, day_start, stars)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, day_start)
                   DO UPDATE SET stars=stars+excluded.stars""",
                (int(user_id), int(day_start), awarded),
            )
        return awarded

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
                   range_max, reward_total, reward_total_a, reward_total_b,
                   created_at, updated_at
               ) VALUES (?, ?, ?, 'numbers', ?, ?, 0, 0, 0, ?, ?)""",
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
        async with self._number_reward_lock:
            row = await self.get_battle(game_id)
            if (
                row is None
                or str(row["game_type"] or "") != "numbers"
                or str(row["status"]) != "invited"
                or int(row["user_b"]) != int(user_id)
                or int(row["inviter_id"]) == int(user_id)
            ):
                return None

            cur = await self.db.execute(
                """UPDATE battle_games
                   SET status='active', question_index=0,
                       answer_a=NULL, answer_b=NULL, matches=0,
                       reward_awarded=1, reward_total=0,
                       reward_total_a=0, reward_total_b=0, updated_at=?
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
    ) -> tuple[str, aiosqlite.Row | None, int, int]:
        async with self._number_reward_lock:
            row = await self.get_battle(game_id)
            if (
                row is None
                or str(row["game_type"] or "") != "numbers"
                or user_id not in {int(row["user_a"]), int(row["user_b"])}
            ):
                return "missing", row, 0, 0
            range_max = int(row["range_max"] or 0)
            if range_max not in NUMBER_REWARDS or not 1 <= int(value) <= range_max:
                return "invalid", row, 0, 0
            if row["status"] != "active" or int(row["question_index"]) != round_index:
                return "closed", row, 0, 0

            column = "answer_a" if int(row["user_a"]) == user_id else "answer_b"
            cur = await self.db.execute(
                f"""UPDATE battle_games SET {column}=?, updated_at=?
                     WHERE id=? AND game_type='numbers' AND status='active'
                       AND question_index=? AND {column} IS NULL""",
                (int(value), now(), game_id, round_index),
            )
            if not cur.rowcount:
                await self.db.commit()
                return "already", await self.get_battle(game_id), 0, 0

            game = await self.get_battle(game_id)
            if game is None or game["answer_a"] is None or game["answer_b"] is None:
                await self.db.commit()
                return "waiting", game, 0, 0

            raw_reward = number_reward(
                range_max, int(game["answer_a"]), int(game["answer_b"])
            )
            exact = int(game["answer_a"]) == int(game["answer_b"])
            status = "finished" if round_index >= NUMBER_ROUNDS - 1 else "round_done"

            resolved = await self.db.execute(
                """UPDATE battle_games
                   SET matches=matches+?,
                       status=?, updated_at=?
                   WHERE id=? AND game_type='numbers' AND status='active'
                     AND question_index=? AND answer_a IS NOT NULL AND answer_b IS NOT NULL""",
                (1 if exact else 0, status, now(), game_id, round_index),
            )
            if not resolved.rowcount:
                await self.db.commit()
                return "waiting", await self.get_battle(game_id), 0, 0

            reward_a = 0
            reward_b = 0
            if int(game["reward_awarded"] or 0) and raw_reward > 0:
                day_start = number_reward_day_start()
                reward_a = await self._award_number_daily_unlocked(
                    int(game["user_a"]), raw_reward, day_start, game_id, round_index
                )
                reward_b = await self._award_number_daily_unlocked(
                    int(game["user_b"]), raw_reward, day_start, game_id, round_index
                )

            await self.db.execute(
                """UPDATE battle_games
                   SET reward_total=reward_total+?,
                       reward_total_a=reward_total_a+?,
                       reward_total_b=reward_total_b+?
                   WHERE id=?""",
                (min(reward_a, reward_b), reward_a, reward_b, game_id),
            )
            game = await self.get_battle(game_id)
            if game is not None and status == "finished":
                await self.db.execute("DELETE FROM battle_games WHERE id=?", (game_id,))
            await self.db.commit()
            return "resolved", game, reward_a, reward_b

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

    async def geo_pair_reward_available(self, user_a: int, user_b: int) -> bool:
        return True

    async def recent_geo_place_ids(
        self, user_ids: Sequence[int], limit_per_user: int = 150
    ) -> set[int]:
        """Места, недавно показанные любому из указанных игроков."""
        result: set[int] = set()
        limit = max(1, int(limit_per_user))
        for user_id in {int(value) for value in user_ids}:
            cursor = await self.db.execute(
                """SELECT place_id FROM geo_place_history
                   WHERE user_id=? ORDER BY shown_at DESC LIMIT ?""",
                (user_id, limit),
            )
            result.update(int(row["place_id"]) for row in await cursor.fetchall())
        return result

    async def _remember_geo_places_unlocked(
        self, user_ids: Sequence[int], place_ids: Sequence[int]
    ) -> None:
        timestamp = now()
        rows = [
            (int(user_id), int(place_id), timestamp)
            for user_id in {int(value) for value in user_ids}
            for place_id in {int(value) for value in place_ids}
        ]
        if rows:
            await self.db.executemany(
                """INSERT INTO geo_place_history(user_id, place_id, shown_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, place_id)
                   DO UPDATE SET shown_at=excluded.shown_at""",
                rows,
            )

    async def remember_geo_places(
        self, user_ids: Sequence[int], place_ids: Sequence[int]
    ) -> None:
        await self._remember_geo_places_unlocked(user_ids, place_ids)
        await self.db.commit()

    async def create_geo_invite(
        self, inviter_id: int, partner_id: int, place_ids: Sequence[int]
    ) -> tuple[aiosqlite.Row, bool]:
        ids = [int(value) for value in place_ids]
        total = len(ids)
        if total not in GEO_ROUND_OPTIONS or len(set(ids)) != total:
            raise ValueError("Для Геогусера выбери 3, 5 или 10 разных мест")
        ts = now()
        cur = await self.db.execute(
            """INSERT OR IGNORE INTO battle_games(
                   user_a, user_b, inviter_id, game_type, total_questions,
                   question_ids, reward_total, reward_total_a, reward_total_b,
                   created_at, updated_at
               ) VALUES (?, ?, ?, 'geo', ?, ?, 0, 0, 0, ?, ?)""",
            (
                int(inviter_id), int(partner_id), int(inviter_id), total,
                json.dumps(ids), ts, ts,
            ),
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

    async def accept_geo(self, game_id: int, user_id: int) -> aiosqlite.Row | None:
        async with self._number_reward_lock:
            row = await self.get_battle(game_id)
            if (
                row is None
                or str(row["game_type"] or "") != "geo"
                or str(row["status"]) != "invited"
                or int(row["user_b"]) != int(user_id)
                or int(row["inviter_id"]) == int(user_id)
            ):
                return None
            low, high = sorted((int(row["user_a"]), int(row["user_b"])))
            cur = await self.db.execute(
                """UPDATE battle_games
                   SET status='active', question_index=0, reward_awarded=1,
                       reward_total=0, reward_total_a=0, reward_total_b=0,
                       geo_lat_a=NULL, geo_lon_a=NULL, geo_lat_b=NULL, geo_lon_b=NULL,
                       geo_distance_a=NULL, geo_distance_b=NULL,
                       geo_round_started_at=?, updated_at=?
                   WHERE id=? AND game_type='geo' AND status='invited'
                     AND user_b=? AND inviter_id<>?""",
                (now(), now(), game_id, user_id, user_id),
            )
            if cur.rowcount:
                try:
                    place_ids = [int(value) for value in json.loads(row["question_ids"] or "[]")]
                except (TypeError, ValueError, json.JSONDecodeError):
                    place_ids = []
                await self._remember_geo_places_unlocked((low, high), place_ids)
            await self.db.commit()
            return await self.get_battle(game_id) if cur.rowcount else None

    async def decline_geo(self, game_id: int, user_id: int) -> aiosqlite.Row | None:
        row = await self.get_battle(game_id)
        if (
            row is None
            or str(row["game_type"] or "") != "geo"
            or int(row["user_b"]) != int(user_id)
        ):
            return None
        cur = await self.db.execute(
            "DELETE FROM battle_games WHERE id=? AND game_type='geo' AND status='invited'",
            (game_id,),
        )
        await self.db.commit()
        return row if cur.rowcount else None

    async def _award_geo_daily_unlocked(
        self, user_id: int, requested: int, day_start: int,
        game_id: int = 0, round_index: int = 0,
    ) -> int:
        requested = max(0, int(requested))
        if requested <= 0:
            return 0
        awarded = await self.award_game_xp(
            user_id, requested, source="geoguessr",
            reason=f"GeoGuessr · раунд {round_index + 1}",
            reference_id=str(game_id), commit=False,
        )
        if awarded:
            await self.db.execute(
                """INSERT INTO geo_daily_rewards(user_id, day_start, stars)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, day_start)
                   DO UPDATE SET stars=stars+excluded.stars""",
                (int(user_id), int(day_start), awarded),
            )
        return awarded

    async def _resolve_geo_round_unlocked(
        self, game: aiosqlite.Row, game_id: int, round_index: int
    ) -> tuple[aiosqlite.Row | None, int, int]:
        """Начислить награду за точность и закрыть текущий гео-раунд."""
        raw_a = (
            geo_reward(float(game["geo_distance_a"]))
            if game["geo_lat_a"] is not None and game["geo_distance_a"] is not None
            else 0
        )
        raw_b = (
            geo_reward(float(game["geo_distance_b"]))
            if game["geo_lat_b"] is not None and game["geo_distance_b"] is not None
            else 0
        )
        reward_a = reward_b = 0
        if int(game["reward_awarded"] or 0):
            day = referral_day_start()
            reward_a = await self._award_geo_daily_unlocked(
                int(game["user_a"]), raw_a, day, game_id, round_index
            )
            reward_b = await self._award_geo_daily_unlocked(
                int(game["user_b"]), raw_b, day, game_id, round_index
            )

        total = max(1, int(game["total_questions"] or 1))
        status = "finished" if int(round_index) >= total - 1 else "round_done"
        await self.db.execute(
            """UPDATE battle_games
               SET status=?, reward_total=reward_total+?,
                   reward_total_a=reward_total_a+?, reward_total_b=reward_total_b+?,
                   updated_at=?
               WHERE id=? AND game_type='geo' AND status='active' AND question_index=?""",
            (
                status,
                max(reward_a, reward_b),
                reward_a,
                reward_b,
                now(),
                int(game_id),
                int(round_index),
            ),
        )
        snapshot = await self.get_battle(game_id)
        if snapshot is not None and status == "finished":
            await self.db.execute("DELETE FROM battle_games WHERE id=?", (game_id,))
        await self.db.commit()
        return snapshot, reward_a, reward_b

    async def answer_geo(
        self, game_id: int, user_id: int, round_index: int,
        latitude: float, longitude: float, target_latitude: float, target_longitude: float,
    ) -> tuple[str, aiosqlite.Row | None, int, int]:
        from .geoquest import distance_meters

        latitude, longitude = float(latitude), float(longitude)
        target_latitude, target_longitude = float(target_latitude), float(target_longitude)
        if not all(math.isfinite(value) for value in (
            latitude, longitude, target_latitude, target_longitude,
        )) or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return "invalid", await self.get_battle(game_id), 0, 0
        if not valid_guess_coordinate(latitude, longitude):
            return "outside", await self.get_battle(game_id), 0, 0

        async with self._number_reward_lock:
            row = await self.get_battle(game_id)
            if (
                row is None
                or str(row["game_type"] or "") != "geo"
                or int(user_id) not in {int(row["user_a"]), int(row["user_b"])}
            ):
                return "missing", row, 0, 0
            if str(row["status"]) != "active" or int(row["question_index"]) != int(round_index):
                return "closed", row, 0, 0

            started_at = int(row["geo_round_started_at"] or row["updated_at"] or 0)
            if started_at and now() >= started_at + GEO_ROUND_SECONDS:
                return "expired", row, 0, 0

            suffix = "a" if int(row["user_a"]) == int(user_id) else "b"
            if row[f"geo_lat_{suffix}"] is not None:
                return "already", row, 0, 0
            dist = distance_meters(latitude, longitude, target_latitude, target_longitude)
            cur = await self.db.execute(
                f"""UPDATE battle_games
                    SET geo_lat_{suffix}=?, geo_lon_{suffix}=?, geo_distance_{suffix}=?, updated_at=?
                    WHERE id=? AND game_type='geo' AND status='active'
                      AND question_index=? AND geo_lat_{suffix} IS NULL""",
                (latitude, longitude, dist, now(), game_id, round_index),
            )
            if not cur.rowcount:
                await self.db.commit()
                return "already", await self.get_battle(game_id), 0, 0
            game = await self.get_battle(game_id)
            if game is None or game["geo_lat_a"] is None or game["geo_lat_b"] is None:
                await self.db.commit()
                return "waiting", game, 0, 0

            game, reward_a, reward_b = await self._resolve_geo_round_unlocked(
                game, game_id, round_index
            )
            return "resolved", game, reward_a, reward_b

    async def expire_geo_round(
        self, game_id: int, round_index: int
    ) -> tuple[str, aiosqlite.Row | None, int, int]:
        """Закрывает раунд после двух минут; неответивший получает 0 ⭐."""
        async with self._number_reward_lock:
            row = await self.get_battle(game_id)
            if (
                row is None
                or str(row["game_type"] or "") != "geo"
                or str(row["status"]) != "active"
                or int(row["question_index"]) != int(round_index)
            ):
                return "closed", row, 0, 0
            started_at = int(row["geo_round_started_at"] or row["updated_at"] or 0)
            if started_at and now() < started_at + GEO_ROUND_SECONDS:
                return "early", row, 0, 0
            game, reward_a, reward_b = await self._resolve_geo_round_unlocked(
                row, game_id, round_index
            )
            return "resolved", game, reward_a, reward_b

    async def advance_geo(
        self, game_id: int, user_id: int, round_index: int
    ) -> aiosqlite.Row | None:
        row = await self.get_battle(game_id)
        if (
            row is None
            or str(row["game_type"] or "") != "geo"
            or int(user_id) not in {int(row["user_a"]), int(row["user_b"])}
        ):
            return None
        cur = await self.db.execute(
            """UPDATE battle_games
               SET status='active', question_index=question_index+1,
                   geo_lat_a=NULL, geo_lon_a=NULL, geo_lat_b=NULL, geo_lon_b=NULL,
                   geo_distance_a=NULL, geo_distance_b=NULL,
                   geo_round_started_at=?, updated_at=?
               WHERE id=? AND game_type='geo' AND status='round_done' AND question_index=?""",
            (now(), now(), game_id, round_index),
        )
        await self.db.commit()
        return await self.get_battle(game_id) if cur.rowcount else None

    async def _release_unplayed_number_pair(self, row: Any) -> None:
        if (
            str(row["game_type"] or "battle") == "numbers"
            and str(row["status"]) == "active"
            and int(row["question_index"] or 0) == 0
            and int(row["reward_awarded"] or 0) == 1
        ):
            low, high = sorted((int(row["user_a"]), int(row["user_b"])))
            await self.db.execute(
                "DELETE FROM number_game_pairs WHERE user_low=? AND user_high=?",
                (low, high),
            )

    async def _release_unplayed_geo_pair(self, row: Any) -> None:
        if (
            str(row["game_type"] or "") == "geo"
            and str(row["status"]) == "active"
            and int(row["question_index"] or 0) == 0
            and row["geo_lat_a"] is None
            and row["geo_lat_b"] is None
            and int(row["reward_awarded"] or 0) == 1
        ):
            low, high = sorted((int(row["user_a"]), int(row["user_b"])))
            await self.db.execute(
                """DELETE FROM geo_game_pairs
                   WHERE user_low=? AND user_high=? AND day_start=?""",
                (low, high, referral_day_start()),
            )

    async def cancel_battle(self, game_id: int) -> bool:
        async with self._number_reward_lock:
            row = await self.get_battle(game_id)
            if row is None or str(row["status"]) not in {"invited", "active", "round_done"}:
                return False
            await self._release_unplayed_number_pair(row)
            await self._release_unplayed_geo_pair(row)
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
        params = (*ids, *ids)
        async with self._number_reward_lock:
            rows = await self._fetchall(
                f"""SELECT * FROM battle_games
                     WHERE status IN ('invited', 'active', 'round_done')
                       AND (user_a IN ({placeholders}) OR user_b IN ({placeholders}))""",
                params,
            )
            for row in rows:
                await self._release_unplayed_number_pair(row)
                await self._release_unplayed_geo_pair(row)
            cur = await self.db.execute(
                f"""DELETE FROM battle_games
                     WHERE status IN ('invited', 'active', 'round_done')
                       AND (user_a IN ({placeholders}) OR user_b IN ({placeholders}))""",
                params,
            )
            await self.db.commit()
            return cur.rowcount

    async def award_word_guess(
        self, user_id: int, partner_id: int, requested: int = WORD_REWARD
    ) -> int:
        """Награда за слово с общим дневным лимитом игр 500 ⭐."""
        user_id = int(user_id)
        partner_id = int(partner_id)
        requested = max(0, int(requested))
        if not user_id or not partner_id or user_id == partner_id or requested <= 0:
            return 0

        return await self.award_game_xp(
            user_id, requested, source="word_game",
            reason="Угаданное слово", reference_type="word_partner",
            reference_id=str(partner_id),
        )

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

    async def set_unique_nickname(self, user_id: int, nickname: str) -> bool:
        """Атомарно для одного процесса проверяет уникальность и сохраняет ник."""
        async with self._nickname_lock:
            if await self.nickname_taken(nickname, except_user_id=user_id):
                return False
            await self.set_profile(user_id, nickname=nickname)
            return True

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

    async def effective_xp_reward(self, amount: int) -> int:
        """Фактическая награда с учётом активного x1/x2/x3."""
        base = max(0, int(amount))
        if base <= 0:
            return 0
        return base * await self.xp_multiplier()

    async def award_xp(
        self, user_id: int, amount: int, *, column: str | None = None, commit: bool = True,
        source: str = 'other', reason: str = '',
        reference_type: str = '', reference_id: str = '',
    ) -> int:
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
                f"UPDATE users SET xp = xp + ?, xp_source=?, xp_reason=?, "
                f"xp_reference_type=?, xp_reference_id=?, "
                f"{column} = {column} + ? WHERE user_id = ?",
                (amount, source, reason, reference_type, reference_id, amount, user_id),
            )
        else:
            await self.db.execute(
                "UPDATE users SET xp=xp+?, xp_source=?, xp_reason=?, "
                "xp_reference_type=?, xp_reference_id=? WHERE user_id=?",
                (amount,source,reason,reference_type,reference_id,user_id)
            )
        if int(amount) > 0:
            await self.db.execute(
                """INSERT INTO daily_activity(user_id, day_start, xp_earned)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, day_start)
                   DO UPDATE SET xp_earned=xp_earned+excluded.xp_earned""",
                (int(user_id), referral_day_start(), int(amount)),
            )
        if commit:
            await self.db.commit()
        self._top_cache.clear()
        row = await self._fetchone("SELECT xp FROM users WHERE user_id = ?", (user_id,))
        return int(row["xp"]) if row else 0

    async def reward_claimed(self, user_id: int, reward_key: str) -> bool:
        row = await self._fetchone(
            "SELECT 1 FROM reward_claims WHERE user_id=? AND reward_key=? LIMIT 1",
            (int(user_id), str(reward_key)),
        )
        return row is not None

    async def claim_one_time_reward(
        self, user_id: int, reward_key: str, amount: int
    ) -> bool:
        """Атомарно выдаёт одноразовую награду. Повторный claim ничего не начисляет."""
        reward_key = str(reward_key or "").strip()
        amount = max(0, int(amount))
        if not reward_key or amount <= 0:
            return False
        amount = await self.effective_xp_reward(amount)
        ts = now()
        cur = await self.db.execute(
            """INSERT OR IGNORE INTO reward_claims(user_id, reward_key, amount, created_at)
               VALUES (?, ?, ?, ?)""",
            (int(user_id), reward_key, amount, ts),
        )
        if cur.rowcount != 1:
            await self.db.commit()
            return False
        await self.db.execute(
            "UPDATE users SET xp=xp+?, xp_source=?, xp_reason=?, "
            "xp_reference_type='reward_claim', xp_reference_id=? WHERE user_id=?",
            (amount, ('subscription' if reward_key.startswith('channel_subscription') else
                      'report' if reward_key.startswith('approved_report') else
                      'one_time_reward'), reward_key, reward_key, int(user_id)),
        )
        await self.db.execute(
            """INSERT INTO daily_activity(user_id, day_start, xp_earned)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id, day_start)
               DO UPDATE SET xp_earned=xp_earned+excluded.xp_earned""",
            (int(user_id), referral_day_start(ts), amount),
        )
        await self.db.commit()
        self._top_cache.clear()
        return True

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
        amount = await self.effective_xp_reward(amount)
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
                "UPDATE users SET xp=xp+?, xp_source='referral', xp_reason=?, "
                "xp_reference_type='referral', xp_reference_id=? WHERE user_id=?",
                (amount, f"Приглашён пользователь {invitee_id}", str(invitee_id), referrer_id),
            )
            await self.db.execute(
                """INSERT INTO daily_activity(user_id, day_start, xp_earned)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, day_start)
                   DO UPDATE SET xp_earned=xp_earned+excluded.xp_earned""",
                (int(referrer_id), referral_day_start(timestamp), int(amount)),
            )
            await self.db.commit()
            self._top_cache.clear()
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
        self._top_cache.clear()
        self._top_cache.clear()
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
                """SELECT r.invitee_id, r.xp_awarded, r.created_at, u.user_id AS existing_user_id,
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

            referral_xp = sum(int(row["xp_awarded"] or 0) for row in rows)
            await cleanup.execute(
                "UPDATE users SET xp=MAX(0, xp-?), xp_source='referral_correction' WHERE user_id=?",
                (referral_xp, referrer_id),
            )
            by_day: dict[int, int] = {}
            for row in rows:
                day = referral_day_start(int(row["created_at"] or 0) or now())
                by_day[day] = by_day.get(day, 0) + int(row["xp_awarded"] or 0)
            for day, amount in by_day.items():
                await cleanup.execute(
                    """UPDATE daily_activity
                          SET xp_earned=MAX(0, xp_earned-?)
                        WHERE user_id=? AND day_start=?""",
                    (amount, referrer_id, day),
                )
            await cleanup.execute("DELETE FROM referrals WHERE referrer_id=?", (referrer_id,))

            # Два поля в одном DELETE дают по два параметра на id; размер 400 ниже
            # стандартного лимита SQLite в 999 переменных.
            for offset in range(0, len(deleted_user_ids), 400):
                chunk = deleted_user_ids[offset : offset + 400]
                marks = ",".join("?" for _ in chunk)
                twice = (*chunk, *chunk)
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
                    f"DELETE FROM number_game_pairs WHERE user_low IN ({marks}) OR user_high IN ({marks})",
                    twice,
                )
                await cleanup.execute(
                    f"DELETE FROM number_daily_rewards WHERE user_id IN ({marks})",
                    tuple(chunk),
                )
                await cleanup.execute(
                    f"DELETE FROM daily_activity WHERE user_id IN ({marks})",
                    tuple(chunk),
                )
                await cleanup.execute(
                    f"DELETE FROM user_engagement WHERE user_id IN ({marks})",
                    tuple(chunk),
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
        cur = await self.db.execute(
            """INSERT OR IGNORE INTO payments
               (user_id, kind, stars, telegram_payment_charge_id,
                provider_payment_charge_id, created_at, payload)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, kind, stars, telegram_charge_id, provider_charge_id, now(), payload),
        )
        if cur.rowcount != 1:
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

    async def record_anon_plus_payment(
        self,
        user_id: int,
        stars: int,
        telegram_charge_id: str,
        provider_charge_id: str,
        payload: str,
        days: int = 0,
    ) -> tuple[bool, int]:
        ts = now()
        async with aiosqlite.connect(self.path, timeout=15.0) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("BEGIN IMMEDIATE")
            row = await (await conn.execute(
                "SELECT premium_until FROM users WHERE user_id=?", (int(user_id),)
            )).fetchone()
            if row is None:
                await conn.rollback()
                raise ValueError("User does not exist")
            cur = await conn.execute(
                """INSERT OR IGNORE INTO payments
                   (user_id, kind, stars, telegram_payment_charge_id,
                    provider_payment_charge_id, created_at, payload)
                   VALUES (?, 'anonplus', ?, ?, ?, ?, ?)""",
                (
                    int(user_id), int(stars), str(telegram_charge_id),
                    str(provider_charge_id or ""), ts, str(payload),
                ),
            )
            if cur.rowcount != 1:
                await conn.commit()
                return False, int(row["premium_until"] or 0)
            premium_until = ANON_PLUS_LIFETIME_UNTIL
            await conn.execute(
                "UPDATE users SET premium_until=? WHERE user_id=?",
                (premium_until, int(user_id)),
            )
            await conn.commit()
            return True, premium_until

    async def set_anon_plus_theme(self, user_id: int, theme: str) -> None:
        await self.db.execute(
            "UPDATE users SET anon_plus_theme=? WHERE user_id=?",
            (str(theme)[:24], int(user_id)),
        )
        await self.db.commit()

    async def set_anon_plus_identity(
        self, user_id: int, *, emoji: str | None = None,
        show_nick: bool | None = None,
    ) -> None:
        sets: list[str] = []
        values: list[Any] = []
        if emoji is not None:
            sets.append("anon_plus_emoji=?")
            values.append(str(emoji)[:24])
        if show_nick is not None:
            sets.append("anon_plus_show_nick=?")
            values.append(1 if show_nick else 0)
        if not sets:
            return
        values.append(int(user_id))
        await self.db.execute(
            f"UPDATE users SET {', '.join(sets)} WHERE user_id=?", values
        )
        await self.db.commit()
        self._top_cache.clear()

    async def adjust_anon_plus(self, user_id: int, days: int) -> int:
        """Совместимый админ-метод: любое положительное значение включает Plus навсегда, 0/минус выключает."""
        await self._ensure_row(int(user_id))
        premium_until = ANON_PLUS_LIFETIME_UNTIL if int(days) > 0 else 0
        await self.db.execute(
            "UPDATE users SET premium_until=? WHERE user_id=?",
            (premium_until, int(user_id)),
        )
        await self.db.commit()
        return premium_until

    async def create_sbp_order(
        self, *, order_id: str, user_id: int, kind: str,
        amount_rub: int, premium_days: int = 0,
    ) -> str:
        local_id = f"creating:{order_id}"
        await self.db.execute(
            """INSERT INTO sbp_payments
               (payment_id, order_id, user_id, kind, amount_rub, premium_days,
                status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'creating', ?)""",
            (
                local_id, str(order_id), int(user_id), str(kind),
                int(amount_rub), max(0, int(premium_days)), now(),
            ),
        )
        await self.db.commit()
        return local_id

    async def attach_sbp_provider_payment(
        self, local_id: str, payment_id: str, pay_url: str
    ) -> None:
        cur = await self.db.execute(
            """UPDATE sbp_payments
               SET payment_id=?, pay_url=?, status='awaiting_payment'
               WHERE payment_id=? AND status='creating'""",
            (str(payment_id), str(pay_url), str(local_id)),
        )
        if cur.rowcount != 1:
            raise ValueError("Local payment order is not attachable")
        await self.db.commit()

    async def get_sbp_payment(self, payment_id: str) -> dict[str, Any] | None:
        row = await self._fetchone(
            "SELECT * FROM sbp_payments WHERE payment_id=?",
            (str(payment_id),),
        )
        return dict(row) if row else None

    async def list_pending_sbp_payments(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            """SELECT * FROM sbp_payments
               WHERE status IN ('creating','awaiting_payment','pending','processing')
               ORDER BY created_at ASC LIMIT ?""",
            (max(1, min(int(limit), 300)),),
        )
        return [dict(row) for row in rows]

    async def set_sbp_status(self, payment_id: str, status: str) -> None:
        await self.db.execute(
            """UPDATE sbp_payments SET status=?
               WHERE payment_id=? AND status!='paid'""",
            (str(status or "")[:32], str(payment_id)),
        )
        await self.db.commit()

    async def settle_sbp_payment(self, payment_id: str) -> dict[str, Any]:
        ts = now()
        async with aiosqlite.connect(self.path, timeout=15.0) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("BEGIN IMMEDIATE")
            payment = await (await conn.execute(
                "SELECT * FROM sbp_payments WHERE payment_id=?", (str(payment_id),)
            )).fetchone()
            if payment is None:
                await conn.rollback()
                raise ValueError("Payment not found")
            user_id = int(payment["user_id"])
            user = await (await conn.execute(
                "SELECT premium_until FROM users WHERE user_id=?", (user_id,)
            )).fetchone()
            if user is None:
                await conn.rollback()
                raise ValueError("Payment user does not exist")
            if str(payment["status"]) == "paid":
                await conn.commit()
                return {
                    "fresh": False, "kind": str(payment["kind"]), "user_id": user_id,
                    "premium_until": int(user["premium_until"] or 0),
                }

            premium_until = int(user["premium_until"] or 0)
            if str(payment["kind"]) == "anonplus":
                premium_until = ANON_PLUS_LIFETIME_UNTIL
                await conn.execute(
                    "UPDATE users SET premium_until=? WHERE user_id=?",
                    (premium_until, user_id),
                )
            if str(payment["kind"]) == "support":
                await conn.execute(
                    "UPDATE users SET support_rub = support_rub + ? WHERE user_id=?",
                    (int(payment["amount_rub"]), user_id),
                )
            await conn.execute(
                "UPDATE sbp_payments SET status='paid', paid_at=? WHERE payment_id=?",
                (ts, str(payment_id)),
            )
            await conn.commit()
            return {
                "fresh": True, "kind": str(payment["kind"]), "user_id": user_id,
                "premium_until": premium_until,
                "amount_rub": int(payment["amount_rub"]),
            }

    async def payment_stats(self) -> dict[str, int]:
        star_rows = await self._fetchall(
            """SELECT kind, COUNT(*) AS count, COALESCE(SUM(stars), 0) AS total
               FROM payments GROUP BY kind"""
        )
        sbp_rows = await self._fetchall(
            """SELECT kind, COUNT(*) AS count, COALESCE(SUM(amount_rub), 0) AS total
               FROM sbp_payments WHERE status='paid' GROUP BY kind"""
        )
        result = {
            "anonplus_stars_count": 0, "anonplus_stars_total": 0,
            "support_stars_count": 0, "support_stars_total": 0,
            "anonplus_sbp_count": 0, "anonplus_sbp_total": 0,
            "support_sbp_count": 0, "support_sbp_total": 0,
            "anonplus_active": 0,
        }
        for row in star_rows:
            kind = str(row["kind"])
            if kind in {"anonplus", "support"}:
                result[f"{kind}_stars_count"] = int(row["count"] or 0)
                result[f"{kind}_stars_total"] = int(row["total"] or 0)
        for row in sbp_rows:
            kind = str(row["kind"])
            if kind in {"anonplus", "support"}:
                result[f"{kind}_sbp_count"] = int(row["count"] or 0)
                result[f"{kind}_sbp_total"] = int(row["total"] or 0)
        active = await self._fetchone(
            "SELECT COUNT(*) AS n FROM users WHERE premium_until > ?", (now(),)
        )
        result["anonplus_active"] = int(active["n"] or 0) if active else 0
        return result

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
        """Commit restriction and user notice atomically, including bot commands."""
        from .admin_events import enqueue
        await self._ensure_row(user_id)
        async with aiosqlite.connect(self.path, isolation_level=None) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA busy_timeout=10000")
            await conn.execute("BEGIN IMMEDIATE")
            try:
                async with conn.execute("SELECT banned,ban_reason FROM users WHERE user_id=?", (int(user_id),)) as cur:
                    prev = await cur.fetchone()
                if not prev:
                    raise ValueError("Пользователь не найден")
                changed = bool(prev["banned"]) != bool(banned) or (
                    bool(banned) and str(prev["ban_reason"] or "") != str(reason)
                )
                await conn.execute(
                    "UPDATE users SET banned=?,ban_reason=?,mute_until=0 WHERE user_id=?",
                    (int(banned), str(reason)[:500] if banned else "", int(user_id)),
                )
                if changed:
                    await enqueue(conn, user_id, "ban" if banned else "unban",
                                  reason=reason or "Решение модерации")
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise
        self._top_cache.clear()

    async def set_mute(self, user_id: int, minutes: int,
                       reason: str = "Решение модерации") -> int:
        from .admin_events import enqueue
        await self._ensure_row(user_id)
        until = now() + max(0, int(minutes)) * 60
        async with aiosqlite.connect(self.path, isolation_level=None) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA busy_timeout=10000")
            await conn.execute("BEGIN IMMEDIATE")
            try:
                async with conn.execute("SELECT mute_until FROM users WHERE user_id=?", (int(user_id),)) as cur:
                    prev = await cur.fetchone()
                if not prev:
                    raise ValueError("Пользователь не найден")
                before = int(prev["mute_until"] or 0)
                await conn.execute("UPDATE users SET mute_until=? WHERE user_id=?", (until, int(user_id)))
                if (int(minutes)>0 and before != until) or (int(minutes)<=0 and before>now()):
                    await enqueue(conn, user_id, "mute" if minutes>0 else "unmute",
                                  reason=reason, minutes=int(minutes), until=until)
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise
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

    async def excluded_partners(self, user_id: int, recent_seconds: int = 0) -> set[int]:
        """Только временно исключает недавно завершённые пары; вечных блокировок больше нет."""
        result: set[int] = set()
        if int(recent_seconds) > 0:
            cutoff = now() - int(recent_seconds)
            recent = await self._fetchall(
                """SELECT CASE WHEN user_a=? THEN user_b ELSE user_a END AS uid
                     FROM matches
                    WHERE ended_at IS NOT NULL
                      AND ended_at>=?
                      AND (user_a=? OR user_b=?)""",
                (user_id, cutoff, user_id, user_id),
            )
            result.update(int(row["uid"]) for row in recent)
        return result

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

    # --------------------------------------------------------- Mini App events/results
    async def add_miniapp_event(
        self,
        user_id: int,
        event_type: str,
        title: str,
        text: str = "",
        *,
        icon: str = "bell",
        action: str = "",
        commit: bool = True,
    ) -> int:
        cur = await self.db.execute(
            """INSERT INTO miniapp_events(user_id,type,icon,title,text,action,created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                int(user_id),
                str(event_type or "system")[:32],
                str(icon or "bell")[:32],
                str(title or "")[:120],
                str(text or "")[:500],
                str(action or "")[:120],
                now(),
            ),
        )
        # Keep the center compact; old events have no product value.
        await self.db.execute(
            """DELETE FROM miniapp_events
               WHERE user_id=? AND id NOT IN (
                   SELECT id FROM miniapp_events WHERE user_id=?
                   ORDER BY created_at DESC, id DESC LIMIT 120
               )""",
            (int(user_id), int(user_id)),
        )
        if commit:
            await self.db.commit()
        return int(cur.lastrowid)

    async def miniapp_events(
        self, user_id: int, *, limit: int = 60
    ) -> list[aiosqlite.Row]:
        return await self._fetchall(
            """SELECT * FROM miniapp_events WHERE user_id=?
               ORDER BY created_at DESC, id DESC LIMIT ?""",
            (int(user_id), max(1, min(int(limit), 120))),
        )

    async def read_miniapp_event(self, user_id: int, event_id: int) -> bool:
        cur = await self.db.execute(
            """UPDATE miniapp_events SET read_at=COALESCE(read_at,?)
               WHERE id=? AND user_id=?""",
            (now(), int(event_id), int(user_id)),
        )
        await self.db.commit()
        return bool(cur.rowcount)

    async def read_all_miniapp_events(self, user_id: int) -> int:
        cur = await self.db.execute(
            "UPDATE miniapp_events SET read_at=? WHERE user_id=? AND read_at IS NULL",
            (now(), int(user_id)),
        )
        await self.db.commit()
        return int(cur.rowcount or 0)

    async def save_dialog_result(
        self,
        user_id: int,
        match_id: int,
        partner_id: int,
        *,
        started_at: int,
        duration: int,
        sent: int,
        received: int,
        earned: int,
        games: list[dict[str, Any]] | None = None,
    ) -> None:
        await self.db.execute(
            """INSERT INTO miniapp_dialog_results(
                   user_id,match_id,partner_id,created_at,started_at,duration,
                   sent,received,earned,games,rated
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
               ON CONFLICT(user_id) DO UPDATE SET
                   match_id=excluded.match_id,
                   partner_id=excluded.partner_id,
                   created_at=excluded.created_at,
                   started_at=excluded.started_at,
                   duration=excluded.duration,
                   sent=excluded.sent,
                   received=excluded.received,
                   earned=excluded.earned,
                   games=excluded.games,
                   rated=0""",
            (
                int(user_id), int(match_id), int(partner_id), now(),
                int(started_at), max(0, int(duration)), max(0, int(sent)),
                max(0, int(received)), max(0, int(earned)),
                json.dumps(games or [], ensure_ascii=False, separators=(",", ":")),
            ),
        )
        await self.db.commit()

    async def dialog_result(self, user_id: int) -> aiosqlite.Row | None:
        row = await self._fetchone(
            "SELECT * FROM miniapp_dialog_results WHERE user_id=?",
            (int(user_id),),
        )
        if row is not None and int(row["created_at"] or 0) < now() - 86_400:
            await self.db.execute(
                "DELETE FROM miniapp_dialog_results WHERE user_id=?",
                (int(user_id),),
            )
            await self.db.commit()
            return None
        return row

    async def mark_dialog_result_rated(self, user_id: int) -> None:
        await self.db.execute(
            "UPDATE miniapp_dialog_results SET rated=1 WHERE user_id=?",
            (int(user_id),),
        )
        await self.db.commit()

    # ------------------------------------------------------------------ dialogs
    async def log_dialog(
        self, user_a: int, user_b: int, msg_a: int, msg_b: int, started_at: int,
        ended_by: int | None, *, count_dialog: bool = True, commit: bool = True,
    ) -> int:
        cur = await self.db.execute(
            """INSERT INTO matches (started_at, ended_at, user_a, user_b, msg_a, msg_b, ended_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (started_at, now(), user_a, user_b, msg_a, msg_b, ended_by),
        )
        if count_dialog:
            await self.db.execute(
                "UPDATE users SET dialogs = dialogs + 1 WHERE user_id IN (?, ?)", (user_a, user_b)
            )
        if commit:
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

    # ------------------------------------------------------------------ engagement
    async def engagement_state(self, user_id: int, *, commit: bool = True) -> aiosqlite.Row:
        await self.db.execute(
            "INSERT OR IGNORE INTO user_engagement(user_id) VALUES (?)",
            (int(user_id),),
        )
        if commit:
            await self.db.commit()
        row = await self._fetchone(
            "SELECT * FROM user_engagement WHERE user_id=?", (int(user_id),)
        )
        assert row is not None
        return row

    async def activity_add(
        self, user_id: int, timestamp: int | None = None, *, commit: bool = True, **deltas: int
    ) -> None:
        allowed = {
            "messages", "dialogs", "games", "battle_games", "number_games",
            "ratings_given", "good_ratings", "battle_matches", "battle_questions",
            "number_exact", "xp_earned",
        }
        values = {k: int(v) for k, v in deltas.items() if k in allowed and int(v)}
        if not values:
            return
        day = referral_day_start(timestamp)
        cols = ["user_id", "day_start", *values]
        params = [int(user_id), day, *values.values()]
        updates = ", ".join(f"{key}={key}+excluded.{key}" for key in values)
        await self.db.execute(
            f"INSERT INTO daily_activity({', '.join(cols)}) "
            f"VALUES ({','.join('?' for _ in cols)}) "
            f"ON CONFLICT(user_id, day_start) DO UPDATE SET {updates}",
            params,
        )
        if commit:
            await self.db.commit()
        if 'xp_earned' in values:
            self._top_cache.clear()

    async def activity_totals(self, user_id: int, days: int) -> dict[str, int]:
        days = max(1, min(int(days), 40))
        start = referral_day_start() - (days - 1) * 86_400
        row = await self._fetchone(
            """SELECT COALESCE(SUM(messages),0) messages,
                      COALESCE(SUM(dialogs),0) dialogs,
                      COALESCE(SUM(games),0) games,
                      COALESCE(SUM(battle_games),0) battle_games,
                      COALESCE(SUM(number_games),0) number_games,
                      COALESCE(SUM(ratings_given),0) ratings_given,
                      COALESCE(SUM(good_ratings),0) good_ratings,
                      COALESCE(SUM(battle_matches),0) battle_matches,
                      COALESCE(SUM(battle_questions),0) battle_questions,
                      COALESCE(SUM(number_exact),0) number_exact,
                      COALESCE(SUM(xp_earned),0) xp_earned
                 FROM daily_activity
                WHERE user_id=? AND day_start>=?""",
            (int(user_id), start),
        )
        return {key: int(row[key] or 0) for key in row.keys()} if row else {}

    def _period_start(self, days: int) -> int:
        return (
            week_period_start() if days == 7
            else month_period_start() if days == 30
            else referral_day_start() - (max(1, days) - 1) * 86_400
        )

    @staticmethod
    def _period_scores_sql() -> str:
        """Единые очки в Telegram и API; списания учитываются отдельно от daily_activity."""
        return """
            WITH activity AS (
                SELECT user_id, SUM(xp_earned) credits, SUM(dialogs) dialogs,
                       SUM(messages) messages
                  FROM daily_activity WHERE day_start >= ? GROUP BY user_id
            ), deductions AS (
                SELECT user_id, SUM(amount) debits
                  FROM xp_transactions
                 WHERE created_at >= ? AND amount < 0 AND source <> 'referral_correction'
                 GROUP BY user_id
            ), scores AS (
                SELECT u.user_id, u.nickname, u.support_stars,
                       u.premium_until, u.anon_plus_emoji, u.support_rub,
                       COALESCE(a.credits,0) + COALESCE(d.debits,0) xp,
                       COALESCE(a.dialogs,0) dialogs,
                       COALESCE(a.messages,0) messages
                  FROM users u
                  LEFT JOIN activity a ON a.user_id=u.user_id
                  LEFT JOIN deductions d ON d.user_id=u.user_id
                 WHERE u.banned=0 AND (
                       COALESCE(a.credits,0)>0 OR COALESCE(a.dialogs,0)>0
                       OR COALESCE(a.messages,0)>0
                 )
            )
        """

    async def top_period(self, days: int, limit: int = 10) -> list[aiosqlite.Row]:
        days = int(days)
        limit = max(1, min(int(limit), 50))
        key = (days, limit, self._period_start(days) if days > 0 else 0)
        cached = self._top_cache.get(key)
        now_mono = time.monotonic()
        if cached is not None and now_mono - cached[0] < 15:
            return cached[1]
        if days <= 0:
            rows = await self.top(limit)
        else:
            start = self._period_start(days)
            rows = await self._fetchall(
                self._period_scores_sql() +
                "SELECT * FROM scores ORDER BY xp DESC, dialogs DESC, messages DESC, user_id ASC LIMIT ?",
                (start, start, limit),
            )
        self._top_cache[key] = (now_mono, rows)
        if len(self._top_cache) > 12:
            self._top_cache = {k:v for k,v in self._top_cache.items() if now_mono-v[0]<30}
        return rows

    async def top_position_period(self, user_id: int, days: int) -> dict[str, int]:
        uid = int(user_id)
        if not await self.get_user(uid):
            return {"place": 0, "stars": 0, "to_top10": 0}
        if int(days) <= 0:
            ranked_sql = """
                SELECT user_id, xp, ROW_NUMBER() OVER (
                    ORDER BY xp DESC, dialogs DESC, messages DESC, user_id ASC
                ) AS place FROM users WHERE banned=0
            """
            row = await self._fetchone(
                f"SELECT place,xp FROM ({ranked_sql}) WHERE user_id=?", (uid,),
            )
            top10 = await self.top(10)
        else:
            start = self._period_start(int(days))
            ranked_sql = self._period_scores_sql() + """
                SELECT user_id, xp, ROW_NUMBER() OVER (
                    ORDER BY xp DESC, dialogs DESC, messages DESC, user_id ASC
                ) AS place FROM scores
            """
            row = await self._fetchone(
                f"SELECT place,xp FROM ({ranked_sql}) WHERE user_id=?",
                (start, start, uid),
            )
            top10 = await self.top_period(days, 10)
        place = int(row["place"] or 0) if row else 0
        stars = int(row["xp"] or 0) if row else 0
        threshold = int(top10[-1]["xp"] or 0) if len(top10) >= 10 else 0
        return {
            "place": place,
            "stars": stars,
            "to_top10": max(0, threshold - stars + (1 if place > 10 and threshold >= stars else 0)),
        }

    async def update_streak(
        self, user_id: int, timestamp: int | None = None, *, commit: bool = True
    ) -> tuple[int, int]:
        day = referral_day_start(timestamp)
        async with self._engagement_lock:
            row = await self.engagement_state(user_id, commit=commit)
            last = int(row["last_active_day"] or 0)
            current = int(row["current_streak"] or 0)
            best = int(row["best_streak"] or 0)
            if last == day:
                return current, best
            current = current + 1 if last == day - 86_400 else 1
            best = max(best, current)
            await self.db.execute(
                """UPDATE user_engagement
                      SET current_streak=?, best_streak=?, last_active_day=?
                    WHERE user_id=?""",
                (current, best, day, int(user_id)),
            )
            if commit:
                await self.db.commit()
            return current, best

    async def record_dialog_engagement(self, user_id: int, *, commit: bool = True) -> None:
        await self.engagement_state(user_id, commit=commit)
        await self.db.execute(
            "UPDATE user_engagement SET dialogs_total=dialogs_total+1 WHERE user_id=?",
            (int(user_id),),
        )
        if commit:
            await self.db.commit()

    async def record_game_engagement(
        self, user_id: int, kind: str, matches: int = 0, total: int = 0,
        number_exact: int = 0, range_max: int = 0,
    ) -> None:
        await self.engagement_state(user_id)
        battle5 = int(kind == "battle" and total == 5 and matches == 5)
        battle10 = int(kind == "battle" and total == 10 and matches == 10)
        exact1000 = int(kind == "numbers" and range_max == 1000 and number_exact > 0)
        await self.db.execute(
            """UPDATE user_engagement
                  SET games_total=games_total+1,
                      battle_games_total=battle_games_total+?,
                      number_games_total=number_games_total+?,
                      battle_perfect_5=battle_perfect_5+?,
                      battle_perfect_10=battle_perfect_10+?,
                      number_exact_1000=number_exact_1000+?
                WHERE user_id=?""",
            (
                int(kind == "battle"), int(kind == "numbers"),
                battle5, battle10, exact1000, int(user_id),
            ),
        )
        day = referral_day_start()
        await self.db.execute(
            """INSERT INTO daily_activity(
                   user_id, day_start, games, battle_games, number_games,
                   battle_matches, battle_questions, number_exact
               ) VALUES (?, ?, 1, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, day_start) DO UPDATE SET
                   games=games+1,
                   battle_games=battle_games+excluded.battle_games,
                   number_games=number_games+excluded.number_games,
                   battle_matches=battle_matches+excluded.battle_matches,
                   battle_questions=battle_questions+excluded.battle_questions,
                   number_exact=number_exact+excluded.number_exact""",
            (
                int(user_id), day, int(kind == "battle"), int(kind == "numbers"),
                int(matches if kind == "battle" else 0),
                int(total if kind == "battle" else 0),
                int(number_exact if kind == "numbers" else 0),
            ),
        )
        await self.db.commit()

    async def unlock_achievement(self, user_id: int, key: str, reward: int) -> bool:
        async with self._engagement_lock:
            row = await self.engagement_state(user_id)
            try:
                unlocked = set(json.loads(str(row["achievements"] or "[]")))
            except (json.JSONDecodeError, TypeError):
                unlocked = set()
            if key in unlocked:
                return False
            unlocked.add(str(key))
            reward = await self.effective_xp_reward(reward)
            await self.db.execute(
                "UPDATE user_engagement SET achievements=? WHERE user_id=?",
                (json.dumps(sorted(unlocked), ensure_ascii=False), int(user_id)),
            )
            if reward:
                await self.db.execute(
                    "UPDATE users SET xp=xp+?, xp_source='achievement', xp_reason=? WHERE user_id=?",
                    (reward, str(key), int(user_id))
                )
                day = referral_day_start()
                await self.db.execute(
                    """INSERT INTO daily_activity(user_id, day_start, xp_earned)
                       VALUES (?, ?, ?)
                       ON CONFLICT(user_id, day_start)
                       DO UPDATE SET xp_earned=xp_earned+excluded.xp_earned""",
                    (int(user_id), day, reward),
                )
            await self.db.commit()
            self._top_cache.clear()
            return True

    async def daily_quest_claimed(self, user_id: int, day: int | None = None) -> set[str]:
        day = referral_day_start() if day is None else int(day)
        row = await self.engagement_state(user_id)
        if int(row["quest_day"] or 0) != day:
            return set()
        try:
            return set(json.loads(str(row["quest_claimed"] or "[]")))
        except (json.JSONDecodeError, TypeError):
            return set()

    async def claim_daily_quest(
        self, user_id: int, day: int, quest_key: str, reward: int
    ) -> bool:
        async with self._engagement_lock:
            row = await self.engagement_state(user_id)
            claimed: set[str] = set()
            if int(row["quest_day"] or 0) == int(day):
                try:
                    claimed = set(json.loads(str(row["quest_claimed"] or "[]")))
                except (json.JSONDecodeError, TypeError):
                    claimed = set()
            if quest_key in claimed:
                return False
            claimed.add(str(quest_key))
            reward = await self.effective_xp_reward(reward)
            await self.db.execute(
                """UPDATE user_engagement SET quest_day=?, quest_claimed=?
                    WHERE user_id=?""",
                (int(day), json.dumps(sorted(claimed), ensure_ascii=False), int(user_id)),
            )
            if reward:
                await self.db.execute(
                    "UPDATE users SET xp=xp+?, xp_source='daily_quest', xp_reason=? WHERE user_id=?",
                    (reward, str(quest_key), int(user_id))
                )
                await self.db.execute(
                    """INSERT INTO daily_activity(user_id, day_start, xp_earned)
                       VALUES (?, ?, ?)
                       ON CONFLICT(user_id, day_start)
                       DO UPDATE SET xp_earned=xp_earned+excluded.xp_earned""",
                    (int(user_id), int(day), reward),
                )
            await self.db.commit()
            self._top_cache.clear()
            return True

    async def cleanup_daily_activity(self, retention_days: int = 40) -> int:
        cutoff = referral_day_start() - (max(2, int(retention_days)) - 1) * 86_400
        cur = await self.db.execute(
            "DELETE FROM daily_activity WHERE day_start < ?", (cutoff,)
        )
        await self.db.commit()
        return int(cur.rowcount or 0)

    async def cleanup_service_data(self) -> dict[str, int]:
        """Редкая безопасная чистка служебной истории, не затрагивающая профили и активные данные."""
        ts = now()
        old_matches = await self.db.execute(
            "DELETE FROM matches WHERE ended_at IS NOT NULL AND ended_at < ?",
            (ts - 90 * 86_400,),
        )
        old_reports = await self.db.execute(
            """DELETE FROM reports
               WHERE status='done' AND handled_at IS NOT NULL AND handled_at < ?""",
            (ts - 90 * 86_400,),
        )
        await self.db.execute(
            "DELETE FROM anonymous_reply_routes WHERE created_at < ?",
            (ts - 30 * 86_400,),
        )
        old_poll_ids = [
            int(row["id"]) for row in await self._fetchall(
                "SELECT id FROM polls WHERE active=0 AND closed_at IS NOT NULL AND closed_at < ?",
                (ts - 30 * 86_400,),
            )
        ]
        poll_votes = 0
        polls = 0
        if old_poll_ids:
            for offset in range(0, len(old_poll_ids), 400):
                chunk = old_poll_ids[offset:offset + 400]
                marks = ",".join("?" for _ in chunk)
                cur_votes = await self.db.execute(
                    f"DELETE FROM poll_votes WHERE poll_id IN ({marks})", tuple(chunk)
                )
                cur_polls = await self.db.execute(
                    f"DELETE FROM polls WHERE id IN ({marks})", tuple(chunk)
                )
                poll_votes += int(cur_votes.rowcount or 0)
                polls += int(cur_polls.rowcount or 0)
        await self.db.commit()
        return {
            "matches": int(old_matches.rowcount or 0),
            "reports": int(old_reports.rowcount or 0),
            "polls": polls,
            "poll_votes": poll_votes,
        }

    async def game_diagnostics(self) -> dict[str, int]:
        cutoff = now() - GAME_INACTIVE_TTL_SECONDS
        row = await self._fetchone(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN game_type='battle' THEN 1 ELSE 0 END) battle,
                      SUM(CASE WHEN game_type='numbers' THEN 1 ELSE 0 END) numbers,
                      SUM(CASE WHEN game_type='geo' THEN 1 ELSE 0 END) geo,
                      SUM(CASE WHEN updated_at<=? THEN 1 ELSE 0 END) stale
                 FROM battle_games
                WHERE status IN ('invited','active','round_done')""",
            (cutoff,),
        )
        return {
            "total": int(row["total"] or 0) if row else 0,
            "battle": int(row["battle"] or 0) if row else 0,
            "numbers": int(row["numbers"] or 0) if row else 0,
            "geo": int(row["geo"] or 0) if row else 0,
            "stale": int(row["stale"] or 0) if row else 0,
        }

    async def online_peak(self, current: int) -> int:
        day = referral_day_start()
        raw_day = await self.get_kv("online_peak_day")
        raw_value = await self.get_kv("online_peak_value")
        saved_day = int(raw_day) if raw_day.isdigit() else 0
        peak = int(raw_value) if raw_value.isdigit() else 0
        if saved_day != day:
            peak = max(0, int(current))
            await self.set_kv("online_peak_day", str(day))
            await self.set_kv("online_peak_value", str(peak))
        elif int(current) > peak:
            peak = int(current)
            await self.set_kv("online_peak_value", str(peak))
        return peak

    # ------------------------------------------------------------------ stats
    async def active_ids(self, days: int = 7, limit: int = 100000) -> list[int]:
        rows = await self._fetchall(
            "SELECT user_id FROM users WHERE banned = 0 AND last_seen > ? ORDER BY last_seen DESC LIMIT ?",
            (now() - days * 86400, limit),
        )
        return [int(r["user_id"]) for r in rows]


    async def broadcast_ids(
        self, limit: int = 100000, *, exclude_anon_plus: bool = False
    ) -> list[int]:
        """Получатели массовой рассылки. Рекламу можно исключить для Анон Plus."""
        limit = max(1, min(int(limit), 100000))
        if exclude_anon_plus:
            rows = await self._fetchall(
                """SELECT user_id FROM users
                   WHERE banned = 0 AND premium_until <= ?
                   ORDER BY last_seen DESC LIMIT ?""",
                (now(), limit),
            )
        else:
            rows = await self._fetchall(
                "SELECT user_id FROM users WHERE banned = 0 ORDER BY last_seen DESC LIMIT ?",
                (limit,),
            )
        return [int(r["user_id"]) for r in rows]

    async def stats(self) -> dict[str, Any]:
        total = await self._fetchone("SELECT COUNT(*) AS c FROM users")
        week = await self._fetchone(
            "SELECT COUNT(*) AS c FROM users WHERE last_seen > ?", (now() - 7 * 86400,)
        )
        today = await self._fetchone(
            "SELECT COUNT(*) AS c FROM users WHERE created_at >= ?", (referral_day_start(),)
        )
        dialogs = await self._fetchone("SELECT COUNT(*) AS c FROM matches")
        msgs = await self._fetchone("SELECT COALESCE(SUM(messages), 0) AS c FROM users")
        open_reports = await self._fetchone(
            "SELECT COUNT(*) AS c FROM reports WHERE status = 'new'"
        )
        active_today = await self._fetchone(
            "SELECT COUNT(*) AS c FROM users WHERE last_seen>=?", (referral_day_start(),)
        )
        banned = await self._fetchone("SELECT COUNT(*) AS c FROM users WHERE banned=1")
        muted = await self._fetchone(
            "SELECT COUNT(*) AS c FROM users WHERE mute_until>?", (now(),)
        )
        awarded = await self._fetchone(
            "SELECT COALESCE(SUM(amount),0) AS c FROM xp_transactions "
            "WHERE amount>0 AND source<>'opening_balance' AND created_at>=?",
            (referral_day_start(),)
        )
        return {
            "active_today": int(active_today["c"]) if active_today else 0,
            "banned": int(banned["c"]) if banned else 0,
            "muted": int(muted["c"]) if muted else 0,
            "xp_today": int(awarded["c"]) if awarded else 0,
            "users": int(total["c"]) if total else 0,
            "new_today": int(today["c"]) if today else 0,
            "active_week": int(week["c"]) if week else 0,
            "dialogs": int(dialogs["c"]) if dialogs else 0,
            "messages": int(msgs["c"]) if msgs else 0,
            "open_reports": int(open_reports["c"]) if open_reports else 0,
        }

    async def top(self, limit: int = 10) -> list[aiosqlite.Row]:
        """Активность с упором на диалоги и оценки; спам в одном чате быстро упирается в лимит."""
        return await self._fetchall(
            """SELECT user_id, nickname, messages, xp, dialogs, good_ratings,
                      support_stars, support_rub, premium_until, anon_plus_emoji
               FROM users WHERE banned = 0
               ORDER BY xp DESC, dialogs DESC, messages DESC, user_id ASC LIMIT ?""",
            (limit,),
        )

    # ------------------------------------------------------------------ events / polls
    async def xp_multiplier(self) -> int:
        """Эффективный множитель: Пн/Ср/Пт по Магнитогорску автоматически не ниже x2."""
        if self._xp_multiplier_cache in {1, 2, 3}:
            manual = int(self._xp_multiplier_cache)
        else:
            raw = await self.get_kv("xp_multiplier", "1")
            manual = int(raw) if str(raw).isdigit() and int(raw) in {1, 2, 3} else 1
            self._xp_multiplier_cache = manual

        # UTC+5: Monday=0, Wednesday=2, Friday=4.
        mgn_weekday = time.gmtime(now() + REFERRAL_TIMEZONE_OFFSET).tm_wday
        scheduled = 2 if mgn_weekday in {0, 2, 4} else 1
        return max(manual, scheduled)

    async def set_xp_multiplier(self, value: int) -> int:
        value = int(value)
        if value not in {1, 2, 3}:
            raise ValueError("Множитель может быть только x1, x2 или x3")
        self._xp_multiplier_cache = value
        await self.set_kv("xp_multiplier", str(value))
        return await self.xp_multiplier()

    async def create_poll(
        self, question: str, option_a: str, option_b: str, created_by: int
    ) -> int:
        question = str(question or "").strip()[:250]
        option_a = str(option_a or "").strip()[:48]
        option_b = str(option_b or "").strip()[:48]
        if not question or not option_a or not option_b:
            raise ValueError("Вопрос и оба варианта обязательны")
        ts = now()
        await self.db.execute(
            "UPDATE polls SET active=0, closed_at=? WHERE active=1", (ts,)
        )
        cur = await self.db.execute(
            """INSERT INTO polls(question, option_a, option_b, active, created_by, created_at)
               VALUES (?, ?, ?, 1, ?, ?)""",
            (question, option_a, option_b, int(created_by), ts),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def active_poll(self) -> aiosqlite.Row | None:
        return await self._fetchone(
            "SELECT * FROM polls WHERE active=1 ORDER BY id DESC LIMIT 1"
        )

    async def close_active_poll(self) -> bool:
        cur = await self.db.execute(
            "UPDATE polls SET active=0, closed_at=? WHERE active=1", (now(),)
        )
        await self.db.commit()
        return bool(cur.rowcount)

    async def vote_poll(self, poll_id: int, user_id: int, choice: int) -> bool:
        if int(choice) not in {0, 1}:
            return False
        poll = await self._fetchone(
            "SELECT id FROM polls WHERE id=? AND active=1", (int(poll_id),)
        )
        if poll is None:
            return False
        ts = now()
        await self.db.execute(
            """INSERT INTO poll_votes(poll_id, user_id, choice, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(poll_id, user_id) DO UPDATE SET
                   choice=excluded.choice, updated_at=excluded.updated_at""",
            (int(poll_id), int(user_id), int(choice), ts, ts),
        )
        await self.db.commit()
        return True

    async def poll_vote_for(self, poll_id: int, user_id: int) -> int | None:
        row = await self._fetchone(
            "SELECT choice FROM poll_votes WHERE poll_id=? AND user_id=?",
            (int(poll_id), int(user_id)),
        )
        return int(row["choice"]) if row is not None else None

    async def poll_results(self, poll_id: int) -> dict[str, int]:
        row = await self._fetchone(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN choice=0 THEN 1 ELSE 0 END) AS a,
                      SUM(CASE WHEN choice=1 THEN 1 ELSE 0 END) AS b
                 FROM poll_votes WHERE poll_id=?""",
            (int(poll_id),),
        )
        total = int(row["total"] or 0) if row else 0
        a = int(row["a"] or 0) if row else 0
        b = int(row["b"] or 0) if row else 0
        if total <= 0:
            return {"total": 0, "a": 0, "b": 0, "pct_a": 0, "pct_b": 0}
        pct_a = round(a * 100 / total)
        return {"total": total, "a": a, "b": b, "pct_a": pct_a, "pct_b": 100 - pct_a}

    async def poll_voters(self, poll_id: int, limit: int = 200) -> list[aiosqlite.Row]:
        return await self._fetchall(
            """SELECT v.user_id, v.choice, v.updated_at,
                      u.nickname, u.username, u.first_name, u.support_stars
                 FROM poll_votes v
                 LEFT JOIN users u ON u.user_id=v.user_id
                WHERE v.poll_id=?
                ORDER BY v.updated_at DESC LIMIT ?""",
            (int(poll_id), max(1, min(int(limit), 500))),
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

    async def anonymous_question_token(self, user_id: int) -> str:
        """Постоянный короткий код пользователя для ссылки на анонимные вопросы."""
        user_key = f"anonq:user:{int(user_id)}"
        current = await self.get_kv(user_key)
        if current:
            return current

        alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        async with self._anon_question_lock:
            current = await self.get_kv(user_key)
            if current:
                return current

            for _ in range(32):
                token = "".join(secrets.choice(alphabet) for _ in range(6))
                token_key = f"anonq:token:{token}"
                if await self.get_kv(token_key):
                    continue
                await self.db.execute(
                    "INSERT INTO kv (key, value) VALUES (?, ?), (?, ?)",
                    (
                        user_key, token,
                        token_key, str(int(user_id)),
                    ),
                )
                await self.db.commit()
                return token

        raise RuntimeError("Не удалось создать короткую ссылку анонимных вопросов")

    async def anonymous_question_user(self, token: str) -> int | None:
        """Разрешает короткий код обратно в Telegram user_id."""
        value = str(token or "").strip()
        if len(value) != 6 or not value.isalnum():
            return None
        raw = await self.get_kv(f"anonq:token:{value}")
        return int(raw) if raw.isdigit() else None

    async def remember_anonymous_reply(
        self, recipient_id: int, message_id: int, target_id: int
    ) -> None:
        """Запоминает, кому отправить свайп-ответ на конкретную анонимку."""
        await self.db.execute(
            """INSERT INTO anonymous_reply_routes(
                   recipient_id, message_id, target_id, created_at
               ) VALUES (?, ?, ?, ?)
               ON CONFLICT(recipient_id, message_id)
               DO UPDATE SET target_id=excluded.target_id, created_at=excluded.created_at""",
            (int(recipient_id), int(message_id), int(target_id), now()),
        )

    async def anonymous_reply_target(
        self, recipient_id: int, message_id: int
    ) -> int | None:
        row = await self._fetchone(
            """SELECT target_id FROM anonymous_reply_routes
               WHERE recipient_id=? AND message_id=? LIMIT 1""",
            (int(recipient_id), int(message_id)),
        )
        return int(row["target_id"]) if row else None

    async def save_matchmaker(self, state: dict[str, Any]) -> None:
        await self.set_kv(
            "matchmaker_state",
            json.dumps(state, ensure_ascii=False, separators=(",", ":")),
        )
        from .diagnostics import METRICS
        METRICS.last_matchmaker_save_at = now()

    def schedule_matchmaker_save(self, matchmaker) -> None:
        """Дешёвый debounce: на каждом апдейте сравниваем только integer revision.

        Snapshot не сериализуется и SQLite не пишется на каждое сообщение. При
        активном чате изменения сбрасываются каждые 0.3 секунды.
        """
        revision = int(getattr(matchmaker, "persistence_revision", 0))
        if revision == self._matchmaker_revision:
            return
        self._matchmaker_revision = revision
        self._matchmaker = matchmaker
        self._matchmaker_dirty = True
        if self._matchmaker_task is None or self._matchmaker_task.done():
            self._matchmaker_task = asyncio.create_task(self._save_matchmaker_loop())

    async def _save_matchmaker_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(0.3)
                self._matchmaker_dirty = False
                if self._matchmaker is not None:
                    state = self._matchmaker.snapshot()
                    try:
                        await self.save_matchmaker(state)
                    except Exception:
                        logging.getLogger(__name__).exception(
                            "Matchmaker persistence failed; retrying instead of losing the revision"
                        )
                        self._matchmaker_dirty = True
                        await asyncio.sleep(2)
                        continue
                    self._matchmaker_snapshot_key = json.dumps(
                        state, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                    )
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
        self._matchmaker_revision = 0
        try:
            state = json.loads(value)
        except json.JSONDecodeError:
            return None
        if not isinstance(state, dict):
            return None

        # Старые версии клали последние сообщения пары в snapshot. Удаляем их
        # с диска сразу при старте; контекст жалобы теперь живёт только в RAM.
        sanitized = False
        for pair in state.get("pairs", []):
            if isinstance(pair, dict) and "history" in pair:
                pair.pop("history", None)
                sanitized = True
        if sanitized:
            await self.save_matchmaker(state)
            self._matchmaker_snapshot_key = json.dumps(
                state, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
        return state

    async def delete_kv(self, key: str) -> None:
        await self.db.execute("DELETE FROM kv WHERE key = ?", (key,))
        await self.db.commit()

    async def bump(
        self, user_id: int, column: str, amount: int = 1, *, commit: bool = True
    ) -> None:
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
        if commit:
            await self.db.commit()

    async def adjust_xp(self, user_id: int, amount: int) -> int:
        await self._ensure_row(user_id)
        await self.db.execute(
            "UPDATE users SET xp = MAX(0, xp + ?), xp_source='admin_legacy' WHERE user_id = ?", (int(amount), user_id)
        )
        await self.db.commit()
        self._top_cache.clear()
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
        anon_token = await self.get_kv(f"anonq:user:{int(user_id)}")
        row = await self.get_user(user_id)
        restricted = bool(row and (row["banned"] or int(row["mute_until"] or 0) > now()))
        if restricted:
            await self.db.execute(
                """UPDATE users SET username=NULL, first_name='Удалённый пользователь', nickname='',
                   nick_key='', age=0, xp=0, messages=0, dialogs=0, good_ratings=0,
                   bad_ratings=0, reports_sent=0, district='', gender='', looking_for='', same_district=0,
                   about='', last_seen=0, premium_until=0, anon_plus_theme='pink',
                   anon_plus_emoji='', anon_plus_show_nick=0, support_stars=0,
                   support_rub=0, profile_deleted=1 WHERE user_id=?""",
                (user_id,),
            )
        else:
            await self.db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))

        # Служебные данные игр не являются модерационными доказательствами и не должны
        # переживать удаление профиля.
        await self.db.execute(
            "DELETE FROM number_daily_rewards WHERE user_id = ?",
            (user_id,),
        )
        await self.db.execute(
            "DELETE FROM number_game_pairs WHERE user_low = ? OR user_high = ?",
            (user_id, user_id),
        )
        await self.db.execute(
            "DELETE FROM word_game_rewards WHERE user_id = ? OR partner_id = ?",
            (user_id, user_id),
        )
        await self.db.execute(
            "DELETE FROM geo_daily_rewards WHERE user_id = ?",
            (user_id,),
        )
        await self.db.execute(
            "DELETE FROM geo_game_pairs WHERE user_low = ? OR user_high = ?",
            (user_id, user_id),
        )
        await self.db.execute(
            "DELETE FROM battle_games WHERE user_a = ? OR user_b = ?",
            (user_id, user_id),
        )
        await self.db.execute(
            "DELETE FROM active_chat_events WHERE user_low = ? OR user_high = ?",
            (user_id, user_id),
        )
        await self.db.execute(
            "DELETE FROM miniapp_events WHERE user_id = ?",
            (user_id,),
        )
        await self.db.execute(
            "DELETE FROM miniapp_dialog_results WHERE user_id = ?",
            (user_id,),
        )
        await self.db.execute("DELETE FROM daily_activity WHERE user_id=?", (user_id,))
        await self.db.execute("DELETE FROM user_engagement WHERE user_id=?", (user_id,))
        await self.db.execute(
            "DELETE FROM anonymous_reply_routes WHERE recipient_id=? OR target_id=?",
            (user_id, user_id),
        )
        # Короткая ссылка анонимных вопросов относится к профилю и после удаления
        # не должна продолжать разрешаться обратно в Telegram ID.
        await self.db.execute("DELETE FROM kv WHERE key=?", (f"anonq:user:{int(user_id)}",))
        if anon_token:
            await self.db.execute("DELETE FROM kv WHERE key=?", (f"anonq:token:{anon_token}",))
        # История диалогов/жалоб нужна для блокировок и открытой модерации; личные поля там не хранятся.
        await self.db.commit()
        self._top_cache.clear()

    async def find_user_ids(self, name: str, limit: int = 10) -> list[aiosqlite.Row]:
        like = f"%{name.lstrip('@')}%"
        return await self._fetchall(
            "SELECT user_id, username, first_name, nickname, messages, xp, dialogs, reports_received, "
            "banned, support_stars "
            "FROM users "
            "WHERE username LIKE ? OR first_name LIKE ? OR nickname LIKE ? LIMIT ?",
            (like, like, like, limit),
        )
