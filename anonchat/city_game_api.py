"""Standalone MGN Zahvat aiohttp routes; mount into existing authenticated Mini App."""
from aiohttp import web
from . import city_capture as game
import sqlite3
import time

def routes(database_path, authenticate):
    """authenticate(request) must validate Telegram initData and return Telegram user ID."""
    async def state(request):
        uid = await authenticate(request)
        with sqlite3.connect(database_path, timeout=10) as db:
            game.init_db(db)
            db.executemany("INSERT OR IGNORE INTO city_zones(id,name,lat,lon,enabled) VALUES(?,?,?,?,1)", [
                (1,"Парк у Вечного огня",53.4217,58.9877),
                (2,"Парк Притяжение",53.3776,58.9778),
                (3,"Сквер Металлургов",53.4185,58.9791),
            ])
            db.commit()
            zones = db.execute(
                "SELECT z.id,z.name,z.lat,z.lon,o.user_id FROM city_zones z "
                "LEFT JOIN city_ownership o ON z.id=o.zone_id WHERE z.enabled=1"
            ).fetchall()
        return web.json_response({"user_id":uid,"zones":[
            {"id":z[0],"name":z[1],"lat":z[2],"lon":z[3],
             "mine":z[4]==uid,"occupied":z[4] is not None} for z in zones]})
    async def capture(request):
        uid = await authenticate(request)
        body = await request.json()
        try:
            with sqlite3.connect(database_path, timeout=10, isolation_level=None) as db:
                game.init_db(db)
                result = game.capture(db,int(uid),int(body["zone_id"]),
                    float(body["lat"]),float(body["lon"]),
                    float(body["accuracy_m"]),float(body["timestamp_s"]))
            return web.json_response({"ok":True,"result":result})
        except (KeyError,TypeError,ValueError,sqlite3.Error) as exc:
            raise web.HTTPBadRequest(text=str(exc))
    return [web.get("/api/city/state",state),web.post("/api/city/capture",capture)]
