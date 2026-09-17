"""Панель модератора прямо в телеге: сводка, жалобы, санкции, рассылка.

Служебные команды (/stats, /ban, …) остались и работают, если ввести их руками, но
в меню команд Telegram они не показываются — наружу торчит только <code>/admin</code>,
дальше всё кнопками (см. anonchat/commands.py).
"""

from __future__ import annotations

import asyncio
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import keyboards as K
from .. import nick as nicklib
from .. import texts
from ..actions import Ctx, DeliveryResult, break_pair, send_to
from ..config import Config
from ..db import Database
from ..levels import rank_for
from ..matching import Matchmaker

router = Router(name="admin")


def _is_admin(ctx: Ctx) -> bool:
    return bool(ctx.cfg.admin_ids) and ctx.user_id in ctx.cfg.admin_ids


async def _deny(ctx: Ctx) -> bool:
    if _is_admin(ctx):
        return False
    hint = (
        "В .env пропиши <code>ADMIN_IDS=твой_telegram_id</code> и перезапусти бота."
        if not ctx.cfg.admin_ids
        else "Это раздел модерации."
    )
    await ctx.reply(f"Доступ только у админов. {hint}")
    return True


def _parse_args(text: str) -> list[str]:
    return (text or "").split(maxsplit=3)[1:] if text else []


def _body(text: str, *drop: str) -> str:
    """Текст команды без первой(ых) страниц: «/ban 123 спам» без «/ban»."""
    parts = (text or "").split(maxsplit=len(drop))
    return parts[-1].strip() if len(parts) > len(drop) else ""


async def clear_kb(event: CallbackQuery) -> None:
    """Снимаем кнопки с карточки жалобы, когда она отработана."""
    message = event.message
    if message is None or not hasattr(message, "edit_reply_markup"):
        return
    try:
        await message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass


# ---------------------------------------------------------------------------------- тексты экранов
async def stats_text(db: Database, mm: Matchmaker, cfg: Config) -> str:
    s = await db.stats()
    return (
        f"📈 <b>Анончат {texts.esc(cfg.city_short)} · сводка</b>\n\n"
        f"👥 Пользователей: <b>{s['users']}</b>\n"
        f"🟢 Активны за 7 дней: <b>{s['active_week']}</b>\n"
        f"💬 Диалогов сыграно: <b>{s['dialogs']}</b>\n"
        f"✉️ Сообщений переслано: <b>{s['messages']}</b>\n"
        f"⏳ В очереди: <b>{mm.queue_size()}</b> · в парах: <b>{mm.online_pairs()}</b>\n"
        f"🚩 Открытых жалоб: <b>{s['open_reports']}</b>"
    )


def queue_text(mm: Matchmaker) -> str:
    snap = mm.queue_snapshot(15)
    lines = [f"⏳ <b>Очередь · {mm.queue_size()}</b> · в парах: {mm.online_pairs()}", ""]
    for i, (uid, district) in enumerate(snap, start=1):
        lines.append(f"<code>{i}</code> <code>{uid}</code> · {texts.esc(district or 'район не указан')}")
    if not snap:
        lines.append("Пусто — никто не ждёт.")
    return "\n".join(lines)


async def find_text(db: Database, query: str) -> str:
    if not query:
        return "🔎 Пришли @username, имя, ник или id."
    if query.lstrip("-").isdigit():
        rows = [r for r in [await db.get_user(int(query))] if r]
    else:
        rows = await db.find_user_ids(query, 10)
    if not rows:
        return "🔎 Никого не нашёл."
    lines = ["🔎 <b>Найдено</b>", ""]
    for r in rows:
        rank = rank_for(int(r["messages"]))
        lines.append(
            f"<code>{r['user_id']}</code> · 🙋 "
            f"<b>{texts.esc(nicklib.display(r['nickname'], int(r['user_id']), r['premium_until']))}</b>"
            f" · {texts.esc(r['first_name'])} ({texts.esc(r['username'] or '-')})\n"
            f"   {rank.name} · {rank.pretty(int(r['messages']))} сообщ. · ⭐ {rank.pretty(int(r['xp']))}"
            f" · диалогов {r['dialogs']} · жалоб {r['reports_received']}"
            + (" · ⛔ бан" if r["banned"] else "")
        )
    return "\n".join(lines)


