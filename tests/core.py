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

    saved = {k: os.environ.get(k) for k in ("BOT_TOKEN", "CITY_NAME", "ADMIN_IDS", "AUTO_MUTE_REPORTS")}
    os.environ["BOT_TOKEN"] = "12:TEST"
    os.environ.pop("CITY_NAME", None)
    os.environ["ADMIN_IDS"] = "777, 888"
    try:
        cfg = Config.from_env(dotenv=".__no_such_env__.local")
        assert cfg.city == "Магнитогорск" and cfg.city_short == "МГН"
        assert cfg.admin_ids == (777, 888)
        assert cfg.auto_mute_reports == 3 and isinstance(cfg.auto_mute_reports, int)
        assert cfg.emoji_pack_url.startswith("https://t.me/addemoji/")
        assert cfg.max_message_len == 3000

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
    """Ранги — по сообщениям: 🔰 Старт → 🥉 Бронза → 🥈 Серебро → 🥇 Золото → 💎 VIP."""
    first = rank_for(0)
    assert first.index == 1 and first.title == "Старт" and first.emoji == "🔰"
    assert first.progress == 0.0 and first.to_next == 1_000 and first.next_title == "Бронза"

    bronze = rank_for(1_000)
    assert bronze.title == "Бронза" and bronze.progress == 0.0
    assert bronze.to_next == 14_000 and bronze.next_title == "Серебро"

    mid = rank_for(8_000)
    assert mid.title == "Бронза" and 0.4 < mid.progress < 0.6
    assert len(mid.bar) == 8 and mid.bar.startswith("▰▰▰▰▱")

    silver = rank_for(15_000)
    assert silver.title == "Серебро" and silver.emoji == "🥈"
    gold = rank_for(100_000)
    assert gold.title == "Золото" and gold.emoji == "🥇"
    vip = rank_for(500_000)
    assert vip.title == "VIP" and vip.emoji == "💎" and vip.is_max and vip.to_next is None
    assert rank_for(99_999_999).index == len(RANKS)

    # человекочитаемые числа с неразрывными пробелами
    assert rank_for(15_000).pretty(12345) == "12 345"
    assert "15 000" in rank_for(12_345).label
    assert rank_for(0).name == "🔰 Старт"


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
    mm.refresh(1, district="Правобережный", gender="", same_district=False)
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


# --------------------------------------------------------------------------------- database
def test_database() -> None:
    holder: dict[str, object] = {}

    async def scenario() -> None:
        path = Path(tempfile.mkdtemp()) / "t.db"
        db = await Database(path).start()
        holder["db"] = db

        row = await db.ensure_user(10, "petr", "Пётр")
        assert row["xp"] == 0 and row["district"] == ""

        await db.set_profile(10, district="Правобережный", about="люблю ММК и тишину")
        row = await db.get_user(10)
        assert row["district"] == "Правобережный"

        assert await db.award_xp(10, 70) == 70
        assert rank_for(70).title == "Старт", "70 сообщений — ещё не бронза"
        assert rank_for(1_000).title == "Бронза"

        await db.ensure_user(11, None, "Аня")
        rid, day_count = await db.add_report(10, 11, "spam", "реклама казино")
        assert rid >= 1 and day_count == 1
        reports = await db.list_reports("new")
        assert reports and reports[0]["target_id"] == 11

        until = await db.set_mute(11, 30)
        assert until > 0 and await db.is_restricted(11) == "muted"
        assert await db.resolve_report(rid, 10) is True
        assert await db.list_reports("new") == []

        match_id = await db.log_dialog(10, 11, 5, 4, 1_000, 10)
        assert await db.rate_dialog(match_id, 10, 1) == 11
        rated = await db.get_user(11)
        assert rated["good_ratings"] == 1

        stats = await db.stats()
        assert stats["users"] == 2 and stats["dialogs"] == 1

        await db.bump(10, "messages", 5)
        assert (await db.get_user(10))["messages"] == 5
        top = await db.top(5)
        assert top[0]["user_id"] == 10

        await db.set_ban(11, True, "спам")
        assert await db.is_restricted(11) == "banned"
        await db.set_ban(11, False)
        assert await db.is_restricted(11) is None

        await db.forget_user(10)
        assert await db.get_user(10) is None
        assert (await db.stats())["dialogs"] == 0  # диалоги удалённого пользователя тоже стёрты
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
    assert nick.auto_nick(1001) == "Аноним-1001"
    assert nick.auto_nick(-98765432) == "Аноним-5432"  # отрицательные id тоже не ломают ник
    assert nick.display("", 5) == "Аноним-0005"
    assert nick.display("  ", 5) == "Аноним-0005"
    assert nick.display("Лена", 5) == "Лена"


