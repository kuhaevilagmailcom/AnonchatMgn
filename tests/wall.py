"""End-to-end domain checks for the Wall, run with python -m tests.wall."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from anonchat.db import Database
from anonchat.wall import Wall


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, user_id, text, **options):
        self.sent.append((user_id, text, options))


class FakeServer:
    def __init__(self, db):
        self.db = db
        self.cfg = SimpleNamespace(admin_ids=(101, 102))
        self.bot = FakeBot()
        self.events = []

    async def _auth(self, request):
        user_id = request.uid
        row = await self.db.ensure_user(user_id, None, "Пользователь")
        return user_id, {"id": user_id}, row

    async def _push_event(self, user_id, kind, title, text, **opts):
        self.events.append((user_id, title, text, opts))
        return 1


class Req:
    def __init__(self, uid, data=None, post=None, **query):
        self.uid = uid
        self.data = data or {}
        self.query = query
        self.match_info = {"post_id": str(post), "comment_id": str(post)}

    async def json(self):
        return self.data


async def check_wall():
    db = await Database(":memory:").start()
    try:
        server = FakeServer(db)
        wall = Wall(server)
        await wall.ensure_schema()
        await db.ensure_user(101, None, "Автор")
        await db.ensure_user(102, None, "Участник")
        await db.ensure_user(103, None, "Посторонний")
        allowed = json.loads((await wall.access(Req(101))).text)
        denied = json.loads((await wall.access(Req(103))).text)
        assert allowed["allowed"] is True and denied["allowed"] is False
        from aiohttp import web
        try:
            await wall.feed(Req(103,sort="new"))
            assert False, "Non-admin unexpectedly read Wall"
        except web.HTTPForbidden:
            pass
        await db.set_unique_nickname(101, "Автор МГН")
        new_post = await wall.create(Req(101, {"body": "Какие у нас новости?", "client_key": "post_create_demo_01"}))
        import json
        pid = json.loads(new_post.text)["id"]
        duplicate = await wall.create(Req(101, {"body":"Какие у нас новости?", "client_key":"post_create_demo_01"}))
        assert json.loads(duplicate.text)["id"] == pid
        assert json.loads(duplicate.text)["existing"]
        listing = json.loads((await wall.feed(Req(102,sort="new"))).text)
        assert listing["items"][0]["nick"] == "Автор МГН", listing
        assert "author_id" not in listing["items"][0]
        await wall.like(Req(102,{},pid))
        liked = json.loads((await wall.detail(Req(102,post=pid))).text)["post"]
        assert liked["likes"] == 1 and liked["liked"]
        await wall.like(Req(102,{},pid))
        disliked = json.loads((await wall.detail(Req(102,post=pid))).text)["post"]
        assert disliked["likes"] == 0 and not disliked["liked"]

        top_comment = json.loads((await wall.comment(Req(
            102, {"body": "Привет, я отвечаю!"}, pid
        ))).text)["id"]
        assert server.events[-1][0] == 101
        assert "Новый комментарий" in server.events[-1][1]
        assert server.bot.sent[-1][2]["reply_markup"].inline_keyboard[0][0].text == "Открыть стену"
        await db.db.execute(
            "UPDATE wall_comments SET created_at=created_at-15 WHERE id=?", (top_comment,)
        )
        reply = await wall.comment(Req(101,{"body": "А я отвечаю на комментарий", "parent_id":top_comment},pid))
        assert reply.status == 201
        assert server.events[-1][0] == 102
        assert "Вам ответили на комментарий" == server.events[-1][1]
        assert server.events[-1][3]["action"] == f"wall:{pid}"

        await db.set_unique_nickname(101, "Новый Ник")
        refreshed = json.loads((await wall.feed(Req(102,sort="new"))).text)
        assert refreshed["items"][0]["nick"] == "Новый Ник"

        await wall.report(Req(102,{"type":"post","id":pid}))
        reports = json.loads((await wall.moderation(Req(101))).text)
        assert len(reports["items"]) == 1
        await wall.moderate(Req(101,{"type":"post","id":pid,"hide":True}))
        hidden = json.loads((await wall.feed(Req(102,sort="new"))).text)
        assert hidden["items"] == []
        print("Wall checks passed: closed access, idempotent post, likes, replies, nicknames, moderation")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(check_wall())
