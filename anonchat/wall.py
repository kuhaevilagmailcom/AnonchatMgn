"""Anon MGN Wall: Threads-like posts, comments, reactions and moderation.

Telegram identities are stored only in SQLite. Public responses contain display
nicknames, never Telegram user IDs/usernames.
"""
from __future__ import annotations

import html
import json
import os
import logging
import time

from aiohttp import web
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import nick as nicklib
from .safety import contains_contact

log = logging.getLogger(__name__)

WALL_SCHEMA = """
CREATE TABLE IF NOT EXISTS wall_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id INTEGER NOT NULL REFERENCES users(user_id),
    body TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    hidden INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_wall_posts_feed ON wall_posts(hidden, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_wall_posts_author ON wall_posts(author_id, created_at DESC);
CREATE TABLE IF NOT EXISTS wall_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES wall_posts(id),
    parent_id INTEGER REFERENCES wall_comments(id),
    author_id INTEGER NOT NULL REFERENCES users(user_id),
    body TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    hidden INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_wall_comments_post ON wall_comments(post_id, hidden, created_at, id);
CREATE TABLE IF NOT EXISTS wall_likes (
    post_id INTEGER NOT NULL REFERENCES wall_posts(id),
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    created_at INTEGER NOT NULL,
    PRIMARY KEY (post_id, user_id)
);
CREATE TABLE IF NOT EXISTS wall_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id INTEGER NOT NULL REFERENCES users(user_id),
    target_type TEXT NOT NULL CHECK(target_type IN ('post','comment')),
    target_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    resolved_at INTEGER,
    UNIQUE(reporter_id, target_type, target_id)
);
CREATE INDEX IF NOT EXISTS idx_wall_reports_pending ON wall_reports(resolved_at, created_at DESC);
"""


def _error(code: int, message: str):
    exceptions = {
        400: web.HTTPBadRequest,
        403: web.HTTPForbidden,
        404: web.HTTPNotFound,
        409: web.HTTPConflict,
        429: web.HTTPTooManyRequests,
    }
    raise exceptions.get(code, web.HTTPBadRequest)(
        text=json.dumps({"message": message}, ensure_ascii=False),
        content_type="application/json",
    )


def _body(value, maximum: int) -> str:
    if not isinstance(value, str):
        _error(400, "Текст обязателен")
    text = value.strip()
    if not text or len(text) > maximum:
        _error(400, f"Напиши от 1 до {maximum} символов")
    if contains_contact(text):
        _error(400, "Нельзя публиковать контакты и личные данные")
    return text


