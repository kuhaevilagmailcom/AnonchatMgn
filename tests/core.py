"""Самопроверка ядра: уровни, матчмейкер, база. Запуск: pytest -q (или python -m tests.core)."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anonchat.db import Database  # noqa: E402
from anonchat.levels import LEVELS, level_for  # noqa: E402
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
    first = level_for(0)
    assert first.level == 1 and first.title == LEVELS[0][1]
    assert first.progress == 0.0 and first.to_next == LEVELS[1][0]

    mid = level_for(150)
    assert mid.level == 3, mid
    assert 0.0 < mid.progress < 1.0
    assert len(mid.bar) == 10 and mid.bar.startswith("▓")

    top = level_for(999_999)
    assert top.level == len(LEVELS) and top.to_next is None


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
        assert level_for(70).level == 2

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


def run_all() -> int:  # python -m tests.core
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\nall {len(fns)} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_all())
