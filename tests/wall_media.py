"""Wall media and moderator acceptance checks; run python -m tests.wall_media."""
import asyncio
import io
import json
import tempfile
import os
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web
from PIL import Image

from anonchat.db import Database
from anonchat.wall import Wall
from anonchat.wall_admin import WallAdmin
from tests.wall import FakeServer, Req


class Part:
    name = "file"
    headers = {"Content-Type":"image/png"}

    def __init__(self, content):
        self.content=content
        self.read=False

    async def read_chunk(self, size=0):
        if self.read:
            return b""
        self.read=True
        return self.content


class Parts:
    def __init__(self, content):
        self.part=Part(content)

    async def next(self):
        return self.part


class Upload(Req):
    content_type="multipart/form-data"

    def __init__(self, uid, content):
        super().__init__(uid)
        self.content=content

    async def multipart(self):
        return Parts(self.content)


async def test():
    with tempfile.TemporaryDirectory() as temp:
        os.environ["WALL_MEDIA_DIR"]=temp
        db=await Database(":memory:").start()
        try:
            server=FakeServer(db)
            wall=Wall(server)
            await wall.ensure_schema()
            await db.ensure_user(101,None,"Администратор")
            await db.ensure_user(103,None,"Посторонний")
            image=Image.new("RGB",(100,90),(220,100,160))
            buf=io.BytesIO();image.save(buf,format="PNG")
            result=await wall.media.upload(Upload(101,buf.getvalue()))
            assert result.status==201
            attachment=json.loads(result.text)["media"]
            assert attachment["kind"]=="image" and attachment["id"]>0

            post=await wall.create(Req(101,{
                "body":"","media_ids":[attachment["id"]],"client_key":"media_upload_first01"
            }))
            assert post.status==201
            pid=json.loads(post.text)["id"]
            detail=json.loads((await wall.detail(Req(101,post=pid))).text)
            assert detail["post"]["media"][0]["id"]==attachment["id"]
            request=Req(101,post=pid)
            request.match_info["media_id"]=str(attachment["id"])
            response=await wall.media.read(request)
            assert isinstance(response,web.FileResponse)

            stranger=Req(103,post=pid)
            stranger.match_info["media_id"]=str(attachment["id"])
            assert isinstance(await wall.media.read(stranger),web.FileResponse)

            admin=WallAdmin(wall)
            stats=json.loads((await admin.overview(Req(101))).text)
            assert stats["total"]==1
            items=json.loads((await admin.posts(Req(101))).text)
            assert items["items"][0]["author_id"]==101
            assert items["items"][0]["show_nick"] is True
            assert items["items"][0]["media"][0]["id"]==attachment["id"]
            await admin.action(Req(101,{"type":"post","id":pid,"action":"hide"}))
            hidden=json.loads((await admin.posts(Req(101,filter="hidden"))).text)
            assert hidden["items"][0]["hidden"]==1
            await admin.action(Req(101,{"type":"post","id":pid,"action":"restore"}))
            restored=json.loads((await wall.detail(Req(101,post=pid))).text)
            assert restored["post"]["media"]
            audit=json.loads((await admin.audit(Req(101))).text)
            assert len(audit["items"])==2

            # Damaged images are never persisted as playable files.
            try:
                await wall.media.upload(Upload(101,b"fake image bytes"))
                assert False, "Invalid media accepted"
            except web.HTTPBadRequest:
                pass
            print("Wall media/admin checks passed")
        finally:
            await db.close()
            os.environ.pop("WALL_MEDIA_DIR",None)


if __name__=="__main__":
    asyncio.run(test())
