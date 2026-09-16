"""Интегральный прогон без сети: апдейты идут в Dispatcher, ответы пишутся в запись.

Запуск:  python -m tests.flow      (или pytest -q tests/flow.py)
Проверяет реальный сценарий: /start → 🔎 → ⏭/⏹ → профиль → 🚩 жалоба → оценка.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, Update, User

from anonchat import commands as commands_mod
from anonchat import texts
from anonchat.commands import register_common
from anonchat.config import Config
from anonchat.db import Database
from anonchat.handlers import get_routers
from anonchat.matching import Matchmaker
from anonchat.middlewares import DataContext, Throttling
from anonchat.pack import ICONS as PACK_ICONS
from anonchat.pack import EmojiPack

ADMIN = 999
A, B, C = 1001, 1002, 1003


class RecordingSession(BaseSession):
    """Фейковая Bot API: всё отправленное ботом попадает в self.outbox."""

    def __init__(self) -> None:
        super().__init__()
        self.outbox: list[dict[str, Any]] = []
        #: setMyCommands переживают clear() — проверяем, что именно уехало в Telegram
        self.menus: list[dict[str, Any]] = []
        self._mid = 0

    async def close(self) -> None:  # pragma: no cover
        return None

    async def stream_content(self, *a: Any, **k: Any):  # pragma: no cover
        yield b""

    async def make_request(self, bot: Bot, method: Any, timeout: int | None = None) -> Any:
        name = method.__api_method__
        data = method.model_dump(exclude_none=True, by_alias=True)
        self.outbox.append({"method": name, **data})
        if name == "setMyCommands":
            self.menus.append(data)

        if name == "getMe":
            return User(id=777, is_bot=True, first_name="Анончат", username="anonchat_mgn_bot")
        if name in {"getUpdates", "deleteWebhook", "setMyCommands", "answerCallbackQuery"}:
            return True if name == "answerCallbackQuery" else []
        self._mid += 1
        return Message(
            message_id=self._mid,
            date=1_700_000_000,
            chat=Chat(id=int(data.get("chat_id", 0)), type="private"),
            text=data.get("text"),
            caption=data.get("caption"),
        )

    # ------------------------------------------------------------------ helpers
    def to(self, chat_id: int) -> list[dict[str, Any]]:
        return [m for m in self.outbox if m.get("chat_id") == chat_id]

    def texts_to(self, chat_id: int) -> list[str]:
        return [str(m.get("text") or m.get("caption") or "") for m in self.to(chat_id)]

    def last_to(self, chat_id: int) -> str:
        texts = self.texts_to(chat_id)
        return texts[-1] if texts else ""

    def has_keyboard(self, chat_id: int) -> bool:
        return any(m.get("reply_markup") for m in self.to(chat_id))

    def clear(self) -> None:
        self.outbox.clear()


def msg_update(bot: Bot, uid: int, text: str, update_id: int, entities: list[dict] | None = None) -> Update:
    message: dict[str, Any] = {
        "message_id": update_id,
        "date": 1_700_000_000,
        "chat": {"id": uid, "type": "private", "first_name": f"U{uid}"},
        "from": {"id": uid, "is_bot": False, "first_name": f"U{uid}"},
        "text": text,
    }
    if entities:
        message["entities"] = entities
    payload = {"update_id": update_id, "message": message}
    return Update.model_validate(payload, context={"bot": bot})


def cb_update(bot: Bot, uid: int, data: str, update_id: int) -> Update:
    payload = {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb{update_id}",
            "chat_instance": "1",
            "from": {"id": uid, "is_bot": False, "first_name": f"U{uid}"},
            "data": data,
            "message": {
                "message_id": update_id,
                "date": 1_700_000_000,
                "chat": {"id": uid, "type": "private", "first_name": f"U{uid}"},
                "from": {"id": uid, "is_bot": False, "first_name": f"U{uid}"},
                "text": "меню",
            },
        },
    }
    return Update.model_validate(payload, context={"bot": bot})


async def run_flow(holder: dict[str, Any] | None = None) -> None:
    tmp = Path(tempfile.mkdtemp())
    cfg = Config(bot_token="42:TEST", admin_ids=(ADMIN,), db_path=tmp / "flow.db")
    db = await Database(cfg.db_path).start()
    if holder is not None:
        holder["db"] = db
    mm = Matchmaker()
    session = RecordingSession()
    bot = Bot(
        cfg.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())
    pack = EmojiPack(cfg.emoji_pack_url)
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(Throttling(cfg, limit=200))
        observer.middleware(DataContext(cfg, db, mm, pack))
    for router in get_routers():
        dp.include_router(router)
    await register_common(bot, cfg)  # как это делает main.py на старте

    step = 0

    async def send(uid: int, text: str, entities: list[dict] | None = None) -> None:
        nonlocal step
        step += 1
        await dp.feed_update(bot, msg_update(bot, uid, text, step, entities))

    async def press(uid: int, data: str) -> None:
        nonlocal step
        step += 1
        await dp.feed_update(bot, cb_update(bot, uid, data, step))

    def check(cond: bool, label: str) -> None:
        if not cond:
            raise AssertionError(f"{label}\noutbox A/B: {session.texts_to(A)} | {session.texts_to(B)}")
        print(f"  ok  {label}")

    # 1. /start — приветствие, авто-ник и минималистичное меню
    await send(A, "/start")
    check("Анонимный чат" in session.last_to(A), "/start показывает приветствие с меню")
    check("Аноним-1001" in session.last_to(A), "при первом входе выдаётся авто-ник вместо имени из Telegram")
    check((await db.get_user(A))["nickname"] == "Аноним-1001", "авто-ник сохранился в базу")
    check(session.has_keyboard(A), "в меню есть инлайн-кнопки")
    kb = session.to(A)[-1]["reply_markup"]["inline_keyboard"]
    buttons = [btn for row in kb for btn in row]
    labels = [btn["text"] for btn in buttons]
    for needle in (
        "Поиск собеседника",
        "Следующий",
        "Стоп",
        "Жалоба",
        "Профиль",
        "Настройки",
        "Топ",
        "Правила",
        "Помощь",
    ):
        check(needle in labels, f"кнопка «{needle}» на месте")
    check(len(labels) == 9, f"в главном меню 9 кнопок, не {len(labels)}")
    check(
        all("url" not in str(btn) for btn in buttons),
        "кнопки с эмодзи-паком в меню больше нет (ссылка осталась в /help)",
    )
    # эмодзи на кнопках — анимированные из пака, а не юникодные в подписи
    check(
        all(btn.get("icon_custom_emoji_id") for btn in buttons),
        f"у каждой кнопки есть icon_custom_emoji_id: {[list(b) for b in buttons[:2]]}",
    )
    check(
        all(str(btn["icon_custom_emoji_id"]).isdigit() for btn in buttons),
        "id эмодзи — числовой, как в NewsEmoji",
    )
    check(
        all(not any(ord(c) > 0x2500 for c in t) for t in labels),
        f"подписи кнопок чистые, эмодзи — иконкой: {labels}",
    )
    styles = {btn["text"]: btn.get("style") for btn in buttons}
    check(styles["Поиск собеседника"] == "success", "главное действие подсвечено")
    check(styles["Стоп"] == "danger", "стоп — красный")
    check(
        f'<tg-emoji emoji-id="{PACK_ICONS["profile"]}">🙂</tg-emoji>' in session.last_to(A),
        "приветствие сразу пишет премиум-эмодзи пака (не юникодный значок)",
    )

    # 2. A жмёт поиск — встаёт в очередь
    session.clear()
    await press(A, "act:connect")
    check("Ищу пару" in session.last_to(A), "кнопка 🔎 ставит в очередь")
    check(mm.status(A) == "queued", "матчмейкер видит A в очереди")

    # 3. B жмёт поиск — сводим обоих
    await send(B, "/start")
    session.clear()
    await press(B, "act:connect")
    check(mm.partner(A) == B and mm.partner(B) == A, "A и B стали парой")
    check("Собеседник найден" in session.last_to(A), "A получил «Собеседник найден»")
    check("Собеседник найден" in session.last_to(B), "B получил «Собеседник найден»")
    check("/next" in session.last_to(A) and "/stop" in session.last_to(A), "в тексте подсказки /next и /stop")
    check(
        all(m.get("reply_markup") is None for m in session.to(A) + session.to(B) if m["method"] == "sendMessage"),
        "на сообщении о паре — никаких кнопок, только текст с командами",
    )
    matched_a = session.texts_to(A)[-1] if session.to(A) else session.last_to(A)
    check("Аноним-1002" in matched_a, "A видит ник найденного собеседника")
    check("Старт" in matched_a and "сообщ" in matched_a, "в карточке собеседника ранг и число сообщений")
    check("жалоб: 0" in matched_a and "👍" in matched_a and "⭐" in matched_a,
          "в карточке собеседника опыт, оценки и жалобы")
    check("Ты в чате как" in matched_a and "Аноним-1001" in matched_a, "A видит и свой ник в этом диалоге")
    check("Аноним-1001" in session.last_to(B), "B видит ник A, а не его настоящее имя")
    check("U1001" not in session.last_to(B) and "Аня" not in session.last_to(B),
          "реальные имя/id собеседнику не показываются")

    # 4. анонимная пересылка туда-сюда
    session.clear()
    await send(A, "Привет! Ты с какой стороны Магнитки?")
    check("Привет! Ты с какой стороны Магнитки?" in session.last_to(B), "сообщение дошло B")
    check(session.to(A) == [], "бот не пишет «доставлено анонимно» — человек и так всё понял")
    await send(B, "С Правобережного 🙂")
    check("С Правобережного" in session.last_to(A), "ответ дошёл A")
    await send(A, "О, тогда нам по пути — я от Вокзала")
    await send(B, "Бывает 🙂")
    await send(A, "Как тебе наш снег?")
    await send(B, "Хуже, чем обычно")

    # 5. мусорные типы не пересылаем, команды не теряем
    session.clear()
    await send(A, "/unknowncmd")
    check("Не знаю такой команды" in session.last_to(A), "неизвестная команда не улетает собеседнику")

    # 5b. пока идёт диалог — свои экраны закрыты, надо /stop
    session.clear()
    await send(A, "/profile")
    check("заверши диалог" in session.last_to(A).lower() and "/stop" in session.last_to(A),
          "в диалоге профиль закрыт: просит /stop")
    check(mm.status(A) == "paired", "диалог при этом не распался")
    session.clear()
    await press(A, "act:settings")
    check("заверши диалог" in session.last_to(A).lower(), "и настройки закрыты в диалоге")
    session.clear()
    await press(A, "act:top")
    check("заверши диалог" in session.last_to(A).lower(), "топ тоже закрыт до /stop")
    session.clear()
    await press(A, "act:connect")
    check("уже в диалоге" in session.last_to(A).lower(), "повторный поиск говорит, что ты в диалоге")
    kb_paired = session.to(A)[-1]["reply_markup"]["inline_keyboard"]
    paired_labels = [btn["text"] for row in kb_paired for btn in row]
    check(
        len(paired_labels) == 4 and "Профиль" not in paired_labels and "Настройки" not in paired_labels,
        f"в меню во время диалога только действия диалога: {paired_labels}",
    )

    # 6. стоп + начисление опыта
    session.clear()
    await send(A, "/stop")
    check(mm.status(A) == "free" and mm.status(B) == "free", "после /stop оба свободны")
    check("Остановить диалог" in " ".join(session.texts_to(A)) or "диалог остановлен" in session.last_to(A).lower(),
          "A получил подтверждение остановки")
    check("собеседник вышел" in " ".join(session.texts_to(B)).lower(), "B узнал, что собеседник вышел")
    row_a = await db.get_user(A)
    check(row_a["dialogs"] == 1, "диалог записан в статистику")

    # 7. оценка собеседника (+XP тому, кого оценили)
    session.clear()
    before_b = (await db.get_user(B))["xp"]
    await press(A, "rate:1")
    after_b = (await db.get_user(B))["xp"]
    check(after_b - before_b == cfg.xp_good_rating, "👍 добавило собеседнику xp_good_rating")
    check((await db.get_user(A))["xp"] >= 2, "за сообщения потёк опыт")
    await press(A, "rate:1")
    check((await db.get_user(B))["xp"] == after_b, "повторная та же оценка ничего не добавляет")

    # 8. настройки и профиль
    session.clear()
    await press(A, "act:settings")
    await press(A, "cfg:district:right")
    check((await db.get_user(A))["district"] == "Правобережный", "район сохранился")
    await send(A, "/profile")
    card = session.last_to(A)
    check("Старт" in card and "🔰" in card, "профиль показывает ранг по числу сообщений")
    check("<code>▱▱▱▱" in card, "полоса прогресса до следующего ранга на месте")
    check("⭐" in card and "Сообщений" in card and "✍️" in card, "профиль — карточка со статистикой")
    check("до «Бронза»" in card and "1 000" in card, "видно, сколько осталось до Бронзы")

    # 8b. свой ник вместо реального имени
    session.clear()
    await send(A, "/nick Ким Вайнон")
    check((await db.get_user(A))["nickname"] == "Ким Вайнон", "/nick сохранил выбранный ник")
    check("Ким Вайнон" in " ".join(session.texts_to(A)), "бот подтвердил ник")
    await send(B, "/nick Ким Вайнон")
    check("уже занят" in " ".join(session.texts_to(B)), "дубликат ника не проходят")
    await send(B, "/nick Магнит")
    check((await db.get_user(B))["nickname"] == "Магнит", "свободный ник принимается")
    await send(A, "/nick " + "а" * 40)
    check("максимум" in " ".join(session.texts_to(A)).lower(), "слишком длинный ник отклонён")
    await send(A, "/nick <b>хакер</b>")
    check("<b>хакер" not in " ".join(session.texts_to(A)), "HTML-мусор в ник не проскакивает")
    await send(A, "/nick Лена О")
    check((await db.get_user(A))["nickname"] == "Лена О", "ник с пробелом нормален")
    await send(A, "/nick -")
    check((await db.get_user(A))["nickname"] == "Аноним-1001", "«-» возвращает авто-ник")
    await send(A, "/nick Лена О")
    check((await db.get_user(A))["nickname"] == "Лена О", "ник можно вернуть обратно")
    # после команды с аргументом (даже неудачным) обычный текст должен доходить собеседнику
    await press(A, "act:connect")
    await press(B, "act:connect")
    check(mm.partner(A) == B, "A и B снова в паре")
    session.clear()
    await send(A, "обычное сообщение в чат")
    check("обычное сообщение в чат" in session.last_to(B), "текст уходит собеседнику, а не съедается вводом ника")
    await send(A, "/stop")

    session.clear()
    await send(ADMIN, "/top")
    top_text = " ".join(session.texts_to(ADMIN))
    check("Лена О" in top_text and "Магнит" in top_text, "в топе — выбранные ники")
    check("U1001" not in top_text and "U1002" not in top_text, "в топе нет реальных имён из Telegram")

    # 8c. эмодзи из городского пака в текстах бота
    session.clear()
    await send(
        A,
        "🧲 привет",
        entities=[{"type": "custom_emoji", "offset": 0, "length": 2, "custom_emoji_id": "AQADBAD123"}],
    )
    check(pack.extra() == 1 and pack.has("🧲"), "бот подсмотрел id эмодзи из пака у пользователя")
    check(json.loads(await db.get_kv("emoji_ids")) == [["🧲", "AQADBAD123"]], "id эмодзи пережил рестарт (в базе)")
    await send(A, "/start")
    check(
        '<tg-emoji emoji-id="AQADBAD123">🧲</tg-emoji>' in session.last_to(A),
        "в своих текстах бот использует эмодзи из пака",
    )
    pack.enabled = False  # Telegram может запретить — проверяем откат
    await send(A, "/start")
    check("tg-emoji" not in session.last_to(A), "если эмодзи недоступны — текст уходит обычными смайлами")
    pack.enabled = True

    # 9. жалоба от A на C
    session.clear()
    await press(A, "act:connect")
    await send(C, "/start")
    await press(C, "act:connect")
    check(mm.partner(A) == C, "A и C в паре")
    await send(A, "тебе спамить буду")
    await press(A, "act:report")
    await press(A, "rep:spam")
    await send(A, "реклама казино, бесячье")
    card = " ".join(session.texts_to(ADMIN))
    check("Жалоба #" in card and "spam" in card.lower() or "Спам" in card, "админ получил карточку жалобы")
    check(str(C) in card, "в карточке есть id нарушителя")
    reports = await db.list_reports("new")
    check(len(reports) == 1 and reports[0]["target_id"] == C, "жалоба легла в базу")
    check(mm.partner(A) == C, "жалоба сама по себе диалог не рвёт")

    # 10. админ мутит нарушителя и закрывает жалобу
    session.clear()
    await press(ADMIN, f"adm:mute:{reports[0]['id']}")
    check(await db.is_restricted(C) == "muted", "по кнопке нарушитель ушёл в мут")
    check(await db.list_reports("new") == [], "жалоба закрыта")
    check(mm.status(C) == "free", "мут расцепил пару")
    await press(A, "act:stop")

    # 11. следующий собеседник
    session.clear()
    await press(A, "act:connect")
    await press(B, "act:connect")
    check(mm.partner(A) == B, "A снова в паре с B")
    session.clear()
    await press(A, "act:next")
    check(mm.status(A) in {"queued", "paired"}, "после «Следующий» A снова в поиске")
    check("собеседник сменил чат" in " ".join(session.texts_to(B)).lower()
          or mm.status(B) in {"free", "queued", "paired"}, "B уведомлён о скипе")

    # 12. чужие команды модерации недоступны
    session.clear()
    await send(A, "/stats")
    check("Доступ только у админов" in session.last_to(A), "/stats не для обычных пользователей")
    await send(ADMIN, "/stats")
    check("сводка" in session.last_to(ADMIN).lower(), "админ видит статистику")

    # 13. право на забвение
    session.clear()
    await press(A, "act:settings")
    await press(A, "cfg:forget:ask")
    await press(A, "cfg:forget:yes")
    check(await db.get_user(A) is None, "/forget стёр профиль полностью")

    # 14. админские команды модерации
    session.clear()
    # считаем, что при старте процесса админу ещё не могли поставить меню (чат «не найден»):
    # /start обязан донастроить личное меню модератора
    commands_mod._done.clear()
    await send(ADMIN, "/start")
    check(
        any(m["method"] == "setMyCommands" for m in session.outbox),
        "/start админа донастраивает личное меню модератора",
    )
    await send(ADMIN, "/queue")
    check("Очередь" in session.last_to(ADMIN), "/queue показывает очередь")
    await send(ADMIN, f"/find {B}")
    check(str(B) in session.last_to(ADMIN), "/find нашёл пользователя по id")
    await send(ADMIN, "/resolve")
    check("Формат" in session.last_to(ADMIN), "/resolve без аргументов подсказывает формат")

    await send(ADMIN, f"/ban {B} спам и хамство")
    check(await db.is_restricted(B) == "banned", "/ban забанил пользователя")
    session.clear()
    await press(B, "act:connect")
    check("заблокирован" in session.last_to(B).lower(), "баненному отказано в поиске пары")
    check(mm.status(B) == "free", "бан выкинул из очереди/пары")

    session.clear()
    await send(ADMIN, f"/unban {B}")
    check(await db.is_restricted(B) is None, "/unban вернул в игру")
    await send(ADMIN, "/bc 🌨 Первый снег — болтайте тёпло!")
    check("Рассылаю" in " ".join(session.texts_to(ADMIN)), "/bc запущен и отчитался")
    check(any("Первый снег" in t for t in session.texts_to(B)), "рассылка дошла пользователю")

    await send(ADMIN, "/mute 4242 5")
    check("заглушён на 5 мин" in session.last_to(ADMIN), "/mute работает даже по «сырому» id")
    check(await db.is_restricted(4242) == "muted", "мут применился и создал заглушку-профиль")

    # 15. панель модератора: всё кнопками, команды наружу не торчат
    session.clear()
    await send(ADMIN, "/admin")
    check("Панель модератора" in session.last_to(ADMIN), "/admin открыл панель модератора")
    kb = session.to(ADMIN)[-1]["reply_markup"]["inline_keyboard"]
    panel_labels = [btn["text"] for row in kb for btn in row]
    check(
        all(x in panel_labels for x in ("Сводка", "Жалобы", "Очередь", "Найти профиль", "Рассылка",
                                        "Мут по id", "Бан по id", "Разбан по id", "В меню")),
        f"в панели все разделы: {panel_labels}",
    )
    check(
        all(btn.get("icon_custom_emoji_id") for row in kb for btn in row),
        "кнопки панели тоже с эмодзи из пака",
    )

    session.clear()
    await press(ADMIN, "adm:panel:stats")
    check("сводка" in session.last_to(ADMIN).lower() and "Пользователей" in session.last_to(ADMIN),
          "кнопка «Сводка» показывает статистику, не уходя из панели")
    await press(ADMIN, "adm:panel:queue")
    check("Очередь" in session.last_to(ADMIN), "кнопка «Очередь» показывает очередь")
    await press(ADMIN, "adm:panel:back")
    check("Панель модератора" in session.last_to(ADMIN), "«Назад в панель» возвращает")

    await press(ADMIN, "adm:panel:find")
    check("Кого ищем" in session.last_to(ADMIN), "«Найти профиль» спрашивает, кого искать")
    await send(ADMIN, str(B))
    admin_tape = " ".join(session.texts_to(ADMIN))
    check(str(B) in admin_tape, "поиск по id из панели сработал")
    check("Панель модератора" in session.last_to(ADMIN), "после действия вернулись в панель")

    await press(ADMIN, "adm:panel:ban")
    check("Кому бан" in session.last_to(ADMIN), "«Бан по id» просит id и причину")
    await send(ADMIN, f"{C} спам с панели")
    check(await db.is_restricted(C) == "banned", "бан из панели применился")
    check("забанен" in " ".join(session.texts_to(ADMIN)).lower(), "панель отчиталась о бане")
    await press(ADMIN, "adm:panel:unban")
    await send(ADMIN, str(C))
    check(await db.is_restricted(C) is None, "разбан из панели вернул пользователя")

    await press(ADMIN, "adm:panel:mute")
    await send(ADMIN, "-")
    check("Отменил" in " ".join(session.texts_to(ADMIN)), "«-» отменяет ввод и возвращает в панель")

    def menu_for(scope_type: str) -> list[str]:
        entry = next(
            (m for m in reversed(session.menus)
             if isinstance(m.get("scope"), dict) and m["scope"].get("type") == scope_type),
            None,
        )
        assert entry, f"в аутбоке нет setMyCommands для scope {scope_type}"
        return [c["command"] for c in entry["commands"]]

    admin_menu = menu_for("chat")
    check("admin" in admin_menu, "админу в меню виден /admin")
    check(
        not {"stats", "ban", "unban", "mute", "bc", "reports", "queue", "find"} & set(admin_menu),
        f"служебные команды не светятся даже админу: {admin_menu}",
    )
    public = menu_for("all_private_chats")
    check("admin" not in public and "stats" not in public, "обычный пользователь не видит админского")

    await bot.session.close()
    await db.close()
    print("\nflow test passed")


async def run_flow_modern(holder: dict[str, Any] | None = None) -> None:
    """Новый мобильный сценарий: онбординг, безопасность, жалобы, recent/block и FSM."""
    tmp = Path(tempfile.mkdtemp())
    cfg = Config(
        bot_token="42:TEST", admin_ids=(ADMIN,), db_path=tmp / "flow-modern.db",
        auto_mute_reports=0,
    )
    db = await Database(cfg.db_path).start()
    if holder is not None:
        holder["db"] = db
    mm = Matchmaker()
    session = RecordingSession()
    bot = Bot(cfg.bot_token, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    pack = EmojiPack(cfg.emoji_pack_url)
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(Throttling(cfg, limit=200))
        observer.middleware(DataContext(cfg, db, mm, pack))
    for router in get_routers():
        dp.include_router(router)

    step = 1000

    async def send(uid: int, text: str) -> None:
        nonlocal step
        step += 1
        await dp.feed_update(bot, msg_update(bot, uid, text, step))

    async def press(uid: int, data: str) -> None:
        nonlocal step
        step += 1
        await dp.feed_update(bot, cb_update(bot, uid, data, step))

    async def payload(uid: int, **content: Any) -> None:
        nonlocal step
        step += 1
        message = {
            "message_id": step, "date": 1_700_000_000,
            "chat": {"id": uid, "type": "private", "first_name": f"U{uid}"},
            "from": {"id": uid, "is_bot": False, "first_name": f"U{uid}"},
            **content,
        }
        await dp.feed_update(bot, Update.model_validate(
            {"update_id": step, "message": message}, context={"bot": bot}
        ))

    def check(value: bool, label: str) -> None:
        if not value:
            raise AssertionError(f"{label}\noutbox={session.outbox[-8:]}")
        print(f"  ok  {label}")

    async def onboard(uid: int, age: int) -> None:
        await send(uid, "/start")
        check("Анонимный чат" in session.last_to(uid), "первый запуск показывает короткое приветствие")
        await press(uid, "onboard:continue")
        check("Сколько тебе лет" in session.last_to(uid), "после продолжения бот спрашивает возраст")
        await press(uid, f"onboard:age:{age}")
        row = await db.get_user(uid)
        check(bool(row and row["age"] == age and row["nickname"]), "возраст и случайный ник сохранены")

    await onboard(A, 17)
    await onboard(B, 18)
    await onboard(C, 16)

    session.clear()
    await press(A, "act:more")
    await press(A, "act:support")
    check("количество звёзд" in session.last_to(A), "поддержка спрашивает количество звёзд")
    await send(A, "25")
    invoice = next((item for item in reversed(session.outbox) if item["method"] == "sendInvoice"), None)
    check(
        bool(invoice and invoice["currency"] == "XTR" and invoice["prices"][0]["amount"] == 25),
        "бот создаёт счёт Telegram Stars на введённую сумму",
    )

    session.clear()
    await press(A, "act:connect")
    check(mm.status(A) == "queued" and "Ищу собеседника" in session.last_to(A), "поиск ставит в очередь")
    await press(B, "act:connect")
    check(mm.partner(A) == B, "возраст не разделяет очередь")
    check("Собеседник найден" in session.last_to(A), "экран найденного собеседника отправлен")
    check("U1002" not in session.last_to(A) and str(B) not in session.last_to(A),
          "Telegram-имя и id не попадают собеседнику")

    session.clear()
    await send(A, "@secret_user")
    check("@secret_user" in session.last_to(B), "@username пересылается собеседнику")
    session.clear()
    await send(A, "+7 999 123-45-67")
    check(session.to(B) == [] and "контакты" in session.last_to(A), "телефон не пересылается")
    session.clear()
    await send(A, "https://example.com")
    check("https://example.com" in session.last_to(B), "ссылка пересылается собеседнику")

    session.clear()
    await send(A, "/send @explicit_user")
    check("@explicit_user" in session.last_to(B), "/send отправляет username без текста команды")
    session.clear()
    await send(A, "/user https://t.me/example")
    check("https://t.me/example" in session.last_to(B), "/user отправляет ссылку")

    for body, label in (
        ({"location": {"latitude": 53.4, "longitude": 58.9}}, "location"),
        ({"contact": {"phone_number": "+79991234567", "first_name": "X"}}, "contact"),
        ({"document": {"file_id": "f", "file_unique_id": "u"}}, "документ"),
    ):
        session.clear()
        await payload(A, **body)
        check(session.to(B) == [], f"{label} не пересылается")

    await send(A, "обычное сообщение")
    await send(B, "ответ")
    await press(A, "act:report")
    await press(A, "rep:spam")
    await send(A, "мешает общаться")
    reports = await db.list_reports("new")
    check(len(reports) == 1 and "обычное сообщение" in reports[0]["context"],
          "жалоба сохраняет только последние сообщения как контекст")
    check(await db.is_restricted(B) is None, "AUTO_MUTE_REPORTS=0 полностью отключает авто-мут")
    await press(A, "act:report")
    await press(A, "rep:spam")
    await send(A, "повтор")
    check(len(await db.list_reports("new")) == 1 and texts.REPORT_DUPLICATE in session.last_to(A),
          "повторная жалоба на тот же диалог не считается")

    await send(A, "/stop")
    await press(A, "rate:block")
    check(B in await db.excluded_partners(A), "блок-лист сохраняет пару")
    await press(A, "act:connect")
    await press(B, "act:connect")
    check(mm.partner(A) != B, "заблокированные и недавние собеседники не соединяются снова")
    await press(C, "act:connect")
    check(mm.partner(A) == C, "очередь выбирает следующего подходящего пользователя")

    await send(A, "/stop")
    await press(A, "cfg:nick:ask")
    await press(A, "act:menu")
    old_nick = (await db.get_user(A))["nickname"]
    await send(A, "это обычный текст")
    check((await db.get_user(A))["nickname"] == old_nick, "выход в меню очищает FSM ввода")

    await db.set_ban(C, True, "тест")
    await db.forget_user(C)
    check(await db.is_restricted(C) == "banned", "/forget не снимает действующий бан")

    await bot.session.close()
    await db.close()
    print("\nmodern flow test passed")


def test_flow() -> None:
    """Гарантированно закрываем БД: иначе worker-поток aiosqlite вешает процесс при упавшем асерте."""
    holder: dict[str, Any] = {}

    async def guarded() -> None:
        try:
            await run_flow_modern(holder)
        finally:
            db = holder.get("db")
            if db is not None:
                await db.close()

    asyncio.run(guarded())


if __name__ == "__main__":
    test_flow()
