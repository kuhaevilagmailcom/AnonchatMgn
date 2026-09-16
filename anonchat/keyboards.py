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
CB_MORE = "act:more"
CB_SUPPORT = "act:support"
CB_CONTINUE = "onboard:continue"
CB_BLOCK = "rate:block"
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


CB_ADMIN_PANEL = "adm:panel"


def menu_keyboard(status: str = "free", queue_size: int = 0, admin: bool = False) -> InlineKeyboardMarkup:
    """Главное меню.

    В диалоге оставляем только действия диалога: профиль/настройки во время
    переписки не смотрят (и не тыкают в них собеседнику под «печатает…»).
    """
    b = InlineKeyboardBuilder()
    if status == "paired":
        _button(b, "Следующий", callback_data=CB_NEXT, icon="next")
        _button(b, "Стоп", callback_data=CB_STOP, icon="check", style="danger")
        _button(b, "Жалоба", callback_data=CB_REPORT, icon="warn")
        b.adjust(1, 2)
        return b.as_markup()

    if status == "queued":
        _button(b, "Отменить поиск", callback_data=CB_STOP, icon="check", style="danger")
        _button(b, "Профиль", callback_data=CB_PROFILE, icon="profile")
        _button(b, "Настройки", callback_data=CB_SETTINGS, icon="settings")
        b.adjust(1, 2)
        return b.as_markup()
    else:
        _button(b, "Найти собеседника", callback_data=CB_CONNECT, icon="view", style="success")
    _button(b, "Профиль", callback_data=CB_PROFILE, icon="profile")
    _button(b, "Настройки", callback_data=CB_SETTINGS, icon="settings")
    _button(b, "Ещё", callback_data=CB_MORE, icon="add")
    rows = [1, 2, 1]
    if admin:
        _button(b, "Панель модератора", callback_data=CB_ADMIN_PANEL, icon="bonus", style="primary")
        rows.append(1)
    b.adjust(*rows)
    return b.as_markup()


def continue_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, "Продолжить", callback_data=CB_CONTINUE, icon="next", style="success")
    return b.as_markup()


def age_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for age in range(13, 21):
        _button(b, str(age), callback_data=f"onboard:age:{age}")
    b.adjust(4, 4)
    return b.as_markup()


def chat_keyboard() -> InlineKeyboardMarkup:
    return menu_keyboard("paired")


def profile_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, "Изменить ник", callback_data=CB_NICK, icon="edit")
    _button(b, "Настройки", callback_data=CB_SETTINGS, icon="settings")
    _button(b, "Назад", callback_data=CB_MENU, icon="home")
    b.adjust(1, 2)
    return b.as_markup()


def more_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, "Топ", callback_data=CB_TOP, icon="stats")
    _button(b, "Правила", callback_data=CB_RULES, icon="ticket")
    _button(b, "Помощь", callback_data=CB_HELP, icon="support")
    _button(b, "Поддержать проект", callback_data=CB_SUPPORT, icon="stars", style="success")
    _button(b, "Удалить мои данные", callback_data="cfg:forget:ask", icon="delete", style="danger")
    _button(b, "Назад", callback_data=CB_MENU, icon="home")
    b.adjust(2, 1, 1, 1, 1)
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


def settings_keyboard(same_district: bool, district: str, nickname: str, has_about: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, f"Ник: {nickname}", callback_data=CB_NICK, icon="profile")
    _button(b, f"Район: {district or 'не выбран'}", callback_data="cfg:district:ask", icon="geo")
    _button(
        b,
        "Ищу: мой район" if same_district else "Ищу: весь город",
        callback_data="cfg:same:toggle",
        icon="view",
    )
    _button(b, "Возраст", callback_data="cfg:age:ask", icon="stars")
    _button(b, "Удалить профиль", callback_data="cfg:forget:ask", icon="delete", style="danger")
    _button(b, "В меню", callback_data=CB_MENU, icon="home")
    b.adjust(1, 1, 1, 1, 1, 1)
    return b.as_markup()


#: (подпись, код причины, иконка)
REPORT_REASONS: tuple[tuple[str, str, str], ...] = (
    ("Оскорбления / травля", "insults", "warn"),
    ("18+ контент", "nsfw", "view"),
    ("Просит контакты / адрес", "contacts", "profile"),
    ("Мошенничество", "scam", "money"),
    ("Спам", "spam", "delete"),
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
    _button(b, "👍 Норм", callback_data="rate:1", icon="bonus", style="success")
    _button(b, "Не зашло", callback_data="rate:0", icon="warn")
    _button(b, "Больше не встречаться", callback_data=CB_BLOCK, icon="delete")
    _button(b, "Найти ещё", callback_data=CB_CONNECT, icon="view")
    b.adjust(2, 1, 1)
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


# ---------------------------------------------------------------------------------- панель модератора
CB_PANEL = "adm:panel"
CB_PANEL_STATS = "adm:panel:stats"
CB_PANEL_REPORTS = "adm:panel:reports"
CB_PANEL_QUEUE = "adm:panel:queue"
CB_PANEL_FIND = "adm:panel:find"
CB_PANEL_BC = "adm:panel:broadcast"
CB_PANEL_MUTE = "adm:panel:mute"
CB_PANEL_BAN = "adm:panel:ban"
CB_PANEL_UNBAN = "adm:panel:unban"
CB_PANEL_BACK = "adm:panel:back"


def admin_panel_keyboard(open_reports: int = 0) -> InlineKeyboardMarkup:
    """Панель модератора: никаких команд в счёт, всё кнопками."""
    b = InlineKeyboardBuilder()
    _button(b, "Сводка", callback_data=CB_PANEL_STATS, icon="stats")
    _button(
        b,
        f"Жалобы · {open_reports}" if open_reports else "Жалобы",
        callback_data=CB_PANEL_REPORTS,
        icon="warn",
        style="danger" if open_reports else "",
    )
    _button(b, "Очередь", callback_data=CB_PANEL_QUEUE, icon="refresh")
    _button(b, "Найти профиль", callback_data=CB_PANEL_FIND, icon="view")
    _button(b, "Рассылка", callback_data=CB_PANEL_BC, icon="support")
    _button(b, "Мут по id", callback_data=CB_PANEL_MUTE, icon="settings", style="primary")
    _button(b, "Бан по id", callback_data=CB_PANEL_BAN, icon="delete", style="danger")
    _button(b, "Разбан по id", callback_data=CB_PANEL_UNBAN, icon="check")
    _button(b, "В меню", callback_data=CB_MENU, icon="home")
    b.adjust(2, 2, 2, 2, 1)
    return b.as_markup()


def panel_back_keyboard() -> InlineKeyboardMarkup:
    """Из любого экрана панели — назад в панель и в меню."""
    b = InlineKeyboardBuilder()
    _button(b, "Назад в панель", callback_data=CB_PANEL_BACK, icon="next")
    _button(b, "В меню", callback_data=CB_MENU, icon="home")
    b.adjust(2)
    return b.as_markup()


def panel_cancel_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _button(b, "Отмена", callback_data=CB_PANEL_BACK, icon="check")
    b.adjust(1)
    return b.as_markup()
