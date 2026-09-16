"""Небольшой фильтр личных контактов без хранения переписки и внешних сервисов."""

from __future__ import annotations

import re

_CONTACT_PATTERNS = (
    # Username и ссылки разрешены; телефон и email по-прежнему скрываем.
    re.compile(r"(?i)\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
    re.compile(r"(?<!\d)(?:\+?7|8)[\s()\-]*\d{3}[\s()\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)"),
)


def contains_contact(value: str) -> bool:
    text = value or ""
    return any(pattern.search(text) for pattern in _CONTACT_PATTERNS)
