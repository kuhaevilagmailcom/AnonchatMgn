"""Regression tests for MGN ZAHVAT geometry, gate and capture API."""
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
        self.assertEqual(len(zones), 17)
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
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE users(user_id INTEGER PRIMARY KEY, nickname TEXT NOT NULL DEFAULT '')")
            db.execute("INSERT INTO users VALUES(20,'Тестовый игрок')")
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
            self.assertEqual(len([z for z in data["zones"] if z["kind"] == "district"]), 5)
            self.assertTrue(all(z.get("official_name") and z.get("address") for z in data["zones"]))
            self.assertTrue(data["can_capture"])

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
            self.assertGreater(data["cooldown_remaining_s"], 0)
            self.assertEqual(data["zones"][0]["owner_name"], "Тестовый игрок")
            self.assertEqual(data["leaderboard"][0]["zones"], 1)

        async with self.client.post("/api/city/capture", json=payload) as response:
            self.assertEqual(response.status, 400)

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
