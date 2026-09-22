"""Эмодзи из городского пака NewsEmoji (https://t.me/addemoji/NewsEmoji).

В Telegram эмодзи из пака — это не юникодный символ, а анимированный файл с id.
Бот может ставить его двумя способами:

* в **текст** — тегом ``<tg-emoji emoji-id="…">👀</tg-emoji>`` (обычные символы
  внутри тега Telegram заменит на анимацию; у тех, у кого нет премиума — статичная
  картинка пака);
* в **кнопку** — полем ``icon_custom_emoji_id`` (работает и у inline-, и у reply-кнопок).

Таблица ``PACK`` ниже фиксирована в коде: сообщения пользователей никогда не меняют
оформление интерфейса бота.

Алиасы нужны, чтобы не переписывать тексты: в них ``✅``, а в паке этот же знак
называется ``✔️`` — пишем одно, показываем другое.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

log = logging.getLogger(__name__)

TG_EMOJI_OPEN = re.compile(r"<tg-emoji[^>]*>")
TG_EMOJI_CLOSE = re.compile(r"</tg-emoji>")

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

DEFAULT_EXTRA_PACKS: tuple[str, ...] = (
    "TgAndroidIcons",
    "CryptoGIFTPODARKI",
    "progressBarEmoji",
)

# semantic icon name -> canonical fallback glyph from PACK
_CANONICAL_BY_NAME: dict[str, str] = {
    name: canonical for name, (_emoji_id, canonical, _aliases) in PACK.items()
}


def _sticker_glyphs(sticker) -> tuple[str, ...]:
    values: list[str] = []
    emoji = str(getattr(sticker, "emoji", "") or "").strip()
    if emoji:
        values.append(emoji)
    # Telegram may expose additional emoji variants in emoji_list.
    for item in getattr(sticker, "emoji_list", None) or ():
        value = str(item or "").strip()
        if value and value not in values:
            values.append(value)
    return tuple(values)



class EmojiPack:
    def __init__(self, url: str = "") -> None:
        self.url = url
        self.enabled = True
        # символ -> (id, чем его показывать внутри тега)
        self._map: dict[str, tuple[str, str]] = {}
        for _name, (emoji_id, canonical, aliases) in PACK.items():
            for glyph in (canonical, *aliases):
                self._map.setdefault(glyph, (emoji_id, canonical))

    def register_sticker_set(self, stickers: Iterable[object], *, override: bool = True) -> int:
        """Добавляет custom emoji из Telegram StickerSet в RAM.

        В текстах подмена идёт по стандартному emoji, указанному у sticker.
        Для кнопок semantic-иконка обновляется только если glyph совпадает с
        каноническим знаком уже известной иконки.
        """
        added = 0
        canonical_to_names: dict[str, list[str]] = {}
        for name, canonical in _CANONICAL_BY_NAME.items():
            canonical_to_names.setdefault(canonical, []).append(name)

        for sticker in stickers:
            custom_id = str(getattr(sticker, "custom_emoji_id", "") or "")
            if not custom_id:
                continue
            for glyph in _sticker_glyphs(sticker):
                if override or glyph not in self._map:
                    self._map[glyph] = (custom_id, glyph)
                    added += 1
                for name in canonical_to_names.get(glyph, ()):
                    if override or name not in ICONS:
                        ICONS[name] = custom_id
        return added

    async def load_sticker_sets(self, bot, names: Iterable[str] = DEFAULT_EXTRA_PACKS) -> int:
        """Загружает наборы один раз при старте; при ошибке остаётся fallback PACK."""
        total = 0
        for name in names:
            try:
                sticker_set = await bot.get_sticker_set(name=name)
            except Exception as exc:  # Telegram/API failure must not block bot startup
                log.warning("emoji pack %s не загрузился: %s", name, exc)
                continue
            if str(getattr(sticker_set, "sticker_type", "")) != "custom_emoji":
                log.warning("emoji pack %s не custom_emoji — пропускаю", name)
                continue
            count = self.register_sticker_set(getattr(sticker_set, "stickers", ()))
            total += count
            log.info("emoji pack %s: подключено %s emoji", name, count)
        return total
    def known(self) -> int:
        return len(self._map)

    def has(self, emoji: str) -> bool:
        return emoji in self._map

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
