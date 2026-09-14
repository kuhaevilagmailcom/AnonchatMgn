"""Ники: пользователь сам выбирает, как его видеть в топе и профиле.

Реальное имя и @username из Telegram в публичных местах не светятся — это анонимный чат.
"""

from __future__ import annotations

NICK_MIN = 2
NICK_MAX = 24
_ALLOWED_EXTRA = set("-_.!?()[]*+~:;='\" ")
_FORBIDDEN = set("<>`\\/@\t\n\r")


def normalize(raw: str) -> str:
    return " ".join((raw or "").split()).strip()[: NICK_MAX + 8]


def validate(raw: str) -> tuple[str, str | None]:
    """Возвращает (ник, ошибка). Пустая строка — «хочу сбросить на авто-ник»."""
    nick = normalize(raw)
    if not nick:
        return "", None
    if len(nick) < NICK_MIN:
        return "", f"Коротко: минимум {NICK_MIN} символа."
    if len(nick) > NICK_MAX:
        return "", f"Длинно: максимум {NICK_MAX} символов (сейчас {len(nick)})."
    for ch in nick:
        if ch in _FORBIDDEN:
            return "", "Такие символы в нике запрещены: < > ` \\ / @ и перенос строки."
        if ch.isspace() or ch in _ALLOWED_EXTRA:
            continue
        if not (ch.isalpha() or ch.isdigit()):
            return "", "Только буквы, цифры, пробел и обычные знаки препинания."
    return nick, None


def auto_nick(user_id: int) -> str:
    """Ник по умолчанию — чтобы в топе не мелькало настоящее имя."""
    return f"Аноним-{abs(int(user_id)) % 10000:04d}"


def display(row_nickname: str | None, user_id: int) -> str:
    nick = normalize(row_nickname or "")
    return nick or auto_nick(user_id)
