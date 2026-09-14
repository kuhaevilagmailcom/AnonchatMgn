"""Админ-панель прямо в телеге: статистика, жалобы, баны, рассылка."""

from __future__ import annotations

import asyncio
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .. import keyboards as K
from .. import nick as nicklib
from .. import texts
from ..actions import Ctx, break_pair, send_to
from ..config import Config
from ..db import Database
from ..levels import level_for
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
        else "Это команды модерации."
    )
    await ctx.reply(f"Доступ только у админов. {hint}")
    return True


def _parse_args(text: str) -> list[str]:
    return (text or "").split(maxsplit=3)[1:] if text else []


async def clear_kb(event: CallbackQuery) -> None:
    """Снимаем кнопки с карточки жалобы, когда она отработана."""
    message = event.message
    if message is None or not hasattr(message, "edit_reply_markup"):
        return
    try:
        await message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass


# ---------------------------------------------------------------------------------- обзор
@router.message(Command("stats"))
async def cmd_stats(message: Message, ctx: Ctx, db: Database, mm: Matchmaker) -> None:
    if await _deny(ctx):
        return
    s = await db.stats()
    await ctx.reply(
        f"<b>Анончат {texts.esc(ctx.cfg.city_short)} · сводка</b>\n\n"
        f"Всего пользователей: <b>{s['users']}</b>\n"
        f"Активны за 7 дней: <b>{s['active_week']}</b>\n"
        f"Диалогов сыграно: <b>{s['dialogs']}</b>\n"
        f"Сообщений переслано: <b>{s['messages']}</b>\n"
        f"В очереди сейчас: <b>{mm.queue_size()}</b>\n"
        f"Активных пар: <b>{mm.online_pairs()}</b>\n"
        f"Открытых жалоб: <b>{s['open_reports']}</b>"
    )


@router.message(Command("queue"))
async def cmd_queue(message: Message, ctx: Ctx, mm: Matchmaker) -> None:
    if await _deny(ctx):
        return
    snap = mm.queue_snapshot(15)
    lines = [f"Очередь: <b>{mm.queue_size()}</b> · пар: <b>{mm.online_pairs()}</b>", ""]
    for i, (uid, district) in enumerate(snap, start=1):
        lines.append(f"{i}. <code>{uid}</code> · {texts.esc(district or 'район не указан')}")
    if not snap:
        lines.append("Пусто — никто не ждёт.")
    await ctx.reply("\n".join(lines))


# ---------------------------------------------------------------------------------- жалобы
@router.message(Command("reports"))
async def cmd_reports(message: Message, ctx: Ctx, db: Database) -> None:
    if await _deny(ctx):
        return
    rows = await db.list_reports("new", 10)
    if not rows:
        await ctx.reply("Открытых жалоб нет — город вежливый.")
        return
    for r in rows:
        await ctx.reply(
            f"🚩 <b>Жалоба #{r['id']}</b> · {time.strftime('%d.%m %H:%M', time.localtime(r['created_at']))}\n"
            f"Причина: <b>{texts.esc(r['reason'])}</b>\n"
            f"На: <code>{r['target_id']}</code> · в чате как "
            f"<b>{texts.esc(nicklib.display(r['target_nickname'], int(r['target_id'])))}</b>"
            f" ({texts.esc(r['target_name'] or '-')})\n"
            f"От: <code>{r['reporter_id']}</code>\n"
            f"{texts.esc(r['comment']) if r['comment'] else '<i>без комментария</i>'}",
            markup=K.admin_report_keyboard(int(r["id"])),
        )


@router.message(Command("resolve"))
async def cmd_resolve(message: Message, ctx: Ctx, db: Database) -> None:
    if await _deny(ctx):
        return
    args = _parse_args(message.text or "")
    if not args or not args[0].isdigit():
        await ctx.reply("Формат: <code>/resolve 12</code>")
        return
    ok = await db.resolve_report(int(args[0]), ctx.user_id)
    await ctx.reply("Жалоба закрыта." if ok else "Не нашёл открытую жалобу с таким номером.")


# ---------------------------------------------------------------------------------- санкции
@router.message(Command("ban"))
async def cmd_ban(message: Message, ctx: Ctx, db: Database, mm: Matchmaker, cfg: Config) -> None:
    if await _deny(ctx):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        await ctx.reply("Формат: <code>/ban 123456 спам и оскорбления</code>")
        return
    uid = int(parts[1])
    reason = parts[2] if len(parts) > 2 else "решение модератора"
    await db.set_ban(uid, True, reason)
    await break_pair(ctx.bot, cfg, mm, uid, "Собеседник отключился.", ctx.pack)
    await send_to(
        ctx.bot, uid, texts.BANNED.format(city=texts.esc(cfg.city), reason=texts.esc(reason)), None, ctx.pack
    )
    await ctx.reply(f"⛔ <code>{uid}</code> забанен. Причина: {texts.esc(reason)}")


@router.message(Command("unban"))
async def cmd_unban(message: Message, ctx: Ctx, db: Database) -> None:
    if await _deny(ctx):
        return
    parts = _parse_args(message.text or "")
    if not parts or not parts[0].lstrip("-").isdigit():
        await ctx.reply("Формат: <code>/unban 123456</code>")
        return
    await db.set_ban(int(parts[0]), False)
    await ctx.reply(f"✅ <code>{parts[0]}</code> разбанен, добро пожаловать обратно в город.")


