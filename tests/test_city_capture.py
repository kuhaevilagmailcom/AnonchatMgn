"""Unit tests for the isolated MGN Zahvat capture engine."""
import sqlite3
import unittest
from anonchat import city_capture as city

class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        city.init_db(self.db)
        self.db.execute("INSERT INTO city_zones VALUES (1,'Test',53.4,58.9,1)")
    def tearDown(self):
        self.db.close()
    def test_capture(self):
        r=city.capture(self.db,123,1,53.4,58.9,5,1000,now=1001)
        self.assertEqual(r["owner_user_id"],123)
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
