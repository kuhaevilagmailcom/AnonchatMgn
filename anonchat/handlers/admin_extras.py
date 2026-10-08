"""Админские экраны: список, карточки, журнал очков и безопасные действия."""
from __future__ import annotations

import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..actions import Ctx
from ..db import Database, month_period_start, referral_day_start, week_period_start
from ..matching import Matchmaker
from .. import nick as nicklib, texts
from .. import keyboards as K
from ..permissions import ALL_ADMIN_PERMISSIONS

router = Router(name="admin_extras")
TZ = ZoneInfo("Asia/Yekaterinburg")
SORTS = {"r": ("recent", "Недавно активные"), "n": ("new", "Новые"),
         "x": ("xp", "По очкам"), "m": ("messages", "По сообщениям"),
         "d": ("dialogs", "По диалогам")}
FILTERS = {"a": ("all", "Все"), "o": ("active", "Недавно онлайн"),
           "q": ("queue", "В поиске"), "c": ("dialog", "В диалоге"),
           "b": ("ban", "Заблокированы"), "u": ("mute", "В муте"),
           "s": ("support", "Поддержали"), "z": ("admins", "Администраторы")}
SOURCES = {"a": ("", "Все источники"), "m": ("message", "Сообщения"),
           "r": ("referral", "Рефералы"), "g": ("geoguessr", "GeoGuessr"),
           "n": ("numbers", "Числа"), "w": ("word_game", "Слова"),
           "b": ("battle", "Битва мнений"), "c": ("admin_award", "Админ +"),
           "d": ("admin_debit", "Админ −"), "o": ("other", "Другое")}
KIND = {"a": "Все", "p": "Начисления", "m": "Списания"}
PERIOD = {"a": "Всё время", "d": "Сегодня", "w": "Неделя", "m": "Месяц"}
XP_NAMES = {
    "opening_balance": "Начальный баланс", "message": "Сообщения",
    "dialog": "Диалог", "rating": "Оценка", "referral": "Приглашение",
    "battle": "Битва мнений", "numbers": "Числа", "word_game": "Слова",
    "geoguessr": "GeoGuessr", "achievement": "Достижение",
    "daily_quest": "Задание дня", "subscription": "Подписка",
    "report": "Жалоба", "admin_award": "Администратор",
    "admin_debit": "Администратор", "admin_legacy": "Старая команда",
    "game_bonus": "Бонус в диалоге",
}


class ExtraStates(StatesGroup):
    search = State()
    amount = State()
    reason = State()


def _date(timestamp: int) -> str:
    if not timestamp:
        return "—"
    return datetime.fromtimestamp(int(timestamp), TZ).strftime("%d.%m.%Y %H:%M")


def _name(row) -> str:
    return nicklib.display(row["nickname"], int(row["user_id"]), row["support_stars"])


def _button(b: InlineKeyboardBuilder, label: str, data: str) -> None:
    b.button(text=label, callback_data=data)


async def _screen(ctx: Ctx, body: str, markup) -> None:
    if not await ctx.edit(body, markup):
        await ctx.reply(body, markup)


