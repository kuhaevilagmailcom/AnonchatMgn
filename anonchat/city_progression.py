"""РАЙОНЫ: inventory progression, chests and verified Telegram Stars receipts.

The existing city_pets and users.xp records are preserved. All rewards are
computed under BEGIN IMMEDIATE, never trusted from the Mini App.
"""
import math
import random
import secrets
import sqlite3
import time
from . import city_pets
from .city_capture import MAX_ACCURACY_M, FIX_MAX_AGE_S, distance_m

PREMIUM = {
    "panda": {"name":"Панда","emoji":"🐼","xtr":15,"stars_h":7,"hp_5m":2.0,"rarity":"rare"},
    "wolf": {"name":"Волк","emoji":"🐺","xtr":25,"stars_h":10,"hp_5m":2.6,"rarity":"epic"},
    "dragon": {"name":"Дракон","emoji":"🐉","xtr":50,"stars_h":15,"hp_5m":3.6,"rarity":"legendary"},
}
RARITY = {"cat":"common","bird":"uncommon","pig":"rare","snake":"epic","lion":"legendary",
          "panda":"rare","wolf":"epic","dragon":"legendary"}
RARITY_RU = {"common":"Обычный","uncommon":"Необычный","rare":"Редкий",
             "epic":"Эпический","legendary":"Легендарный"}