def _id(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        _error(400, "Некорректный номер")
    if number < 1:
        _error(400, "Некорректный номер")
    return number


class Wall:
    def __init__(self, server):
        self.server = server
        self.db = server.db

    async def ensure_schema(self):
        await self.db.db.executescript(WALL_SCHEMA)

    async def _staff(self, uid):
        if int(uid) in self.server.cfg.admin_ids:
            return True
        permissions = await self.db.get_admin_permissions(uid, self.server.cfg.admin_ids)
        return bool(permissions)

    async def access(self, request):
        uid, _, _ = await self.server._auth(request)
        allowed = await self._staff(uid)
        return web.json_response({"allowed": bool(allowed), "public": False})

    async def _user(self, request, *, write=False):
        uid, _tg, row = await self.server._auth(request)
        # Feature is in closed beta: never expose content based only on a
        # client-side hidden navigation button or user-supplied uid.
        if not await self._staff(uid):
            _error(403, "Стена пока доступна только администраторам")
        if write and (bool(row["banned"]) or int(row["mute_until"] or 0) > int(time.time())):
            _error(403, "Публикации временно недоступны")
        return uid

    async def _admin(self, uid):
        perms = await self.db.get_admin_permissions(uid, self.server.cfg.admin_ids)
        return "reports" in perms

    def _post_payload(self, r, uid):
        author_id = int(r["author_id"])
        return {
            "id": int(r["id"]),
            "body": str(r["body"]),
            "nick": nicklib.display(r["nickname"], author_id, r["support_stars"]),
            "mine": uid == author_id,
            "created_at": int(r["created_at"]),
            "updated_at": int(r["updated_at"]),
            "likes": int(r["likes"]),
            "comments": int(r["comments"]),
            "liked": bool(r["liked"]),
        }

    async def _post(self, post_id, uid):
        return await self.db._fetchone(
            """SELECT p.*, u.nickname, u.support_stars,
                      (SELECT COUNT(*) FROM wall_likes l WHERE l.post_id=p.id) AS likes,
                      (SELECT COUNT(*) FROM wall_comments c
                        WHERE c.post_id=p.id AND c.hidden=0) AS comments,
                      EXISTS(SELECT 1 FROM wall_likes l
                        WHERE l.post_id=p.id AND l.user_id=?) AS liked
               FROM wall_posts p JOIN users u ON u.user_id=p.author_id
               WHERE p.id=? AND p.hidden=0""",
            (uid, post_id),
        )

    async def feed(self, request):
        uid = await self._user(request)
        mode = request.query.get("sort", "new")
        if mode not in ("new", "top", "mine"):
            _error(400, "Неизвестная сортировка")
        try:
            offset = max(0, min(int(request.query.get("offset", "0")), 2000))
        except ValueError:
            _error(400, "Некорректная страница")
        where = "p.hidden=0"
        params = [uid]
        if mode == "mine":
            where += " AND p.author_id=?"
            params.append(uid)
        order = ("(SELECT COUNT(*) FROM wall_likes l WHERE l.post_id=p.id) * 3 + "
                 "(SELECT COUNT(*) FROM wall_comments c WHERE c.post_id=p.id AND c.hidden=0) * 2 DESC, "
                 "p.created_at DESC") if mode == "top" else "p.created_at DESC, p.id DESC"
        # Parenthesize the entire score to sort it as one expression.
        if mode == "top":
            order = ("((SELECT COUNT(*) FROM wall_likes l WHERE l.post_id=p.id) * 3 + "
                     "(SELECT COUNT(*) FROM wall_comments c WHERE c.post_id=p.id AND c.hidden=0) * 2) DESC, "
                     "p.created_at DESC")
        rows = await self.db._fetchall(
            f"""SELECT p.*, u.nickname, u.support_stars,
                        (SELECT COUNT(*) FROM wall_likes l WHERE l.post_id=p.id) AS likes,
                        (SELECT COUNT(*) FROM wall_comments c
                         WHERE c.post_id=p.id AND c.hidden=0) AS comments,
                        EXISTS(SELECT 1 FROM wall_likes l
                         WHERE l.post_id=p.id AND l.user_id=?) AS liked
                 FROM wall_posts p JOIN users u ON u.user_id=p.author_id
                 WHERE {where} ORDER BY {order} LIMIT 21 OFFSET ?""",
            (*params, offset),
        )
        return web.json_response({
            "items": [self._post_payload(r, uid) for r in rows[:20]],
            "more": len(rows) > 20,
            "offset": offset + min(len(rows), 20),
            "is_admin": await self._admin(uid),
        })

    async def create(self, request):
        uid = await self._user(request, write=True)
        data = await request.json()
        body = _body(data.get("body"), 1000)
        last = await self.db._fetchone(
            "SELECT created_at FROM wall_posts WHERE author_id=? ORDER BY id DESC LIMIT 1",
            (uid,),
        )
        now = int(time.time())
        if last and now - int(last["created_at"]) < 60:
            _error(429, "Новый пост можно опубликовать через минуту")
        cur = await self.db.db.execute(
            "INSERT INTO wall_posts(author_id,body,created_at,updated_at) VALUES(?,?,?,?)",
            (uid, body, now, now),
        )
        return web.json_response({"ok": True, "id": cur.lastrowid}, status=201)

    async def detail(self, request):
        uid = await self._user(request)
        post_id = _id(request.match_info["post_id"])
        r = await self._post(post_id, uid)
        if not r:
            _error(404, "Пост не найден или скрыт")
        rows = await self.db._fetchall(
            """SELECT c.*,u.nickname,u.support_stars
               FROM wall_comments c JOIN users u ON u.user_id=c.author_id
               WHERE c.post_id=? AND c.hidden=0
               ORDER BY c.created_at ASC,c.id ASC LIMIT 501""",
            (post_id,),
        )
        return web.json_response({
            "post": self._post_payload(r, uid),
            "comments": [{
                "id": int(c["id"]), "parent_id": c["parent_id"],
                "body": str(c["body"]), "mine": int(c["author_id"]) == uid,
                "is_author": int(c["author_id"]) == int(r["author_id"]),
                "nick": nicklib.display(c["nickname"], int(c["author_id"]), c["support_stars"]),
                "created_at": int(c["created_at"]),
            } for c in rows[:500]],
            "truncated": len(rows) > 500,
            "is_admin": await self._admin(uid),
        })

    async def comment(self, request):
        uid = await self._user(request, write=True)
        post_id = _id(request.match_info["post_id"])
        data = await request.json()
        body = _body(data.get("body"), 500)
        post = await self._post(post_id, uid)
        if not post:
            _error(404, "Пост не найден")
        parent_id = _id(data["parent_id"]) if data.get("parent_id") else None
        parent = None
        if parent_id:
            parent = await self.db._fetchone(
                "SELECT * FROM wall_comments WHERE id=? AND post_id=? AND hidden=0",
                (parent_id, post_id),
            )
            if not parent:
                _error(404, "Комментарий для ответа не найден")
        latest = await self.db._fetchone(
            "SELECT created_at FROM wall_comments WHERE author_id=? ORDER BY id DESC LIMIT 1",
            (uid,),
        )
        now = int(time.time())
        if latest and now - int(latest["created_at"]) < 8:
            _error(429, "Подожди несколько секунд перед следующим комментарием")
        cur = await self.db.db.execute(
            """INSERT INTO wall_comments(post_id,parent_id,author_id,body,created_at,updated_at)
               VALUES(?,?,?,?,?,?)""",
            (post_id, parent_id, uid, body, now, now),
        )
        # Replies notify their comment's author; top-level messages notify post's author.
        recipient = int(parent["author_id"]) if parent else int(post["author_id"])
        if recipient != uid:
            title = "Вам ответили на комментарий" if parent else "Новый комментарий к вашему посту"
            snippet = str(post["body"]).replace("\n", " ")[:85]
            await self.server._push_event(
                recipient, "personal", title, f"Под постом: {snippet}",
                icon="message-circle", action=f"wall:{post_id}",
            )
            # Telegram failures must never roll back an already-published comment.
            try:
                await self.server.bot.send_message(
                    recipient,
                    f"💬 <b>{html.escape(title)}</b>\nПод постом: «{html.escape(snippet)}»",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(
                            text="Открыть стену",
                            url=f"https://t.me/AnonChatMgn_Bot/anonmgn?startapp=wall_{post_id}",
                        )
                    ]]),
                )
            except Exception as exc:
                log.info("wall reply Telegram notice skipped: %s", type(exc).__name__)
        return web.json_response({"ok": True, "id": cur.lastrowid}, status=201)

    async def like(self, request):
        uid = await self._user(request, write=True)
        post_id = _id(request.match_info["post_id"])
        if not await self._post(post_id, uid):
            _error(404, "Пост не найден")
        found = await self.db._fetchone(
            "SELECT 1 FROM wall_likes WHERE post_id=? AND user_id=?", (post_id, uid)
        )
        if found:
            await self.db.db.execute(
                "DELETE FROM wall_likes WHERE post_id=? AND user_id=?", (post_id, uid)
            )
        else:
            await self.db.db.execute(
                "INSERT OR IGNORE INTO wall_likes(post_id,user_id,created_at) VALUES(?,?,?)",
                (post_id, uid, int(time.time())),
            )
        row = await self._post(post_id, uid)
        return web.json_response({"ok": True, "liked": bool(row["liked"]), "likes": int(row["likes"])})

    async def edit(self, request):
        uid = await self._user(request, write=True)
        post_id = _id(request.match_info["post_id"])
        row = await self._post(post_id, uid)
        if not row or int(row["author_id"]) != uid:
            _error(404, "Свой пост не найден")
        body = _body((await request.json()).get("body"), 1000)
        await self.db.db.execute(
            "UPDATE wall_posts SET body=?,updated_at=? WHERE id=? AND author_id=? AND hidden=0",
            (body, int(time.time()), post_id, uid),
        )
        return web.json_response({"ok": True})

    async def remove(self, request):
        uid = await self._user(request, write=True)
        post_id = _id(request.match_info["post_id"])
        cur = await self.db.db.execute(
            "UPDATE wall_posts SET hidden=2 WHERE id=? AND author_id=? AND hidden=0",
            (post_id, uid),
        )
        if not cur.rowcount:
            _error(404, "Свой пост не найден")
        return web.json_response({"ok": True})

    async def remove_comment(self, request):
        uid = await self._user(request, write=True)
        cid = _id(request.match_info["comment_id"])
        cur = await self.db.db.execute(
            "UPDATE wall_comments SET hidden=2 WHERE id=? AND author_id=? AND hidden=0",
            (cid, uid),
        )
        if not cur.rowcount:
            _error(404, "Свой комментарий не найден")
        return web.json_response({"ok": True})

    async def report(self, request):
        uid = await self._user(request, write=True)
        data = await request.json()
        target_type = data.get("type")
        target_id = _id(data.get("id"))
        reason = str(data.get("reason") or "Нарушение правил").strip()[:200]
        if target_type not in ("post", "comment"):
            _error(400, "Тип жалобы не поддерживается")
        table = "wall_posts" if target_type == "post" else "wall_comments"
        target = await self.db._fetchone(
            f"SELECT author_id FROM {table} WHERE id=? AND hidden=0", (target_id,)
        )
        if not target:
            _error(404, "Публикация не найдена")
        if int(target["author_id"]) == uid:
            _error(400, "Нельзя пожаловаться на себя")
        await self.db.db.execute(
            """INSERT OR IGNORE INTO wall_reports
               (reporter_id,target_type,target_id,reason,created_at)
               VALUES(?,?,?,?,?)""",
            (uid, target_type, target_id, reason, int(time.time())),
        )
        return web.json_response({"ok": True})

    async def moderation(self, request):
        uid = await self._user(request)
        if not await self._admin(uid):
            _error(403, "Нет доступа")
        rows = await self.db._fetchall(
            """SELECT r.*, CASE WHEN r.target_type='post' THEN
                    (SELECT body FROM wall_posts WHERE id=r.target_id)
                   ELSE (SELECT body FROM wall_comments WHERE id=r.target_id) END AS body
               FROM wall_reports r WHERE r.resolved_at IS NULL
               ORDER BY r.created_at ASC LIMIT 100"""
        )
        return web.json_response({"items": [
            {"id": r["id"], "type": r["target_type"], "target_id": r["target_id"],
             "body": r["body"], "reason": r["reason"], "created_at": r["created_at"]}
            for r in rows
        ]})

    async def moderate(self, request):
        uid = await self._user(request)
        if not await self._admin(uid):
            _error(403, "Нет доступа")
        data = await request.json()
        target_type = data.get("type")
        target_id = _id(data.get("id"))
        if target_type not in ("post", "comment"):
            _error(400, "Неизвестный тип")
        table = "wall_posts" if target_type == "post" else "wall_comments"
        hide = bool(data.get("hide", True))
        await self.db.db.execute(
            f"UPDATE {table} SET hidden=? WHERE id=? AND hidden<>2",
            (1 if hide else 0, target_id),
        )
        await self.db.db.execute(
            "UPDATE wall_reports SET resolved_at=? WHERE target_type=? AND target_id=?",
            (int(time.time()), target_type, target_id),
        )
        return web.json_response({"ok": True})


def install_wall_routes(app, server):
    wall = Wall(server)
    server.wall = wall
    prefix = "/api/miniapp/wall"
    app.router.add_get(prefix + "/access", wall.access)
    app.router.add_get(prefix, wall.feed)
    app.router.add_post(prefix, wall.create)
    app.router.add_get(prefix + "/moderation", wall.moderation)
    app.router.add_post(prefix + "/moderate", wall.moderate)
    app.router.add_post(prefix + "/report", wall.report)
    app.router.add_post(prefix + "/comments/{comment_id}/delete", wall.remove_comment)
    app.router.add_get(prefix + "/{post_id}", wall.detail)
    app.router.add_post(prefix + "/{post_id}/comments", wall.comment)
    app.router.add_post(prefix + "/{post_id}/like", wall.like)
    app.router.add_post(prefix + "/{post_id}/edit", wall.edit)
    app.router.add_post(prefix + "/{post_id}/delete", wall.remove)
