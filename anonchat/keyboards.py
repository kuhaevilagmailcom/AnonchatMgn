"""Инлайн-клавиатуры: тот самый «магнитогорский» меню-блок с эмодзи-кнопками."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

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


def menu_keyboard(emoji_pack_url: str, status: str = "free") -> InlineKeyboardMarkup:
    """Главное меню. Статус меняет только подпись верхней кнопки — ряды всегда на месте."""
    b = InlineKeyboardBuilder()

    search = "💬 Вы в диалоге" if status == "paired" else (
        "⏳ Уже в очереди…" if status == "queued" else "🔎 Поиск собеседника"
    )
    b.button(text=search, callback_data=CB_CONNECT)
    b.button(text="⏭️ Следующий", callback_data=CB_NEXT)
    b.button(text="⏹️ Остановить диалог", callback_data=CB_STOP)
    b.button(text="🚩 Пожаловаться", callback_data=CB_REPORT)
    b.button(text="📊 Профиль · уровень", callback_data=CB_PROFILE)
    b.button(text="⚙️ Настройки", callback_data=CB_SETTINGS)
    b.button(text="🏆 Топ МГН", callback_data=CB_TOP)
    b.button(text="📜 Правила", callback_data=CB_RULES)
    b.button(text="✨ Эмодзи для чата", url=emoji_pack_url)
    b.adjust(1, 2, 2, 2)
    return b.as_markup()


def district_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for title, value in (
        ("🏙️ Правобережный", "right"),
        ("🌉 Левобережный", "left"),
        ("🏭 Орджоникидзевский", "ordz"),
        ("🧭 Не важно", "none"),
    ):
        b.button(text=title, callback_data=f"cfg:district:{value}")
    b.button(text="⬅️ Назад", callback_data=CB_SETTINGS)
    b.adjust(1, 1, 1, 1, 1)
    return b.as_markup()


def gender_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🙋‍♂️ Парень", callback_data="cfg:gender:m")
    b.button(text="🙋‍♀️ Девушка", callback_data="cfg:gender:f")
    b.button(text="🤫 Не указывать", callback_data="cfg:gender:none")
    b.button(text="⬅️ Назад", callback_data=CB_SETTINGS)
    b.adjust(2, 1, 1)
    return b.as_markup()


def settings_keyboard(same_district: bool, district: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    toggle = "🔒 Только мой район" if not same_district else "🔓 Ищу по всему МГН"
    b.button(text=toggle, callback_data="cfg:same:toggle")
    b.button(text=f"📍 Район: {district or 'не выбран'}", callback_data="cfg:district:ask")
    b.button(text="👤 Пол в профиле", callback_data="cfg:gender:ask")
    b.button(text="📝 Описание профиля", callback_data="cfg:about:ask")
    b.button(text="🧹 Сбросить настройки", callback_data="cfg:reset")
    b.button(text="🗑 Удалить профиль", callback_data="cfg:forget:ask")
    b.button(text="⬅️ В меню", callback_data=CB_MENU)
    b.adjust(1, 1, 1, 1, 1, 1, 1)
    return b.as_markup()


def confirm_forget_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🗑 Да, удалить всё", callback_data="cfg:forget:yes")
    b.button(text="❌ Отмена", callback_data="cfg:forget:no")
    b.adjust(1)
    return b.as_markup()


REPORT_REASONS: tuple[tuple[str, str], ...] = (
    ("🤖 Спам и реклама", "spam"),
    ("😡 Оскорбления", "insults"),
    ("🔞 Контент 18+", "nsfw"),
    ("🎭 Выдаёт себя за другого", "fake"),
    ("💸 Предлагают деньги/мошенничество", "scam"),
    ("🧐 Другое", "other"),
)


def report_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for title, value in REPORT_REASONS:
        b.button(text=title, callback_data=f"rep:{value}")
    b.button(text="⬅️ Отмена", callback_data=CB_MENU)
    b.adjust(1, 1, 1, 1, 1, 1)
    return b.as_markup()


def rating_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👍 Собеседник огонь", callback_data="rate:1")
    b.button(text="👎 Скучно было", callback_data="rate:0")
    b.button(text="🔎 Искать ещё", callback_data=CB_CONNECT)
    b.adjust(1, 1)
    return b.as_markup()


def confirm_stop_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да, остановить", callback_data=CB_STOP_YES)
    b.button(text="❌ Нет, продолжить", callback_data=CB_STOP_NO)
    b.adjust(2)
    return b.as_markup()


def back_menu_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ В меню", callback_data=CB_MENU)
    b.adjust(1)
    return b.as_markup()


def skip_cancel_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⏭️ Пропустить", callback_data="rep:skip")
    b.button(text="⬅️ Отмена", callback_data=CB_MENU)
    b.adjust(2)
    return b.as_markup()


def admin_report_keyboard(report_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔇 Мут 60 мин", callback_data=f"adm:mute:{report_id}")
    b.button(text="⛔ Бан", callback_data=f"adm:ban:{report_id}")
    b.button(text="👤 Профиль", callback_data=f"adm:who:{report_id}")
    b.button(text="✅ Закрыть жалобу", callback_data=f"adm:done:{report_id}")
    b.adjust(2, 2)
    return b.as_markup()
