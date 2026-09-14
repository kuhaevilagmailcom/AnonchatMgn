"""Настройки бота: читаются из переменных окружения либо из файла .env."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

#: панели хостинга называют переменную с токеном по-разному — принимаем любой вариант
_TOKEN_KEYS = ("BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN", "BOT_KEY", "TOKEN")


def _load_dotenv(path: Path) -> None:
    """Мини-загрузчик .env без внешних зависимостей."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _parse_ids(raw: str) -> tuple[int, ...]:
    ids = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip().lstrip("@")
        if chunk.lstrip("-").isdigit():
            ids.append(int(chunk))
    return tuple(ids)


def _find_token(cli: str | None = None) -> str:
    if cli and ":" in cli:
        return cli.strip()
    for key in _TOKEN_KEYS:
        value = os.getenv(key, "").strip()
        if value:
            return value
    raise RuntimeError(
        "Не найден токен бота. Задай переменную окружения BOT_TOKEN (поддерживаются также "
        "TELEGRAM_BOT_TOKEN / TELEGRAM_TOKEN) или положи токен вторым аргументом: python main.py <токен>"
    )


def _pick_db_path(raw: str) -> Path:
    """Там, где файловая система READ ONLY (некоторые панели), пишем во временный каталог."""
    path = Path(raw)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        probe = path.parent / ".anonchat_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return path
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "anonchat_mgn.db"
        print(f"[anonchat] {path} недоступен для записи, беру {fallback}")
        return fallback


@dataclass(slots=True)
class Config:
    bot_token: str
    admin_ids: tuple[int, ...] = ()
    db_path: Path = Path("data/anonchat_mgn.db")

    # branded stuff
    city: str = "Магнитогорск"
    city_short: str = "МГН"
    emoji_pack_url: str = "https://t.me/addemoji/NewsEmoji"

    # limits
    max_message_len: int = 3000
    inchat_rate_limit: int = 30          # сообщений в минуту внутри диалога
    menu_rate_limit: int = 12            # команд/нажатий в минуту
    auto_mute_reports: int = 3           # жалоб за сутки -> авто-мут
    auto_mute_minutes: int = 60

    # matching
    queue_soft_limit: int = 500          # сколько максимум держим в очереди
    xp_per_message: int = 1
    xp_message_cap: int = 40             # максимум «за сообщения» с одного диалога
    xp_per_dialog: int = 8
    xp_good_rating: int = 15

    debug: bool = False

    @classmethod
    def _default(cls, name: str) -> Any:
        """Значение поля по умолчанию (у slots-датакласса cls.field — дескриптор, не значение)."""
        return next(f.default for f in fields(cls) if f.name == name)

    @classmethod
    def from_env(cls, dotenv: str | Path = ".env", token_arg: str | None = None) -> "Config":
        _load_dotenv(Path(dotenv))
        env = os.getenv
        return cls(
            bot_token=_find_token(token_arg),
            admin_ids=_parse_ids(env("ADMIN_IDS", env("TELEGRAM_ADMIN_ID", ""))),
            db_path=_pick_db_path(env("DB_PATH", str(cls._default("db_path")))),
            city=env("CITY_NAME", cls._default("city")),
            city_short=env("CITY_SHORT", cls._default("city_short")),
            emoji_pack_url=env("EMOJI_PACK_URL", cls._default("emoji_pack_url")),
            auto_mute_reports=int(env("AUTO_MUTE_REPORTS", str(cls._default("auto_mute_reports")))),
            auto_mute_minutes=int(env("AUTO_MUTE_MINUTES", str(cls._default("auto_mute_minutes")))),
            inchat_rate_limit=int(env("INCHAT_RATE_LIMIT", str(cls._default("inchat_rate_limit")))),
            max_message_len=int(env("MAX_MESSAGE_LEN", str(cls._default("max_message_len")))),
            debug=env("DEBUG", "").lower() in {"1", "true", "yes"},
        )

    @property
    def is_admin(self) -> frozenset[int]:
        return frozenset(self.admin_ids)

    def admin_markup(self) -> str:
        if not self.admin_ids:
            return ""
        return " · ".join(f"@{i}" for i in self.admin_ids)
