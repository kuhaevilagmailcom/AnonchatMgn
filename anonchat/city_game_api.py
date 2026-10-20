"""MGN: ZAHVAT — authenticated, temporarily admin-gated game API.

Territory outlines are deliberately *game sectors*, NOT municipal boundaries.
Capture always happens within 100 metres of a separately marked public point.
The points below are sourced from published local visitor/park information.
"""
import math
import os
import sqlite3
import time

from aiohttp import web

from . import city_capture as game

# Publicly documented places. IDs 1-3 supersede inaccurate prototype coordinates.
# The radius describes the visual game sector, NOT the GPS capture radius.
STARTER_ZONES = (
    (1, "Парк у Вечного огня", 53.404924, 58.990902, 450),
    (2, "Парк «Притяжение»", 53.380514, 58.960070, 610),
    (3, "Сквер Металлургов", 53.422358, 58.990517, 260),
    (4, "Парк Ветеранов Магнитки", 53.428465, 59.000297, 350),
    (5, "Сквер у стелы Магнитки", 53.411091, 58.986059, 280),
)
SECTOR_SIZES = {z[0]: z[4] for z in STARTER_ZONES}


def seed_zones(db):
    """Create demo sectors and fix known inaccurate original GPS anchors.

    Preserve ownership and the operator's enabled/disabled selection.
    """
    game.init_db(db)
    for zone_id, name, lat, lon, _radius in STARTER_ZONES:
        db.execute(
            """INSERT INTO city_zones(id,name,lat,lon,enabled)
               VALUES(?,?,?,?,1)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, lat=excluded.lat, lon=excluded.lon""",
            (zone_id, name, lat, lon),
        )


def polygon_for(zone_id, lat, lon):
    """An irregular but stable 8-sided gameplay polygon in [lat, lon] order."""
    radius = SECTOR_SIZES.get(zone_id, 300)
    outline = []
    for idx in range(8):
        angle = (idx * 45 + 15 + zone_id * 7) * math.pi / 180
        scale = (0.86, 1.04, 0.92, 1.10, 0.95, 1.02, 0.87, 1.05)[idx]
        distance = radius * scale
        dlat = math.cos(angle) * distance / 111_320
        dlon = math.sin(angle) * distance / (111_320 * math.cos(math.radians(lat)))
        outline.append([round(lat + dlat, 6), round(lon + dlon, 6)])
    return outline


def routes(database_path, authenticate, is_admin):
    """All user IDs come from server-verified Telegram initData."""
    async def allowed(uid):
        return os.getenv("CITY_GAME_TEST_ADMINS_ONLY", "1") == "0" or await is_admin(uid)

    async def require_access(request):
        uid = await authenticate(request)
        if not await allowed(uid):
            raise web.HTTPForbidden(text="Игра пока доступна только администраторам")
        return uid

    async def access(request):
        uid = await authenticate(request)
        return web.json_response({"allowed": await allowed(uid)})

    async def state(request):
        uid = await require_access(request)
        with sqlite3.connect(database_path, timeout=10) as db:
            seed_zones(db)
            db.commit()
            zones = db.execute(
                """SELECT z.id, z.name, z.lat, z.lon, o.user_id, o.captured_at,
                          COALESCE(NULLIF(TRIM(u.nickname), ''), 'Аноним')
                   FROM city_zones z
                   LEFT JOIN city_ownership o ON z.id = o.zone_id
                   LEFT JOIN users u ON u.user_id = o.user_id
                   WHERE z.enabled = 1 ORDER BY z.id"""
            ).fetchall()
            board = db.execute(
                """SELECT o.user_id, COUNT(*) AS territories,
                          COALESCE(NULLIF(TRIM(u.nickname), ''), 'Аноним')
                   FROM city_ownership o
                   JOIN city_zones z ON z.id = o.zone_id AND z.enabled = 1
                   LEFT JOIN users u ON u.user_id = o.user_id
                   GROUP BY o.user_id ORDER BY territories DESC, o.user_id LIMIT 30"""
            ).fetchall()
            last_row = db.execute(
                "SELECT MAX(captured_at) FROM city_capture_events WHERE user_id = ?",
                (uid,),
            ).fetchone()
            total_captures = db.execute(
                "SELECT COUNT(*) FROM city_capture_events"
            ).fetchone()[0]
        last_capture = last_row[0]
        remaining = max(0, int(game.COOLDOWN_S - (time.time() - last_capture))) if last_capture is not None else 0
        return web.json_response({
            "user_id": uid, "can_capture": True, "test_mode": os.getenv("CITY_GAME_TEST_ADMINS_ONLY", "1") != "0",
            "capture_radius_m": game.RADIUS_M, "max_accuracy_m": game.MAX_ACCURACY_M,
            "cooldown_remaining_s": remaining, "total_captures": total_captures,
            "my_zones": sum(1 for z in zones if z[4] == uid),
            "leaderboard": [
                {"name": row[2], "zones": row[1], "mine": row[0] == uid}
                for row in board
            ],
            "zones": [
                {"id": z[0], "name": z[1], "lat": z[2], "lon": z[3],
                 "polygon": polygon_for(z[0], z[2], z[3]),
                 "size": "Большой" if SECTOR_SIZES.get(z[0], 300) >= 400 else "Малый",
                 "mine": z[4] == uid, "occupied": z[4] is not None,
                 "owner_name": z[6] if z[4] is not None else None,
                 "captured_at": z[5]}
                for z in zones
            ],
        })

    async def capture(request):
        uid = await require_access(request)
        try:
            body = await request.json()
            with sqlite3.connect(database_path, timeout=10, isolation_level=None) as db:
                seed_zones(db)
                result = game.capture(
                    db, int(uid), int(body["zone_id"]), float(body["lat"]),
                    float(body["lon"]), float(body["accuracy_m"]),
                    float(body["timestamp_s"]),
                )
            return web.json_response({"ok": True, "result": result})
        except (KeyError, TypeError, ValueError, sqlite3.Error) as exc:
            raise web.HTTPBadRequest(text=str(exc))

    return [
        web.get("/api/city/access", access),
        web.get("/api/city/state", state),
        web.post("/api/city/capture", capture),
    ]
