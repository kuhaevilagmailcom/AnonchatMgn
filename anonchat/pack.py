"""Эмодзи из городского пака NewsEmoji (https://t.me/addemoji/NewsEmoji).

В Telegram эмодзи из пака — это не юникодный символ, а анимированный файл с id.
Бот может ставить его двумя способами:

* в **текст** — тегом ``<tg-emoji emoji-id="…">👀</tg-emoji>`` (обычные символы
  внутри тега Telegram заменит на анимацию; у тех, у кого нет премиума — статичная
  картинка пака);
* в **кнопку** — полем ``icon_custom_emoji_id`` (работает и у inline-, и у reply-кнопок).

id нельзя «скачать» со страницы пака — бот узнаёт их только из чужих сообщений.
Поэтому таблица ``PACK`` ниже — это id того же пака NewsEmoji, которые уже собраны
и обкатаны в ``limuzinov_shop_bot`` (22 эмодзи), а ``harvest()`` доращивает её прямо
в рантайме: стоит участнику прислать боту эмодзи, которого в таблице нет, — он
запомнится и уедет в БД (``kv["emoji_ids"]``).

Алиасы нужны, чтобы не переписывать тексты: в них ``✅``, а в паке этот же знак
называется ``✔️`` — пишем одно, показываем другое.
"""

from __future__ import annotations

import re
from typing import Iterable

from aiogram.types import Message

TG_EMOJI_OPEN = re.compile(r"<tg-emoji[^>]*>")
TG_EMOJI_CLOSE = re.compile(r"</tg-emoji>")

#: обрезают эмодзи-последовательность пополам: ZWJ с любой стороны, вариационный селектор в начале
_ZWJ = "\u200d"
_JOINERS = ("\u200d", "\ufe0f", "\ufe0e")

#: сколько эмодзи пака в одном сообщении бота. Больше — уже карнавал.
MAX_WRAP_PER_MESSAGE = 5

#: имя -> (custom_emoji_id, как знак выглядит без анимации, какие символы ещё сводим на него)
PACK: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "support": ("5443038326535759644", "💬", ("💌",)),
    "check": ("5206607081334906820", "✔️", ("✅", "☑️")),
    "warn": ("5447644880824181073", "⚠️", ("❗", "🚩")),
    "money": ("5409048419211682843", "💵", ("💸", "💰")),
    "catalog": ("5229064374403998351", "🛍", ()),
    "ticket": ("5222444124698853913", "🔖", ("📜",)),
    "profile": ("5461117441612462242", "🙂", ("🙋", "👤")),
    "bonus": ("5427168083074628963", "💎", ()),
    "settings": ("5341715473882955310", "⚙️", ("⚙",)),
    "home": ("5416041192905265756", "🏠", ()),
    "next": ("5416117059207572332", "➡️", ("⏭",)),
    "stars": ("5438496463044752972", "⭐️", ("⭐", "🌟")),
    "geo": ("5391032818111363540", "📍", ("📌",)),
    "gift": ("5461151367559141950", "🎉", ("🎁",)),
    "refresh": ("5375338737028841420", "🔄", ("♻️", "🔁", "🔃")),
    "promo": ("5341498088408234504", "💯", ()),
    "link": ("5271604874419647061", "🔗", ()),
    "stats": ("5231200819986047254", "📊", ("📈",)),
    "add": ("5397916757333654639", "➕", ()),
    "edit": ("5395444784611480792", "✏️", ("✍️", "📝")),
    "view": ("5210956306952758910", "👀", ()),
    "delete": ("5445267414562389170", "🗑", ("🧹",)),
}

#: имя -> id, для кнопок (icon_custom_emoji_id)
ICONS: dict[str, str] = {name: emoji_id for name, (emoji_id, _, _) in PACK.items()}


class EmojiPack:
    def __init__(self, url: str = "") -> None:
        self.url = url
        self.enabled = True
        # символ -> (id, чем его показывать внутри тега)
        self._map: dict[str, tuple[str, str]] = {}
        for _name, (emoji_id, canonical, aliases) in PACK.items():
            for glyph in (canonical, *aliases):
                self._map.setdefault(glyph, (emoji_id, canonical))
        #: что приехало из кода — в базу не пишем; сохраняем только «подсмотренное» из чатов
        self._seed = set(self._map)

    # ------------------------------------------------------------------ store
    def load(self, pairs: Iterable[tuple[str, str]]) -> None:
        """Догнать таблицу id, сохранёнными в БД (подсмотренными из сообщений)."""
        for emoji, emoji_id in pairs:
            if emoji and emoji_id:
                self._map.setdefault(str(emoji), (str(emoji_id), str(emoji)))

    def as_pairs(self) -> list[tuple[str, str]]:
        return [
            (glyph, emoji_id)
            for glyph, (emoji_id, _) in self._map.items()
            if glyph not in self._seed
        ]

    def known(self) -> int:
        return len(self._map)

    def extra(self) -> int:
        """Сколько id добавилось из чатов поверх встроенной таблицы пака."""
        return len(self._map) - len(self._seed)

    def has(self, emoji: str) -> bool:
        return emoji in self._map

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
            if chunk not in self._map:
                found.append(chunk)
            self._map[chunk] = (str(emoji_id), chunk)
        return found

    # ------------------------------------------------------------------ render
    def wrap(self, text: str, limit: int = MAX_WRAP_PER_MESSAGE) -> str:
        """Первые `limit` эмодзи, для которых есть id, заворачиваем в тег пака.

        Идём слева направо, поэтому достается в первую очередь заголовкам.
        Внутри тега всегда канонический знак пака (``✅`` → ``✔️``), иначе Telegram
        может счесть вложенный символ не соответствующим id.
        """
        if not self.enabled or not self._map or not text:
            return text
        keys = sorted(self._map, key=len, reverse=True)
        used: set[str] = set()
        out: list[str] = []
        i, n, budget = 0, len(text), limit
        while i < n:
            matched = False
            if budget:
                for key in keys:
                    if text.startswith(key, i) and key not in used:
                        emoji_id, canonical = self._map[key]
                        out.append(f'<tg-emoji emoji-id="{emoji_id}">{canonical}</tg-emoji>')
                        used.add(key)
                        # тот же знак больше не оборачиваем: глазами это один акцент
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
