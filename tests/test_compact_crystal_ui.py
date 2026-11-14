"""Compact button-first UX and unambiguous internal crystal currency."""
from anonchat import keyboards as K, texts
from anonchat.commands import ADMIN_VISIBLE, COMMANDS
from anonchat.handlers.nft_giveaway import Giveaway, _keyboard, _message
from anonchat.pack import ICONS


def _labels(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def test_main_menu_is_compact_and_chat_first() -> None:
    labels = _labels(K.menu_keyboard("free", nft_active=True))
    assert labels[0] == "Начать общение"
    assert labels == [
        "Начать общение", "Розыгрыш", "Профиль", "Топ", "Настройки", "Правила",
    ]


def test_internal_rewards_are_crystals_not_telegram_stars() -> None:
    assert "💎" in texts.XP_EARNED
    assert "⭐" not in texts.XP_EARNED
    assert "кристалл" in texts.RULES.lower()
    assert "очки внутри бота" not in texts.RULES.lower()
    assert any(
        "100 кристаллов" in label for label in _labels(K.profile_keyboard(subscription_reward=100))
    )
    reward_button = next(
        button
        for row in K.profile_keyboard(subscription_reward=100).inline_keyboard
        for button in row
        if "100 кристаллов" in button.text
    )
    assert ICONS["bonus"] == "5427168083074628963"
    assert reward_button.icon_custom_emoji_id == ICONS["bonus"]


def test_commands_are_hidden_behind_buttons() -> None:
    assert [command.command for command in COMMANDS] == ["start"]
    assert [command.command for command in ADMIN_VISIBLE] == ["admin"]


def test_raffle_is_compact_and_administered_from_one_button_hub() -> None:
    giveaway = Giveaway("campaign", "https://t.me/nft/Test", 9_999_999_999, "20.11 · 20:00")
    body = _message(giveaway)
    assert "ВАЖНО" not in body
    assert len(body) < 320
    assert _labels(_keyboard(True)) == ["Купить билеты", "Мои билеты", "В меню"]
    assert "NFT-розыгрыш" in _labels(K.admin_panel_keyboard(owner=True))
    assert hasattr(K, "admin_raffle_keyboard")
    assert _labels(K.admin_raffle_keyboard()) == [
        "Открыть", "Создать", "Рассылка", "Опубликовать", "Статистика", "Завершить", "В панель",
    ]

