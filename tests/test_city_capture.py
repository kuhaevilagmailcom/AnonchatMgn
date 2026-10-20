"""Unit tests for the isolated MGN Zahvat capture engine."""
import sqlite3
import unittest
from anonchat import city_capture as city
from anonchat import city_pets

class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        city.init_db(self.db)
        city_pets.init_db(self.db)
        self.db.execute("""CREATE TABLE users(
          user_id INTEGER PRIMARY KEY, xp INTEGER NOT NULL DEFAULT 0,
          xp_source TEXT DEFAULT '', xp_reason TEXT DEFAULT '',
          xp_reference_type TEXT DEFAULT '', xp_reference_id TEXT DEFAULT '')""")
        self.db.execute("INSERT INTO users(user_id,xp) VALUES(123,0)")
        self.db.execute("INSERT INTO city_zones VALUES (1,'Test',53.4,58.9,1)")
    def tearDown(self):
        self.db.close()
    def test_capture(self):
        r=city.capture(self.db,123,1,53.4,58.9,5,1000,now=1001)
        self.assertEqual(r["owner_user_id"],123)
        self.assertEqual(self.db.execute("SELECT xp FROM users WHERE user_id=123").fetchone()[0],50)
    def test_far_away(self):
        with self.assertRaises(ValueError):
            city.capture(self.db,123,1,53.5,58.9,5,1000,now=1001)
    def test_stale_fix(self):
        with self.assertRaises(ValueError):
            city.capture(self.db,123,1,53.4,58.9,5,900,now=1001)
    def test_cooldown(self):
        city.capture(self.db,123,1,53.4,58.9,5,1000,now=1001)
        self.db.execute("INSERT INTO city_zones VALUES (2,'Test 2',53.4,58.9,1)")
        with self.assertRaises(ValueError):
            city.capture(self.db,123,2,53.4,58.9,5,1002,now=1003)

if __name__=="__main__":
    unittest.main()
