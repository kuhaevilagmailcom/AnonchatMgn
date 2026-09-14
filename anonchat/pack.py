"""Эмодзи из городского пака (https://t.me/addemoji/NewsEmoji).

Как это работает в Telegram: эмодзи из паков — это не юникодный символ, а файл с id.
Бот может ставить такие эмодзи в свои тексты тегом `<tg-emoji emoji-id="…">🧲</tg-emoji>`,
но id обязан где-то «встретиться» боту. Поэтому:

* при каждом сообщении пользователя разбираем его entities и запоминаем
  соответствия «символ → custom_emoji_id» (и складываем в БД — переживают рестарт);
* в своих текстах подменяем символы, для которых id уже есть;
* если Telegram откажет (аккаунту бота такие эмодзи недоступны) — один раз откатываемся
  на обычный текст и больше не пробуем: пользователя об ошибках не узнает.
"""

from __future__ import annotations

import re
from typing import Iterable

from aiogram.types import Message

TG_EMOJI_OPEN = re.compile(r"<tg-emoji[^>]*>")
TG_EMOJI_CLOSE = re.compile(r"</tg-emoji>")

#: обрезают эмодзи-последовательность пополам: ZWJ с любой стороны, вариационный селектор в начале
#: (а вот U+FE0F в конце — норма для «♂️», «⛹️» и компании)
_ZWJ = "\u200d"
_JOINERS = ("\u200d", "\ufe0f", "\ufe0e")

MAX_WRAP_PER_MESSAGE = 3


class EmojiPack:
    def __init__(self, url: str = "") -> None:
        self.url = url
        self.enabled = True
        self._ids: dict[str, str] = {}  # сам emoji-символ -> custom_emoji_id

    # ------------------------------------------------------------------ store
    def load(self, pairs: Iterable[tuple[str, str]]) -> None:
        for emoji, emoji_id in pairs:
            if emoji and emoji_id:
                self._ids.setdefault(emoji, emoji_id)

    def as_pairs(self) -> list[tuple[str, str]]:
        return list(self._ids.items())

    def known(self) -> int:
        return len(self._ids)

    def has(self, emoji: str) -> bool:
        return emoji in self._ids

    # ------------------------------------------------------------------ harvest
    def harvest(self, message: Message) -> list[str]:
        """Запомнить кастомные эмодзи из сообщения пользователя. Возвращает новые символы."""
        found: list[str] = []
        for entity in message.entities or []:
            emoji_id = getattr(entity, "custom_emoji_id", None)
            if entity.type != "custom_emoji" or not emoji_id:
                continue
            offset = int(entity.offset)
            length = int(entity.length)
            raw = message.text or ""
            # offset/length Telegram отдаёт в UTF-16 — режем по тому же представлению
            chunk = raw.encode("utf-16-le")[offset * 2 : (offset + length) * 2].decode(
                "utf-16-le", errors="ignore"
            )
            if not chunk:
                continue
            try:
                chunk.encode("utf-16-be")  # отбрасываем «половинки» ZWJ-последовательностей
            except UnicodeEncodeError:
                continue
            if chunk.startswith(_JOINERS) or chunk.endswith(_ZWJ):
                continue  # обрезанная последовательность — такой эмодзи не запоминаем
            if chunk not in self._ids:
                self._ids[chunk] = emoji_id
                found.append(chunk)
            else:
                self._ids[chunk] = emoji_id
        return found

    # ------------------------------------------------------------------ render
    def wrap(self, text: str, limit: int = MAX_WRAP_PER_MESSAGE) -> str:
        """Заменить первые `limit` известных эмодзи на тег пака (ZWJ-последовательности целиком)."""
        if not self.enabled or not self._ids or not text:
            return text
        keys = sorted(self._ids, key=len, reverse=True)
        out: list[str] = []
        i, n, budget = 0, len(text), limit
        while i < n:
            matched = False
            if budget:
                for key in keys:
                    if text.startswith(key, i):
                        out.append(f'<tg-emoji emoji-id="{self._ids[key]}">{key}</tg-emoji>')
                        i += len(key)
                        budget -= 1
                        matched = True
                        break
            if not matched:
                out.append(text[i])
                i += 1
        return "".join(out)

    def accept(self, exc: Exception) -> bool:
        """Telegram ругнулся на эмодзи-тег? Отключаем пак и пробуем обычным текстом."""
        message = str(getattr(exc, "message", "") or exc)
        if self.enabled and self.looks_like_emoji_error(message):
            self.enabled = False
            return True
        return False

    @staticmethod
    def strip(text: str) -> str:
        return TG_EMOJI_CLOSE.sub("", TG_EMOJI_OPEN.sub("", text))

    @staticmethod
    def looks_like_emoji_error(message: str) -> bool:
        low = (message or "").lower()
        return "tg-emoji" in low or "custom_emoji" in low or "emoji" in low
