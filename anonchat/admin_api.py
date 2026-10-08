"""Access-controlled Telegram Mini App administration API.

Every request is authenticated through Telegram-signed initData, then its
permission is checked against the current database policy. No admin data is
exposed by ordinary Mini App endpoints.
"""
from __future__ import annotations

import asyncio
import json
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import aiosqlite
from aiohttp import web

from .db import referral_day_start, week_period_start, month_period_start, now
from .permissions import ALL_ADMIN_PERMISSIONS, parse_permissions
from .diagnostics import METRICS


def _json_error(status: int, message: str) -> web.HTTPException:
    cls = {400: web.HTTPBadRequest, 401: web.HTTPUnauthorized,
           403: web.HTTPForbidden, 404: web.HTTPNotFound,
           409: web.HTTPConflict, 422: web.HTTPUnprocessableEntity}.get(status, web.HTTPBadRequest)
    return cls(text=json.dumps({"message": message}, ensure_ascii=False),
               content_type="application/json")


def _number(v: object, default: int = 0, low: int = 0, high: int = 100000) -> int:
    try:
        n = int(v)
    except (ValueError, TypeError):
        n = default
    return min(high, max(low, n))


def _rows(rows) -> list[dict]:
    return [dict(r) for r in rows]


def _since(period: str) -> int:
    return {
        "today": referral_day_start,
        "week": week_period_start,
        "month": month_period_start,
        "all": lambda: 0,
    }.get(period, lambda: 0)()