def report_card(r) -> str:
    """Карточка жалобы для модератора: здесь настоящие данные уместны."""
    return (
        f"🚩 <b>Жалоба #{r['id']}</b> · {time.strftime('%d.%m %H:%M', time.localtime(r['created_at']))}\n"
        f"Причина: <b>{texts.esc(r['reason'])}</b>\n"
        f"На: <code>{r['target_id']}</code> · в чате как "
        f"<b>{texts.esc(nicklib.display(r['target_nickname'], int(r['target_id']), r['target_premium_until'] or 0))}</b>"
        f" ({texts.esc(r['target_name'] or '-')})\n"
        f"От: <code>{r['reporter_id']}</code>\n"
        f"Последние сообщения:\n{texts.esc(r['context']) if r['context'] else '<i>нет контекста</i>'}\n\n"
        f"Комментарий: {texts.esc(r['comment']) if r['comment'] else '<i>без комментария</i>'}"
    )


async def who_text(db: Database, uid: int) -> str | None:
    row = await db.get_user(uid)
    if row is None:
        return None
    rank = rank_for(int(row["messages"]))
    return (
        f"👤 <code>{uid}</code> · 🙋 "
        f"<b>{texts.esc(nicklib.display(row['nickname'], uid, row['premium_until']))}</b>\n"
        f"📛 {texts.esc(row['first_name'])} ({texts.esc(row['username'] or '-')})\n"
        f"{rank.name} · {rank.pretty(int(row['messages']))} сообщ. · ⭐ {rank.pretty(int(row['xp']))}\n"
        f"💬 диалогов: {row['dialogs']} · 👍 {row['good_ratings']} · 👎 {row['bad_ratings']}\n"
        f"🚩 жалоб: {row['reports_received']} · {texts.esc(row['district'] or 'район не указан')}\n"
        f"АНОН+: {'до ' + time.strftime('%d.%m.%Y', time.localtime(row['premium_until'])) if nicklib.is_premium(row['premium_until']) else 'нет'}\n"
        f"в чате с {time.strftime('%d.%m.%Y', time.localtime(row['created_at']))}"
        + ("\n⛔ в бане" if row["banned"] else "")
    )


# ---------------------------------------------------------------------------------- санкции
async def do_ban(ctx: Ctx, db: Database, mm: Matchmaker, cfg: Config, uid: int, reason: str) -> str:
    await db.set_ban(uid, True, reason)
    await break_pair(ctx.bot, cfg, mm, uid, texts.PARTNER_LEFT, ctx.pack)
    await send_to(
        ctx.bot, uid, texts.BANNED.format(city=texts.esc(cfg.city), reason=texts.esc(reason)),
        None, ctx.pack,
    )
    return f"⛔ <code>{uid}</code> забанен. Причина: {texts.esc(reason)}"


async def do_unban(db: Database, uid: int) -> str:
    await db.set_ban(uid, False)
    return f"✅ <code>{uid}</code> разбанен, добро пожаловать обратно в город."