ITEMS = {
    "shield":{"name":"Щит района","emoji":"🛡️","rarity":"rare","seconds":3600,
              "description":"Сужает радиус вражеского захвата района до 65 м на час"},
    "medkit":{"name":"Аптечка","emoji":"❤️","rarity":"common","seconds":0,
              "description":"Мгновенно восстанавливает 30 HP"},
    "income":{"name":"Ускоритель дохода","emoji":"⚡","rarity":"rare","seconds":3600,
              "description":"Увеличивает будущий доход питомца в квартале на 50%"},
    "lock":{"name":"Замок района","emoji":"🔒","rarity":"epic","seconds":3600,
            "description":"Временная защита квартала от захвата"},
    "luck":{"name":"Билет удачи","emoji":"🎟️","rarity":"uncommon","seconds":0,
            "description":"Увеличивает шанс редкой награды из следующего сундука"},
}
CHEST_TYPES = {"common":("📦",70),"rare":("🎁",22),"epic":("💎",7),"legendary":("👑",1)}
CHEST_INTERVAL = 5*3600
# Independently validated/public pedestrian anchors only; no generated random GPS points.
# Chest positions select among these anchors, not arbitrary buildings or roads.
CHEST_POINTS = [
    (53.404924,58.990902,"Парк у Вечного огня"),
    (53.380514,58.960070,"Парк «Притяжение»"),
    (53.422358,58.990517,"Сквер Металлургов"),
    (53.428465,59.000297,"Парк Ветеранов"),
    (53.411091,58.986059,"Сквер у стелы"),
    (53.402300,58.952800,"Экологический парк"),
    (53.393547,59.063386,"Площадь Победы"),
    (53.415252,59.054228,"Комсомольская площадь"),
]
def init_db(db):
    city_pets.init_db(db)
    columns = {r[1] for r in db.execute("PRAGMA table_info(city_pets)")}
    if "level" not in columns:
        db.execute("ALTER TABLE city_pets ADD COLUMN level INTEGER NOT NULL DEFAULT 1")
    if "pet_hp" not in columns:
        db.execute("ALTER TABLE city_pets ADD COLUMN pet_hp INTEGER NOT NULL DEFAULT 100")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS city_items (
       owner_id INTEGER NOT NULL, kind TEXT NOT NULL, quantity INTEGER NOT NULL DEFAULT 0,
       PRIMARY KEY(owner_id,kind)
    );
    CREATE TABLE IF NOT EXISTS city_effects (
       zone_id INTEGER NOT NULL, kind TEXT NOT NULL, owner_id INTEGER NOT NULL,
       expires_at INTEGER NOT NULL, PRIMARY KEY(zone_id,kind,owner_id)
    );
    CREATE TABLE IF NOT EXISTS city_chests (
       id TEXT PRIMARY KEY, cycle INTEGER NOT NULL, kind TEXT NOT NULL,
       lat REAL NOT NULL, lon REAL NOT NULL, place TEXT NOT NULL, expires_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS city_chest_claims (
       chest_id TEXT NOT NULL, user_id INTEGER NOT NULL,
       reward_kind TEXT NOT NULL, reward_amount INTEGER NOT NULL,
       claimed_at INTEGER NOT NULL, PRIMARY KEY(chest_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS city_premium_orders (
       id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL,
       amount INTEGER NOT NULL, created_at INTEGER NOT NULL,
       fulfilled_at INTEGER NOT NULL DEFAULT 0,
       charge_id TEXT UNIQUE, pet_id INTEGER, refunded_at INTEGER NOT NULL DEFAULT 0
    );
    """)
    order_columns={r[1] for r in db.execute("PRAGMA table_info(city_premium_orders)")}
    if "pet_id" not in order_columns:
        db.execute("ALTER TABLE city_premium_orders ADD COLUMN pet_id INTEGER")
    if "refunded_at" not in order_columns:
        db.execute("ALTER TABLE city_premium_orders ADD COLUMN refunded_at INTEGER NOT NULL DEFAULT 0")

def stats(kind, level=1):
    base = {**city_pets.PET_TYPES,**PREMIUM}.get(kind)
    if not base: raise ValueError("Неизвестный питомец")
    level = max(1,min(10,int(level)))
    rarity = RARITY[kind]
    return {"kind":kind,"name":base["name"],"emoji":base["emoji"],
            "rarity":rarity,"rarity_name":RARITY_RU[rarity],"level":level,
            "stars_h":round(base["stars_h"]*(1+.12*(level-1)),2),
            "hp_5m":round(min(5,base["hp_5m"]*(1+.08*(level-1))),2),
            "pet_hp":100,"xtr":base.get("xtr",0)}

def upgrade_cost(kind, level):
    if int(level)>=10: return None
    premium_multiplier = 2 if kind in PREMIUM else 1
    return premium_multiplier * (80 + 55*int(level)*int(level))

def upgrade(db,uid,pet_id):
    city_pets._begin(db)
    try:
        row=db.execute("SELECT kind,level FROM city_pets WHERE id=? AND owner_id=?",
                       (pet_id,uid)).fetchone()
        if not row: raise ValueError("Питомец не найден")
        cost=upgrade_cost(*row)
        if cost is None: raise ValueError("Максимальный уровень")
        old=stats(*row)
        balance=city_pets._change_xp(db,uid,-cost,"city_pet_upgrade","Улучшение питомца",pet_id)
        db.execute("UPDATE city_pets SET level=level+1 WHERE id=?",(pet_id,))
        db.commit()
        return {"before":old,"after":stats(row[0],row[1]+1),"cost":cost,"balance":balance}
    except BaseException:
        db.rollback();raise

def inventory(db,uid):
    pets=[]
    for row in db.execute("SELECT id,kind,level,pet_hp,zone_id FROM city_pets WHERE owner_id=? ORDER BY id DESC",(uid,)):
        item=stats(row[1],row[2])
        item.update({
            "id": row[0], "pet_hp": row[3], "zone_id": row[4],
            "upgrade_cost": upgrade_cost(row[1], row[2]),
            # Preview values are calculated by the same trusted server formula
            # as an actual upgrade. Do not calculate combat stats in the UI.
            "next_stats": stats(row[1], row[2] + 1) if row[2] < 10 else None,
        })
        pets.append(item)
    items=[{"kind":k,"quantity":q,**ITEMS[k]} for k,q in db.execute(
        "SELECT kind,quantity FROM city_items WHERE owner_id=? AND quantity>0",(uid,)) if k in ITEMS]
    effects=[{"zone_id":z,"kind":k,"expires_at":exp} for z,k,exp in db.execute(
        "SELECT zone_id,kind,expires_at FROM city_effects WHERE owner_id=? AND expires_at>?",
        (uid,int(time.time())))]
    return {"inventory_pets":pets,"items":items,"effects":effects,
            "premium_catalog":[stats(k) for k in PREMIUM]}

def grant_pet(db,uid,kind,now):
    if kind not in {**city_pets.PET_TYPES,**PREMIUM}: raise ValueError("Неизвестный питомец")
    cur=db.execute("INSERT INTO city_pets(owner_id,kind,purchased_at) VALUES(?,?,?)",
                   (uid,kind,int(now)))
    return cur.lastrowid

def grant_item(db,uid,kind,quantity=1):
    if kind not in ITEMS or not 1<=quantity<=100: raise ValueError("Неверный предмет")
    db.execute("""INSERT INTO city_items(owner_id,kind,quantity) VALUES(?,?,?)
                  ON CONFLICT(owner_id,kind) DO UPDATE SET quantity=quantity+excluded.quantity""",
               (uid,kind,quantity))

def use_item(db,uid,kind,zone_id=None,now=None):
    now=int(time.time() if now is None else now)
    if kind not in ITEMS: raise ValueError("Неизвестный предмет")
    city_pets._begin(db)
    try:
        if kind!="medkit" and kind!="luck":
            if zone_id is None or not city_pets._owner_has_zone(db,uid,int(zone_id)):
                raise ValueError("Выбери свой район")
        hit=db.execute("UPDATE city_items SET quantity=quantity-1 WHERE owner_id=? AND kind=? AND quantity>0",
                       (uid,kind))
        if hit.rowcount!=1: raise ValueError("Предмет закончился")
        if kind=="medkit":
            hp=db.execute("SELECT hp_milli FROM city_player_hp WHERE user_id=?",(uid,)).fetchone()
            if hp and hp[0]<=0: raise ValueError("Сначала возродись")
            db.execute("""INSERT INTO city_player_hp(user_id,hp_milli,last_tick) VALUES(?,?,?)
              ON CONFLICT(user_id) DO UPDATE SET hp_milli=MIN(100000,hp_milli+30000)""",
              (uid,100000,now))
        elif kind=="luck":
            db.execute("""INSERT INTO city_effects(zone_id,kind,owner_id,expires_at) VALUES(0,'luck',?,?)
               ON CONFLICT(zone_id,kind,owner_id) DO UPDATE SET expires_at=excluded.expires_at""",
               (uid,now+86400))
        else:
            db.execute("""INSERT INTO city_effects(zone_id,kind,owner_id,expires_at)
              VALUES(?,?,?,?) ON CONFLICT(zone_id,kind,owner_id) DO UPDATE SET
              expires_at=excluded.expires_at""",
              (int(zone_id),kind,uid,now+ITEMS[kind]["seconds"]))
        db.commit()
        return {"kind":kind,"zone_id":zone_id,"expires_at":now+ITEMS[kind]["seconds"]}
    except BaseException:
        db.rollback();raise

def current_chests(db,now=None):
    now=int(time.time() if now is None else now)
    cycle=now//CHEST_INTERVAL
    # One common cycle for all players; persistent even when server restarts.
    # No user-specific spawns or client-provided random outcome.
    existing=db.execute("SELECT COUNT(*) FROM city_chests WHERE cycle=?",(cycle,)).fetchone()[0]
    if not existing:
        picks=random.SystemRandom().sample(CHEST_POINTS,min(6,len(CHEST_POINTS)))
        kinds=list(CHEST_TYPES)
        weights=[CHEST_TYPES[k][1] for k in kinds]
        for i,(lat,lon,place) in enumerate(picks):
            kind=random.SystemRandom().choices(kinds,weights)[0]
            db.execute("""INSERT OR IGNORE INTO city_chests(id,cycle,kind,lat,lon,place,expires_at)
                 VALUES(?,?,?,?,?,?,?)""",
                 (f"{cycle}-{i}",cycle,kind,lat,lon,place,(cycle+1)*CHEST_INTERVAL))
    return [
        {"id":r[0],"kind":r[1],"emoji":CHEST_TYPES[r[1]][0],
         "lat":r[2],"lon":r[3],"place":r[4],"expires_at":r[5]}
        for r in db.execute("SELECT id,kind,lat,lon,place,expires_at FROM city_chests WHERE cycle=? ORDER BY id",(cycle,))
    ]

def open_chest(db,uid,chest_id,lat,lon,accuracy,timestamp,now=None):
    now=float(time.time() if now is None else now)
    vals=(lat,lon,accuracy,timestamp)
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in vals):
        raise ValueError("Некорректные координаты")
    if not (0<=accuracy<=MAX_ACCURACY_M) or not (-2<=now-timestamp<=FIX_MAX_AGE_S):
        raise ValueError("Проверь GPS")
    city_pets._begin(db)
    try:
        current_chests(db,now)
        chest=db.execute("SELECT kind,lat,lon,expires_at FROM city_chests WHERE id=?",(chest_id,)).fetchone()
        if chest is None or chest[3]<=now: raise ValueError("Сундук уже исчез")
        if distance_m(lat,lon,chest[1],chest[2])+accuracy>70:
            raise ValueError("Подойди ближе к сундуку")
        old=db.execute("SELECT 1 FROM city_chest_claims WHERE chest_id=? AND user_id=?",(chest_id,uid)).fetchone()
        if old: raise ValueError("Этот сундук уже открыт")
        kind=chest[0]
        # Reward buckets: rare premium pets possible, but cannot be guaranteed.
        lucky=db.execute("SELECT 1 FROM city_effects WHERE zone_id=0 AND kind='luck' AND owner_id=? AND expires_at>?",
                         (uid,now)).fetchone()
        roll=secrets.randbelow(10000)
        bonus=2 if lucky else 1
        premium_cutoff={"common":0,"rare":5,"epic":18,"legendary":60}[kind]*bonus
        pet_cutoff={"common":20,"rare":350,"epic":900,"legendary":2000}[kind]*bonus
        item_cutoff={"common":650,"rare":2400,"epic":4800,"legendary":6500}[kind]*bonus
        if roll<premium_cutoff:
            reward="pet";value=random.SystemRandom().choice(list(PREMIUM))
            pet_id=grant_pet(db,uid,value,now)
            description=f"{PREMIUM[value]['emoji']} {PREMIUM[value]['name']}"
        elif roll<pet_cutoff:
            reward="pet";value=random.SystemRandom().choice(list(city_pets.PET_TYPES))
            pet_id=grant_pet(db,uid,value,now)
            description=f"{city_pets.PET_TYPES[value]['emoji']} {city_pets.PET_TYPES[value]['name']}"
        elif roll<item_cutoff:
            reward="item";value=random.SystemRandom().choice(list(ITEMS))
            grant_item(db,uid,value)
            description=f"{ITEMS[value]['emoji']} {ITEMS[value]['name']}"
        else:
            reward="stars";value=random.SystemRandom().randint(
                *{"common":(20,75),"rare":(80,200),"epic":(220,450),"legendary":(500,1000)}[kind])
            city_pets._change_xp(db,uid,value,"city_chest","Сундук РАЙОНЫ",chest_id)
            description=f"+{value} игровых ⭐"
        db.execute("""INSERT INTO city_chest_claims(chest_id,user_id,reward_kind,reward_amount,claimed_at)
                      VALUES(?,?,?,?,?)""",
                   (chest_id,uid,reward, value if isinstance(value,int) else 1,int(now)))
        if lucky:
            db.execute("DELETE FROM city_effects WHERE zone_id=0 AND kind='luck' AND owner_id=?",(uid,))
        db.commit()
        return {"reward":reward,"description":description,"pet_id":pet_id if reward=="pet" else None}
    except BaseException:
        db.rollback();raise

def create_order(db,uid,kind,now=None):
    if kind not in PREMIUM:raise ValueError("Нет такого платного питомца")
    now=int(time.time() if now is None else now)
    order_id=secrets.token_urlsafe(18)
    db.execute("""INSERT INTO city_premium_orders(id,user_id,kind,amount,created_at)
                  VALUES(?,?,?,?,?)""",(order_id,uid,kind,PREMIUM[kind]["xtr"],now))
    return {"order_id":order_id,"amount":PREMIUM[kind]["xtr"],"kind":kind}

def validate_precheckout(db,uid,payload,currency,amount,now=None):
    now=int(time.time() if now is None else now)
    row=db.execute("SELECT user_id,amount,created_at,fulfilled_at FROM city_premium_orders WHERE id=?",(payload,)).fetchone()
    return bool(row and row[0]==uid and row[1]==amount and currency=="XTR"
                and now-row[2]<=3600 and not row[3])

def confirm_paid(db,uid,payload,currency,amount,charge,now=None):
    now=int(time.time() if now is None else now)
    if not charge or len(charge)>255:raise ValueError("Неизвестный платёж")
    city_pets._begin(db)
    try:
        row=db.execute("SELECT user_id,kind,amount,fulfilled_at,charge_id FROM city_premium_orders WHERE id=?",(payload,)).fetchone()
        if not row or row[0]!=uid or row[2]!=amount or currency!="XTR":
            raise ValueError("Платёж не совпадает с заказом")
        if row[3]:
            if row[4]!=charge:raise ValueError("Заказ уже оплачен другим платежом")
            db.commit();return {"replayed":True}
        if db.execute("SELECT 1 FROM city_premium_orders WHERE charge_id=?",(charge,)).fetchone():
            raise ValueError("Этот платёж уже обработан")
        pet_id=grant_pet(db,uid,row[1],now)
        db.execute("UPDATE city_premium_orders SET fulfilled_at=?,charge_id=?,pet_id=? WHERE id=?",
                   (now,charge,pet_id,payload))
        db.commit()
        return {"pet_id":pet_id,"kind":row[1],"replayed":False}
    except BaseException:
        db.rollback();raise


def mark_refunded(db,uid,charge,now=None):
    """Finalize an already successful Telegram refund and revoke its one pet."""
    now=int(time.time() if now is None else now)
    city_pets._begin(db)
    try:
        row=db.execute("""SELECT id,pet_id,refunded_at FROM city_premium_orders
                           WHERE user_id=? AND charge_id=? AND fulfilled_at>0""",
                       (uid,charge)).fetchone()
        if not row:raise ValueError("Платёж не найден")
        if row[2]:
            db.commit()
            return {"replayed":True}
        if row[1]:
            db.execute("DELETE FROM city_pets WHERE id=? AND owner_id=?",(row[1],uid))
        db.execute("UPDATE city_premium_orders SET refunded_at=? WHERE id=?",(now,row[0]))
        db.commit()
        return {"refunded":True,"pet_id":row[1]}
    except BaseException:
        db.rollback()
        raise
