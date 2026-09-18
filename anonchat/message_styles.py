"""Стилизация исходящих сообщений для действующей подписки Holy Gram."""

from __future__ import annotations

import re
import time
from typing import Protocol


STYLE_LABELS = {
    "cute": "🎀 Няшный",
    "vasya": "🧢 Вася",
    "brother": "🤝 Брат",
    "dumb": "🧠 Тупой",
}

_PROTECTED_RE = re.compile(
    r"(?i)(?:(?:https?|tg)://|www\.|(?:^|\s)(?:t\.me|telegram\.me)/|"
    r"(?:^|\s)@[a-z0-9_]{3,32}\b|\b[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:/\S*)?|"
    r"(?<!\d)(?:\+?\d[\d\s()\-]{6,}\d)(?!\d))"
)


class StyleDatabase(Protocol):
    async def get_user(self, user_id: int): ...


def should_skip_style(text: str) -> bool:
    value = (text or "").strip()
    return not value or value.startswith("/") or bool(_PROTECTED_RE.search(value))


def stylize_text(style: str, text: str) -> str:
    """Меняет только манеру речи; повторный вызов не наслаивает тот же стиль."""
    value = (text or "").strip()
    if style not in STYLE_LABELS or should_skip_style(value):
        return text

    lowered = value.casefold()
    if style == "cute":
        if ":3" in value or "💗" in value:
            return value
        result = re.sub(r"(?i)\bты где\b", "ты гдеее", value)
        result = re.sub(r"(?i)\bпривет\b", "приветик", result)
        result = re.sub(r"(?i)\bпожалуйста\b", "пожалуйстааа", result)
        return f"{result} :3 💗"

    if style == "vasya":
        if lowered.startswith("вась,"):
            return value
        result = re.sub(r"(?i)\bили что\b", "или чё", value)
        result = re.sub(r"(?i)\bчто\?", "чё?", result)
        return f"вась, {result[0].lower() + result[1:] if result else result}"

    if style == "brother":
        if re.match(r"(?i)^(?:брат|братан|бро|родной)\b", value):
            return value
        if value.endswith("?"):
            return f"брат, {value[:-1].rstrip()}, родной?"
        return f"брат, {value}"

    if lowered.startswith("это..."):
        return value
    if value.endswith("?"):
        return f"это... {value[:-1].rstrip()}, получается?"
    return f"это... {value}, короче"


async def transform_message_style(
    db: StyleDatabase, user_id: int, text: str, *, max_length: int | None = None
) -> str:
    """Единый фильтр: БД → активная подписка → выбранный стиль → итоговый текст."""
    if should_skip_style(text):
        return text
    row = await db.get_user(user_id)
    if row is None or int(row["premium_until"] or 0) <= int(time.time()):
        return text
    result = stylize_text(str(row["communication_style"] or ""), text)
    # Telegram отклоняет текст >4096 и подпись >1024. Исходный смысл важнее
    # декоративного суффикса, поэтому пограничное сообщение доставляем как есть.
    return text if max_length is not None and len(result) > max_length else result
