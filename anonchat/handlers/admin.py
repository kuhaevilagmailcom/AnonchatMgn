"""Панель модератора прямо в телеге: сводка, жалобы, санкции, рассылка.

Служебные команды (/stats, /ban, …) остались и работают, если ввести их руками, но
в меню команд Telegram они не показываются — наружу торчит только <code>/admin</code>,
дальше всё кнопками (см. anonchat/commands.py).
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message

from .. import keyboards as K
from .. import nick as nicklib
from .. import texts
from ..actions import Ctx, DeliveryResult, break_pair, send_to
from ..commands import ensure_for_admin, remove_admin_commands
from ..config import Config
from ..db import Database
from ..levels import rank_for
from ..matching import Matchmaker
from ..permissions import ALL_ADMIN_PERMISSIONS, PERMISSION_LABELS, parse_permissions
from .reports import format_report_card

router = Router(name="admin")


def _is_admin(ctx: Ctx) -> bool:
    return ctx.is_admin


async def _deny(ctx: Ctx, permission: str | None = None) -> bool:
    if _is_admin(ctx) and (permission is None or ctx.can(permission)):
        return False
    await ctx.reply("Нет доступа к этому разделу модерации.")
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
            f"<b>{texts.esc(nicklib.display(r['nickname'], int(r['user_id']), r['support_stars']))}</b>"
            f" · {texts.esc(r['first_name'])} ({texts.esc(r['username'] or '-')})\n"
            f"   {rank.name} · {rank.pretty(int(r['messages']))} сообщ. · ⭐ {rank.pretty(int(r['xp']))}"
            f" · диалогов {r['dialogs']} · жалоб {r['reports_received']}"
            + (" · ⛔ бан" if r["banned"] else "")
        )
    return "\n".join(lines)


def report_card(r) -> str:
    return format_report_card(r)


async def who_text(db: Database, uid: int) -> str | None:
    row = await db.get_user(uid)
    if row is None:
        return None
    rank = rank_for(int(row["messages"]))
    return (
        f"👤 <code>{uid}</code> · 🙋 "
        f"<b>{texts.esc(nicklib.display(row['nickname'], uid, row['support_stars']))}</b>\n"
        f"📛 {texts.esc(row['first_name'])} ({texts.esc(row['username'] or '-')})\n"
        f"{rank.name} · {rank.pretty(int(row['messages']))} сообщ. · ⭐ {rank.pretty(int(row['xp']))}\n"
        f"💬 диалогов: {row['dialogs']} · 👍 {row['good_ratings']} · 👎 {row['bad_ratings']}\n"
        f"🚩 жалоб: {row['reports_received']} · {texts.esc(row['district'] or 'район не указан')}\n"
        f"💎 Поддержка: {int(row['support_stars'])} ⭐\n"
        f"в чате с {time.strftime('%d.%m.%Y', time.localtime(row['created_at']))}"
        + ("\n⛔ в бане" if row["banned"] else "")
    )


async def users_text(db: Database, limit: int = 30, offset: int = 0) -> tuple[str, int]:
    rows = await db.list_users(limit, offset)
    lines = [f"👥 <b>Пользователи · {offset + 1}–{offset + len(rows)}</b>", ""]
    for row in rows:
        username = f"@{row['username']}" if row["username"] else "без username"
        lines.append(
            f"<code>{row['user_id']}</code> · {texts.esc(username)} · "
            f"{texts.esc(row['first_name'] or '-')} · {int(row['xp'])} ⭐"
        )
    return "\n".join(lines), len(rows)


async def restricted_text(
    db: Database, kind: str, limit: int = 10, offset: int = 0
) -> tuple[str, list[int], int]:
    rows, total = await db.list_restricted(kind, limit, offset)
    title = "⛔ <b>Бан-лист</b>" if kind == "ban" else "🔇 <b>Мут-лист</b>"
    lines = [f"{title} · всего: <b>{total}</b>", ""]
    for index, row in enumerate(rows, start=offset + 1):
        user_id = int(row["user_id"])
        nick = nicklib.display(row["nickname"], user_id, row["support_stars"])
        username = f"@{row['username']}" if row["username"] else "нет username"
        lines.append(
            f"<b>{index}. {texts.esc(nick)}</b> · {texts.esc(username)}\n"
            f"ID: <code>{user_id}</code>"
        )
        if kind == "ban":
            lines.append(f"Причина: {texts.esc(row['ban_reason'] or 'не указана')}\n")
        else:
            remaining = max(1, (int(row["mute_until"]) - int(time.time()) + 59) // 60)
            lines.append(
                f"До: <b>{time.strftime('%d.%m.%Y · %H:%M', time.localtime(row['mute_until']))}</b>"
                f" · осталось {remaining} мин.\n"
            )
    if not rows:
        lines.append("Список пуст.")
    return "\n".join(lines), [int(row["user_id"]) for row in rows], total


async def restriction_screen(ctx: Ctx, db: Database, kind: str, offset: int = 0) -> None:
    body, user_ids, total = await restricted_text(db, kind, offset=offset)
    if not user_ids and offset > 0 and total:
        offset = max(0, offset - 10)
        body, user_ids, total = await restricted_text(db, kind, offset=offset)
    markup = K.restricted_list_keyboard(kind, user_ids, offset, total)
    if not await ctx.edit(body, markup):
        await ctx.reply(body, markup)


async def admins_text(db: Database, owner_ids: tuple[int, ...]) -> str:
    lines = ["👮 <b>Администраторы</b>", ""]
    for owner_id in owner_ids:
        lines.append(f"<code>{owner_id}</code> · владелец · все права")
    for row in await db.list_admins():
        permissions = ", ".join(
            PERMISSION_LABELS.get(item, item)
            for item in str(row["permissions"] or "").split(",") if item
        )
        username = f"@{row['username']}" if row["username"] else (row["first_name"] or "-")
        lines.append(f"<code>{row['user_id']}</code> · {texts.esc(username)}\n{permissions}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------- санкции
async def do_ban(ctx: Ctx, db: Database, mm: Matchmaker, cfg: Config, uid: int, reason: str) -> str:
    await db.set_ban(uid, True, reason)
    await break_pair(ctx.bot, cfg, mm, uid, texts.PARTNER_LEFT, ctx.pack, db)
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
    await break_pair(ctx.bot, cfg, mm, uid, texts.MOD_CLOSED_DIALOG, ctx.pack, db)
    return f"🔇 <code>{uid}</code> заглушён на {mins} мин."


async def do_broadcast(ctx: Ctx, db: Database, body: str) -> str:
    ids = await db.active_ids(days=7)
    await ctx.reply(texts.PANEL_BC_PROGRESS.format(total=len(ids)))
    sent = 0
    for uid in ids:
        if await send_to(ctx.bot, uid, body, None, ctx.pack) is DeliveryResult.DELIVERED:
            sent += 1
        await asyncio.sleep(0.05)  # бережём лимиты Telegram
    return texts.PANEL_BC_DONE.format(sent=sent, total=len(ids))


async def do_broadcast_message(ctx: Ctx, db: Database, message: Message) -> str:
    """Копирует текст/фото/видео как есть, всегда без inline-кнопок."""
    ids = await db.active_ids(days=7)
    await ctx.reply(texts.PANEL_BC_PROGRESS.format(total=len(ids)))
    sent = 0
    for uid in ids:
        try:
            await message.send_copy(chat_id=uid, reply_markup=None)
            sent += 1
        except TelegramAPIError:
            pass
        await asyncio.sleep(0.05)
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
    kb = K.admin_panel_keyboard(
        int(s["open_reports"]), ctx.admin_permissions, owner=ctx.is_owner,
        monitor_enabled=await db.get_kv(f"chat_monitor:{ctx.user_id}") == "1",
    )
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
    K.CB_PANEL_POINTS: (
        "points",
        "⭐ Пришли <code>id +50</code> для выдачи или <code>id -50</code> для снятия очков.",
    ),
    K.CB_PANEL_ADMINS: (
        "admins",
        "👮 Пришли <code>id права</code>. Права через запятую: "
        + ", ".join(sorted(ALL_ADMIN_PERMISSIONS))
        + ". Можно указать <code>all</code> или <code>remove</code> для снятия.",
    ),
}


@router.message(Command("admin", "mod", "панель"))
async def cmd_admin_panel(message: Message, ctx: Ctx, db: Database, mm: Matchmaker) -> None:
    if await _deny(ctx):
        return
    await panel_screen(ctx, db, mm, edit=False)


@router.callback_query(F.data == K.CB_ADMIN_PANEL)
async def cb_open_panel(event: CallbackQuery, ctx: Ctx, db: Database, mm: Matchmaker, state: FSMContext) -> None:
    if not _is_admin(ctx):
        await ctx.ack("Не для тебя", alert=True)
        return
    await state.clear()
    await panel_screen(ctx, db, mm)


# --------------------------------------------------------------- команды (вне меню, но живые)
@router.message(Command("stats"))
async def cmd_stats(message: Message, ctx: Ctx, db: Database, mm: Matchmaker) -> None:
    if await _deny(ctx, "stats"):
        return
    await ctx.reply(await stats_text(db, mm, ctx.cfg))


@router.message(Command("queue"))
async def cmd_queue(message: Message, ctx: Ctx, mm: Matchmaker) -> None:
    if await _deny(ctx, "queue"):
        return
    await ctx.reply(queue_text(mm))


@router.message(Command("reports"))
async def cmd_reports(message: Message, ctx: Ctx, db: Database) -> None:
    if await _deny(ctx, "reports"):
        return
    await send_report_cards(ctx, db)


async def send_report_cards(ctx: Ctx, db: Database) -> None:
    rows = await db.list_reports("new", 10)
    if not rows:
        await ctx.reply("🚩 Открытых жалоб нет — город вежливый.")
        return
    for r in rows:
        await ctx.reply(
            report_card(r), markup=K.admin_report_keyboard(int(r["id"]), ctx.admin_permissions)
        )


@router.message(Command("resolve"))
async def cmd_resolve(message: Message, ctx: Ctx, db: Database) -> None:
    if await _deny(ctx, "reports"):
        return
    args = _parse_args(message.text or "")
    if not args or not args[0].isdigit():
        await ctx.reply("Формат: <code>/resolve 12</code>")
        return
    ok = await db.resolve_report(int(args[0]), ctx.user_id)
    await ctx.reply("🚩 Жалоба закрыта." if ok else "Не нашёл открытую жалобу с таким номером.")


@router.message(Command("ban"))
async def cmd_ban(message: Message, ctx: Ctx, db: Database, mm: Matchmaker, cfg: Config) -> None:
    if await _deny(ctx, "ban"):
        return
    uid, reason = _id_args(_body(message.text or "", "/ban"))
    if uid is None:
        await ctx.reply("Формат: <code>/ban 123456 спам и оскорбления</code>")
        return
    await ctx.reply(await do_ban(ctx, db, mm, cfg, uid, reason or "решение модератора"))


@router.message(Command("unban"))
async def cmd_unban(message: Message, ctx: Ctx, db: Database) -> None:
    if await _deny(ctx, "ban"):
        return
    uid, _ = _id_args(_body(message.text or "", "/unban"))
    if uid is None:
        await ctx.reply("Формат: <code>/unban 123456</code>")
        return
    await ctx.reply(await do_unban(db, uid))


@router.message(Command("mute"))
async def cmd_mute(message: Message, ctx: Ctx, db: Database, mm: Matchmaker, cfg: Config) -> None:
    if await _deny(ctx, "mute"):
        return
    parts = _parse_args(message.text or "")
    if len(parts) < 2 or not parts[0].lstrip("-").isdigit() or not parts[1].isdigit():
        await ctx.reply("Формат: <code>/mute 123456 60</code> (id и минуты)")
        return
    await ctx.reply(await do_mute(ctx, db, mm, cfg, int(parts[0]), int(parts[1])))


@router.message(Command("find"))
async def cmd_find(message: Message, ctx: Ctx, db: Database) -> None:
    if await _deny(ctx, "users"):
        return
    await ctx.reply(await find_text(db, _body(message.text or "", "/find")))


@router.message(Command("bc"))
async def cmd_broadcast(message: Message, ctx: Ctx, db: Database) -> None:
    if await _deny(ctx, "broadcast"):
        return
    body = _body(message.text or "", "/bc")
    if not body:
        await ctx.reply("Формат: <code>/bc текст рассылки</code>")
        return
    await ctx.reply(await do_broadcast(ctx, db, body))


@router.message(Command("users"))
async def cmd_users(message: Message, ctx: Ctx, db: Database) -> None:
    if await _deny(ctx, "users"):
        return
    parts = _parse_args(message.text or "")
    offset = int(parts[0]) if parts and parts[0].isdigit() else 0
    body, count = await users_text(db, offset=offset)
    await ctx.reply(body, K.users_page_keyboard(offset, count))


@router.message(Command("points"))
async def cmd_points(message: Message, ctx: Ctx, db: Database) -> None:
    if await _deny(ctx, "points"):
        return
    parts = _parse_args(message.text or "")
    if len(parts) < 2 or not parts[0].isdigit():
        await ctx.reply("Формат: <code>/points 123456 +50</code> или <code>/points 123456 -50</code>")
        return
    try:
        amount = int(parts[1])
    except ValueError:
        await ctx.reply("Количество очков должно быть целым числом со знаком.")
        return
    balance = await db.adjust_xp(int(parts[0]), amount)
    await ctx.reply(f"⭐ Баланс <code>{parts[0]}</code>: <b>{balance}</b> очков.")


@router.message(Command("adminadd", "adminperms"))
async def cmd_admin_add(message: Message, ctx: Ctx, db: Database) -> None:
    if not ctx.is_owner:
        await ctx.reply("Назначать администраторов может только владелец.")
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await ctx.reply("Формат: <code>/adminadd 123456 reports,users,mute</code>")
        return
    permissions = parse_permissions(parts[2])
    if not permissions:
        await ctx.reply("Не нашёл допустимых прав.")
        return
    uid = int(parts[1])
    if uid in ctx.cfg.admin_ids:
        await ctx.reply("Это владелец из ADMIN_IDS — его права всегда полные.")
        return
    await db.set_admin(uid, permissions, ctx.user_id)
    await ensure_for_admin(ctx.bot, ctx.cfg, uid, quiet=True, authorized=True)
    await ctx.reply(f"Администратор <code>{uid}</code> сохранён: {', '.join(sorted(permissions))}.")


@router.message(Command("admindel"))
async def cmd_admin_del(message: Message, ctx: Ctx, db: Database) -> None:
    if not ctx.is_owner:
        await ctx.reply("Снимать администраторов может только владелец.")
        return
    parts = _parse_args(message.text or "")
    if not parts or not parts[0].isdigit():
        await ctx.reply("Формат: <code>/admindel 123456</code>")
        return
    uid = int(parts[0])
    if uid in ctx.cfg.admin_ids:
        await ctx.reply("Владельца из ADMIN_IDS нужно убирать через конфигурацию сервера.")
        return
    removed = await db.remove_admin(uid)
    await remove_admin_commands(ctx.bot, uid)
    await ctx.reply("Администратор снят." if removed else "Такого назначенного администратора нет.")


@router.message(Command("adminlist"))
async def cmd_admin_list(message: Message, ctx: Ctx, db: Database) -> None:
    if not ctx.is_owner:
        await ctx.reply("Список администраторов доступен только владельцу.")
        return
    await ctx.reply(await admins_text(db, ctx.cfg.admin_ids))


# --------------------------------------------------------------- кнопки панели
@router.callback_query(F.data.startswith("adm:panel:"))
async def cb_panel(event: CallbackQuery, ctx: Ctx, db: Database, mm: Matchmaker, state: FSMContext) -> None:
    if not _is_admin(ctx):
        await ctx.ack("Не для тебя", alert=True)
        return
    data = event.data or ""
    required = {
        K.CB_PANEL_STATS: "stats",
        K.CB_PANEL_REPORTS: "reports",
        K.CB_PANEL_QUEUE: "queue",
        K.CB_PANEL_FIND: "users",
        K.CB_PANEL_USERS: "users",
        K.CB_PANEL_BC: "broadcast",
        K.CB_PANEL_MUTE: "mute",
        K.CB_PANEL_MUTE_LIST: "mute",
        K.CB_PANEL_BAN: "ban",
        K.CB_PANEL_UNBAN: "ban",
        K.CB_PANEL_BAN_LIST: "ban",
        K.CB_PANEL_POINTS: "points",
        K.CB_PANEL_MONITOR: "monitor",
    }.get(data)
    if required and not ctx.can(required):
        await ctx.ack("У тебя нет этого права", alert=True)
        return
    if data == K.CB_PANEL_ADMINS and not ctx.is_owner:
        await ctx.ack("Только для владельца", alert=True)
        return
    if data == K.CB_PANEL_BACKUP and not ctx.is_owner:
        await ctx.ack("Только для владельца", alert=True)
        return
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
    if data == K.CB_PANEL_USERS:
        body, count = await users_text(db)
        await ctx.reply(body, K.users_page_keyboard(0, count))
        await ctx.ack()
        return
    if data == K.CB_PANEL_BAN_LIST:
        await ctx.ack()
        await restriction_screen(ctx, db, "ban")
        return
    if data == K.CB_PANEL_MUTE_LIST:
        await ctx.ack()
        await restriction_screen(ctx, db, "mute")
        return
    if data == K.CB_PANEL_MONITOR:
        key = f"chat_monitor:{ctx.user_id}"
        enabled = await db.get_kv(key) != "1"
        await db.set_kv(key, "1" if enabled else "0")
        await ctx.ack(f"Слежение за чатами {'включено' if enabled else 'выключено'}")
        await panel_screen(ctx, db, mm)
        return
    if data == K.CB_PANEL_BACKUP:
        await ctx.ack("Готовлю базу…")
        await db.flush_matchmaker(mm)
        with tempfile.NamedTemporaryFile(prefix="anonchat_backup_", suffix=".db", delete=False) as tmp:
            backup_path = Path(tmp.name)
        try:
            await db.backup_to(backup_path)
            if event.message is not None:
                await event.message.answer_document(
                    FSInputFile(backup_path, filename=f"anonchat_{time.strftime('%Y%m%d_%H%M%S')}.db"),
                    caption="Резервная копия базы AnonchatMgn.",
                )
        finally:
            backup_path.unlink(missing_ok=True)
        return
    if data == K.CB_PANEL_ADMINS:
        await state.set_state(AdminStates.await_input)
        await state.update_data(adm="admins")
        await ctx.edit(
            (await admins_text(db, ctx.cfg.admin_ids))
            + "\n\n"
            + PANEL_PROMPTS[K.CB_PANEL_ADMINS][1],
            K.panel_cancel_keyboard(),
        )
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
            await ctx.reply(
                report_card(r),
                markup=K.admin_report_keyboard(int(r["id"]), ctx.admin_permissions),
            )
        await ctx.ack(f"{len(rows)} карточек")
        return

    if data in PANEL_PROMPTS:
        what, prompt = PANEL_PROMPTS[data]
        await _ask(ctx, state, what, prompt)
        await ctx.ack()
        return

    await ctx.ack("Не понимаю кнопку")


@router.message(AdminStates.await_input)
async def panel_input(message: Message, ctx: Ctx, db: Database, mm: Matchmaker, cfg: Config,
                      state: FSMContext) -> None:
    """Ввод после кнопки панели: id, id+причина, id+минуты или текст рассылки."""
    if await _deny(ctx):
        return
    data = await state.get_data()
    what = (data or {}).get("adm", "")
    raw = (message.text or message.caption or "").strip()
    await state.clear()

    required = {
        "find": "users", "ban": "ban", "unban": "ban", "mute": "mute",
        "bc": "broadcast", "points": "points",
    }.get(what)
    if required and not ctx.can(required):
        await ctx.reply("У тебя нет этого права.")
        return
    if what == "admins" and not ctx.is_owner:
        await ctx.reply("Назначать администраторов может только владелец.")
        return

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
        await ctx.reply(await do_broadcast_message(ctx, db, message))
    elif what == "points":
        uid, tail = _id_args(raw)
        try:
            amount = int(tail)
        except ValueError:
            amount = 0
        if uid is None or amount == 0:
            await ctx.reply("Формат: <code>123456 +50</code> или <code>123456 -50</code>.")
        else:
            balance = await db.adjust_xp(uid, amount)
            await ctx.reply(f"⭐ Баланс <code>{uid}</code>: <b>{balance}</b> очков.")
    elif what == "admins":
        uid, tail = _id_args(raw)
        permissions = parse_permissions(tail)
        remove = tail.strip().lower() in {"remove", "del", "снять", "удалить"}
        if uid is None or (not permissions and not remove):
            await ctx.reply("Формат: <code>123456 reports,users,mute</code>.")
        elif uid in cfg.admin_ids:
            await ctx.reply("Это владелец из ADMIN_IDS — его права всегда полные.")
        elif remove:
            await db.remove_admin(uid)
            await remove_admin_commands(ctx.bot, uid)
            await ctx.reply(f"Администратор <code>{uid}</code> снят.")
        else:
            await db.set_admin(uid, permissions, ctx.user_id)
            await ensure_for_admin(ctx.bot, cfg, uid, quiet=True, authorized=True)
            await ctx.reply(f"Администратор <code>{uid}</code> сохранён.")
    else:
        await ctx.reply("Кнопку панели не помню — открой /admin заново.")
        return
    await panel_screen(ctx, db, mm, edit=False)


# ---------------------------------------------------------------------------------- страницы пользователей
@router.callback_query(F.data.startswith("adm:users:"))
async def cb_users_page(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    if not ctx.can("users"):
        await ctx.ack("У тебя нет этого права", alert=True)
        return
    try:
        offset = max(0, int((event.data or "").rsplit(":", 1)[1]))
    except (ValueError, IndexError):
        offset = 0
    body, count = await users_text(db, offset=offset)
    if not await ctx.edit(body, K.users_page_keyboard(offset, count)):
        await ctx.reply(body, K.users_page_keyboard(offset, count))
    await ctx.ack()


@router.callback_query(F.data.startswith("adm:restrict:"))
async def cb_restricted_list(event: CallbackQuery, ctx: Ctx, db: Database) -> None:
    if not _is_admin(ctx):
        await ctx.ack("Не для тебя", alert=True)
        return
    parts = (event.data or "").split(":")
    if len(parts) != 5:
        await ctx.ack("Кнопка устарела", alert=True)
        return
    action, value, raw_offset = parts[2], parts[3], parts[4]
    try:
        offset = max(0, int(raw_offset))
    except ValueError:
        await ctx.ack("Кнопка устарела", alert=True)
        return
    if action == "list" and value in {"ban", "mute"}:
        if not ctx.can(value):
            await ctx.ack("У тебя нет этого права", alert=True)
            return
        await ctx.ack()
        await restriction_screen(ctx, db, value, offset)
        return
    if action not in {"unban", "unmute"} or not value.isdigit():
        await ctx.ack("Кнопка устарела", alert=True)
        return
    permission = "ban" if action == "unban" else "mute"
    if not ctx.can(permission):
        await ctx.ack("У тебя нет этого права", alert=True)
        return
    user_id = int(value)
    if action == "unban":
        await db.set_ban(user_id, False)
        await ctx.ack("Пользователь разбанен")
        await restriction_screen(ctx, db, "ban", offset)
    else:
        await db.set_mute(user_id, 0)
        await ctx.ack("Мут снят")
        await restriction_screen(ctx, db, "mute", offset)


# ---------------------------------------------------------------------------------- кнопки в карточке жалобы
@router.callback_query(F.data.startswith("adm:"))
async def cb_admin(event: CallbackQuery, ctx: Ctx, db: Database, mm: Matchmaker, cfg: Config) -> None:
    if not _is_admin(ctx):
        await ctx.ack("Не для тебя", alert=True)
        return
    parts = (event.data or "").split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return  # adm:panel:* живёт в своём хендлере выше
    action, raw_id = parts[1], parts[2]
    required = {"done": "reports", "who": "users", "mute": "mute", "ban": "ban"}.get(action)
    if required and not ctx.can(required):
        await ctx.ack("У тебя нет этого права", alert=True)
        return
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