async def do_mute(
    ctx: Ctx, db: Database, mm: Matchmaker, cfg: Config, uid: int, mins: int
) -> str:
    until = await db.set_mute(uid, mins)
    await send_to(
        ctx.bot, uid, texts.MUTED.format(mins=max(1, int((until - time.time()) // 60))), None, ctx.pack
    )
    await break_pair(ctx.bot, cfg, mm, uid, texts.MOD_CLOSED_DIALOG, ctx.pack)
    return f"🔇 <code>{uid}</code> заглушён на {mins} мин."


async def do_broadcast(ctx: Ctx, db: Database, body: str) -> str:
    ids = await db.active_ids(days=7)
    await ctx.reply(texts.PANEL_BC_PROGRESS.format(total=len(ids)))
    sent = 0
    for uid in ids:
        if await send_to(ctx.bot, uid, f"📣 {body}", K.menu_keyboard(), ctx.pack) is DeliveryResult.DELIVERED:
            sent += 1
        await asyncio.sleep(0.05)  # бережём лимиты Telegram
    return texts.PANEL_BC_DONE.format(sent=sent, total=len(ids))


def _id_args(raw: str) -> tuple[int | None, str]:
    """«123 причина» → (123, «причина»). None — не распарсилось."""
    parts = (raw or "").strip().split(maxsplit=1)
    if not parts or not parts[0].lstrip("-").isdigit():
        return None, ""
    return int(parts[0]), (parts[1].strip() if len(parts) > 1 else "")


# ---------------------------------------------------------------------------------- панель
class AdminStates(StatesGroup):
    """Один ввод — одно состояние: ждём id/текст после нажатия кнопки панели."""

    await_input = State()


async def panel_screen(ctx: Ctx, db: Database, mm: Matchmaker, edit: bool = True) -> None:
    await db.cleanup_report_context(ctx.cfg.report_context_retention_days)
    s = await db.stats()
    body = (
        f"{texts.PANEL_TITLE.format(city=texts.esc(ctx.cfg.city))}\n\n"
        f"👥 {s['users']} · 🟢 {s['active_week']} · ⏳ {mm.queue_size()} · 💬 {mm.online_pairs()}\n"
        f"🚩 открытых жалоб: <b>{s['open_reports']}</b>\n\n"
        f"{texts.PANEL_NOTE}"
    )
    kb = K.admin_panel_keyboard(int(s["open_reports"]))
    if edit and await ctx.edit(body, kb):
        return
    await ctx.reply(body, kb)


async def _ask(ctx: Ctx, state: FSMContext, what: str, prompt: str) -> None:
    await state.set_state(AdminStates.await_input)
    await state.update_data(adm=what)
    await ctx.edit(prompt, K.panel_cancel_keyboard())


#: кнопка панели → (что ждём, подсказка); None — действие выполняется сразу
PANEL_PROMPTS = {
    K.CB_PANEL_FIND: ("find", texts.PANEL_ASK_FIND),
    K.CB_PANEL_BAN: ("ban", texts.PANEL_ASK_BAN),
    K.CB_PANEL_UNBAN: ("unban", texts.PANEL_ASK_UNBAN),
    K.CB_PANEL_MUTE: ("mute", texts.PANEL_ASK_MUTE),
    K.CB_PANEL_BC: ("bc", texts.PANEL_ASK_BC),
}


@router.message(Command("admin", "mod", "панель"))
async def cmd_admin_panel(message: Message, ctx: Ctx, db: Database, mm: Matchmaker) -> None:
    if await _deny(ctx):
        return
    await panel_screen(ctx, db, mm, edit=False)


@router.callback_query(F.data == K.CB_ADMIN_PANEL)
async def cb_open_panel(event: CallbackQuery, ctx: Ctx, db: Database, mm: Matchmaker, state: FSMContext) -> None:
    if not _is_admin(ctx):
        await ctx.ack("Не для тебя", show_alert=True)
        return
    await state.clear()
    await panel_screen(ctx, db, mm)


# --------------------------------------------------------------- команды (вне меню, но живые)
@router.message(Command("stats"))
async def cmd_stats(message: Message, ctx: Ctx, db: Database, mm: Matchmaker) -> None:
    if await _deny(ctx):
        return
    await ctx.reply(await stats_text(db, mm, ctx.cfg))


@router.message(Command("queue"))
async def cmd_queue(message: Message, ctx: Ctx, mm: Matchmaker) -> None:
    if await _deny(ctx):
        return
    await ctx.reply(queue_text(mm))


@router.message(Command("reports"))
async def cmd_reports(message: Message, ctx: Ctx, db: Database) -> None:
    if await _deny(ctx):
        return
    await send_report_cards(ctx, db)


async def send_report_cards(ctx: Ctx, db: Database) -> None:
    rows = await db.list_reports("new", 10)
    if not rows:
        await ctx.reply("🚩 Открытых жалоб нет — город вежливый.")
        return
    for r in rows:
        await ctx.reply(report_card(r), markup=K.admin_report_keyboard(int(r["id"])))


@router.message(Command("resolve"))
async def cmd_resolve(message: Message, ctx: Ctx, db: Database) -> None:
    if await _deny(ctx):
        return
    args = _parse_args(message.text or "")
    if not args or not args[0].isdigit():
        await ctx.reply("Формат: <code>/resolve 12</code>")
        return
    ok = await db.resolve_report(int(args[0]), ctx.user_id)
    await ctx.reply("🚩 Жалоба закрыта." if ok else "Не нашёл открытую жалобу с таким номером.")


@router.message(Command("ban"))
async def cmd_ban(message: Message, ctx: Ctx, db: Database, mm: Matchmaker, cfg: Config) -> None:
    if await _deny(ctx):
        return
    uid, reason = _id_args(_body(message.text or "", "/ban"))
    if uid is None:
        await ctx.reply("Формат: <code>/ban 123456 спам и оскорбления</code>")
        return
    await ctx.reply(await do_ban(ctx, db, mm, cfg, uid, reason or "решение модератора"))


@router.message(Command("unban"))
async def cmd_unban(message: Message, ctx: Ctx, db: Database) -> None:
    if await _deny(ctx):
        return
    uid, _ = _id_args(_body(message.text or "", "/unban"))
    if uid is None:
        await ctx.reply("Формат: <code>/unban 123456</code>")
        return
    await ctx.reply(await do_unban(db, uid))


@router.message(Command("mute"))
async def cmd_mute(message: Message, ctx: Ctx, db: Database, mm: Matchmaker, cfg: Config) -> None:
    if await _deny(ctx):
        return
    parts = _parse_args(message.text or "")
    if len(parts) < 2 or not parts[0].lstrip("-").isdigit() or not parts[1].isdigit():
        await ctx.reply("Формат: <code>/mute 123456 60</code> (id и минуты)")
        return
    await ctx.reply(await do_mute(ctx, db, mm, cfg, int(parts[0]), int(parts[1])))


@router.message(Command("find"))
async def cmd_find(message: Message, ctx: Ctx, db: Database) -> None:
    if await _deny(ctx):
        return
    await ctx.reply(await find_text(db, _body(message.text or "", "/find")))


@router.message(Command("bc"))
async def cmd_broadcast(message: Message, ctx: Ctx, db: Database) -> None:
    if await _deny(ctx):
        return
    body = _body(message.text or "", "/bc")
    if not body:
        await ctx.reply("Формат: <code>/bc текст рассылки</code>")
        return
    await ctx.reply(await do_broadcast(ctx, db, body))


# --------------------------------------------------------------- кнопки панели
@router.callback_query(F.data.startswith("adm:panel:"))
async def cb_panel(event: CallbackQuery, ctx: Ctx, db: Database, mm: Matchmaker, state: FSMContext) -> None:
    if not _is_admin(ctx):
        await ctx.ack("Не для тебя", show_alert=True)
        return
    data = event.data or ""

    if data == K.CB_PANEL_BACK:
        await state.clear()
        await panel_screen(ctx, db, mm)
        return
    if data == K.CB_PANEL_STATS:
        await ctx.edit(await stats_text(db, mm, ctx.cfg), K.panel_back_keyboard())
        return
    if data == K.CB_PANEL_QUEUE:
        await ctx.edit(queue_text(mm), K.panel_back_keyboard())
        return
    if data == K.CB_PANEL_REPORTS:
        rows = await db.list_reports("new", 10)
        if not rows:
            await ctx.edit("🚩 Открытых жалоб нет — город вежливый.", K.panel_back_keyboard())
            return
        await ctx.edit(
            f"🚩 <b>Открытые жалобы · {len(rows)}</b>\n"
            "Ниже — карточки с кнопками; сама карточка не меняется.",
            K.panel_back_keyboard(),
        )
        for r in rows:
            await ctx.reply(report_card(r), markup=K.admin_report_keyboard(int(r["id"])))
        await ctx.ack(f"{len(rows)} карточек")
        return

    if data in PANEL_PROMPTS:
        what, prompt = PANEL_PROMPTS[data]
        await _ask(ctx, state, what, prompt)
        await ctx.ack()
        return

    await ctx.ack("Не понимаю кнопку")


@router.message(AdminStates.await_input, F.text, ~F.text.startswith("/"))
async def panel_input(message: Message, ctx: Ctx, db: Database, mm: Matchmaker, cfg: Config,
                      state: FSMContext) -> None:
    """Ввод после кнопки панели: id, id+причина, id+минуты или текст рассылки."""
    if await _deny(ctx):
        return
    data = await state.get_data()
    what = (data or {}).get("adm", "")
    raw = (message.text or "").strip()
    await state.clear()

    if raw in {"-", "—", "--", "/cancel", "отмена"}:
        await ctx.reply(texts.PANEL_CANCELLED)
        await panel_screen(ctx, db, mm, edit=False)
        return

    if what == "find":
        await ctx.reply(await find_text(db, raw))
    elif what == "ban":
        uid, reason = _id_args(raw)
        await ctx.reply(
            texts.PANEL_NO_ID if uid is None
            else await do_ban(ctx, db, mm, cfg, uid, reason or "решение модератора")
        )
    elif what == "unban":
        uid, _ = _id_args(raw)
        await ctx.reply(texts.PANEL_NO_ID if uid is None else await do_unban(db, uid))
    elif what == "mute":
        uid, tail = _id_args(raw)
        mins = int(tail.split(maxsplit=1)[0]) if tail and tail.split(maxsplit=1)[0].isdigit() else 60
        await ctx.reply(texts.PANEL_NO_ID if uid is None else await do_mute(ctx, db, mm, cfg, uid, mins))
    elif what == "bc":
        await ctx.reply(await do_broadcast(ctx, db, raw))
    else:
        await ctx.reply("Кнопку панели не помню — открой /admin заново.")
        return
    await panel_screen(ctx, db, mm, edit=False)


# ---------------------------------------------------------------------------------- кнопки в карточке жалобы
@router.callback_query(F.data.startswith("adm:"))
async def cb_admin(event: CallbackQuery, ctx: Ctx, db: Database, mm: Matchmaker, cfg: Config) -> None:
    if not _is_admin(ctx):
        await ctx.ack("Не для тебя", show_alert=True)
        return
    parts = (event.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return  # adm:panel:* живёт в своём хендлере выше
    action, raw_id = parts[1], parts[2]
    report = await db.get_report(int(raw_id))
    if report is None:
        await ctx.ack("Жалоба не найдена", alert=True)
        return
    target = int(report["target_id"])

    if action == "done":
        await db.resolve_report(int(raw_id), ctx.user_id)
        await ctx.ack("Закрыто")
        await clear_kb(event)
        return

    if action == "who":
        card = await who_text(db, target)
        if card is None:
            await ctx.ack("Нет такого профиля", alert=True)
            return
        await ctx.reply(card)
        await ctx.ack("Показал профиль")
        return

    if action == "mute":
        await do_mute(ctx, db, mm, cfg, target, 60)
        await db.resolve_report(int(raw_id), ctx.user_id)
        await ctx.ack("Мут на 60 мин")
        await clear_kb(event)
        return

    if action == "ban":
        await do_ban(ctx, db, mm, cfg, target, f"жалоба #{raw_id}: {report['reason']}")
        await db.resolve_report(int(raw_id), ctx.user_id)
        await ctx.ack("Забанен")
        await clear_kb(event)
        return

    await ctx.ack("Не понимаю кнопку")