async def show_users(
    ctx: Ctx, db: Database, mm: Matchmaker, state: FSMContext,
    sort: str = "r", filt: str = "a", page: int = 0,
) -> None:
    if not ctx.can("users"):
        await ctx.ack("Нет доступа", alert=True)
        return
    sort = sort if sort in SORTS else "r"
    filt = filt if filt in FILTERS else "a"
    page = max(0, min(int(page), 100000))
    stored = await state.get_data()
    query = str(stored.get("ax_query") or "")[:100]
    ids: list[int] = []
    if filt == "q":
        ids = list(mm._queue)
    elif filt == "c":
        ids = list(mm._pairs)
    rows, total = await db.admin_user_list(
        limit=12, offset=12*page, sort=SORTS[sort][0],
        filter_by=FILTERS[filt][0], query=query, ids=ids,
    )
    if page and page * 12 >= total:
        return await show_users(ctx, db, mm, state, sort, filt, max(0, (total-1)//12))
    pages = max(1, (total+11)//12)
    lines = [f"👥 <b>Пользователи · {total}</b>",
             f"Страница {page+1}/{pages} · {SORTS[sort][1]}",
             f"Фильтр: {FILTERS[filt][1]}" + (f" · поиск: {texts.esc(query)}" if query else ""),
             ""]
    for i, u in enumerate(rows, 1+12*page):
        lines.append(
            f"<b>{i}. {texts.esc(_name(u))}</b> · {int(u['xp']):,} ⭐\n"
            f"{texts.esc('@'+u['username'] if u['username'] else 'username отсутствует')} "
            f"· ID <code>{u['user_id']}</code>\n"
            f"{int(u['messages']):,} сообщений · {int(u['dialogs']):,} диалогов\n"
            f"Был: {_date(u['last_seen'])}\n"
        )
    if not rows:
        lines.append("По этому фильтру никого нет.")
    b = InlineKeyboardBuilder()
    for u in rows:
        _button(b, _name(u)[:25], f"ax:u:{u['user_id']}:{sort}:{filt}:{page}")
    b.adjust(*([1] * len(rows)))
    for code, (_, name) in SORTS.items():
        _button(b, ("✓ " if sort==code else "")+name, f"ax:l:{code}:{filt}:0")
    for code, (_, name) in FILTERS.items():
        _button(b, ("✓ " if filt==code else "")+name, f"ax:l:{sort}:{code}:0")
    if page > 0:
        _button(b, "← Назад", f"ax:l:{sort}:{filt}:{page-1}")
    if (page+1)*12 < total:
        _button(b, "Вперёд →", f"ax:l:{sort}:{filt}:{page+1}")
    _button(b, "🔎 Поиск", "ax:q")
    if query:
        _button(b, "Сбросить поиск", "ax:clear")
    _button(b, "В админку", K.CB_PANEL_BACK)
    b.adjust(*([1] * len(rows)), 2, 2, 1, 2, 2, 2, 2, 2, 1, 1)
    await _screen(ctx, "\n".join(lines)[:4000], b.as_markup())


async def show_card(
    ctx: Ctx, db: Database, mm: Matchmaker, uid: int,
    sort: str = "r", filt: str = "a", page: int = 0,
) -> None:
    if not ctx.can("users"):
        await ctx.ack("Нет доступа", alert=True)
        return
    user = await db.get_user(uid)
    if user is None:
        await ctx.ack("Пользователь не найден", alert=True)
        return
    invited, earned = await db.referral_stats(uid)
    perms = await db.get_admin_permissions(uid, ctx.cfg.admin_ids)
    status = {"free": "Свободен", "queued": "В поиске", "paired": "В диалоге"}.get(mm.status(uid), "—")
    text = (
        f"👤 <b>{texts.esc(_name(user))}</b>\n"
        f"Telegram: {texts.esc('@'+user['username'] if user['username'] else 'username отсутствует')}\n"
        f"ID: <code>{uid}</code> · {texts.esc(user['first_name'] or '—')}\n"
        f"Регистрация: {_date(user['created_at'])}\n"
        f"Был: {_date(user['last_seen'])} · {status}\n"
        f"Район: {texts.esc(user['district'] or 'любой')} · возраст: {user['age']}\n"
        f"Пол: {texts.esc(user['gender'] or 'любой')}; ищет: {texts.esc(user['looking_for'] or 'любого')}\n\n"
        f"⭐ Баланс: <b>{user['xp']}</b> · поддержка: {user['support_stars']} Stars\n"
        f"Сообщения: {user['messages']} · диалоги: {user['dialogs']}\n"
        f"Оценки: 👍 {user['good_ratings']} · 👎 {user['bad_ratings']}\n"
        f"Жалобы: {user['reports_received']}\n"
        f"Приглашения: {invited} · получено: {earned} ⭐\n"
        f"Бан: {'да' if user['banned'] else 'нет'} · {texts.esc(user['ban_reason'] or '—')}\n"
        f"Мут до: {_date(user['mute_until']) if int(user['mute_until'])>int(datetime.now(TZ).timestamp()) else 'нет'}\n"
        f"Админ: {'да' if perms else 'нет'}"
        + (f" · {texts.esc(', '.join(sorted(perms)))}" if perms else "")
    )
    b = InlineKeyboardBuilder()
    _button(b,"⭐ История начислений",f"ax:h:{uid}:a:a:0:a")
    if ctx.can('points'):
        _button(b,"➕ Выдать",f"ax:a:{uid}:+")
        _button(b,"➖ Списать",f"ax:a:{uid}:-")
    if ctx.can('monitor'):
        _button(b,"💬 Текущий диалог",f"ax:chat:{uid}")
    if ctx.can('reports'):
        _button(b,"🚩 Жалобы",f"ax:reports:{uid}")
    if ctx.can('ban'):
        _button(b,"⛔ Разбан" if user['banned'] else "⛔ Бан",f"ax:b:{uid}")
    if ctx.can('mute'):
        _button(b,"🔇 Снять мут" if int(user['mute_until'])>int(datetime.now(TZ).timestamp()) else "🔇 Мут 60 мин",f"ax:m:{uid}")
    if ctx.is_owner or ctx.admin_permissions == ALL_ADMIN_PERMISSIONS:
        _button(b,"👮 Права",f"ax:perms:{uid}")
    _button(b,"🔄 Обновить",f"ax:u:{uid}:{sort}:{filt}:{page}")
    _button(b,"← К списку",f"ax:l:{sort}:{filt}:{page}")
    b.adjust(1,2,1,1,2,1,1)
    await _screen(ctx,text,b.as_markup())


async def show_history(
    ctx: Ctx, db: Database, uid: int, kind: str = 'a',
    period: str = 'a', offset: int = 0, source_code: str = 'a',
) -> None:
    if not ctx.can("users"):
        await ctx.ack("Нет доступа", alert=True)
        return
    user = await db.get_user(uid)
    if user is None:
        await ctx.ack("Нет профиля", alert=True)
        return
    kind = kind if kind in KIND else 'a'
    period = period if period in PERIOD else 'a'
    source_code = source_code if source_code in SOURCES else 'a'
    since = {'a':0, 'd':referral_day_start(), 'w':week_period_start(),
             'm':month_period_start()}[period]
    offset = max(0, int(offset))
    rows, info = await db.xp_history(
        uid, offset=offset, kind={'a':'all','p':'plus','m':'minus'}[kind],
        since=since, source=SOURCES[source_code][0],
    )
    opening_amount = 0
    if kind in {'a', 'p'} and source_code == 'a':
        opening = await db._fetchone(
            "SELECT COALESCE(SUM(amount),0) AS n FROM xp_transactions "
            "WHERE user_id=? AND source='opening_balance' AND created_at>=?",
            (uid, since),
        )
        opening_amount = int(opening["n"] or 0) if opening else 0
    lines = [f"⭐ <b>История · {texts.esc(_name(user))}</b>",
             f"Баланс: <b>{user['xp']} ⭐</b>",
             f"{KIND[kind]} · {PERIOD[period]} · {SOURCES[source_code][1]}",
             f"Начислено: +{max(0, info['credits'] - opening_amount)} · Списано: −{info['debits']}",
             f"Начальный баланс: {opening_amount} ⭐ (архив)" if opening_amount else "",
             f"Операций: {info['count']}", ""]
    for r in rows:
        amount = int(r['amount'])
        details = str(r['reason'] or r['reference_id'] or '')
        lines.append(
            f"{amount:+} ⭐ · <b>{texts.esc(XP_NAMES.get(r['source'],r['source']))}</b>\n"
            f"{_date(r['created_at'])}"
            + (f" · {texts.esc(details[:85])}" if details else "")
            + (f" · админ <code>{r['actor_id']}</code>" if r['actor_id'] else "")
            + "\n"
        )
    if not rows:
        lines.append("Операций пока нет.")
    b = InlineKeyboardBuilder()
    for code, label in KIND.items():
        _button(b,("✓ " if code==kind else "")+label,f"ax:h:{uid}:{code}:{period}:0:{source_code}")
    for code,label in PERIOD.items():
        _button(b,("✓ " if code==period else "")+label,f"ax:h:{uid}:{kind}:{code}:0:{source_code}")
    for code, (_, label) in SOURCES.items():
        _button(b, ("✓ " if code==source_code else "")+label,
                f"ax:h:{uid}:{kind}:{period}:0:{code}")
    if offset:
        _button(b,"← Назад",f"ax:h:{uid}:{kind}:{period}:{max(0,offset-10)}:{source_code}")
    if offset+10 < info['count']:
        _button(b,"Вперёд →",f"ax:h:{uid}:{kind}:{period}:{offset+10}:{source_code}")
    _button(b,"← Профиль",f"ax:u:{uid}:r:a:0")
    b.adjust(3,4,2,2,2,2,2,1)
    await _screen(ctx,"\n".join(lines)[:3900],b.as_markup())


async def show_top_check(ctx: Ctx, db: Database, period: str) -> None:
    if not ctx.can('stats'):
        await ctx.ack("Нет доступа",alert=True)
        return
    period = period if period in {'w','m','a'} else 'w'
    days={'w':7,'m':30,'a':0}[period]
    rows = await db.top_period(days,10)
    lines=[f"🏆 <b>Проверка топа · {PERIOD[{'w':'w','m':'m','a':'a'}[period]]}</b>",""]
    for i,u in enumerate(rows,1):
        lines.append(f"{i}. {texts.esc(_name(u))} · {u['xp']} ⭐ · ID <code>{u['user_id']}</code>")
    if not rows:
        lines.append("Пока нет участников.")
    lines.append("\nПериоды: Магнитогорск (UTC+5). Telegram и Mini App используют общие методы БД.")
    b=InlineKeyboardBuilder()
    for c,label in [('w','Неделя'),('m','Месяц'),('a','Всё время')]:
        _button(b,("✓ " if c==period else "")+label,f"ax:t:{c}")
    _button(b,"В админку",K.CB_PANEL_BACK)
    b.adjust(3,1)
    await _screen(ctx,"\n".join(lines),b.as_markup())



async def show_global_ledger(ctx: Ctx, db: Database, offset: int = 0) -> None:
    """Админский журнал без загрузки всего массива транзакций."""
    if not ctx.can("points"):
        await ctx.ack("Нет доступа", alert=True)
        return
    offset = max(0, min(int(offset), 1000000))
    rows = await db._fetchall(
        """SELECT t.*, u.nickname, u.support_stars
           FROM xp_transactions t
           JOIN users u ON u.user_id=t.user_id
          ORDER BY t.id DESC LIMIT 13 OFFSET ?""",
        (offset,),
    )
    totals = await db._fetchone(
        """SELECT
           COALESCE(SUM(CASE WHEN amount>0 AND source<>'opening_balance'
                             THEN amount ELSE 0 END),0) AS earned,
           COALESCE(SUM(CASE WHEN amount<0 THEN -amount ELSE 0 END),0) AS spent
           FROM xp_transactions WHERE created_at>=?""",
        (referral_day_start(),),
    )
    shown = rows[:12]
    lines = ["⭐ <b>Начисления · журнал</b>",
             f"За сегодня: +{int(totals['earned'] or 0)} ⭐ · −{int(totals['spent'] or 0)} ⭐",
             "<i>Начальный баланс — это снимок, не заработанные сегодня очки.</i>",
             f"Операции {offset+1}–{offset+len(shown)}", ""]
    b = InlineKeyboardBuilder()
    for r in shown:
        sign = int(r["amount"])
        desc = XP_NAMES.get(str(r["source"]), str(r["source"]))
        lines.append(
            f"<b>{sign:+} ⭐</b> · {texts.esc(desc)} · {texts.esc(_name(r))}\n"
            f"ID <code>{r['user_id']}</code> · {_date(r['created_at'])}"
            + (f" · {texts.esc(str(r['reason'])[:70])}" if r["reason"] else "")
        )
        if ctx.can("users"):
            _button(b, f"ID {r['user_id']} · {sign:+} ⭐", f"ax:u:{r['user_id']}:r:a:0")
    if not shown:
        lines.append("Операций ещё нет.")
    if offset:
        _button(b, "← Назад", f"ax:ledger:{max(0,offset-12)}")
    if len(rows) > 12:
        _button(b, "Дальше →", f"ax:ledger:{offset+12}")
    if ctx.can("users"):
        _button(b, "Найти пользователя", "ax:q")
    _button(b, "В админку", K.CB_PANEL_BACK)
    b.adjust(*([1]*len(shown)), 2, 1, 1)
    await _screen(ctx, "\n".join(lines)[:3900], b.as_markup())


async def show_active_chats(ctx: Ctx, db: Database, mm: Matchmaker, page: int = 0) -> None:
    if not ctx.can("monitor"):
        await ctx.ack("Нет доступа", alert=True)
        return
    # Обходим только активные пары matchmaker, не всю таблицу users.
    pairs = sorted({
        tuple(sorted((int(uid), int(pair.partner_of(uid)))))
        for uid, pair in mm._pairs.items()
    })
    page = max(0, min(int(page), max(0, (len(pairs)-1)//12)))
    selected = pairs[page*12:(page+1)*12]
    user_ids = sorted({uid for pair in selected for uid in pair})
    user_rows = {}
    if user_ids:
        placeholders = ",".join("?" for _ in user_ids)
        people = await db._fetchall(
            f"SELECT user_id, nickname, support_stars FROM users WHERE user_id IN ({placeholders})",
            tuple(user_ids),
        )
        user_rows = {int(u["user_id"]): u for u in people}
    lines = [f"💬 <b>Активные диалоги · {len(pairs)}</b>",
             f"Страница {page+1}/{max(1,(len(pairs)+11)//12)}", ""]
    b = InlineKeyboardBuilder()
    for i, (a,c) in enumerate(selected, 1+12*page):
        name_a = _name(user_rows[a]) if a in user_rows else str(a)
        name_c = _name(user_rows[c]) if c in user_rows else str(c)
        lines.append(f"{i}. {texts.esc(name_a)} ↔ {texts.esc(name_c)}\n"
                     f"<code>{a}</code> · <code>{c}</code>")
        if ctx.can("users"):
            _button(b, f"Карточка {a}", f"ax:u:{a}:r:a:0")
            _button(b, f"Карточка {c}", f"ax:u:{c}:r:a:0")
    if not selected:
        lines.append("Сейчас нет активных диалогов.")
    if page:
        _button(b, "← Назад", f"ax:chats:{page-1}")
    if (page+1)*12 < len(pairs):
        _button(b, "Вперёд →", f"ax:chats:{page+1}")
    _button(b, "Обновить", f"ax:chats:{page}")
    _button(b, "В админку", K.CB_PANEL_BACK)
    b.adjust(*([2]*len(selected)), 2, 2)
    await _screen(ctx, "\n".join(lines)[:3900], b.as_markup())


async def start_search(ctx: Ctx,state:FSMContext) -> None:
    await state.set_state(ExtraStates.search)
    await _screen(ctx,"🔎 Отправь ID, @username, ник или имя. Для сброса нажми «Отмена».",K.panel_cancel_keyboard())


async def _preview(ctx:Ctx, state:FSMContext, db:Database, uid:int, delta:int, reason:str) -> None:
    user=await db.get_user(uid)
    if user is None:
        await ctx.reply("Пользователь не найден.")
        return
    before=int(user['xp'])
    if before+delta<0:
        await ctx.reply("Недостаточно очков для списания.")
        return
    nonce=secrets.token_hex(8)
    await state.set_state(None)
    await state.update_data(ax_uid=uid,ax_delta=delta,ax_reason=reason,ax_nonce=nonce)
    b=InlineKeyboardBuilder()
    _button(b,"Подтвердить",f"ax:ok:{nonce}")
    _button(b,"Отмена",f"ax:u:{uid}:r:a:0")
    b.adjust(2)
    await ctx.reply(
        f"⭐ <b>Изменение баланса</b>\n"
        f"Пользователь: {texts.esc(_name(user))}\nID: <code>{uid}</code>\n"
        f"Было: {before} ⭐\nИзменение: {delta:+} ⭐\n"
        f"Станет: {before+delta} ⭐\nПричина: {texts.esc(reason)}",
        b.as_markup()
    )


@router.message(ExtraStates.search)
async def search_message(message:Message,ctx:Ctx,db:Database,mm:Matchmaker,state:FSMContext) -> None:
    if not ctx.can("users"):
        await state.clear()
        return
    query=(message.text or '').strip()[:100]
    await state.set_state(None)
    await state.update_data(ax_query=query)
    await show_users(ctx,db,mm,state)


@router.message(ExtraStates.amount)
async def amount_message(message:Message,ctx:Ctx,db:Database,state:FSMContext) -> None:
    if not ctx.can("points"):
        await state.clear()
        return
    stored=await state.get_data()
    raw=(message.text or '').strip()
    if not raw.isdigit() or not 1<=int(raw)<=1000000:
        await ctx.reply("Укажи целое число от 1 до 1 000 000.")
        return
    await state.update_data(ax_delta=int(raw)*int(stored.get('ax_sign',1)))
    await state.set_state(ExtraStates.reason)
    await ctx.reply("Укажи причину операции (обязательно):")


@router.message(ExtraStates.reason)
async def reason_message(message:Message,ctx:Ctx,db:Database,state:FSMContext) -> None:
    if not ctx.can("points"):
        await state.clear()
        return
    stored=await state.get_data()
    reason=(message.text or '').strip()
    if not reason or len(reason)>500:
        await ctx.reply("Укажи причину от 1 до 500 символов.")
        return
    uid=int(stored.get('ax_uid',0))
    delta=int(stored.get('ax_delta',0))
    if not uid or not delta:
        await state.clear()
        await ctx.reply("Действие устарело, начни заново.")
        return
    await _preview(ctx,state,db,uid,delta,reason)


@router.callback_query(F.data.startswith("ax:"))
async def extras_callback(
    event:CallbackQuery,ctx:Ctx,db:Database,mm:Matchmaker,state:FSMContext,
) -> None:
    if not ctx.is_admin:
        await ctx.ack("Нет доступа",alert=True)
        return
    parts=(event.data or '').split(':')
    action=parts[1] if len(parts)>1 else ''
    try:
        if action == 'ledger' and len(parts)==3:
            await show_global_ledger(ctx, db, int(parts[2]))
        elif action == 'chats' and len(parts)==3:
            await show_active_chats(ctx, db, mm, int(parts[2]))
        elif action == 'l' and len(parts)==5:
            await show_users(ctx,db,mm,state,parts[2],parts[3],int(parts[4]))
        elif action == 'q':
            if not ctx.can("users"):
                raise PermissionError
            await start_search(ctx,state)
        elif action == 'clear':
            if not ctx.can("users"):
                raise PermissionError
            await state.update_data(ax_query='')
            await show_users(ctx,db,mm,state)
        elif action == 'u' and len(parts)==6:
            await show_card(ctx,db,mm,int(parts[2]),parts[3],parts[4],int(parts[5]))
        elif action == 'h' and len(parts)==7:
            await show_history(ctx,db,int(parts[2]),parts[3],parts[4],int(parts[5]),parts[6])
        elif action == 't' and len(parts)==3:
            await show_top_check(ctx,db,parts[2])
        elif action == 'a' and len(parts)==4:
            if not ctx.can('points'):
                raise PermissionError
            uid=int(parts[2])
            sign=1 if parts[3]=='+' else -1
            await state.set_state(None)
            await state.update_data(ax_uid=uid,ax_sign=sign)
            b=InlineKeyboardBuilder()
            for amount in (10,25,50,100,250,500):
                _button(b,f"{amount} ⭐",f"ax:v:{uid}:{sign*amount}")
            _button(b,"Другая сумма",f"ax:c:{uid}:{sign}")
            _button(b,"Отмена",f"ax:u:{uid}:r:a:0")
            b.adjust(3,3,1,1)
            await _screen(ctx,"Выдача очков" if sign==1 else "Списание очков",b.as_markup())
        elif action == 'v' and len(parts)==4:
            if not ctx.can('points'):
                raise PermissionError
            uid,delta=int(parts[2]),int(parts[3])
            if not 1<=abs(delta)<=1000000:
                raise ValueError
            await state.set_state(ExtraStates.reason)
            await state.update_data(ax_uid=uid,ax_delta=delta)
            await _screen(ctx,f"Изменение: {delta:+} ⭐\nОтправь обязательную причину:",K.panel_cancel_keyboard())
        elif action == 'c' and len(parts)==4:
            if not ctx.can('points'):
                raise PermissionError
            await state.set_state(ExtraStates.amount)
            await state.update_data(ax_uid=int(parts[2]),ax_sign=int(parts[3]))
            await _screen(ctx,"Введи сумму от 1 до 1 000 000:",K.panel_cancel_keyboard())
        elif action == 'ok' and len(parts)==3:
            if not ctx.can('points'):
                raise PermissionError
            stored=await state.get_data()
            if parts[2] != stored.get('ax_nonce'):
                await ctx.ack("Подтверждение устарело",alert=True)
                return
            uid=int(stored['ax_uid'])
            balance,applied=await db.change_xp(
                uid,int(stored['ax_delta']),
                source='admin_award' if int(stored['ax_delta'])>0 else 'admin_debit',
                reason=str(stored['ax_reason']), actor_id=ctx.user_id,
                idempotency_key=f"admin:{ctx.user_id}:{parts[2]}",
            )
            await state.clear()
            await _screen(ctx,f"{'Готово' if applied else 'Уже выполнено'}. Баланс <code>{uid}</code>: <b>{balance} ⭐</b>",K.panel_back_keyboard())
        elif action in ('b','m') and len(parts)==3:
            needed='ban' if action=='b' else 'mute'
            if not ctx.can(needed):
                raise PermissionError
            uid=int(parts[2]);u=await db.get_user(uid)
            if u is None:
                raise ValueError
            op = 'unban' if action=='b' and u['banned'] else (
                 'ban' if action=='b' else 'unmute' if int(u['mute_until'])>int(datetime.now(TZ).timestamp()) else 'mute')
            nonce=secrets.token_hex(5)
            await state.update_data(ax_mod_uid=uid,ax_mod_op=op,ax_mod_nonce=nonce)
            b=InlineKeyboardBuilder()
            _button(b,"Подтвердить",f"ax:mod:{nonce}")
            _button(b,"Отмена",f"ax:u:{uid}:r:a:0")
            b.adjust(2)
            await _screen(ctx,f"Подтвердить {texts.esc(op)} для ID <code>{uid}</code>?",b.as_markup())
        elif action=='mod' and len(parts)==3:
            d=await state.get_data()
            uid=int(d.get('ax_mod_uid') or 0);op=d.get('ax_mod_op')
            if not uid or d.get('ax_mod_nonce')!=parts[2]:
                await ctx.ack("Действие устарело",alert=True)
                return
            needed='ban' if op in ('ban','unban') else 'mute'
            if not ctx.can(needed):
                raise PermissionError
            from .admin import do_ban, do_mute
            await state.clear()
            if op=='ban':
                await do_ban(ctx,db,mm,ctx.cfg,uid,'решение администрации')
            elif op=='unban':
                await db.set_ban(uid,False)
            elif op=='mute':
                await do_mute(ctx,db,mm,ctx.cfg,uid,60)
            elif op=='unmute':
                await db.set_mute(uid,0)
            await show_card(ctx,db,mm,uid)
        elif action=='chat' and len(parts)==3:
            if not ctx.can('monitor'):
                raise PermissionError
            uid=int(parts[2]);p=mm.partner(uid)
            await _screen(ctx,f"💬 ID <code>{uid}</code> · собеседник: <code>{p}</code>" if p else "Активного диалога нет.",K.panel_back_keyboard())
        elif action=='reports' and len(parts)==3:
            if not ctx.can('reports'):
                raise PermissionError
            uid=int(parts[2])
            rows=await db._fetchall("SELECT id, reason, status, created_at FROM reports WHERE target_id=? ORDER BY created_at DESC LIMIT 10",(uid,))
            lines=[f"🚩 Жалобы на <code>{uid}</code>"]
            lines += [f"#{r['id']} · {texts.esc(r['reason'])} · {texts.esc(r['status'])}" for r in rows]
            await _screen(ctx,"\n".join(lines),K.panel_back_keyboard())
        elif action=='perms' and len(parts)==3:
            if not (ctx.is_owner or ctx.admin_permissions == ALL_ADMIN_PERMISSIONS):
                raise PermissionError
            uid=int(parts[2]);perms=await db.get_admin_permissions(uid,ctx.cfg.admin_ids)
            await _screen(ctx,f"👮 ID <code>{uid}</code>\nПрава: {texts.esc(', '.join(sorted(perms)) or 'нет')}\nИзменить: /adminperms {uid} all",K.panel_back_keyboard())
        else:
            await ctx.ack("Кнопка устарела",alert=True)
            return
        await ctx.ack()
    except PermissionError:
        await ctx.ack("У тебя нет этого права",alert=True)
    except (ValueError, KeyError, IndexError):
        await ctx.ack("Некорректная или устаревшая кнопка",alert=True)