# --------------------------------------------------------------------------------- кнопки
def test_keyboard_styles_and_icons() -> None:
    """Все клавиатуры: иконки — числовые id пака, цвета — только те, что принимает Bot API.

    «warning» Bot API отвергает (проверено живьём: Invalid button style specified),
    поэтому любая опечатка в style роняет отправку сообщения.
    """
    from anonchat import keyboards as K

    markups = [
        K.menu_keyboard("free"), K.menu_keyboard("queued", 3), K.menu_keyboard("paired"),
        K.district_keyboard(), K.gender_keyboard(),
        K.settings_keyboard(True, "Правобережный", "Лена О", True),
        K.report_keyboard(), K.rating_keyboard(), K.confirm_stop_keyboard(),
        K.confirm_forget_keyboard(), K.back_menu_keyboard(), K.skip_cancel_keyboard(),
        K.admin_report_keyboard(1),
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
                assert all(
                    ord(c) < 0x2500 or c in "\ufe0f\ufe0e\u200d" for c in btn.text
                ), f"в подписи кнопки остался юникодный эмодзи: {btn.text!r}"


# --------------------------------------------------------------------------------- пак эмодзи
def test_pack_emoji() -> None:
    from types import SimpleNamespace

    from anonchat.pack import ICONS, PACK, EmojiPack

    def fake_message(text: str, emoji_id: str, length: int) -> SimpleNamespace:
        entity = SimpleNamespace(type="custom_emoji", offset=0, length=length, custom_emoji_id=emoji_id)
        return SimpleNamespace(text=text, entities=[entity])

    # id пака зашиты в код: премиум-эмодзи работают с первого сообщения, ничего ждать не надо
    assert len(PACK) >= 20 and len(ICONS) == len(PACK)
    assert all(emoji_id.isdigit() for emoji_id, _, _ in PACK.values()), "custom_emoji_id — цифры"
    fresh = EmojiPack()
    assert fresh.wrap("📊 Профиль") == '<tg-emoji emoji-id="5231200819986047254">📊</tg-emoji> Профиль'
    assert fresh.extra() == 0 and fresh.as_pairs() == [], "встроенное в код в базу не пишем"

    pack = EmojiPack("https://t.me/addemoji/NewsEmoji")
    assert pack.wrap("🧲 старт") == "🧲 старт"  # магнита в паке нет — остаётся юникодом

    assert pack.harvest(fake_message("🧲 привет", "AAA111", 2)) == ["🧲"]
    assert pack.has("🧲") and pack.extra() == 1
    assert pack.harvest(fake_message("🧲 ещё раз", "AAA222", 2)) == []  # символ уже известен
    assert pack.as_pairs() == [("🧲", "AAA222")], "id обновляем на последний увиденный"

    assert pack.wrap("🧲 старт") == '<tg-emoji emoji-id="AAA222">🧲</tg-emoji> старт'
    assert pack.strip(pack.wrap("🧲 старт")).startswith("🧲 старт")

    # алиасы: в тексте «✅», в паке этот же знак «✔️» — внутрь тега у канонический символ
    aliased = pack.wrap("✅ готово")
    assert aliased == '<tg-emoji emoji-id="5206607081334906820">✔️</tg-emoji> готово', aliased

    # один и тот же знак в сообщении оборачиваем один раз — глазами это один акцент
    twice = pack.wrap("📊 и ещё 📊")
    assert twice.count("<tg-emoji") == 1, twice

    # ZWJ-последовательность целиком, а не по половинкам (🙋‍♂️ = 5 единиц UTF-16)
    pack.harvest(fake_message("🙋‍♂️ хай", "BBB333", 5))
    wrapped = pack.wrap("🙋‍♂️ и ещё 🧲")
    assert 'emoji-id="BBB333">🙋‍♂️<' in wrapped, wrapped

    # битая длина у entity не должна ронять бота и резать эмодзи пополам
    broken = EmojiPack()
    broken.harvest(fake_message("🙋‍♂️ хай", "XXX", 3))
    assert broken.extra() == 0, "осколки ZWJ-последовательности не запоминаем"

    # лимит подмены: украшаем максимум N эмодзи в сообщении, начиная с заголовка
    pack.load([("✨", "CCC"), ("🕓", "DDD"), ("⏳", "EEE")])
    limited = pack.wrap("✨🕓⏳🧲", limit=2)
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
