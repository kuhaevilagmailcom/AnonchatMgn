"""Regression tests for MGN ZAHVAT geometry, gate and capture API."""
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from anonchat import city_game_api as city


class GeometryTests(unittest.TestCase):
    def test_sector_polygons_are_distinct_and_stable(self):
        zones = city.STARTER_ZONES
        self.assertEqual(len(zones), 16)
        zone_names = {row[1] for row in zones}
        self.assertTrue({"Ашик", "Гостинка", "Контик", "Джазик", "Ленинский район", "Площадь Победы", "Соцгород", "Комсомольская площадь", "Левобережный ДК"}.issubset(zone_names))
        self.assertEqual(city.ZONE_META[6][1], "ТРК «Семейный парк»")
        self.assertEqual(city.ZONE_META[7][1], "ТРК «Гостиный двор»")
        self.assertEqual(city.ZONE_META[8][1], "ТРК «Континент»")
        self.assertEqual(city.ZONE_META[9][1], "ТРК «Jazz Mall»")
        self.assertGreater(len({row[4] for row in zones}), 1)  # big and small
        self.assertTrue(all(radius > 100 for _, _, _, _, radius in zones))

    def test_seed_fixes_legacy_coordinates_without_erasing_owner(self):
        db = sqlite3.connect(":memory:", isolation_level=None)
        try:
            city.game.init_db(db)
            db.execute("INSERT INTO city_zones VALUES(1,'Old point',53.4217,58.9877,1)")
            db.execute("INSERT INTO city_ownership VALUES(1,55,100)")
            city.seed_zones(db)
            name, lat, lon = db.execute("SELECT name,lat,lon FROM city_zones WHERE id=1").fetchone()
            self.assertEqual(name, "Парк у Вечного огня")
            self.assertAlmostEqual(lat, 53.404924)
            self.assertAlmostEqual(lon, 58.990902)
            self.assertEqual(db.execute("SELECT user_id FROM city_ownership WHERE zone_id=1").fetchone()[0], 55)
        finally:
            db.close()


class CityRoutesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tempdir.name) / "game.db")
        # Stable verified road block around zone 1, for real GPS combat tests.
        # RoadGeometry reads this cache before registering HTTP handlers.
        (Path(self.tempdir.name) / "city_road_shapes.json").write_text(
            json.dumps({"version":4,"shapes":{"1":[
                [53.4044,58.9902],[53.4044,58.9916],
                [53.4055,58.9916],[53.4055,58.9902]
            ]},"extra_zones":[]}),
            encoding="utf-8",
        )
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE users(
                user_id INTEGER PRIMARY KEY, nickname TEXT NOT NULL DEFAULT '',
                xp INTEGER NOT NULL DEFAULT 0, xp_source TEXT NOT NULL DEFAULT '',
                xp_reason TEXT NOT NULL DEFAULT '',
                xp_reference_type TEXT NOT NULL DEFAULT '',
                xp_reference_id TEXT NOT NULL DEFAULT '')""")
            db.execute("INSERT INTO users(user_id,nickname,xp) VALUES(20,'Тестовый игрок',0)")
            db.execute("INSERT INTO users(user_id,nickname,xp) VALUES(10,'Админ',500)")
            db.commit()

        self.prior_gate = os.environ.get("CITY_GAME_TEST_ADMINS_ONLY")
        os.environ["CITY_GAME_TEST_ADMINS_ONLY"] = "1"

        async def authenticate(request):
            return int(request.headers.get("X-Test-User", "20"))

        async def is_admin(uid):
            return uid == 10

        app = web.Application()
        app.add_routes(city.routes(self.path, authenticate, is_admin))
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        if self.prior_gate is None:
            os.environ.pop("CITY_GAME_TEST_ADMINS_ONLY", None)
        else:
            os.environ["CITY_GAME_TEST_ADMINS_ONLY"] = self.prior_gate
        self.tempdir.cleanup()

    async def test_admin_only_gate_blocks_state_and_capture(self):
        async with self.client.get("/api/city/access") as response:
            self.assertFalse((await response.json())["allowed"])
        async with self.client.get("/api/city/state") as response:
            self.assertEqual(response.status, 403)
        async with self.client.post("/api/city/capture", json={"zone_id": 1}) as response:
            self.assertEqual(response.status, 403)

        async with self.client.get("/api/city/state", headers={"X-Test-User": "10"}) as response:
            self.assertEqual(response.status, 200)
            data = await response.json()
            self.assertEqual(len(data["zones"]), len(city.STARTER_ZONES))
            self.assertTrue(all(z["polygon"] == [] for z in data["zones"]))  # no invented boundaries
            self.assertEqual(len([z for z in data["zones"] if z["kind"] == "mall"]), 4)
            self.assertEqual(len([z for z in data["zones"] if z["kind"] == "district"]), 4)
            self.assertTrue(all(z.get("official_name") and z.get("address") for z in data["zones"]))
            self.assertTrue(data["can_capture"])
            self.assertEqual(data["wallet"], 500)
            self.assertEqual(len(data["catalog"]), 5)

    async def test_every_player_can_capture_when_gate_opens(self):
        os.environ["CITY_GAME_TEST_ADMINS_ONLY"] = "0"
        async with self.client.get("/api/city/state") as response:
            self.assertTrue((await response.json())["can_capture"])

        now = time.time()
        payload = {
            "zone_id": 1, "lat": 53.404924, "lon": 58.990902,
            "accuracy_m": 5, "timestamp_s": now,
        }
        async with self.client.post("/api/city/capture", json=payload) as response:
            self.assertEqual(response.status, 200)
        async with self.client.get("/api/city/state") as response:
            data = await response.json()
            self.assertEqual(data["my_zones"], 1)
            self.assertEqual(data["wallet"], 50)
            self.assertEqual(data["hp"], 100)
            self.assertGreater(data["cooldown_remaining_s"], 0)
            self.assertEqual(data["zones"][0]["owner_name"], "Тестовый игрок")
            self.assertEqual(data["leaderboard"][0]["zones"], 1)

        async with self.client.post("/api/city/capture", json=payload) as response:
            self.assertEqual(response.status, 400)

    async def test_shop_obeys_admin_gate_and_guards_owned_zones(self):
        user = {"X-Test-User": "20"}
        admin = {"X-Test-User": "10"}
        async with self.client.post("/api/city/pets/buy", headers=user, json={"kind":"cat"}) as r:
            self.assertEqual(r.status, 403)
        async with self.client.get("/api/city/state", headers=admin) as r:
            self.assertEqual(r.status, 200)
        async with self.client.post(
            "/api/city/pets/buy", headers=admin,
            json={"kind":"cat","request_id":"pet-first"},
        ) as r:
            self.assertEqual(r.status, 200)
            pet = await r.json()
        async with self.client.post(
            "/api/city/pets/buy", headers=admin,
            json={"kind":"cat","request_id":"pet-first"},
        ) as r:
            self.assertEqual(r.status, 200)
            replay = await r.json()
            self.assertEqual(replay["pet_id"],pet["pet_id"])
        async with self.client.post(
            "/api/city/pets/place", headers=admin,
            json={"pet_id":pet["pet_id"],"zone_id":1}
        ) as r:
            self.assertEqual(r.status, 400)  # not owned yet
        async with self.client.post(
            "/api/city/capture", headers=admin,
            json={"zone_id":1,"lat":53.404924,"lon":58.990902,
                  "accuracy_m":5,"timestamp_s":time.time()},
        ) as r:
            self.assertEqual(r.status, 200)
        async with self.client.post(
            "/api/city/pets/place", headers=admin,
            json={"pet_id":pet["pet_id"],"zone_id":1}
        ) as r:
            self.assertEqual(r.status, 200)
        async with self.client.get("/api/city/state", headers=admin) as r:
            data = await r.json()
            self.assertEqual(data["wallet"], 500-100+50)
            self.assertEqual(len(data["guards"]), 1)
            self.assertTrue(data["guards"][0]["mine"])
        async with self.client.post("/api/city/pets/claim", headers=admin,
                                    json={}) as r:
            self.assertEqual(r.status, 200)

    async def test_fatal_gps_attack_frees_zones_for_everyone_then_respawns(self):
        os.environ["CITY_GAME_TEST_ADMINS_ONLY"] = "0"
        admin = {"X-Test-User":"10"}
        victim = {"X-Test-User":"20"}
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE users SET xp=10000 WHERE user_id=10")
            db.commit()
        async with self.client.get("/api/city/state", headers=admin) as r:
            self.assertEqual(r.status,200)
        async with self.client.post("/api/city/capture", headers=admin,
                                    json={"zone_id":1,"lat":53.404924,
                                          "lon":58.990902,"accuracy_m":5,
                                          "timestamp_s":time.time()}) as r:
            self.assertEqual(r.status,200)
        async with self.client.post("/api/city/pets/buy", headers=admin,
                                    json={"kind":"lion","request_id":"guard"} ) as r:
            self.assertEqual(r.status,200)
            pet = (await r.json())["pet_id"]
        async with self.client.post("/api/city/pets/place", headers=admin,
                                    json={"pet_id":pet,"zone_id":1}) as r:
            self.assertEqual(r.status,200)
        victim_zone = city.STARTER_ZONES[1]
        async with self.client.post("/api/city/capture", headers=victim,
                                    json={"zone_id":victim_zone[0],
                                          "lat":victim_zone[2],"lon":victim_zone[3],
                                          "accuracy_m":5,
                                          "timestamp_s":time.time()}) as r:
            self.assertEqual(r.status,200)
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT INTO city_player_hp(user_id,hp_milli,last_tick) VALUES(20,400,?)",
                (int(time.time()) - 60,),
            )
            db.commit()
        gps = {"lat":53.404924,"lon":58.990902,
               "accuracy_m":5,"timestamp_s":time.time()}
        async with self.client.post("/api/city/presence",
                                    headers=victim,json=gps) as r:
            self.assertEqual(r.status,200)
            death = await r.json()
            self.assertTrue(death["dead"])
            self.assertTrue(death["died"])
            self.assertEqual(death["hp"],0)
            self.assertEqual(death["zones_lost"],1)
        async with self.client.get("/api/city/state",headers=victim) as r:
            data = await r.json()
            self.assertEqual(data["hp"],0)
            self.assertTrue(data["dead"])
            self.assertEqual(data["my_zones"],0)
            self.assertEqual(data["zones_lost"],1)
            self.assertFalse(data["zones"][1]["occupied"])
            self.assertEqual(data["wallet"],50)
        async with self.client.get("/api/city/state",headers=admin) as r:
            data = await r.json()
            self.assertFalse(data["zones"][1]["occupied"])
            self.assertEqual(len(data["guards"]),1)
            self.assertEqual(data["guards"][0]["kind"],"lion")
        async with self.client.post("/api/city/presence",
                                    headers=victim,json=gps) as r:
            self.assertEqual(r.status,200)
            self.assertFalse((await r.json())["died"])
        async with self.client.post("/api/city/capture",headers=victim,
                                    json={"zone_id":victim_zone[0],
                                          "lat":victim_zone[2],"lon":victim_zone[3],
                                          "accuracy_m":5,
                                          "timestamp_s":time.time()}) as r:
            self.assertEqual(r.status,400)
            self.assertIn("возродись",await r.text())
        async with self.client.post("/api/city/respawn",headers=victim) as r:
            self.assertEqual(r.status,200)
            revived = await r.json()
            self.assertEqual(revived["hp"],100)
            self.assertFalse(revived["dead"])
        async with self.client.get("/api/city/state",headers=victim) as r:
            data = await r.json()
            self.assertFalse(data["dead"])
            self.assertEqual(data["hp"],100)
            self.assertEqual(data["my_zones"],0)  # death penalty survives respawn
        async with self.client.post("/api/city/respawn",headers=victim) as r:
            self.assertEqual(r.status,400)

    async def test_capture_requires_proximity_not_just_sector_click(self):
        os.environ["CITY_GAME_TEST_ADMINS_ONLY"] = "0"
        payload = {
            "zone_id": 1, "lat": 53.44, "lon": 58.99,
            "accuracy_m": 5, "timestamp_s": time.time(),
        }
        async with self.client.post("/api/city/capture", json=payload) as response:
            self.assertEqual(response.status, 400)


if __name__ == "__main__":
    unittest.main()