class MiniAppAdmin:
    def __init__(self, server):
        self.s = server
        self.jobs: dict[str, dict] = {}

    async def access(self, request: web.Request, permission: str | None = None):
        uid, _, _ = await self.s._auth(request)
        perms = await self.s.db.get_admin_permissions(uid, self.s.cfg.admin_ids)
        if not perms:
            raise _json_error(403, "Раздел доступен только администрации")
        if permission and permission not in perms:
            raise _json_error(403, "Недостаточно прав для этого действия")
        return uid, perms, uid in self.s.cfg.admin_ids

    async def body(self, request):
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (ValueError, TypeError, json.JSONDecodeError):
            raise _json_error(400, "Некорректные данные запроса")

    async def dashboard(self, request):
        uid, permissions, owner = await self.access(request)
        stats = await self.s.db.stats()
        games = await self.s.db.game_diagnostics()
        from .runtime_state import online_count
        return web.json_response({
            "id": uid, "owner": owner, "permissions": sorted(permissions),
            "stats": stats, "games": games,
            "queue": self.s.mm.queue_size(), "dialogs": self.s.mm.online_pairs(),
            "online": online_count(), "multiplier": await self.s.db.xp_multiplier(),
            "db_mb": round(self.s.db.path.stat().st_size / 1048576, 2) if self.s.db.path.exists() else 0,
            "uptime": METRICS.uptime_seconds(),
            "version": METRICS.version,
        })

    async def users(self, request):
        await self.access(request, "users")
        q = request.query
        filt = q.get("filter", "all")
        ids: list[int] = []
        if filt == "queue":
            ids = list(self.s.mm._queue)
        elif filt == "dialog":
            ids = list(self.s.mm._pairs)
        page = _number(q.get("page", "0"), high=100000)
        rows, count = await self.s.db.admin_user_list(
            sort=q.get("sort", "recent"), filter_by=filt,
            query=q.get("q", "")[:100], ids=ids, limit=12, offset=page * 12
        )
        return web.json_response({
            "items": _rows(rows), "total": count, "page": page, "pages": max(1, (count+11)//12),
        })

    async def user(self, request):
        await self.access(request, "users")
        uid = _number(request.match_info["user_id"], low=1, high=9999999999999)
        r = await self.s.db.get_user(uid)
        if r is None:
            raise _json_error(404, "Пользователь не найден")
        invited, earned = await self.s.db.referral_stats(uid)
        permissions = await self.s.db.get_admin_permissions(uid, self.s.cfg.admin_ids)
        return web.json_response({
            "user": dict(r), "status": self.s.mm.status(uid),
            "partner_id": self.s.mm.partner(uid),
            "referrals": {"invited": invited, "earned": earned},
            "admin_permissions": sorted(permissions),
        })

    async def transactions(self, request):
        uid, perms, _ = await self.access(request)
        q = request.query
        selected_user = _number(q.get("user_id"), low=0, high=9999999999999)
        if selected_user:
            if not ({"users", "points"} & set(perms)):
                raise _json_error(403, "Нет права просмотра истории пользователей")
        elif "points" not in perms:
            raise _json_error(403, "Глобальный журнал доступен только администраторам экономики")
        kind = q.get("kind", "all")
        if kind not in ("all", "plus", "minus"):
            kind = "all"
        period = q.get("period", "all")
        source = q.get("source", "")[:60]
        page = _number(q.get("page", "0"), high=100000)
        parts = ["1=1"]
        args: list[object] = []
        if selected_user:
            parts.append("t.user_id=?")
            args.append(selected_user)
        if kind == "plus":
            parts.append("t.amount>0")
        elif kind == "minus":
            parts.append("t.amount<0")
        if source:
            parts.append("t.source=?")
            args.append(source)
        since = _since(period)
        if since:
            parts.append("t.created_at>=?")
            args.append(since)
        where = " AND ".join(parts)
        totals = await self.s.db._fetchone(
            f"""SELECT COUNT(*) n,
                     COALESCE(SUM(CASE WHEN t.amount>0 AND t.source<>'opening_balance' THEN t.amount ELSE 0 END),0) credits,
                     COALESCE(SUM(CASE WHEN t.amount<0 THEN -t.amount ELSE 0 END),0) debits
                FROM xp_transactions t WHERE {where}""", args
        )
        rows = await self.s.db._fetchall(
            f"""SELECT t.id,t.user_id,t.amount,t.balance_after,t.source,t.reason,
                       t.actor_id,t.reference_type,t.reference_id,t.created_at,
                       u.nickname,u.username,
                       COALESCE(u.support_stars,0) support_stars
                  FROM xp_transactions t
                  LEFT JOIN users u ON u.user_id=t.user_id
                 WHERE {where}
                 ORDER BY t.id DESC LIMIT 21 OFFSET ?""",
            (*args, page * 20),
        )
        # The opening balance is a snapshot, not new earnings. Show it as a
        # separate metric to prevent misleading "+earned today" totals.
        opening = await self.s.db._fetchone(
            "SELECT COALESCE(SUM(amount),0) n FROM xp_transactions "
            "WHERE source='opening_balance'" + (" AND user_id=?" if selected_user else ""),
            (selected_user,) if selected_user else (),
        )
        return web.json_response({
            "items": _rows(rows[:20]), "has_more": len(rows)>20, "page":page,
            "totals": {k: int(totals[k]) for k in ("n","credits","debits")},
            "opening_balance": int(opening["n"] or 0),
            "note": "Стартовый баланс — снимок прошлого. Историю до внедрения журнала невозможно восстановить.",
        })

    async def sources(self, request):
        await self.access(request, "points")
        rows = await self.s.db._fetchall(
            "SELECT source, COUNT(*) n FROM xp_transactions GROUP BY source ORDER BY n DESC LIMIT 100"
        )
        return web.json_response({"items": _rows(rows)})

    async def adjust(self, request):
        uid, _, _ = await self.access(request, "points")
        data = await self.body(request)
        target = _number(data.get("user_id"), low=1, high=9999999999999)
        try:
            amount = int(data.get("amount"))
        except (ValueError, TypeError):
            raise _json_error(400, "Укажи сумму")
        reason = str(data.get("reason") or "").strip()
        key = str(data.get("key") or "")
        if not amount or abs(amount) > 1000000:
            raise _json_error(400, "Сумма от 1 до 1 000 000 очков")
        if not reason or len(reason)>500:
            raise _json_error(400, "Причина обязательна (до 500 символов)")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{16,90}", key):
            raise _json_error(400, "Некорректный ключ подтверждения")
        try:
            balance, applied = await self.s.db.change_xp(
                target, amount, source="admin_award" if amount>0 else "admin_debit",
                reason=reason, actor_id=uid,
                reference_type="miniapp", reference_id="manual",
                idempotency_key=f"miniadmin:{uid}:{key}",
            )
        except ValueError as exc:
            raise _json_error(400, str(exc))
        return web.json_response({"balance":balance, "applied":applied, "user_id":target})

    async def rankings(self, request):
        await self.access(request, "stats")
        periods = {"week":7, "month":30, "all":0}
        period=request.query.get("period","week")
        if period not in periods:
            raise _json_error(400, "Неподдерживаемый период")
        rows=await self.s.db.top_period(periods[period], 10)
        return web.json_response({"period":period,"items":[
            {"place":i,"user_id":int(row["user_id"]),"nickname":row["nickname"] or "",
             "xp":int(row["xp"] or 0),"messages":int(row["messages"] or 0),
             "dialogs":int(row["dialogs"] or 0)}
            for i,row in enumerate(rows,1)
        ]})

    async def reports(self, request):
        await self.access(request, "reports")
        status=request.query.get("status","new")
        if status not in ("new","done"):
            status="new"
        page=_number(request.query.get("page",0),high=100000)
        count = await self.s.db._fetchone(
            "SELECT COUNT(*) n FROM reports WHERE status=?", (status,)
        )
        rows=await self.s.db._fetchall(
            """SELECT r.id,r.created_at,r.reporter_id,r.target_id,r.reason,r.comment,
                      r.status,r.handled_by,r.handled_at,
                      u.nickname target_nickname, u.username target_username
                 FROM reports r LEFT JOIN users u ON u.user_id=r.target_id
                WHERE r.status=? ORDER BY r.created_at DESC,r.id DESC LIMIT 15 OFFSET ?""",
            (status,page*15),
        )
        return web.json_response({"items":_rows(rows),"total":int(count["n"]),"page":page,
                                  "pages":max(1,(int(count["n"])+14)//15)})

    async def restrictions(self, request):
        uid, perms, _ = await self.access(request)
        kind = request.query.get("kind","ban")
        if kind not in ("ban","mute") or kind not in perms:
            raise _json_error(403,"Нет доступа к списку ограничений")
        page=_number(request.query.get("page",0),high=100000)
        rows,total=await self.s.db.list_restricted(kind,limit=15,offset=page*15)
        return web.json_response({"items":_rows(rows),"total":total,"page":page,
                                  "pages":max(1,(total+14)//15)})

    async def moderation(self, request):
        actor, perms, owner=await self.access(request)
        data=await self.body(request)
        action=str(data.get("action") or "")
        reason=str(data.get("reason") or "").strip()[:500]
        key=str(data.get("key") or "")
        target=_number(data.get("user_id"),low=0,high=9999999999999)
        report_id=_number(data.get("report_id"),low=0,high=9999999999)
        minutes=_number(data.get("minutes",60),low=1,high=43200)
        if not re.fullmatch(r"[a-zA-Z0-9_-]{16,90}",key) or not reason:
            raise _json_error(400,"Подтверждение и причина обязательны")
        if action not in ("ban","unban","mute","unmute","report_close","report_ban","report_mute"):
            raise _json_error(400,"Неизвестное действие")
        need=("reports" if action=="report_close" else
              "ban" if action in ("ban","unban","report_ban") else "mute")
        if need not in perms or (action.startswith("report_") and "reports" not in perms):
            raise _json_error(403,"Недостаточно прав")
        db=self.s.db
        async with aiosqlite.connect(db.path,isolation_level=None) as con:
            con.row_factory=aiosqlite.Row
            await con.execute("PRAGMA busy_timeout=10000")
            await con.execute("BEGIN IMMEDIATE")
            try:
                async with con.execute("SELECT id FROM admin_action_log WHERE action_key=?",(key,)) as cur:
                    previous=await cur.fetchone()
                if previous:
                    await con.rollback()
                    return web.json_response({"applied":False,"message":"Действие уже выполнено"})
                if action.startswith("report_"):
                    async with con.execute(
                        "SELECT * FROM reports WHERE id=? AND status='new'",(report_id,)
                    ) as cur:
                        report=await cur.fetchone()
                    if not report:
                        raise _json_error(409,"Жалоба уже рассмотрена")
                    target=int(report["target_id"])
                else:
                    report=None
                if action!="report_close":
                    if not target or target==actor or target in self.s.cfg.admin_ids:
                        raise _json_error(403,"Нельзя ограничить этот аккаунт")
                    async with con.execute("SELECT 1 FROM admins WHERE user_id=?",(target,)) as cur:
                        if await cur.fetchone():
                            raise _json_error(403,"Сначала сними права администратора")
                    async with con.execute("SELECT 1 FROM users WHERE user_id=?",(target,)) as cur:
                        if not await cur.fetchone():
                            raise _json_error(404,"Пользователь не найден")
                if action in ("ban","report_ban"):
                    await con.execute("UPDATE users SET banned=1,ban_reason=?,mute_until=0 WHERE user_id=?",(reason,target))
                if action=="unban":
                    await con.execute("UPDATE users SET banned=0,ban_reason='' WHERE user_id=?",(target,))
                if action in ("mute","report_mute"):
                    await con.execute("UPDATE users SET mute_until=? WHERE user_id=?",(now()+minutes*60,target))
                if action=="unmute":
                    await con.execute("UPDATE users SET mute_until=0 WHERE user_id=?",(target,))
                if report is not None:
                    await con.execute(
                        "UPDATE reports SET status='done',handled_by=?,handled_at=? WHERE id=?",
                        (actor,now(),report_id)
                    )
                await con.execute(
                    """INSERT INTO admin_action_log(
                       action_key,actor_id,target_id,action,reason,reference_id,created_at
                    ) VALUES(?,?,?,?,?,?,?)""",
                    (key,actor,target,action,reason,report_id,now()),
                )
                await con.commit()
            except BaseException:
                await con.rollback()
                raise
        db._top_cache.clear()
        if action in ("ban","mute","report_ban","report_mute"):
            from .actions import break_pair, send_to
            from . import texts
            try:
                await break_pair(
                    self.s.bot,self.s.cfg,self.s.mm,target,texts.MOD_CLOSED_DIALOG,
                    self.s.pack,db,
                )
                db.schedule_matchmaker_save(self.s.mm)
                if action in ("ban","report_ban"):
                    await send_to(
                        self.s.bot,target,
                        texts.BANNED.format(
                            city=texts.esc(self.s.cfg.city),
                            reason=texts.esc(reason)),
                        None,self.s.pack,
                    )
                else:
                    await send_to(
                        self.s.bot,target,
                        texts.MUTED.format(mins=minutes),None,self.s.pack,
                    )
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Failed to notify moderation target")
        # Reward only when moderation actually took effect, once per report.
        if report is not None and action in ("report_ban","report_mute"):
            try:
                await db.claim_one_time_reward(
                    int(report["reporter_id"]),f"approved_report:{report_id}",10
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Report reward failed: %s",report_id)
        return web.json_response({"applied":True,"message":"Действие выполнено","target_id":target})

    async def action_log(self, request):
        await self.access(request,"stats")
        page=_number(request.query.get("page",0),high=100000)
        rows=await self.s.db._fetchall(
            "SELECT actor_id,target_id,action,reason,reference_id,created_at "
            "FROM admin_action_log ORDER BY id DESC LIMIT 21 OFFSET ?",
            (page*20,),
        )
        return web.json_response({"items":_rows(rows[:20]),"page":page,"has_more":len(rows)>20})

    async def chats(self, request):
        await self.access(request,"monitor")
        page=_number(request.query.get("page",0),high=10000)
        pairs=sorted({(min(uid, pair.partner_of(uid)),max(uid,pair.partner_of(uid)))
                     for uid,pair in self.s.mm._pairs.items()})
        selected=pairs[page*15:(page+1)*15]
        return web.json_response({"total":len(pairs),"page":page,
              "pages":max(1,(len(pairs)+14)//15),
              "items":[{"user_a":a,"user_b":b} for a,b in selected]})

    async def queue(self, request):
        await self.access(request,"queue")
        page=_number(request.query.get("page",0),high=10000)
        entries=self.s.mm.queue_debug_snapshot((page+1)*15)
        selected=entries[page*15:(page+1)*15]
        return web.json_response({"items":selected,"page":page,
          "total":self.s.mm.queue_size(),
          "pages":max(1,(self.s.mm.queue_size()+14)//15)})

    async def polls(self, request):
        _,_,owner=await self.access(request)
        if not owner:
            raise _json_error(403,"Опросами управляет владелец")
        poll=await self.s.db.active_poll()
        return web.json_response({
            "active":dict(poll) if poll else None,
            "results":await self.s.db.poll_results(int(poll["id"])) if poll else {},
            "voters":_rows(await self.s.db.poll_voters(int(poll["id"]),limit=80)) if poll else [],
        })

    async def update_poll(self, request):
        actor,_,owner=await self.access(request)
        if not owner:
            raise _json_error(403,"Опросами управляет владелец")
        data=await self.body(request)
        action=str(data.get("action") or "")
        key=str(data.get("key") or "")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{16,90}",key):
            raise _json_error(400,"Некорректное подтверждение")
        if action not in ("create","close"):
            raise _json_error(400,"Неизвестное действие")
        q=str(data.get("question") or "").strip()[:250]
        a=str(data.get("option_a") or "").strip()[:48]
        b=str(data.get("option_b") or "").strip()[:48]
        if action=="create" and not (q and a and b):
            raise _json_error(400,"Укажи вопрос и два варианта ответа")
        row=await self.s.db.db.execute(
            """INSERT OR IGNORE INTO admin_action_log
               (action_key,actor_id,target_id,action,reason,created_at)
               VALUES(?,?,0,?,?,?)""",(key,actor,"poll_"+action,q,now()),
        )
        if not row.rowcount:
            return web.json_response({"applied":False})
        try:
            if action=="create":
                poll_id=await self.s.db.create_poll(q,a,b,actor)
                return web.json_response({"applied":True,"id":poll_id})
            result=await self.s.db.close_active_poll()
            return web.json_response({"applied":True,"closed":result})
        except Exception:
            await self.s.db.db.execute(
                "DELETE FROM admin_action_log WHERE action_key=?",(key,)
            )
            raise

    async def export_transactions(self, request):
        actor,permissions,_=await self.access(request)
        selected=_number(request.query.get("user_id"),low=0,high=9999999999999)
        if not ("points" in permissions or (selected and "users" in permissions)):
            raise _json_error(403,"Экспорт недоступен")
        period=request.query.get("period","all")
        kind=request.query.get("kind","all")
        source=request.query.get("source","")[:60]
        query=["1=1"]
        args=[]
        if selected:
            query.append("t.user_id=?");args.append(selected)
        if kind=="plus":
            query.append("t.amount>0")
        elif kind=="minus":
            query.append("t.amount<0")
        if source:
            query.append("t.source=?");args.append(source)
        since=_since(period)
        if since:
            query.append("t.created_at>=?");args.append(since)
        import csv
        import io
        response=web.StreamResponse(headers={
            "Content-Type":"text/csv; charset=utf-8",
            "Content-Disposition":'attachment; filename="anon_mgn_xp_history.csv"',
            "Cache-Control":"no-store",
        })
        await response.prepare(request)
        await response.write(bytes((239,187,191)))
        def csvline(values):
            buf=io.StringIO()
            writer=csv.writer(buf)
            writer.writerow([
                "'"+str(v) if str(v).lstrip().startswith(("=","+","-","@")) and not isinstance(v,(int,float)) else v
                for v in values
            ])
            return buf.getvalue().encode("utf-8")
        await response.write(csvline(["id","user_id","amount","balance_after","source","reason",
                                      "actor_id","reference_type","reference_id","created_at"]))
        cursor=await self.s.db.db.execute(
            """SELECT t.id,t.user_id,t.amount,t.balance_after,t.source,t.reason,
                      t.actor_id,t.reference_type,t.reference_id,t.created_at
                 FROM xp_transactions t WHERE """+" AND ".join(query)+
            " ORDER BY t.id DESC LIMIT 50000",tuple(args)
        )
        try:
            async for row in cursor:
                await response.write(csvline(tuple(row)))
        finally:
            await cursor.close()
        await response.write_eof()
        return response

    async def games(self, request):
        await self.access(request,"monitor")
        page=_number(request.query.get("page",0),high=100000)
        count=await self.s.db._fetchone(
            "SELECT COUNT(*) n FROM battle_games WHERE status IN ('invited','active','round_done')"
        )
        rows=await self.s.db._fetchall(
            """SELECT id,user_a,user_b,game_type,status,question_index,total_questions,
                      range_max,updated_at FROM battle_games
               WHERE status IN ('invited','active','round_done')
               ORDER BY updated_at DESC LIMIT 15 OFFSET ?""",(page*15,)
        )
        return web.json_response({"items":_rows(rows),"total":int(count["n"]), "page":page,
                                  "pages":max(1,(int(count["n"])+14)//15)})

    async def analytics(self, request):
        await self.access(request,"stats")
        payments=await self.s.db.payment_stats()
        grouped=await self.s.db._fetchall(
            """SELECT source, COUNT(*) operations,
                      COALESCE(SUM(CASE WHEN amount>0 THEN amount ELSE 0 END),0) credits,
                      COALESCE(SUM(CASE WHEN amount<0 THEN -amount ELSE 0 END),0) debits
               FROM xp_transactions WHERE created_at>=? AND source<>'opening_balance'
               GROUP BY source ORDER BY credits DESC""",(week_period_start(),)
        )
        return web.json_response({"payments":payments,"sources":_rows(grouped),
                                  "games":await self.s.db.game_diagnostics()})

    async def admins(self, request):
        actor,_,owner=await self.access(request)
        if not owner:
            raise _json_error(403,"Управление администраторами доступно владельцу")
        rows=await self.s.db.list_admins()
        return web.json_response({"items":_rows(rows),
                  "owners":list(self.s.cfg.admin_ids),
                  "permission_names":sorted(ALL_ADMIN_PERMISSIONS)})

    async def save_admin(self, request):
        actor,_,owner=await self.access(request)
        if not owner:
            raise _json_error(403,"Только владелец может менять права")
        data=await self.body(request)
        target=_number(data.get("user_id"),low=1,high=9999999999999)
        if target in self.s.cfg.admin_ids:
            raise _json_error(400,"Права владельца задаются ADMIN_IDS")
        p=data.get("permissions")
        permissions=parse_permissions(",".join(str(x) for x in p)) if isinstance(p,list) else parse_permissions(str(p or ""))
        if permissions:
            await self.s.db.set_admin(target,permissions,actor)
        else:
            await self.s.db.remove_admin(target)
        return web.json_response({"ok":True,"permissions":sorted(permissions)})

    async def diagnostics(self, request):
        await self.access(request,"stats")
        db=self.s.db
        return web.json_response({
            "status":"online","version":METRICS.version,"uptime":METRICS.uptime_seconds(),
            "db_bytes":db.path.stat().st_size if db.path.exists() else 0,
            "queue":self.s.mm.queue_size(),"pairs":self.s.mm.online_pairs(),
            "games":await db.game_diagnostics(),
            "telegram_errors":METRICS.temp_errors, "unavailable":METRICS.unavailable,
            "janitor_removed_games":METRICS.janitor_removed_games,
            "last_cleanup_at":METRICS.last_cleanup_at,
            "last_matchmaker_save_at":METRICS.last_matchmaker_save_at,
        })

    async def change_multiplier(self, request):
        actor,_,owner=await self.access(request,"points")
        if not owner:
            raise _json_error(403,"Множителем управляет только владелец")
        data=await self.body(request)
        value=_number(data.get("value"),low=1,high=3)
        if value not in (1,2,3):
            raise _json_error(400,"Множитель x1/x2/x3")
        return web.json_response({"multiplier":await self.s.db.set_xp_multiplier(value)})

    async def broadcast(self, request):
        actor, _, _ = await self.access(request, "broadcast")
        data = await self.body(request)
        message = str(data.get("message") or "").strip()
        key = str(data.get("key") or "")
        label = str(data.get("button_text") or "").strip()[:45]
        url = str(data.get("button_url") or "").strip()
        if not message or len(message) > 3000:
            raise _json_error(400, "Текст рассылки должен содержать от 1 до 3000 символов")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{16,90}", key):
            raise _json_error(400, "Необходимо подтверждение рассылки")
        if bool(label) != bool(url):
            raise _json_error(400, "Для кнопки нужны и текст, и ссылка")
        if url and (urlsplit(url).scheme != "https" or not urlsplit(url).netloc):
            raise _json_error(400, "Разрешены только HTTPS-ссылки")
        cur = await self.s.db.db.execute(
            """INSERT OR IGNORE INTO admin_action_log
               (action_key,actor_id,target_id,action,reason,created_at)
               VALUES(?,?,0,'broadcast',?,?)""",
            (key, actor, f"Text broadcast ({len(message)} chars)", now()),
        )
        if not cur.rowcount:
            return web.json_response({"started":False,"message":"Эта рассылка уже запускалась"})
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        markup = (InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=label, url=url)
        ]]) if url else None)
        self.jobs[key] = {"status":"running","sent":0,"failed":0}
        async def deliver():
            from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
            last_id = 0
            try:
                while True:
                    receivers = await self.s.db._fetchall(
                        """SELECT user_id FROM users WHERE user_id>? AND banned=0
                           ORDER BY user_id ASC LIMIT 100""",(last_id,)
                    )
                    if not receivers:
                        break
                    for r in receivers:
                        target = int(r["user_id"])
                        last_id = target
                        try:
                            await self.s.bot.send_message(
                                target,message,parse_mode=None,reply_markup=markup,
                                disable_web_page_preview=True,
                            )
                            self.jobs[key]["sent"] += 1
                        except TelegramRetryAfter as exc:
                            await asyncio.sleep(min(float(exc.retry_after), 30.0))
                            self.jobs[key]["failed"] += 1
                        except TelegramAPIError:
                            self.jobs[key]["failed"] += 1
                        await asyncio.sleep(0.06)
                self.jobs[key]["status"] = "complete"
            except Exception:
                self.jobs[key]["status"] = "error"
                import logging
                logging.getLogger(__name__).exception("Admin broadcast failed")
        asyncio.create_task(deliver(),name=f"admin-broadcast:{key[:10]}")
        return web.json_response({"started":True,"key":key})

    async def broadcast_status(self, request):
        await self.access(request,"broadcast")
        key=request.query.get("key","")
        return web.json_response(self.jobs.get(key,{"status":"unknown","sent":0,"failed":0}))

    async def backup(self, request):
        _,_,owner=await self.access(request)
        if not owner:
            raise _json_error(403,"Только владелец скачивает базу")
        import aiofiles
        with tempfile.NamedTemporaryFile(prefix="anonmgn_",suffix=".db",delete=False) as f:
            path=Path(f.name)
        try:
            await self.s.db.flush_matchmaker(self.s.mm)
            await self.s.db.backup_to(path)
            resp=web.StreamResponse(headers={
                "Content-Type":"application/octet-stream",
                "Content-Disposition":'attachment; filename="anon_mgn_backup.db"',
                "Cache-Control":"no-store",
            })
            await resp.prepare(request)
            async with aiofiles.open(path,"rb") as f:
                while chunk:=await f.read(128*1024):
                    await resp.write(chunk)
            await resp.write_eof()
            return resp
        finally:
            path.unlink(missing_ok=True)


def install_admin_routes(app: web.Application, server) -> MiniAppAdmin:
    a=MiniAppAdmin(server)
    prefix="/api/miniapp/admin"
    for path,handler in (
        ("/bootstrap",a.dashboard), ("/users",a.users),
        ("/users/{user_id}",a.user), ("/transactions",a.transactions),
        ("/sources",a.sources),("/rankings",a.rankings),
        ("/reports",a.reports), ("/restrictions",a.restrictions),
        ("/chats",a.chats),("/queue",a.queue),("/games",a.games),
        ("/polls",a.polls),("/transactions/export",a.export_transactions),
        ("/analytics",a.analytics),("/admins",a.admins),
        ("/actions",a.action_log), ("/diagnostics",a.diagnostics),
        ("/backup",a.backup),("/broadcast/status",a.broadcast_status),
    ):
        app.router.add_get(prefix+path,handler)
    for path,handler in (
        ("/adjust",a.adjust), ("/moderate",a.moderation),
        ("/admins",a.save_admin),("/multiplier",a.change_multiplier),
        ("/broadcast",a.broadcast),("/polls",a.update_poll)
    ):
        app.router.add_post(prefix+path,handler)
    return a
