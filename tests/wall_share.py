"""Native Wall sharing: branded JPEG, full caption, tagged deep links."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web

from anonchat.db import Database
from anonchat.wall import Wall
from anonchat.wall_share import wall_link, share_caption, preview, prepare_share
from tests.wall import FakeServer, FakeBot, Req


class PreparedBot(FakeBot):
    def __init__(self):
        super().__init__()
        self.prepared = None

    async def save_prepared_inline_message(self, **kwargs):
        self.prepared = kwargs
        return SimpleNamespace(id="test-prepared-message")


async def check():
    assert "startapp=wall__utm_source_tg__utm_medium_post" in wall_link(
        source="tg", medium="post", campaign="wall"
    )
    assert "startapp=wall_24__utm_source_channel" in wall_link(
        24, source="channel", medium="post", campaign="october"
    )
    assert len(share_caption({"title": "Тема", "body": "С" * 1200},
                             wall_link(24))) <= 1024
    db = await Database(":memory:").start()
    try:
        server = FakeServer(db)
        server.bot = PreparedBot()
        server.web_dir = Path("miniapp/web")
        server.cfg.miniapp_url = "https://example.org"
        wall = Wall(server)
        await wall.ensure_schema()
        await db.ensure_user(101, None, "Автор")
        response = await wall.create(Req(101, {
            "title": "Новости Магнитогорска",
            "body": "Текст публикации",
            "client_key": "share-check-1",
        }))
        post_id = json.loads(response.text)["id"]
        prepared = json.loads((await prepare_share(
            wall, Req(101, post=post_id))).text)
        assert prepared["prepared_id"] == "test-prepared-message"
        result = server.bot.prepared["result"]
        assert result.photo_url.endswith(
            f"/api/miniapp/wall/share-preview/{post_id}.jpg")
        assert "Новости Магнитогорска" in result.caption
        assert "Текст публикации" in result.caption
        assert f"startapp=wall_{post_id}__utm_" in result.caption
        assert result.reply_markup.inline_keyboard[0][0].url.startswith(
            "https://t.me/AnonChatMgn_Bot/anonmgn?startapp=wall_"
        )
        image = await preview(wall, Req(101, post=post_id))
        assert image.content_type == "image/jpeg"
        assert image.body[:2] == b"\\xff\\xd8"
        await db.db.execute(
            "UPDATE wall_posts SET hidden=1 WHERE id=?", (post_id,))
        try:
            await preview(wall, Req(101, post=post_id))
            assert False, "hidden posts must not expose public previews"
        except web.HTTPNotFound:
            pass
        print("Wall share checks passed: native prepared photo, UTM links, hidden media.")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(check())
