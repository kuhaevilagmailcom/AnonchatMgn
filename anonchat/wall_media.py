"""Private persistent photo/video storage for Anon MGN Wall.

All reads and writes require authenticated staff via Wall._user. Only validated
media IDs are exposed, never filesystem paths. An unattached upload expires.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import secrets
import shutil
import subprocess
import time
from pathlib import Path

from aiohttp import web
from PIL import Image, ImageFile, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 30_000_000
ImageFile.LOAD_TRUNCATED_IMAGES = False

MEDIA_SCHEMA = """
CREATE TABLE IF NOT EXISTS wall_media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    post_id INTEGER,
    key TEXT NOT NULL UNIQUE,
    mime TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('image','video')),
    byte_size INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    poster_key TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_wall_media_post ON wall_media(post_id,id);
CREATE INDEX IF NOT EXISTS idx_wall_media_stale ON wall_media(post_id,created_at);
CREATE TABLE IF NOT EXISTS wall_create_keys(
    owner_id INTEGER NOT NULL,
    client_key TEXT NOT NULL,
    post_id INTEGER NOT NULL,
    PRIMARY KEY(owner_id,client_key)
);
"""

PHOTO_LIMIT = 10 * 1024 * 1024
VIDEO_LIMIT = 50 * 1024 * 1024
MAX_REQUEST = VIDEO_LIMIT + 1024 * 1024
KINDS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}


class MediaValidationError(ValueError):
    pass


class WallMedia:
    def __init__(self, wall):
        self.wall = wall
        self.db = wall.db
        default = Path(self.db.path).resolve().parent / "wall_media"
        self.base = Path(os.getenv("WALL_MEDIA_DIR", str(default))).resolve()

    async def ensure_schema(self):
        self.base.mkdir(parents=True, exist_ok=True)
        marker = self.base / ".write_probe"
        marker.write_text("ready", encoding="utf-8")
        marker.unlink()
        await self.db.db.executescript(MEDIA_SCHEMA)
        await self.cleanup()

    async def cleanup(self):
        # Remove uploads abandoned for over 1 hour and assets whose parent posts
        # were removed during profile deletion. Do not erase moderated posts.
        cutoff = int(time.time()) - 3600
        rows = await self.db._fetchall(
            """SELECT m.id,m.key,m.poster_key FROM wall_media m
                 LEFT JOIN wall_posts p ON p.id=m.post_id
               WHERE (m.post_id IS NULL AND m.created_at<?)
                  OR (m.post_id IS NOT NULL AND p.id IS NULL)""",
            (cutoff,),
        )
        for row in rows:
            self._unlink(row["key"])
            self._unlink(row["poster_key"])
            await self.db.db.execute("DELETE FROM wall_media WHERE id=?", (row["id"],))

    def _unlink(self, key):
        if key and "/" not in key and "\\" not in key and key not in (".", ".."):
            (self.base / key).unlink(missing_ok=True)

    def _public(self, row):
        return {
            "id": int(row["id"]), "kind": row["kind"],
            "url": f"/api/miniapp/wall/media/{row['id']}",
            "poster": (f"/api/miniapp/wall/media/{row['id']}?poster=1"
                       if row["poster_key"] else ""),
        }

    async def for_post(self, post_id):
        rows = await self.db._fetchall(
            "SELECT * FROM wall_media WHERE post_id=? ORDER BY id", (post_id,)
        )
        return [self._public(row) for row in rows]

    async def for_posts(self, ids):
        if not ids:
            return {}
        ids = list(dict.fromkeys(int(x) for x in ids))[:50]
        sql = ",".join("?" * len(ids))
        rows = await self.db._fetchall(
            f"SELECT * FROM wall_media WHERE post_id IN ({sql}) ORDER BY id", ids
        )
        result = {pid: [] for pid in ids}
        for r in rows:
            result[int(r["post_id"])].append(self._public(r))
        return result

    async def read(self, request):
        await self.wall._user(request)
        media_id = self.wall._parse_id(request.match_info["media_id"])
        row = await self.db._fetchone(
            """SELECT m.*,p.hidden AS post_hidden FROM wall_media m
               LEFT JOIN wall_posts p ON p.id=m.post_id WHERE m.id=?""",
            (media_id,),
        )
        if not row or row["post_id"] is None or int(row["post_hidden"] or 0) != 0:
            raise web.HTTPNotFound()
        poster = request.query.get("poster") == "1"
        key = row["poster_key"] if poster else row["key"]
        if not key or "/" in key or "\\" in key:
            raise web.HTTPNotFound()
        path = self.base / key
        if not path.is_file():
            raise web.HTTPNotFound()
        response = web.FileResponse(path, headers={"Content-Disposition":"inline"})
        response.content_type = "image/jpeg" if poster else row["mime"]
        return response

    @staticmethod
    def _validate_photo(raw):
        try:
            with Image.open(io.BytesIO(raw)) as im:
                fmt = im.format
                if fmt not in KINDS:
                    raise MediaValidationError("Допустимы JPEG, PNG и WebP")
                if im.width < 1 or im.height < 1 or im.width * im.height > 30_000_000:
                    raise MediaValidationError("Слишком большое изображение")
                im.verify()
            return KINDS[fmt]
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise MediaValidationError("Изображение повреждено или не поддерживается") from exc

    async def _video_info(self, path):
        probe = shutil.which("ffprobe")
        if not probe:
            raise MediaValidationError("Серверу требуется ffprobe для проверки видео")
        proc = await asyncio.create_subprocess_exec(
            probe, "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,codec_name",
            "-of", "json", str(path), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise MediaValidationError("Видео слишком долго обрабатывается")
        if proc.returncode:
            raise MediaValidationError("Видео не удалось проверить")
        try:
            data = json.loads(out)
            duration = float(data["format"]["duration"])
            streams = data.get("streams", [])
            has_video = any(s.get("codec_type")=="video" for s in streams)
            supported = all(s.get("codec_name") in ("h264","aac","mp3","mjpeg","hevc")
                            for s in streams)
            if not 0 < duration <= 60 or not has_video or not supported:
                raise MediaValidationError("Нужно MP4 до 60 секунд с поддерживаемым кодеком")
        except (ValueError, KeyError, TypeError) as exc:
            raise MediaValidationError("Не удалось определить длительность видео") from exc

    async def _poster(self, src, key):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return ""
        dst_key = key + ".poster.jpg"
        dst = self.base / dst_key
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-v", "error", "-nostdin", "-ss", "0.5", "-i", str(src),
            "-frames:v", "1", "-vf", "scale=800:-2", "-y", str(dst),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=12)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
        if proc.returncode == 0 and dst.exists() and dst.stat().st_size:
            return dst_key
        dst.unlink(missing_ok=True)
        return ""

    async def upload(self, request):
        uid = await self.wall._user(request, write=True)
        if not request.content_type.startswith("multipart/form-data"):
            return self.wall._raise(400, "Выбери фотографию или видео")
        pending = await self.db._fetchone(
            "SELECT COUNT(*) AS n,COALESCE(SUM(byte_size),0) AS s FROM wall_media WHERE owner_id=? AND post_id IS NULL",
            (uid,),
        )
        if int(pending["n"]) >= 8 or int(pending["s"]) > 160 * 1024 * 1024:
            return self.wall._raise(429, "Сначала опубликуй или удали выбранные файлы")
        reader = await request.multipart()
        part = await reader.next()
        if part is None or part.name != "file":
            return self.wall._raise(400, "Файл не найден")
        original_type = str(part.headers.get("Content-Type", "")).split(";")[0].lower()
        kind = "video" if original_type.startswith("video/") else "image"
        limit = VIDEO_LIMIT if kind=="video" else PHOTO_LIMIT
        suffix = ".mp4" if kind=="video" else ".upload"
        key = secrets.token_hex(20)+suffix
        target = self.base / key
        count = 0
        try:
            with target.open("xb") as out:
                while True:
                    chunk = await part.read_chunk(size=256*1024)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > limit:
                        raise MediaValidationError("Файл слишком большой")
                    out.write(chunk)
            if not count:
                raise MediaValidationError("Пустой файл")
            poster = ""
            if kind == "image":
                mime, ending = await asyncio.to_thread(self._validate_photo, target.read_bytes())
                newkey = secrets.token_hex(20) + ending
                target.rename(self.base/newkey)
                key = newkey
                target = self.base/newkey
            else:
                with target.open("rb") as f:
                    head=f.read(32)
                if len(head)<12 or head[4:8]!=b"ftyp" or b"qt  " in head[:24]:
                    raise MediaValidationError("Поддерживается только MP4 (не MOV)")
                await self._video_info(target)
                mime = "video/mp4"
                poster = await self._poster(target,key)
            now = int(time.time())
            cur = await self.db.db.execute(
                """INSERT INTO wall_media(owner_id,post_id,key,mime,kind,byte_size,created_at,poster_key)
                   VALUES (?,NULL,?,?,?,?,?,?)""",
                (uid,key,mime,kind,count,now,poster),
            )
            return web.json_response({
                "ok":True, "media": {"id":int(cur.lastrowid),"kind":kind,
                  "url":f"/api/miniapp/wall/media/{cur.lastrowid}",
                  "poster": f"/api/miniapp/wall/media/{cur.lastrowid}?poster=1" if poster else ""}
            }, status=201)
        except (MediaValidationError, OSError) as exc:
            target.unlink(missing_ok=True)
            if "poster" in locals() and poster:
                self._unlink(poster)
            return self.wall._raise(400, str(exc))
        except Exception:
            target.unlink(missing_ok=True)
            raise

    async def remove(self, request):
        uid = await self.wall._user(request, write=True)
        mid = self.wall._parse_id(request.match_info["media_id"])
        row = await self.db._fetchone(
            "SELECT * FROM wall_media WHERE id=? AND owner_id=?", (mid,uid)
        )
        if not row:
            return self.wall._raise(404, "Вложение не найдено")
        if row["post_id"] is not None:
            post = await self.wall._post(int(row["post_id"]),uid)
            if not post or int(post["author_id"]) != uid:
                return self.wall._raise(403, "Нельзя удалить чужое вложение")
        await self.db.db.execute("DELETE FROM wall_media WHERE id=? AND owner_id=?", (mid,uid))
        self._unlink(row["key"])
        self._unlink(row["poster_key"])
        return web.json_response({"ok":True})

    async def validate_ids(self, uid, media_ids, previous_post=None):
        if not isinstance(media_ids,list) or len(media_ids)>4:
            raise MediaValidationError("Можно прикрепить до 4 фотографий или одно видео")
        ids=[]
        for value in media_ids:
            if type(value) is not int or value<=0 or value in ids:
                raise MediaValidationError("Неверные вложения")
            ids.append(value)
        if not ids:
            return []
        rows = await self.db._fetchall(
            f"SELECT * FROM wall_media WHERE owner_id=? AND id IN ({','.join('?'*len(ids))})",
            (uid,*ids),
        )
        if len(rows)!=len(ids):
            raise MediaValidationError("Вложение недоступно")
        for r in rows:
            if r["post_id"] is not None and int(r["post_id"])!=int(previous_post or 0):
                raise MediaValidationError("Вложение уже используется")
        if len(rows)>1 and any(r["kind"]=="video" for r in rows):
            raise MediaValidationError("Видео можно прикрепить только отдельно")
        return ids

    async def attach(self, uid, post_id, ids):
        if ids:
            await self.db.db.execute(
                f"UPDATE wall_media SET post_id=? WHERE owner_id=? AND id IN ({','.join('?'*len(ids))})",
                (post_id,uid,*ids),
            )
