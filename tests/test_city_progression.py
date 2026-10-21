"""РАЙОНЫ: end-to-end SQLite progression/chests/payments/team invariants."""
import sqlite3
import unittest

from anonchat import city_capture, city_pets
from anonchat import city_progression as p
from anonchat import city_warehouses as w


class GameSystemsTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        city_capture.init_db(self.db)
        p.init_db(self.db)
        w.init_db(self.db)
        self.db.executescript("""
        CREATE TABLE users(user_id INTEGER PRIMARY KEY,
          nickname TEXT DEFAULT '', nick_key TEXT DEFAULT '', username TEXT DEFAULT '',
          xp INTEGER NOT NULL DEFAULT 0,xp_source TEXT DEFAULT '',
          xp_reason TEXT DEFAULT '',xp_reference_type TEXT DEFAULT '',
          xp_reference_id TEXT DEFAULT '');
        """)
        self.db.executemany(
            "INSERT INTO users(user_id,nickname,nick_key,xp) VALUES(?,?,?,?)",
            [(10,"Алекс","алекс",20000),(20,"Даня","даня",500),(30,"Игорь","игорь",500)],
        )
        self.db.execute("INSERT INTO city_zones VALUES(1,'Ашик',53.38,58.98,1)")
        self.db.execute("INSERT INTO city_ownership VALUES(1,10,100)")

    def tearDown(self):
        self.db.close()

    def balance(self,uid=10):
        return self.db.execute("SELECT xp FROM users WHERE user_id=?",(uid,)).fetchone()[0]

    def test_old_pet_migrates_without_data_loss_and_upgrade_is_atomic(self):
        pet=city_pets.buy(self.db,10,"cat",now=100)["pet_id"]
        self.assertEqual(p.inventory(self.db,10)["inventory_pets"][0]["level"],1)
        old=self.balance()
        result=p.upgrade(self.db,10,pet)
        self.assertEqual(result["before"]["level"],1)
        self.assertEqual(result["after"]["level"],2)
        self.assertGreater(result["after"]["hp_5m"],result["before"]["hp_5m"])
        self.assertEqual(self.balance(),old-result["cost"])
        for _ in range(8):
            p.upgrade(self.db,10,pet)
        self.assertEqual(p.inventory(self.db,10)["inventory_pets"][0]["level"],10)
        with self.assertRaises(ValueError):
            p.upgrade(self.db,10,pet)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM city_pets WHERE owner_id=10").fetchone()[0],1)

    def test_items_are_consumed_and_locks_block_capture(self):
        p.grant_item(self.db,10,"lock",1)
        result=p.use_item(self.db,10,"lock",1,now=2000)
        self.assertEqual(result["expires_at"],5600)
        with self.assertRaises(ValueError):
            p.use_item(self.db,10,"lock",1,now=2001)
        with self.assertRaisesRegex(ValueError,"замком"):
            city_capture.capture(self.db,20,1,53.38,58.98,5,2010,now=2010)
        # Expiry allows attack, preserving existing cooldown rules.
        result=city_capture.capture(self.db,20,1,53.38,58.98,5,5700,now=5700)
        self.assertEqual(result["owner_user_id"],20)

    def test_medkit_saves_hp_and_income_boost_is_real(self):
        p.grant_item(self.db,10,"medkit")
        self.db.execute("INSERT INTO city_player_hp(user_id,hp_milli,last_tick) VALUES(10,45000,1000)")
        p.use_item(self.db,10,"medkit",now=1100)
        self.assertEqual(city_pets.state(self.db,10)["hp"],75)
        pet=city_pets.buy(self.db,10,"cat",now=1100)["pet_id"]
        city_pets.place(self.db,10,pet,1,now=1100)
        p.grant_item(self.db,10,"income")
        p.use_item(self.db,10,"income",1,now=1100)
        self.assertEqual(city_pets.claim(self.db,10,now=4700)["stars"],1)
        # Rate 1.5 per hour, fractional amount carries to next claim.
        self.assertEqual(city_pets.claim(self.db,10,now=8300)["stars"],1)

    def test_stable_five_hour_chests_single_claim_and_gps(self):
        first=p.current_chests(self.db,now=19000)
        self.assertEqual(len(first),6)
        self.assertEqual(first,p.current_chests(self.db,now=19001))
        self.assertEqual(len(p.current_chests(self.db,now=36001)),6)
        chest=first[0]
        with self.assertRaises(ValueError):
            p.open_chest(self.db,10,chest["id"],0,0,5,19000,now=19000)
        with self.assertRaises(ValueError):
            p.open_chest(self.db,10,chest["id"],chest["lat"],chest["lon"],75,18900,now=19000)
        # Chest expires at 10h, not at current response or app refresh.
        with self.assertRaises(ValueError):
            p.open_chest(self.db,10,chest["id"],chest["lat"],chest["lon"],5,36001,now=36001)
        result=p.open_chest(self.db,10,chest["id"],chest["lat"],chest["lon"],5,19001,now=19001)
        self.assertIn(result["reward"],("pet","item","stars"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM city_chest_claims").fetchone()[0],1)
        with self.assertRaises(ValueError):
            p.open_chest(self.db,10,chest["id"],chest["lat"],chest["lon"],5,19002,now=19002)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM city_chest_claims").fetchone()[0],1)

    def test_paid_pets_only_on_verified_receipt_and_exactly_once(self):
        order=p.create_order(self.db,10,"panda",now=1000)
        amount=order["amount"]
        self.assertEqual(amount,15)
        self.assertFalse(p.validate_precheckout(
            self.db,10,order["order_id"],"XTR",25,now=1001))
        self.assertFalse(p.validate_precheckout(
            self.db,20,order["order_id"],"XTR",15,now=1001))
        self.assertTrue(p.validate_precheckout(
            self.db,10,order["order_id"],"XTR",15,now=1001))
        self.assertFalse(p.validate_precheckout(
            self.db,10,order["order_id"],"XTR",15,now=5000))
        with self.assertRaises(ValueError):
            p.confirm_paid(self.db,10,order["order_id"],"USD",15,"charge-1",now=1005)
        self.assertEqual(len(p.inventory(self.db,10)["inventory_pets"]),0)
        result=p.confirm_paid(self.db,10,order["order_id"],"XTR",15,"charge-1",now=1005)
        self.assertFalse(result["replayed"])
        self.assertTrue(p.confirm_paid(
            self.db,10,order["order_id"],"XTR",15,"charge-1",now=1005)["replayed"])
        self.assertEqual(len(p.inventory(self.db,10)["inventory_pets"]),1)
        pet=p.inventory(self.db,10)["inventory_pets"][0]
        self.assertEqual(pet["kind"],"panda")
        self.assertEqual(pet["rarity"],"rare")
        self.assertEqual(self.balance(),20000)
        with self.assertRaises(ValueError):
            p.confirm_paid(self.db,10,order["order_id"],"XTR",15,"other-charge",now=1005)
        order2=p.create_order(self.db,10,"wolf",now=1000)
        with self.assertRaises(ValueError):
            p.confirm_paid(self.db,10,order2["order_id"],"XTR",25,"charge-1",now=1005)

    def test_warehouse_invitation_roles_capacity_and_ownership(self):
        result=w.create(self.db,10,"Левый Берег","🏚️","Наша команда",now=100)
        self.assertGreater(result["warehouse_id"],0)
        invite=w.invite(self.db,10,"Даня",now=110)
        self.assertEqual(invite["recipient_id"],20)
        with self.assertRaises(ValueError):
            w.invite(self.db,10,"Даня",now=111)
        with self.assertRaises(ValueError):
            w.invite(self.db,10,"Алекс",now=200)
        with self.assertRaises(ValueError):
            w.respond(self.db,30,invite["id"],True,now=120)
        response=w.respond(self.db,20,invite["id"],True,now=120)
        self.assertTrue(response["accepted"])
        with self.assertRaises(ValueError):
            w.respond(self.db,20,invite["id"],True,now=121)
        self.assertEqual(w.my_warehouse(self.db,20)["warehouse"]["name"],"Левый Берег")
        self.assertEqual(w.my_warehouse(self.db,20)["warehouse"]["zones"],1)
        self.assertEqual(self.db.execute("SELECT user_id FROM city_ownership WHERE zone_id=1").fetchone()[0],10)
        with self.assertRaises(ValueError):
            w.create(self.db,20,"Другой склад")
        with self.assertRaises(ValueError):
            w.kick(self.db,20,10)
        self.assertTrue(w.kick(self.db,10,20)["removed"])
        self.assertIsNone(w.my_warehouse(self.db,20)["warehouse"])
        with self.assertRaises(ValueError):
            w.disband(self.db,10,"подтвердить")
        self.assertTrue(w.disband(self.db,10,"УДАЛИТЬ СКЛАД")["deleted"])


if __name__=="__main__":
    unittest.main()
