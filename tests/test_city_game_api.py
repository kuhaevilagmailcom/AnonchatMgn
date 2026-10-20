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
        self.assertGreaterEqual(len(zones), 5)
        self.assertGreater(len({row[4] for row in zones}), 1)  # big and small
        for zone_id, _, lat, lon, radius in zones:
            poly = city.polygon_for(zone_id, lat, lon)
            self.assertEqual(poly, city.polygon_for(zone_id, lat, lon))
            self.assertEqual(len(poly), 8)
            self.assertEqual(len(set(tuple(p) for p in poly)), 8)
            self.assertTrue(all(abs(p[0] - lat) < .02 and abs(p[1] - lon) < .02 for p in poly))
            self.assertGreater(radius, 100)  # capture radius is separate from outline

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
            self.assertTrue(all(len(z["polygon"]) == 8 for z in data["zones"]))
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
