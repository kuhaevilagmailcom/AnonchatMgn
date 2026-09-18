"""Самопроверка ядра: уровни, матчмейкер, база. Запуск: pytest -q (или python -m tests.core)."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anonchat.db import Database  # noqa: E402
from anonchat.levels import RANKS, rank_for  # noqa: E402
from anonchat.matching import Matchmaker  # noqa: E402


# --------------------------------------------------------------------------------- levels
def test_config_defaults(monkeypatch=None) -> None:
    """from_env должен читать дефолты полей, а не slots-дескрипторы (был реальный баг)."""
    import os

    from anonchat.config import Config

    saved = {
        k: os.environ.get(k)
        for k in ("BOT_TOKEN", "CITY_NAME", "ADMIN_IDS", "TELEGRAM_ADMIN_ID", "AUTO_MUTE_REPORTS")
    }
    os.environ["BOT_TOKEN"] = "12:TEST"
    os.environ.pop("CITY_NAME", None)
    os.environ.pop("TELEGRAM_ADMIN_ID", None)
    os.environ["ADMIN_IDS"] = "777, 888"
    try:
        cfg = Config.from_env(dotenv=".__no_such_env__.local")
        assert cfg.city == "Магнитогорск" and cfg.city_short == "МГН"
        assert cfg.admin_ids == (777, 888)
        assert cfg.auto_mute_reports == 3 and isinstance(cfg.auto_mute_reports, int)
        assert cfg.drop_pending_updates is False
        assert cfg.report_context_retention_days == 7
        assert cfg.emoji_pack_url.startswith("https://t.me/addemoji/")
        assert cfg.max_message_len == 3000

        # id администраторов не зашиваются в публичный код
        os.environ["ADMIN_IDS"] = ""
        assert Config.from_env(dotenv=".__no_such_env__.local").admin_ids == ()
        # алиас от панелей хостинга
        os.environ.pop("ADMIN_IDS")
        os.environ["TELEGRAM_ADMIN_ID"] = "4242"
        assert Config.from_env(dotenv=".__no_such_env__.local").admin_ids == (4242,)
        # явный отказ от админов (форк под своего владельца)
        os.environ["ADMIN_IDS"] = "none"
        assert Config.from_env(dotenv=".__no_such_env__.local").admin_ids == ()
        os.environ["ADMIN_IDS"] = "777, 888"

        os.environ["CITY_NAME"] = "Челябинск"
        os.environ["AUTO_MUTE_REPORTS"] = "5"
        cfg2 = Config.from_env(dotenv=".__no_such_env__.local")
        assert cfg2.city == "Челябинск" and cfg2.auto_mute_reports == 5

        os.environ["BOT_TOKEN"] = ""
        try:
            Config.from_env(dotenv=".__no_such_env__.local")
        except RuntimeError:
            pass
        else:
            raise AssertionError("пустой BOT_TOKEN обязан ронять запуск")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_levels_progress() -> None:
    """Уровни достижимы без сотен тысяч сообщений."""
    first = rank_for(0)
    assert first.index == 1 and first.title == "Новичок"
    assert first.progress == 0.0 and first.to_next == 25 and first.next_title == "Общительный"

    bronze = rank_for(25)
    assert bronze.title == "Общительный" and bronze.progress == 0.0
    assert bronze.to_next == 75 and bronze.next_title == "Знакомый"

    mid = rank_for(60)
    assert mid.title == "Общительный" and 0.4 < mid.progress < 0.6
    assert len(mid.bar) == 8 and mid.bar.startswith("▰▰▰▰▱")

    silver = rank_for(100)
    assert silver.title == "Знакомый"
    gold = rank_for(350)
    assert gold.title == "Свой"
    vip = rank_for(1_000)
    assert vip.title == "Легенда" and vip.is_max and vip.to_next is None
    assert rank_for(99_999_999).index == len(RANKS)

    # человекочитаемые числа с неразрывными пробелами
    assert rank_for(15_000).pretty(12345) == "12 345"
    assert "1 000" in rank_for(1_000).label
    assert rank_for(0).name.endswith("Новичок")


# --------------------------------------------------------------------------------- matching
def test_queue_then_pair() -> None:
    mm = Matchmaker()
    assert mm.connect(1) == ("queued", 1)
    assert mm.status(1) == "queued"
    assert mm.connect(2) == ("paired", 1)
    assert mm.status(1) == "paired" and mm.partner(1) == 2
    assert mm.queue_size() == 0

    # счётчик сообщений + корректный разбор пары
    assert mm.count_message(1) == (2, 1)
    mm.count_message(2)
    partner, summary = mm.release(1)
    assert partner == 2 and summary["counts"][1] == 1
    assert mm.status(1) == "free" and mm.status(2) == "free"


def test_district_filter_and_sweep() -> None:
    mm = Matchmaker()
    mm.connect(1, district="Правобережный", same_district=True)
    # второй тоже хочет «только свой», но район другой — не сводим
    assert mm.connect(2, district="Левобережный", same_district=True) == ("queued", 2)
    assert mm.queue_size() == 2

    # первый снял фильтр — sweep обязан найти пару
    mm.refresh(1, district="Правобережный", same_district=False)
    assert mm.status(1) == "paired" and mm.status(2) == "paired"

    # одинаковые районы совместимы всегда
    mm2 = Matchmaker()
    mm2.connect(3, district="Орджоникидзевский", same_district=True)
    assert mm2.connect(4, district="Орджоникидзевский", same_district=True) == ("paired", 3)


def test_forget_and_ratings() -> None:
    mm = Matchmaker()
    mm.connect(1)
    mm.connect(2)
    summary = mm.forget(2)
    assert summary.get("partner") == 1
    assert mm.status(1) == "free"

    mm.remember_rating([1, 2], match_id=42)
    assert mm.pop_rating(1) == (42, 2)
    assert mm.pop_rating(1) is None  # повторно уже не сработает


def test_queue_limit() -> None:
    mm = Matchmaker(queue_limit=2)
    # держим всех в очереди разными районами, иначе они мгновенно свелись бы
    assert mm.connect(1, district="Правобережный", same_district=True) == ("queued", 1)
    assert mm.connect(2, district="Левобережный", same_district=True) == ("queued", 2)
    assert mm.connect(3, district="Орджоникидзевский", same_district=True) == ("full", None)


def test_excluded_users_do_not_match() -> None:
    mm = Matchmaker()
    assert mm.connect(1, excluded={2}) == ("queued", 1)
    assert mm.connect(2) == ("queued", 2)
    assert mm.connect(3) == ("paired", 1)


# --------------------------------------------------------------------------------- database
def test_database() -> None:
    holder: dict[str, object] = {}

    async def scenario() -> None:
        path = Path(tempfile.mkdtemp()) / "t.db"
        db = await Database(path).start()
        holder["db"] = db

        row = await db.ensure_user(10, "petr", "Пётр")
        assert row["xp"] == 0 and row["district"] == ""

        await db.set_profile(10, district="Правобережный")
        row = await db.get_user(10)
        assert row["district"] == "Правобережный"

        assert await db.award_xp(10, 70) == 70
        assert rank_for(70).title == "Общительный"
        assert rank_for(1_000).title == "Легенда"

        await db.ensure_user(11, "friend", "Друг")
        assert await db.award_referral(11, 10, 50) is True
        assert (await db.get_user(10))["xp"] == 120
        assert await db.award_referral(11, 10, 50) is False
        assert await db.award_referral(21, 21, 50) is False

        created, support_total = await db.record_payment(
            10, "support", 1, "charge-1", "", "support:10:1:x"
        )
        assert created and support_total == 1
        duplicate, duplicate_total = await db.record_payment(
            10, "support", 1, "charge-1", "", "support:10:1:x"
        )
        assert duplicate is False and duplicate_total == support_total
        created2, extended = await db.record_payment(
            10, "support", 10, "charge-2", "", "support:10:10:y"
        )
        assert created2 and extended == 11

        perms = await db.set_admin(11, {"reports", "mute"}, 10)
        assert perms == {"reports", "mute"}
        assert await db.get_admin_permissions(11) == perms
        assert "ban" not in await db.get_admin_permissions(11)
        assert await db.get_admin_permissions(10, (10,))
        assert await db.remove_admin(11) is True
        assert not await db.get_admin_permissions(11)
        assert await db.adjust_xp(11, 50) == 50
        assert await db.adjust_xp(11, -80) == 0

        await db.ensure_user(11, None, "Аня")
        rid, day_count = await db.add_report(10, 11, "spam", "реклама казино", "10:11:1")
        assert rid >= 1 and day_count == 1
        duplicate, _ = await db.add_report(10, 11, "spam", "ещё", "10:11:1")
        assert duplicate is None
        rid2, unique_count = await db.add_report(10, 11, "spam", "новый диалог", "10:11:2")
        assert rid2 is not None and unique_count == 1, "один человек не накручивает авто-мут"
        await db.ensure_user(12, None, "Катя")
        await db.block_user(10, 11)
        await db.block_user(12, 10)
        assert await db.clear_blocks(10) == 1
        excluded = await db.excluded_partners(10, recent_seconds=0)
        assert 11 not in excluded and 12 in excluded
        rid3, unique_count = await db.add_report(12, 11, "spam", "независимая", "11:12:1")
        assert rid3 is not None and unique_count == 2
        reports = await db.list_reports("new")
        assert reports and reports[0]["target_id"] == 11

        until = await db.set_mute(11, 30)
        assert until > 0 and await db.is_restricted(11) == "muted"
        assert await db.resolve_report(rid, 10) is True
        assert await db.resolve_report(rid2, 10) is True
        assert await db.resolve_report(rid3, 10) is True
        assert await db.list_reports("new") == []
        await db.db.execute("UPDATE reports SET context='private', handled_at=1 WHERE id=?", (rid,))
        await db.db.commit()
        assert await db.cleanup_report_context(7) == 1
        assert (await db.get_report(rid))["context"] == ""

        match_id = await db.log_dialog(10, 11, 5, 4, 1_000, 10)
        assert 11 not in await db.excluded_partners(10), "недавний диалог не должен ломать очередь"
        assert await db.rate_dialog(match_id, 10, 1) == 11
        rated = await db.get_user(11)
        assert rated["good_ratings"] == 1

        stats = await db.stats()
        assert stats["users"] == 3 and stats["dialogs"] == 1

        await db.bump(10, "messages", 5)
        assert (await db.get_user(10))["messages"] == 5
        top = await db.top(5)
        assert top[0]["user_id"] == 10

        await db.set_ban(11, True, "спам")
        assert await db.is_restricted(11) == "banned"
        await db.forget_user(11)
        assert await db.is_restricted(11) == "banned", "/forget не снимает бан"
        deleted = await db.ensure_user(11, "restored", "Настоящее имя")
        assert deleted["username"] is None and deleted["first_name"] == "Удалённый пользователь"
        assert deleted["profile_deleted"] == 1
        await db.set_ban(11, False)

        await db.set_mute(12, 30)
        await db.forget_user(12)
        assert await db.is_restricted(12) == "muted", "/forget не снимает действующий мут"

        await db.forget_user(10)
        assert await db.get_user(10) is None
        assert (await db.stats())["dialogs"] == 1  # обезличенная история нужна для статистики
        await db.close()

    async def guarded() -> None:
        try:
            await scenario()
        finally:
            db = holder.get("db")
            if db is not None:
                await db.close()

    asyncio.run(guarded())


# --------------------------------------------------------------------------------- ники
def test_nickname_rules() -> None:
    from anonchat import nick

    assert nick.validate("  Ким   Вайнон  ")[0] == "Ким Вайнон"
    assert nick.validate("Магнитка1743")[1] is None
    assert nick.validate("  ")[0] == "" and nick.validate("  ")[1] is None  # пусто = сброс на авто-ник
    assert nick.validate("-")[1] is not None  # сам «-» разбирает set_nick, а не validate
    assert nick.validate("a")[1] and "минимум" in nick.validate("a")[1]
    assert nick.validate("з" * 30)[1] and "максимум" in nick.validate("з" * 30)[1]
    for bad in ("<b>ник</b>", "ник/соslash", "@username", "ник`x", "back\\slash"):
        assert nick.validate(bad)[1] is not None, bad
    assert nick.validate("Йцукен7 !?-_()")[1] is None
    assert nick.auto_nick(1001).startswith("Аноним-") and "1001" not in nick.auto_nick(1001)
    assert nick.auto_nick(-98765432).startswith("Аноним-")
    assert nick.display("", 5) == nick.auto_nick(5)
    assert nick.display("  ", 5) == nick.auto_nick(5)
    assert nick.display("Лена", 5) == "Лена"
    assert nick.display("Лена", 5, 1) == "Лена 💎"
    assert nick.display("Лена", 5, 0) == "Лена"
    assert nick.validate("Лена ✦")[1] is not None


# --------------------------------------------------------------------------------- кнопки
def test_keyboard_styles_and_icons() -> None:
    """Все клавиатуры: иконки — числовые id пака, цвета — только те, что принимает Bot API.

    «warning» Bot API отвергает (проверено живьём: Invalid button style specified),
    поэтому любая опечатка в style роняет отправку сообщения.
    """
    from anonchat import keyboards as K

    markups = [
        K.menu_keyboard("free"), K.menu_keyboard("queued", 3), K.menu_keyboard("paired"),
        K.menu_keyboard("free", admin=True), K.continue_keyboard(), K.age_keyboard(),
        K.chat_keyboard(), K.profile_keyboard("https://t.me/test_bot?start=ref_1"),
        K.district_keyboard(),
        K.settings_keyboard(True, "Правобережный", "Лена О"),
        K.report_keyboard(), K.rating_keyboard(), K.confirm_stop_keyboard(),
        K.confirm_forget_keyboard(), K.confirm_blocks_keyboard(),
        K.contact_confirm_keyboard(), K.back_menu_keyboard(), K.skip_cancel_keyboard(),
        K.admin_report_keyboard(1),
        K.admin_panel_keyboard(3, {"stats", "reports", "queue", "users", "broadcast", "mute", "ban", "points"}, True),
        K.users_page_keyboard(0, 30), K.panel_back_keyboard(),
        K.panel_cancel_keyboard(),
    ]
    icons = set()
    total = 0
    for markup in markups:
        for row in markup.inline_keyboard:
            for btn in row:
                data = btn.model_dump()
                total += 1
                style = data.get("style")
                assert style in (None, "") or style in K.STYLES, f"{btn.text}: style={style}"
                icon = data.get("icon_custom_emoji_id")
                if icon:
                    assert icon.isdigit(), f"{btn.text}: иконка не id — {icon}"
                    icons.add(icon)
    assert total >= 40, f"клавиатур стало подозрительно мало: {total} кнопок"
    assert len(icons) >= 12, f"иконки должны брать из пака, а не из одного места: {len(icons)}"
    # ни одна подпись не содержит юникодный эмодзи: маркер — иконка
    for markup in markups:
        for row in markup.inline_keyboard:
            for btn in row:
                if btn.text != "👍 Норм" and "⭐" not in btn.text:
                    assert all(
                        ord(c) < 0x2500 or c in "\ufe0f\ufe0e\u200d" for c in btn.text
                    ), f"в подписи кнопки остался юникодный эмодзи: {btn.text!r}"

    def texts_of(markup):
        return [btn.text for row in markup.inline_keyboard for btn in row]

    # в диалоге из меню остаются только действия диалога
    assert texts_of(K.menu_keyboard("paired")) == ["Следующий", "Стоп", "Жалоба"]
    # панель модератора: 9 разделов, счётчик жалоб в подписи
    panel = texts_of(K.admin_panel_keyboard(2, {"reports", "mute"}))
    assert panel == ["Жалобы · 2", "Мут по id", "В меню"], panel
    assert "Администраторы" in texts_of(K.admin_panel_keyboard(0, {"stats"}, True))
    # кнопка входа в панель появляется только у админа
    assert texts_of(K.menu_keyboard("free", admin=True))[-1] == "Панель модератора"
    assert texts_of(K.menu_keyboard("free"))[-1] == "Поддержать проект"


def test_contact_filter() -> None:
    from anonchat.safety import contains_contact

    for value in ("+7 999 123-45-67", "mail@example.com", "ул. Ленина 10"):
        assert contains_contact(value), value
    for value in ("@username", "https://example.com", "t.me/test"):
        assert not contains_contact(value), value
    assert not contains_contact("Привет, как дела?")


def test_stars_payment_validation() -> None:
    from types import SimpleNamespace

    from anonchat.handlers.support import _valid_payload

    good = SimpleNamespace(
        invoice_payload="support:42:25:abcdef", from_user=SimpleNamespace(id=42),
        currency="XTR", total_amount=25,
    )
    assert _valid_payload(good)
    premium = SimpleNamespace(
        invoice_payload="premium:42:30:abcdef", from_user=SimpleNamespace(id=42),
        currency="XTR", total_amount=129,
    )
    assert not _valid_payload(premium)
    assert not _valid_payload(SimpleNamespace(**{**good.__dict__, "currency": "RUB"}))
    assert not _valid_payload(SimpleNamespace(**{**good.__dict__, "total_amount": 24}))
    assert not _valid_payload(SimpleNamespace(**{**good.__dict__, "invoice_payload": "bad"}))


def test_retry_after_retries_real_delivery() -> None:
    from aiogram.exceptions import TelegramRetryAfter
    from aiogram.methods import SendMessage

    from anonchat.actions import DeliveryResult, send_copy_to, send_to

    class RetryBot:
        def __init__(self) -> None:
            self.calls = 0

        async def send_message(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise TelegramRetryAfter(SendMessage(chat_id=1, text="x"), "retry", 0)
            return object()

        async def send_chat_action(self, *args, **kwargs):
            return True

    class RetryMessage:
        def __init__(self) -> None:
            self.calls = 0

        async def send_copy(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise TelegramRetryAfter(SendMessage(chat_id=1, text="x"), "retry", 0)
            return object()

    async def scenario() -> None:
        bot = RetryBot()
        assert await send_to(bot, 1, "ok") is DeliveryResult.DELIVERED and bot.calls == 2
        message = RetryMessage()
        assert await send_copy_to(bot, message, 1) is DeliveryResult.DELIVERED and message.calls == 2

    asyncio.run(scenario())


def test_delivery_results() -> None:
    from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
    from aiogram.methods import SendMessage

    from anonchat.actions import DeliveryResult, send_to

    class ErrorBot:
        def __init__(self, exc: Exception) -> None:
            self.exc = exc

        async def send_message(self, *args, **kwargs):
            raise self.exc

    async def scenario() -> None:
        method = SendMessage(chat_id=1, text="x")
        forbidden = ErrorBot(TelegramForbiddenError(method, "bot was blocked"))
        temporary = ErrorBot(TelegramAPIError(method, "temporary failure"))
        assert await send_to(forbidden, 1, "x") is DeliveryResult.UNAVAILABLE
        assert await send_to(temporary, 1, "x") is DeliveryResult.TEMP_ERROR

    asyncio.run(scenario())


def test_screen_fallback_without_image() -> None:
    from types import SimpleNamespace

    from anonchat.actions import Ctx
    from anonchat.config import Config
    from anonchat.matching import Matchmaker
    from anonchat.pack import EmojiPack

    class Target:
        def __init__(self) -> None:
            self.sent = ""

        async def answer(self, text: str, **kwargs):
            self.sent = text
            return self

    async def scenario() -> None:
        target = Target()
        ctx = Ctx(
            bot=SimpleNamespace(), db=SimpleNamespace(), mm=Matchmaker(),
            cfg=Config(bot_token="1:T"), pack=EmojiPack(), event=target, user_id=1,
        )
        await ctx.render_screen("missing-screen.png", "fallback text")
        assert "fallback text" in target.sent

    asyncio.run(scenario())


def test_database_open_error_is_explicit() -> None:
    async def scenario() -> None:
        root = Path(tempfile.mkdtemp())
        parent_file = root / "not-a-directory"
        parent_file.write_text("x", encoding="utf-8")
        try:
            await Database(parent_file / "bot.db").start()
        except RuntimeError as exc:
            assert "SQLite" in str(exc)
        else:
            raise AssertionError("недоступный production DB path обязан завершать запуск")

    asyncio.run(scenario())


def test_supporter_persists_restart() -> None:
    async def scenario() -> None:
        path = Path(tempfile.mkdtemp()) / "support.db"
        db = await Database(path).start()
        await db.ensure_user(77, None, "Тест")
        created, support_total = await db.record_payment(
            77, "support", 1, "persist-charge", "", "support:77:1:x"
        )
        assert created and support_total == 1
        await db.close()
        reopened = await Database(path).start()
        try:
            assert int((await reopened.get_user(77))["support_stars"]) == support_total
        finally:
            await reopened.close()

    asyncio.run(scenario())


# --------------------------------------------------------------------------------- пак эмодзи
def test_pack_emoji() -> None:
    from anonchat.pack import ICONS, PACK, EmojiPack

    # id пака зашиты в код: премиум-эмодзи работают с первого сообщения, ничего ждать не надо
    assert len(PACK) >= 20 and len(ICONS) == len(PACK)
    assert all(emoji_id.isdigit() for emoji_id, _, _ in PACK.values()), "custom_emoji_id — цифры"
    fresh = EmojiPack()
    assert fresh.wrap("📊 Профиль") == '<tg-emoji emoji-id="5231200819986047254">📊</tg-emoji> Профиль'

    pack = EmojiPack("https://t.me/addemoji/NewsEmoji")
    assert pack.wrap("🧲 старт") == "🧲 старт"  # магнита в паке нет — остаётся юникодом
    assert not hasattr(pack, "harvest"), "сообщения пользователей не меняют UI emoji"

    # алиасы: в тексте «✅», в паке этот же знак «✔️» — внутрь тега у канонический символ
    aliased = pack.wrap("✅ готово")
    assert aliased == '<tg-emoji emoji-id="5206607081334906820">✔️</tg-emoji> готово', aliased

    # один и тот же знак в сообщении оборачиваем один раз — глазами это один акцент
    twice = pack.wrap("📊 и ещё 📊")
    assert twice.count("<tg-emoji") == 1, twice

    # лимит подмены: украшаем максимум N эмодзи в сообщении, начиная с заголовка
    limited = pack.wrap("📊⭐⚙️💬", limit=2)
    assert limited.count("<tg-emoji") == 2, limited

    # Telegram запретил тег — откатываемся и больше не пробуем
    assert pack.accept(Exception("Bad Request: can't parse entities: tg-emoji is unsupported")) is True
    assert pack.enabled is False
    assert pack.wrap("🧲 старт") == "🧲 старт"


# --------------------------------------------------------------------------------- база: ник + миграция
def test_db_nickname_and_kv() -> None:
    import sqlite3

    async def scenario() -> None:
        tmp = Path(tempfile.mkdtemp()) / "migrate.db"
        # база, созданная более ранней версией бота: без колонки nickname и таблицы kv
        old = sqlite3.connect(tmp)
        old.execute(
            """CREATE TABLE users (
                   user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
                   created_at INTEGER NOT NULL DEFAULT 0, last_seen INTEGER NOT NULL DEFAULT 0,
                   xp INTEGER NOT NULL DEFAULT 0, messages INTEGER NOT NULL DEFAULT 0,
                   dialogs INTEGER NOT NULL DEFAULT 0, good_ratings INTEGER NOT NULL DEFAULT 0,
                   bad_ratings INTEGER NOT NULL DEFAULT 0, reports_sent INTEGER NOT NULL DEFAULT 0,
                   reports_received INTEGER NOT NULL DEFAULT 0, district TEXT NOT NULL DEFAULT '',
                   gender TEXT NOT NULL DEFAULT '', same_district INTEGER NOT NULL DEFAULT 0,
                   about TEXT NOT NULL DEFAULT '', banned INTEGER NOT NULL DEFAULT 0,
                   ban_reason TEXT NOT NULL DEFAULT '', mute_until INTEGER NOT NULL DEFAULT 0)"""
        )
        old.execute("INSERT INTO users (user_id, first_name, xp) VALUES (7, 'Олд', 100)")
        old.commit()
        old.close()

        db = await Database(tmp).start()
        try:
            assert await db.get_user(7) is not None, "старые данные не потерялись"
            assert (await db.get_user(7))["nickname"] == "", "колонка nickname добавлена на лету"

            await db.set_profile(7, nickname="Старожил")
            assert (await db.get_user(7))["nickname"] == "Старожил"
            assert await db.nickname_taken("старожил") == 7, "кириллица тоже сравнивается без регистра"
            assert await db.nickname_taken("СТАРОЖИЛ") == 7
            assert await db.nickname_taken("Старожил", except_user_id=7) is None
            assert await db.nickname_taken("Свободный") is None
            assert await db.nickname_taken("") is None

            await db.set_kv("emoji_ids", '[["🧲","AAA"]]')
            assert await db.get_kv("emoji_ids") == '[["🧲","AAA"]]'
            await db.set_kv("emoji_ids", '[["🧲","BBB"]]')
            assert await db.get_kv("emoji_ids") == '[["🧲","BBB"]]'
            assert await db.get_kv("нет-такого", "дефолт") == "дефолт"

            top = await db.top(5)
            assert top[0]["nickname"] == "Старожил", "в топ уходит ник, а не настоящее имя"
            assert "first_name" not in top[0].keys()
        finally:
            await db.close()

    asyncio.run(scenario())  # внутри scenario db закрывается в finally — процесс не зависнет


def run_all() -> int:  # python -m tests.core
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\nall {len(fns)} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_all())
