"""Offline pet economy + real GPS HP defence tests."""
import sqlite3
import unittest

from anonchat import city_capture, city_pets


class CityPetsTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        city_capture.init_db(self.db)
        city_pets.init_db(self.db)
        self.db.executescript("""
        CREATE TABLE users(
          user_id INTEGER PRIMARY KEY, nickname TEXT NOT NULL DEFAULT '',
          xp INTEGER NOT NULL DEFAULT 0, xp_source TEXT NOT NULL DEFAULT '',
          xp_reason TEXT NOT NULL DEFAULT '',
          xp_reference_type TEXT NOT NULL DEFAULT '',
          xp_reference_id TEXT NOT NULL DEFAULT '');
        """)
        self.db.executemany(
            "INSERT INTO users(user_id,nickname,xp) VALUES(?,?,?)",
            [(10,"Первый",10000),(20,"Второй",1000)],
        )
        self.db.executemany(
            "INSERT INTO city_zones VALUES(?,?,?,?,1)",
            [(1,"Квартал 1",53.4,58.9),(2,"Квартал 2",53.401,58.901)],
        )
        self.db.execute("INSERT INTO city_ownership VALUES(1,10,100)")
        self.db.execute("INSERT INTO city_ownership VALUES(2,20,100)")
        self.shape = {"1": [
            [53.3996,58.8995], [53.3996,58.9005],
            [53.4005,58.9005], [53.4005,58.8995],
        ]}

    def tearDown(self):
        self.db.close()

    def xp(self, uid=10):
        return self.db.execute("SELECT xp FROM users WHERE user_id=?", (uid,)).fetchone()[0]

    def test_catalog_prices_nonlethal_strength(self):
        catalog = city_pets.catalog()
        self.assertEqual([p["emoji"] for p in catalog], ["🐈","🐤","🐷","🐍","🦁"])
        self.assertEqual([p["price"] for p in catalog], [100,500,1000,2500,5000])
        self.assertLess(catalog[0]["hp_h"], catalog[-1]["hp_h"])
        self.assertLess(catalog[0]["stars_h"], catalog[-1]["stars_h"])
        self.assertLessEqual(catalog[-1]["hp_h"], 5)

    def test_buy_atomic_debit_and_insufficient_funds(self):
        result = city_pets.buy(self.db,10,"cat",now=100)
        self.assertEqual(result["balance"],9900)
        self.assertEqual(self.xp(),9900)
        with self.assertRaises(ValueError):
            city_pets.buy(self.db,20,"lion",now=101)
        self.assertEqual(self.xp(20),1000)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM city_pets").fetchone()[0],1)
        with self.assertRaises(ValueError):
            city_pets.buy(self.db,10,"unknown")
        self.assertEqual(self.xp(),9900)

    def test_guard_only_on_owned_zone_and_one_per_zone(self):
        a = city_pets.buy(self.db,10,"cat",now=100)["pet_id"]
        b = city_pets.buy(self.db,10,"bird",now=101)["pet_id"]
        with self.assertRaises(ValueError):
            city_pets.place(self.db,10,a,2,now=102)
        self.assertEqual(city_pets.place(self.db,10,a,1,now=103)["zone_id"],1)
        with self.assertRaises(ValueError):
            city_pets.place(self.db,10,b,1,now=104)
        with self.assertRaises(ValueError):
            city_pets.place(self.db,20,a,2,now=104)
        self.assertEqual(city_pets.recall(self.db,10,a),{"pet_id":a})
        self.assertEqual(city_pets.place(self.db,10,b,1,now=105)["zone_id"],1)

    def test_passive_income_is_server_timed_and_not_double_paid(self):
        pet = city_pets.buy(self.db,10,"cat",now=100)["pet_id"]
        city_pets.place(self.db,10,pet,1,now=100)
        self.assertEqual(city_pets.claim(self.db,10,now=100+1800)["stars"],0)
        self.assertEqual(city_pets.claim(self.db,10,now=100+3600)["stars"],1)
        self.assertEqual(city_pets.claim(self.db,10,now=100+3600)["stars"],0)
        self.assertEqual(self.xp(),9901)
        self.assertEqual(city_pets.state(self.db,10,now=100+7200)["pending_stars"],1)

    def test_capture_releases_lost_guard_and_gives_reward(self):
        pet = city_pets.buy(self.db,10,"cat",now=100)["pet_id"]
        city_pets.place(self.db,10,pet,1,now=100)
        # Opponent captures by standing on the destination, after the cooldown.
        result = city_capture.capture(
            self.db,20,1,53.4,58.9,5,2000,now=2001
        )
        self.assertEqual(result["owner_user_id"],20)
        self.assertEqual(self.xp(20),1000+city_pets.CAPTURE_STARS)
        self.assertIsNone(self.db.execute("SELECT zone_id FROM city_pets WHERE id=?", (pet,)).fetchone()[0])
        self.assertEqual(city_pets.state(self.db,10,now=2500)["pending_stars"],0)

    def test_hp_requires_real_polygon_and_never_reaches_zero(self):
        lion = city_pets.buy(self.db,10,"lion",now=100)["pet_id"]
        city_pets.place(self.db,10,lion,1,now=100)
        first = city_pets.presence(self.db,20,53.4,58.9,5,2000,self.shape,now=2000)
        self.assertEqual(first["hp"],100)
        second = city_pets.presence(self.db,20,53.4,58.9,5,2060,self.shape,now=2060)
        self.assertEqual(second["attacked_by"],"lion")
        self.assertLess(second["hp"],100)
        self.assertGreater(second["hp"],99.9)
        # GPS outside the real road cell causes no pet damage.
        out = city_pets.presence(self.db,20,53.43,58.93,5,2120,self.shape,now=2120)
        self.assertIsNone(out["attacked_by"])
        self.assertGreater(out["hp"],second["hp"])
        # Without verified road polygons, pets must not harm a visitor.
        no_shape = city_pets.presence(self.db,20,53.4,58.9,5,2180,{},now=2180)
        self.assertIsNone(no_shape["attacked_by"])
        self.db.execute("UPDATE city_player_hp SET hp_milli=1005,last_tick=2180 WHERE user_id=20")
        result = city_pets.presence(self.db,20,53.4,58.9,5,2240,self.shape,now=2240)
        self.assertGreaterEqual(result["hp"],1)
        self.assertFalse(result["hp"]==0)

    def test_no_damage_on_stale_or_inaccurate_gps(self):
        lion = city_pets.buy(self.db,10,"lion",now=100)["pet_id"]
        city_pets.place(self.db,10,lion,1,now=100)
        with self.assertRaises(ValueError):
            city_pets.presence(self.db,20,53.4,58.9,5,1900,self.shape,now=2000)
        with self.assertRaises(ValueError):
            city_pets.presence(self.db,20,53.4,58.9,90,2000,self.shape,now=2000)
        first = city_pets.presence(self.db,20,53.4,58.9,40,2000,self.shape,now=2000)
        second = city_pets.presence(self.db,20,53.4,58.9,40,2060,self.shape,now=2060)
        self.assertEqual(first["hp"],100)
        self.assertEqual(second["hp"],100)


if __name__ == "__main__":
    unittest.main()
