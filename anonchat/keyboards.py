"""Инлайн-клавиатуры.

Здесь нет юникодных эмодзи в подписях: маркер кнопки — анимированный эмодзи из
пака NewsEmoji в поле ``icon_custom_emoji_id`` (тот же приём, что в limuzinov_shop_bot).
``style`` — цвет кнопки: основной/action/опасный.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .pack import ICONS

# callback_data
CB_CONNECT = "act:connect"
CB_NEXT = "act:next"
CB_STOP = "act:stop"
CB_STOP_YES = "act:stop:yes"
CB_STOP_NO = "act:stop:no"
CB_REPORT = "act:report"
CB_MENU = "act:menu"
CB_PROFILE = "act:profile"
CB_SETTINGS = "act:settings"
CB_HELP = "act:help"
CB_RULES = "act:rules"
CB_TOP = "act:top"
CB_NICK = "cfg:nick:ask"


#: Bot API принимает только эти три цвета кнопки («warning» отвергает — проверено живьём)
STYLES = ("primary", "success", "danger")


def _button(
    b: InlineKeyboardBuilder, text: str, callback_data: str = "", url: str = "",
    icon: str = "", style: str = "",
) -> None:
    """Кнопка с иконкой из пака; если id неизвестен — обычная текстовая кнопка."""
    kwargs: dict[str, object] = {"text": text}
    if callback_data:
        kwargs["callback_data"] = callback_data
    if url:
        kwargs["url"] = url
    emoji_id = ICONS.get(icon)
    if emoji_id:
        kwargs["icon_custom_emoji_id"] = emoji_id
    if style in STYLES:
        kwargs["style"] = style
    b.button(**kwargs)


def menu_keyboard(status: str = "free", queue_size: int = 0) -> InlineKeyboardMarkup:
    """Главное меню: сверху поиск/статус, остальное сеткой 2×2."""
    b = InlineKeyboardBuilder()
    if status == "paired":
        head, head_icon, head_style = "Диалог идёт", "support", ""
    elif status == "queued":
        head, head_icon, head_style = f"В очереди · ждёт пары: {queue_size}", "refresh", ""
    else:
        head, head_icon, head_style = "Поиск собеседника", "view", "success"
    _button(b, head, callback_data=CB_CONNECT, icon=head_icon, style=head_style)

    _button(b, "Следующий", callback_data=CB_NEXT, icon="next")
    _button(b, "Стоп", callback_data=CB_STOP, icon="check", style="danger")

    _button(b, "Жалоба", callback_data=CB_REPORT, icon="warn", style="primary")
    _button(b, "Профиль", callback_data=CB_PROFILE, icon="profile")

    _button(b, "Настройки", callback_data=CB_SETTINGS, icon="settings")
    _button(b, "Топ", callback_data=CB_TOP, icon="stats")

    _button(b, "Правила", callback_data=CB_RULES, icon="ticket")
    _button(b, "Помощь", callback_data=CB_HELP, icon="support")
    b.adjust(1, 2, 2, 2, 2)
    return b.as_markup()


def district_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for title, value in (
        ("Правобережный", "right"),
        ("Левобережный", "left"),
        ("Орджоникидзевский", "ordz"),
        ("Не важно", "none"),
    ):
        _button(b, title, callback_data=f"cfg:district:{value}",
                icon="geo" if value != "none" else "check")
    _button(b, "Назад", callback_data=CB_SETTINGS, icon="home")
    b.adjust(1, 1, 1, 1, 1)
    return b.as_markup()


def gender_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, "Парень", callback_data="cfg:gender:m", icon="profile")
    _button(b, "Девушка", callback_data="cfg:gender:f", icon="profile")
    _button(b, "Не указывать", callback_data="cfg:gender:none", icon="check")
    _button(b, "Назад", callback_data=CB_SETTINGS, icon="home")
    b.adjust(2, 1, 1)
    return b.as_markup()


def settings_keyboard(
    same_district: bool, district: str, nickname: str, has_about: bool
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, f"Ник: {nickname}", callback_data=CB_NICK, icon="profile")
    _button(b, f"Район: {district or 'не выбран'}", callback_data="cfg:district:ask", icon="geo")
    _button(
        b,
        "Ищу: мой район" if same_district else "Ищу: весь город",
        callback_data="cfg:same:toggle",
        icon="view",
    )
    _button(
        b, "Описание" if has_about else "Заполнить «о себе»",
        callback_data="cfg:about:ask", icon="edit",
    )
    _button(b, "Пол в профиле", callback_data="cfg:gender:ask", icon="stars")
    _button(b, "Сбросить настройки", callback_data="cfg:reset", icon="refresh")
    _button(b, "Удалить профиль", callback_data="cfg:forget:ask", icon="delete", style="danger")
    _button(b, "В меню", callback_data=CB_MENU, icon="home")
    b.adjust(1, 1, 1, 1, 1, 1, 1, 1)
    return b.as_markup()


#: (подпись, код причины, иконка)
REPORT_REASONS: tuple[tuple[str, str, str], ...] = (
    ("Спам и реклама", "spam", "delete"),
    ("Оскорбления", "insults", "warn"),
    ("Контент 18+", "nsfw", "view"),
    ("Выдаёт себя за другого", "fake", "profile"),
    ("Деньги / мошенничество", "scam", "money"),
    ("Другое", "other", "ticket"),
)

REASON_TITLES = {code: title for title, code, _ in REPORT_REASONS}


def report_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for title, value, icon in REPORT_REASONS:
        _button(b, title, callback_data=f"rep:{value}", icon=icon)
    _button(b, "Отмена", callback_data=CB_MENU, icon="check")
    b.adjust(2, 2, 2, 1)
    return b.as_markup()


def rating_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, "Хороший собеседник", callback_data="rate:1", icon="bonus", style="success")
    _button(b, "Не зашло", callback_data="rate:0", icon="warn")
    _button(b, "Искать ещё", callback_data=CB_CONNECT, icon="view")
    b.adjust(1, 1, 1)
    return b.as_markup()


def confirm_stop_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, "Да, остановить", callback_data=CB_STOP_YES, icon="check", style="danger")
    _button(b, "Продолжить", callback_data=CB_STOP_NO, icon="next")
    b.adjust(2)
    return b.as_markup()


def confirm_forget_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, "Да, удалить всё", callback_data="cfg:forget:yes", icon="delete", style="danger")
    _button(b, "Отмена", callback_data="cfg:forget:no", icon="check")
    b.adjust(2)
    return b.as_markup()


def back_menu_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, "В меню", callback_data=CB_MENU, icon="home")
    b.adjust(1)
    return b.as_markup()


def skip_cancel_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, "Пропустить", callback_data="rep:skip", icon="next")
    _button(b, "Отмена", callback_data=CB_MENU, icon="check")
    b.adjust(2)
    return b.as_markup()


def admin_report_keyboard(report_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, "Мут 60 мин", callback_data=f"adm:mute:{report_id}", icon="warn", style="primary")
    _button(b, "Бан", callback_data=f"adm:ban:{report_id}", icon="delete", style="danger")
    _button(b, "Профиль", callback_data=f"adm:who:{report_id}", icon="profile")
    _button(b, "Закрыть", callback_data=f"adm:done:{report_id}", icon="check", style="success")
    b.adjust(2, 2)
    return b.as_markup()


def plain_button(text: str, callback_data: str, icon: str = "", style: str = "") -> InlineKeyboardButton:
    """Одиночная кнопка для сборных клавиатур (используется хендлерами)."""
    kwargs: dict[str, object] = {"text": text, "callback_data": callback_data}
    emoji_id = ICONS.get(icon)
    if emoji_id:
        kwargs["icon_custom_emoji_id"] = emoji_id
    if style in STYLES:
        kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)  # type: ignore[arg-type]