@router.message(Command("mute"))
async def cmd_mute(message: Message, ctx: Ctx, db: Database, mm: Matchmaker, cfg: Config) -> None:
    if await _deny(ctx):
        return
    parts = _parse_args(message.text or "")
    if len(parts) < 2 or not parts[0].lstrip("-").isdigit() or not parts[1].isdigit():
        await ctx.reply("Формат: <code>/mute 123456 60</code> (id и минуты)")
        return
    until = await db.set_mute(int(parts[0]), int(parts[1]))
    await send_to(
        ctx.bot,
        int(parts[0]),
        texts.MUTED.format(mins=max(1, int((until - time.time()) // 60))),
        None,
        ctx.pack,
    )
    await break_pair(ctx.bot, cfg, mm, int(parts[0]), "Модерация закрыла диалог.", ctx.pack)
    await ctx.reply(f"🔇 <code>{parts[0]}</code> заглушён на {parts[1]} мин.")


@router.message(Command("find"))
async def cmd_find(message: Message, ctx: Ctx, db: Database) -> None:
    if await _deny(ctx):
        return
    query = (message.text or "").partition(" ")[2].strip()
    if not query:
        await ctx.reply("Формат: <code>/find @username</code> или <code>/find 123456</code>")
        return
    if query.lstrip("-").isdigit():
        rows = [r for r in [await db.get_user(int(query))] if r]
    else:
        rows = await db.find_user_ids(query, 10)
    if not rows:
        await ctx.reply("Никого не нашёл.")
        return
    lines = ["<b>Найдено</b>", ""]
    for r in rows:
        info = level_for(int(r["xp"]))
        lines.append(
            f"<code>{r['user_id']}</code> · в чате как <b>{texts.esc(nicklib.display(r['nickname'], int(r['user_id'])))}</b>"
            f" · {texts.esc(r['first_name'])} ({texts.esc(r['username'] or '-')})\n"
            f"   уровень {info.level} · {info.xp} XP · диалогов {r['dialogs']} · жалоб {r['reports_received']}"
            + (" · ⛔ бан" if r["banned"] else "")
        )
    await ctx.reply("\n".join(lines))


# ---------------------------------------------------------------------------------- рассылка
@router.message(Command("bc"))
async def cmd_broadcast(message: Message, ctx: Ctx, db: Database, cfg: Config) -> None:
    if await _deny(ctx):
        return
    body = (message.text or "").partition(" ")[2].strip()
    if not body:
        await ctx.reply("Формат: <code>/bc текст рассылки</code>")
        return
    ids = await db.active_ids(days=7)
    await ctx.reply(f"Рассылаю {len(ids)} адресатам…")
    sent = 0
    for uid in ids:
        if await send_to(ctx.bot, uid, f"📣 {body}", K.menu_keyboard(cfg.emoji_pack_url), ctx.pack):
            sent += 1
        await asyncio.sleep(0.05)  # бережём лимиты Telegram
    await ctx.reply(f"Готово: доставлено {sent} из {len(ids)}.")


# ---------------------------------------------------------------------------------- кнопки в карточке жалобы
@router.callback_query(F.data.startswith("adm:"))
async def cb_admin(event: CallbackQuery, ctx: Ctx, db: Database, mm: Matchmaker, cfg: Config) -> None:
    if not _is_admin(ctx):
        await ctx.ack("Не для тебя", show_alert=True)
        return
    _, action, raw_id = (event.data or "").split(":", 2)
    if not raw_id.isdigit():
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
        row = await db.get_user(target)
        if row is None:
            await ctx.ack("Нет такого профиля", alert=True)
            return
        info = level_for(int(row["xp"]))
        await ctx.reply(
            f"<code>{target}</code> · в чате как "
            f"<b>{texts.esc(nicklib.display(row['nickname'], target))}</b> · "
            f"{texts.esc(row['first_name'])} ({texts.esc(row['username'] or '-')})\n"
            f"уровень {info.level} · {info.xp} XP · «{texts.esc(info.title)}»\n"
            f"диалогов: {row['dialogs']} · сообщений: {row['messages']}\n"
            f"👍 {row['good_ratings']} · 👎 {row['bad_ratings']} · жалоб: {row['reports_received']}\n"
            f"{texts.esc(row['district'] or 'район не указан')} · "
            f"создан {time.strftime('%d.%m.%Y', time.localtime(row['created_at']))}"
            + ("\n⛔ в бане" if row["banned"] else "")
        )
        await ctx.ack("Показал профиль")
        return

    if action == "mute":
        until = await db.set_mute(target, 60)
        await send_to(ctx.bot, target, texts.MUTED.format(mins=60), None, ctx.pack)
        await break_pair(ctx.bot, cfg, mm, target, texts.MOD_CLOSED_DIALOG, ctx.pack)
        await db.resolve_report(int(raw_id), ctx.user_id)
        await ctx.ack(f"Мут до {time.strftime('%H:%M', time.localtime(until))}")
        await clear_kb(event)
        return

    if action == "ban":
        await db.set_ban(target, True, f"жалоба #{raw_id}: {report['reason']}")
        await break_pair(ctx.bot, cfg, mm, target, "Собеседник отключился.", ctx.pack)
        await send_to(
            ctx.bot,
            target,
            texts.BANNED.format(city=texts.esc(cfg.city), reason=texts.esc(f"жалоба #{raw_id}")),
            None,
            ctx.pack,
        )
        await db.resolve_report(int(raw_id), ctx.user_id)
        await ctx.ack("Забанен")
        await clear_kb(event)
        return

    await ctx.ack("Не понимаю кнопку")
