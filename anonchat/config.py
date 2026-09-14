"""Настройки бота: читаются из переменных окружения либо из файла .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
    def from_env(cls, dotenv: str | Path = ".env") -> "Config":
        _load_dotenv(Path(dotenv))
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "Не задан BOT_TOKEN. Скопируйте .env.example в .env и вставьте токен @BotFather."
            )
        db_path = Path(os.getenv("DB_PATH", "data/anonchat_mgn.db"))
        return cls(
            bot_token=token,
            admin_ids=_parse_ids(os.getenv("ADMIN_IDS", "")),
            db_path=db_path,
            city=os.getenv("CITY_NAME", cls.city),
            city_short=os.getenv("CITY_SHORT", cls.city_short),
            emoji_pack_url=os.getenv("EMOJI_PACK_URL", cls.emoji_pack_url),
            auto_mute_reports=int(os.getenv("AUTO_MUTE_REPORTS", cls.auto_mute_reports)),
            auto_mute_minutes=int(os.getenv("AUTO_MUTE_MINUTES", cls.auto_mute_minutes)),
            debug=os.getenv("DEBUG", "").lower() in {"1", "true", "yes"},
        )

    @property
    def is_admin(self) -> frozenset[int]:
        return frozenset(self.admin_ids)

    def admin_markup(self) -> str:
        if not self.admin_ids:
            return ""
        return " · ".join(f"@{i}" for i in self.admin_ids)
